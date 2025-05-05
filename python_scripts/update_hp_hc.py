import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import math

# Configuration
DB_PATH = "/config/home-assistant_v2.db"
CSV_LOG = "/config/corrections_hp_hc.csv"
ANALYSE_MODE = "last_hour"  # "last_hour" ou "since_midnight"
ANALYSE_MODE = "since_midnight"  # "last_hour" ou "since_midnight"

ids = {
    "hp": 248,
    "hc": 249,
    "eco_hp": 361,
    "eco_hc": 360
}
min_diff_kwh = 0.01
max_delta_kwh = 1.0
rounding_step_kwh = 0.01
LOCAL_TZ = timezone(timedelta(hours=2))

# Fonctions utilitaires
def round_to_step(val, step=rounding_step_kwh):
    return round(round(val / step) * step, 3)

def is_hc_time(ts_local):
    """Retourne True si l'heure locale est en HC selon les horaires personnalisés"""
    minutes = ts_local.hour * 60 + ts_local.minute
    return minutes >= 21 * 60 + 8 or minutes < 5 * 60 + 8

def should_correct(ts_local, typ):
    return is_hc_time(ts_local) if typ == "hc" else not is_hc_time(ts_local)

def get_expected_tranches(start_ts):
    return [start_ts + 300 * i for i in range(12)]

def get_actual_tranches(cursor, metadata_id, start_ts):
    cursor.execute(
        "SELECT start_ts, sum FROM statistics_short_term "
        "WHERE metadata_id = ? AND start_ts >= ? AND start_ts < ?",
        (metadata_id, start_ts, start_ts + 3600)
    )
    return {r[0]: r[1] for r in cursor.fetchall()}

def get_hour_starts_to_analyze(now_ts):
    if ANALYSE_MODE == "last_hour":
        last_hour = int(now_ts // 3600) * 3600
        return [last_hour]
    elif ANALYSE_MODE == "since_midnight":
        dt_now = datetime.fromtimestamp(now_ts, tz=LOCAL_TZ)
        midnight = dt_now.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_ts = int(midnight.timestamp())
        current_hour_ts = int(now_ts // 3600) * 3600
        return list(range(midnight_ts, current_hour_ts + 1, 3600))
    else:
        raise ValueError(f"Mode d'analyse inconnu : {ANALYSE_MODE}")

# Connexion DB
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
all_updates = []

now = datetime.now(LOCAL_TZ)
now_ts = int(now.timestamp())
hour_starts = get_hour_starts_to_analyze(now_ts)

for typ in ("hp", "hc"):
    is_hp = typ == "hp"
    conso_id = ids[typ]
    eco_id = ids["eco_" + typ]

    placeholders = ','.join('?' for _ in hour_starts)

    cur.execute(
        f"SELECT s1.start_ts, s1.sum, s2.sum FROM statistics s1 "
        f"JOIN statistics s2 ON s1.metadata_id = s2.metadata_id AND s2.start_ts = s1.start_ts - 3600 "
        f"WHERE s1.metadata_id = ? AND s1.start_ts IN ({placeholders}) ORDER BY s1.start_ts",
        (conso_id, *hour_starts)
    )
    conso_data = cur.fetchall()

    cur.execute(
        f"SELECT s1.start_ts, s1.sum, s2.sum FROM statistics s1 "
        f"JOIN statistics s2 ON s1.metadata_id = s2.metadata_id AND s2.start_ts = s1.start_ts - 3600 "
        f"WHERE s1.metadata_id = ? AND s1.start_ts IN ({placeholders})",
        (eco_id, *hour_starts)
    )
    eco_data = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    for ts, sum_t, sum_t_1 in conso_data:
        if ts not in eco_data:
            continue
        eco_t, eco_t_1 = eco_data[ts]
        ts_local = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
        if not should_correct(ts_local, typ):
            continue

        conso_delta = (sum_t - sum_t_1) / 1000
        eco_delta = eco_t - eco_t_1
        delta_kwh_raw = eco_delta - conso_delta
        delta_kwh = round_to_step(delta_kwh_raw)
        delta_rest = delta_kwh

        print(f"\n🔍 Analyse tranche : {ts_local:%Y-%m-%d %H:%M:%S} ({typ.upper()})", flush=True)
        print(f"    - Conso Δ : {conso_delta:.3f} kWh", flush=True)
        print(f"    - Eco   Δ : {eco_delta:.3f} kWh", flush=True)
        print(f"    - À corriger : {delta_kwh_raw:+.3f} kWh", flush=True)

        if abs(delta_kwh_raw) < min_diff_kwh:
            print(f"➡️  Ignoré : écart brut < {min_diff_kwh} kWh", flush=True)
            continue
        if abs(delta_kwh) > max_delta_kwh:
            print(f"⛔ Ignoré : écart > {max_delta_kwh} kWh", flush=True)
            continue

        # Correction horaire
        cur.execute("SELECT start_ts, sum FROM statistics WHERE metadata_id=? AND start_ts >= ? ORDER BY start_ts", (conso_id, ts))
        future = cur.fetchall()
        for start_ts_f, sum_f in future:
            new_sum = sum_f + int(delta_kwh * 1000)
            cur.execute("UPDATE statistics SET sum=? WHERE metadata_id=? AND start_ts=?", (new_sum, conso_id, start_ts_f))
            ts_local_f = datetime.fromtimestamp(start_ts_f, tz=LOCAL_TZ)
            all_updates.append({
                "type": typ.upper(), "level": "hourly", "start_ts": start_ts_f,
                "timestamp": ts_local_f.strftime("%Y-%m-%d %H:%M:%S"),
                "old": sum_f, "new": new_sum, "delta": delta_kwh
            })

        print(f"✅ Correction {typ.upper()} (hourly) appliquée : {delta_kwh:+.3f} kWh sur {len(future)} tranches", flush=True)

        # Correction 5 min
        actual = get_actual_tranches(cur, conso_id, ts)
        expected = get_expected_tranches(ts)
        df_rows = []
        for t in expected:
            dt = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(LOCAL_TZ)
            df_rows.append({"start_ts": t, "datetime": dt, "sum": actual.get(t)})
        df = pd.DataFrame(df_rows)

        total_applique = 0.0

        if delta_kwh > 0:
            part = math.ceil((delta_kwh / 12) / rounding_step_kwh) * rounding_step_kwh
            part = round_to_step(part)
            needed = math.ceil(delta_kwh / part)
            for i in range(min(needed, len(df))):
                s = df.at[i, "sum"]
                if pd.isna(s): continue
                if delta_rest < rounding_step_kwh: break
                new_s = s + int(part * 1000)
                cur.execute("UPDATE statistics_short_term SET sum=? WHERE metadata_id=? AND start_ts=?",
                            (new_s, conso_id, df.at[i, "start_ts"]))
                total_applique += part
                delta_rest -= part
                all_updates.append({
                    "type": typ.upper(), "level": "5min", "start_ts": df.at[i, "start_ts"],
                    "timestamp": df.at[i, "datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                    "old": s, "new": new_s, "delta": part
                })
        else:
            for i, row in df.iterrows():
                s = row["sum"]
                if pd.isna(s): continue
                prev = df.at[i-1, "sum"] if i > 0 and not pd.isna(df.at[i-1, "sum"]) else s
                d0 = (s - prev) / 1000
                if d0 > 0:
                    to_rem = min(abs(delta_rest), d0)
                    corr = -round_to_step(to_rem)
                    if abs(delta_rest) < rounding_step_kwh: break
                    new_s = s + int(corr * 1000)
                    cur.execute("UPDATE statistics_short_term SET sum=? WHERE metadata_id=? AND start_ts=?",
                                (new_s, conso_id, df.at[i, "start_ts"]))
                    total_applique += corr
                    delta_rest += corr
                    all_updates.append({
                        "type": typ.upper(), "level": "5min", "start_ts": df.at[i, "start_ts"],
                        "timestamp": df.at[i, "datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                        "old": s, "new": new_s, "delta": corr
                    })

        print(f"✅ Correction {typ.upper()} appliquée : total {total_applique:+.3f} kWh", flush=True)

# Finalisation
conn.commit()
conn.close()

if all_updates:
    df_log = pd.DataFrame(all_updates)
    header = not os.path.exists(CSV_LOG)
    df_log.to_csv(CSV_LOG, mode='a', header=header, index=False)

print(f"\n📦 Corrections historisées : {len(all_updates)} ligne(s)", flush=True)
