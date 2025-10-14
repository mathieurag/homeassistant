import os
import sys
import json
import math
import sqlite3
import datetime as dt
from typing import Optional, List, Tuple, Dict
import numpy as np
import pandas as pd

def log(msg):
    print(msg, flush=True)  # Assure que les logs s'affichent

def ensure_out(p):
    os.makedirs(p, exist_ok=True)

def str_bool(v):
    if isinstance(v, (int, float)): return 1 if v > 0 else 0
    if isinstance(v, str): return 1 if v.strip().lower() in ("on", "true", "1", "oui", "yes") else 0
    return 0

def connect(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn

def local_to_utc_iso(date_str, tzname):
    import zoneinfo
    tz = zoneinfo.ZoneInfo(tzname)
    t0 = dt.datetime.fromisoformat(date_str).replace(tzinfo=tz)
    return (t0.astimezone(dt.timezone.utc)).isoformat()

def fetch_states_series(conn, entity_id, start_utc, end_utc):
    q = """
    SELECT s.last_updated AS ts, s.state AS state
    FROM states AS s
    JOIN states_meta AS m ON s.metadata_id = m.metadata_id
    WHERE m.entity_id = ? AND s.last_updated >= ? AND s.last_updated < ?
    ORDER BY s.last_updated ASC
    """
    cur = conn.cursor()
    cur.execute(q, (entity_id, start_utc, end_utc))
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["timestamp", entity_id]).set_index("timestamp")
    ts = pd.to_datetime([r["ts"] for r in rows], utc=True)
    vals = [r["state"] for r in rows]
    df = pd.DataFrame({"timestamp": ts, entity_id: vals}).set_index("timestamp")
    if entity_id.startswith("input_boolean"):
        df[entity_id] = df[entity_id].apply(str_bool)
    else:
        df[entity_id] = pd.to_numeric(df[entity_id], errors="coerce")
    return df.sort_index()

def fetch_statistics_series(conn, statistic_id, table, start_utc, end_utc):
    q = f"""
    SELECT 
      COALESCE(ss.start_ts, CAST(STRFTIME('%s', ss.start) AS REAL)) AS ts,
      ss.mean, ss.state, ss.sum
    FROM {table} AS ss
    JOIN statistics_meta AS sm ON ss.metadata_id = sm.id
    WHERE sm.statistic_id = ? 
      AND ss.start_ts >= CAST(STRFTIME('%s', ?) AS REAL)
      AND ss.start_ts < CAST(STRFTIME('%s', ?) AS REAL)
    ORDER BY ts ASC
    """
    cur = conn.cursor()
    cur.execute(q, (statistic_id, start_utc, end_utc))
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["timestamp", statistic_id]).set_index("timestamp")
    ts = [dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc) for r in rows]
    ts = pd.to_datetime(ts, utc=True)
    if not all(r["mean"] is None for r in rows):
        vals = [r["mean"] for r in rows]
    else:
        vals = [r["state"] if r["state"] is not None else r["sum"] for r in rows]
    df = pd.DataFrame({"timestamp": ts, statistic_id: vals}).set_index("timestamp")
    df[statistic_id] = pd.to_numeric(df[statistic_id], errors="coerce")
    return df.sort_index()

def build_timeseries(conn, cfg):
    frames = []
    for sid in (cfg["ENTITY_T_LOW"], cfg["ENTITY_T_ROOM"], cfg["ENTITY_T_EXT"],
                cfg["ENTITY_POWER"], cfg["ENTITY_ENERGY"], cfg["ENTITY_VOL"]):
        df = fetch_statistics_series(conn, sid, "statistics_short_term", cfg["_START_UTC"], cfg["_END_UTC"])
        if df.empty:
            df = fetch_statistics_series(conn, sid, "statistics", cfg["_START_UTC"], cfg["_END_UTC"])
        if df.empty:
            df = fetch_states_series(conn, sid, cfg["_START_UTC"], cfg["_END_UTC"])
        frames.append(df)
    for eid in (cfg["ENTITY_FLOW"], cfg["ENTITY_LL"], cfg["ENTITY_LV"]):
        df = fetch_states_series(conn, eid, cfg["_START_UTC"], cfg["_END_UTC"])
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, axis=1).sort_index()
    # Enforce true DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[~df.index.isna()]
    # Stabilise dtypes before ffill
    df = df.infer_objects(copy=False).ffill()

    # Resample using "s" (seconds)
    df = df.resample(f"{cfg['FREQ_S']}s").ffill()

    # Guards
    df[cfg["ENTITY_FLOW"]] = df[cfg["ENTITY_FLOW"]].clip(lower=0, upper=60)
    df[cfg["ENTITY_POWER"]] = df[cfg["ENTITY_POWER"]].clip(lower=0, upper=4000)
    df[cfg["ENTITY_T_LOW"]] = df[cfg["ENTITY_T_LOW"]].clip(lower=-5, upper=90)
    df[cfg["ENTITY_T_ROOM"]] = df[cfg["ENTITY_T_ROOM"]].clip(lower=-5, upper=50)
    return df

def find_calm_windows(df, cfg):
    flow = cfg["ENTITY_FLOW"]
    power = cfg["ENTITY_POWER"]
    
    # Identifie les plages horaires de 1h à 6h comme calmement automatiquement
    calm_hours_mask = (df.index.hour >= 1) & (df.index.hour < 6)
    
    # Applique les critères de calme selon les seuils débit et puissance
    mask = (df[flow] < cfg["FLOW_OFF_LMIN"]) & (df[power] < cfg["POWER_OFF_W"]) | calm_hours_mask
    windows = []
    start = None; last = None
    for t, ok in mask.items():
        if ok and start is None:
            start = t
        if not ok and start is not None:
            dur = (t - start).total_seconds()
            if dur >= cfg["CALM_MIN_S"]:  # Une fenêtre valide
                windows.append((start, t))
                log(f"Fenêtre calme trouvée : {start} à {t}, durée : {dur:.2f}s")
            start = None
        last = t
    if start is not None and last is not None:
        dur = (last - start).total_seconds()
        if dur >= cfg["CALM_MIN_S"]:
            windows.append((start, last))
            log(f"Fenêtre calme trouvée : {start} à {last}, durée : {dur:.2f}s")
    
    log(f"{len(windows)} fenêtres calmes détectées.")
    return windows

def regress_k_on_window(df, a, b, cfg):
    T_low = cfg["ENTITY_T_LOW"]; T_room = cfg["ENTITY_T_ROOM"]
    sub = df.loc[a:b]
    
    # Log de la période analysée
    log(f"Analyse de la fenêtre de {a} à {b}, durée : {(b - a).total_seconds()} secondes")
    
    if (b - a).total_seconds() < cfg["CALM_MIN_S"]:
        log(f"Fenêtre rejetée : durée trop courte {(b - a).total_seconds()} secondes")
        return None
    
    # Log des températures de la fenêtre
    log(f"Températures dans la fenêtre : T_low = {sub[T_low].values[:5]}, T_room = {sub[T_room].values[:5]}")
    
    y = (sub[T_low] - sub[T_room]).astype(float).values
    y = np.maximum(0.1, y)
    x = (sub.index - sub.index[0]).total_seconds().astype(float)
    
    if len(x) < 30 or np.nanstd(y) < 0.05:
        log(f"Rejet de la régression : données insuffisantes ou faible variance dans la fenêtre {a} à {b}")
        return None

    ln_y = np.log(y)
    A = np.vstack([x, np.ones_like(x)]).T
    k, c = np.linalg.lstsq(A, ln_y, rcond=None)[0]
    k = float(-k)
    
    # Vérification de la validité de k
    if not (cfg["K_MIN"] < k < cfg["K_MAX"]):
        log(f"Rejet de la régression : k ({k}) hors de la plage valide pour la fenêtre {a} à {b}")
        return None
    
    # Log du résultat de la régression
    log(f"Régression réussie : k = {k} pour la fenêtre {a} à {b}")
    
    # Simuler les résultats et calculer MAE/RMSE
    T0 = float(sub[T_low].iloc[0])
    Tr = sub[T_room].astype(float).values
    dt_s = (sub.index - sub.index[0]).total_seconds().astype(float)
    Tsim = np.zeros_like(dt_s, dtype=float)
    Tsim[0] = T0
    step = dt_s[1] - dt_s[0] if len(dt_s) > 1 else cfg["FREQ_S"]
    
    for i in range(1, len(dt_s)):
        Tsim[i] = Tsim[i-1] + (-k * (Tsim[i-1] - Tr[i])) * step
    
    meas = sub[T_low].astype(float).values
    mae = float(np.nanmean(np.abs(Tsim - meas)))
    rmse = float(np.sqrt(np.nanmean((Tsim - meas) ** 2)))
    ss_res = float(np.nansum((meas - Tsim) ** 2))
    mbar = float(np.nanmean(meas))
    ss_tot = float(np.nansum((meas - mbar) ** 2)) if np.isfinite(mbar) else float("nan")
    r2 = 1.0 - ss_res / ss_tot if ss_tot and ss_tot > 0 else float("nan")
    
    # Log des erreurs de régression
    log(f"Validation de la régression : MAE = {mae:.2f}, RMSE = {rmse:.2f}, R² = {r2:.2f}")
    
    return {
        "start": a.isoformat(),
        "end": b.isoformat(),
        "duration_s": (b - a).total_seconds(),
        "k_s": k,
        "mae_C": mae,
        "rmse_C": rmse,
        "r2": r2
    }

def main():
    cfg = CONFIG.copy()
    ensure_out(cfg["OUT_DIR"])

    # time bounds
    if cfg["START"] and cfg["END"]:
        start_utc = local_to_utc_iso(cfg["START"], cfg["TIMEZONE"])
        end_utc = local_to_utc_iso(cfg["END"], cfg["TIMEZONE"])
    else:
        now_utc = dt.datetime.now(dt.timezone.utc)
        end_utc = now_utc.isoformat()
        start_utc = (now_utc - dt.timedelta(days=cfg["DAYS"])).isoformat()
    cfg["_START_UTC"], cfg["_END_UTC"] = start_utc, end_utc

    log(f"Lecture DB: {cfg['DB_PATH']} [{cfg['_START_UTC']} → {cfg['_END_UTC']}]")
    conn = connect(cfg["DB_PATH"])
    try:
        df = build_timeseries(conn, cfg)
    finally:
        conn.close()

    if df.empty:
        log("Aucune donnée récupérée. Vérifiez la période et les entités.")
        sys.exit(2)

    # save series
    out_csv = os.path.join(cfg["OUT_DIR"], f"timeseries_{cfg['FREQ_S']}s.csv")
    df.to_csv(out_csv); log(f"Écrit: {out_csv}")

    # calm windows
    windows = find_calm_windows(df, cfg)
    log(f"{len(windows)} fenêtres calmes détectées.")

    # per-window k
    per = []
    for (a, b) in windows:
        res = regress_k_on_window(df, a, b, cfg)
        if res: per.append(res)

    import pandas as pd
    per_df = pd.DataFrame(per)
    per_df.to_csv(os.path.join(cfg["OUT_DIR"], "per_window.csv"), index=False)
    log(f"Écrit: {os.path.join(cfg['OUT_DIR'], 'per_window.csv')} ({len(per)} fenêtres valides)")

    k_vals = per_df["k_s"].tolist() if not per_df.empty else []
    if k_vals:
        k_med = float(np.median(k_vals))
        weights = per_df["duration_s"].to_numpy(dtype=float)
        weights = weights / max(1e-9, weights.sum())
        k_w = float(np.sum(weights * per_df["k_s"].to_numpy(dtype=float)))
        k_min, k_max = float(np.min(k_vals)), float(np.max(k_vals))
    else:
        k_med = 0.0016; k_w = k_med; k_min = None; k_max = None

    params = {
        "k_loss_s_median": k_med, "k_loss_s_weighted": k_w,
        "k_min_s": k_min, "k_max_s": k_max,
        "n_calm_windows_found": len(windows), "n_windows_used": int(len(per)),
        "validation_on_subset": {
            "median_k": {"MAE_C": mae_med, "RMSE_C": rmse_med},
            "weighted_k": {"MAE_C": mae_w, "RMSE_C": rmse_w}
        },
        "time_window_utc": {"start": cfg["_START_UTC"], "end": cfg["_END_UTC"]},
        "entities": {"T_low": cfg["ENTITY_T_LOW"], "T_room": cfg["ENTITY_T_ROOM"],
                     "flow": cfg["ENTITY_FLOW"], "power": cfg["ENTITY_POWER"]},
        "calm_criteria": {"flow_off_Lmin": cfg["FLOW_OFF_LMIN"], "power_off_W": cfg["POWER_OFF_W"],
                          "min_duration_s": cfg["CALM_MIN_S"]},
        "resample_s": cfg["FREQ_S"]
    }
    with open(os.path.join(cfg["OUT_DIR"], "params.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    log(f"Écrit: {os.path.join(cfg['OUT_DIR'], 'params.json')}")
