import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os

# Configuration
DB_PATH = "/config/home-assistant_v2.db"
CSV_LOG = "/config/corrections_hp_hc.csv"
ANALYSE_MODE = "since_midnight"
DEBUG_5MIN = True  # Active les logs détaillés 5min

ids = {
    "hp": 248,
    "hc": 249,
    "eco_hp": 361,
    "eco_hc": 360
}
min_diff_kwh = 0.0001
max_delta_kwh = 10.0
rounding_step_kwh = 0.001
LOCAL_TZ = timezone(timedelta(hours=2))

def round_to_step(val, step=rounding_step_kwh):
    return round(round(val / step) * step, 3)

def is_hc_time(ts_local):
    minutes = ts_local.hour * 60 + ts_local.minute
    return minutes >= 21 * 60 + 8 or minutes < 5 * 60 + 8

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
all_hour_starts = sorted(get_hour_starts_to_analyze(now_ts))
hp_hours = [ts for ts in all_hour_starts if not is_hc_time(datetime.fromtimestamp(ts, tz=LOCAL_TZ))]
hc_hours = [ts for ts in all_hour_starts if is_hc_time(datetime.fromtimestamp(ts, tz=LOCAL_TZ))]

totaux = {
    "hp": {"eco": 0.0, "conso": 0.0, "delta": 0.0},
    "hc": {"eco": 0.0, "conso": 0.0, "delta": 0.0}
}

for ts in all_hour_starts:
    ts_local = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
    print(f"\n🕒 Heure analysée : {ts_local:%Y-%m-%d %H:%M:%S}")

    for typ in ("hp", "hc"):
        conso_id = ids[typ]
        eco_id = ids["eco_" + typ]

        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (conso_id, ts))
        conso_now = cur.fetchone()
        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (conso_id, ts - 3600))
        conso_prev = cur.fetchone()
        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (eco_id, ts))
        eco_now = cur.fetchone()
        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (eco_id, ts - 3600))
        eco_prev = cur.fetchone()

        if all([conso_now, conso_prev, eco_now, eco_prev]):
            conso_delta = (conso_now[0] - conso_prev[0]) / 1000
            eco_delta = eco_now[0] - eco_prev[0]
            delta_kwh_raw = eco_delta - conso_delta
            delta_kwh = round_to_step(delta_kwh_raw)

            totaux[typ]["eco"] += eco_delta
            totaux[typ]["conso"] += conso_delta
            totaux[typ]["delta"] += delta_kwh_raw

            print(f"🔍 Analyse {typ.upper()} horaire")
            print(f"    - Conso Δ : {conso_delta:.3f} kWh")
            print(f"    - Eco   Δ : {eco_delta:.3f} kWh")

            if abs(delta_kwh) < min_diff_kwh:
                print(f"➡️  Ignoré : écart brut < {min_diff_kwh} kWh")
            elif abs(delta_kwh) > max_delta_kwh:
                print(f"⛔ Ignoré : écart > {max_delta_kwh} kWh")
            else:
                print(f"    - À corriger : {delta_kwh:+.3f} kWh")
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
                print(f"✅ Correction {typ.upper()} (hourly) appliquée : {delta_kwh:+.3f} kWh sur {len(future)} tranches")
        else:
            print(f"⚠️ Données manquantes pour {typ.upper()} à {ts_local}")
    for typ in ("hp", "hc"):
        conso_id = ids[typ]
        eco_id = ids["eco_" + typ]

        conso_5min = get_actual_tranches(cur, conso_id, ts)
        eco_5min = get_actual_tranches(cur, eco_id, ts)
        expected = get_expected_tranches(ts)

        df_rows = []
        for t in expected:
            dt_local = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(LOCAL_TZ)
            df_rows.append({
                "start_ts": t,
                "datetime": dt_local,
                "conso": conso_5min.get(t),
                "eco": eco_5min.get(t)
            })
        df = pd.DataFrame(df_rows)

        has_delta = False
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            if pd.isna(row["conso"]) or pd.isna(prev["conso"]) or pd.isna(row["eco"]) or pd.isna(prev["eco"]):
                continue

            delta_conso = (row["conso"] - prev["conso"]) / 1000
            delta_eco = row["eco"] - prev["eco"]
            ecart_raw = delta_eco - delta_conso
            ecart = round_to_step(ecart_raw)

            if abs(ecart) < min_diff_kwh:
                continue

            has_delta = True

            if DEBUG_5MIN:
                print(f"    ➕ {row['datetime'].strftime('%H:%M:%S')} - ΔC: {delta_conso:.5f} | ΔE: {delta_eco:.5f} | Brut: {ecart_raw:+.5f} | Arrondi: {ecart:+.3f}")

            mode_label = typ.upper()
            print(f"➡️ {row['datetime'].strftime('%Y-%m-%d %H:%M:%S')} [{mode_label}] - ΔConso: {delta_conso:.3f} | ΔEco: {delta_eco:.3f} | Écart: {ecart:+.3f} kWh")

            start_ts_key = int(row["start_ts"])
            cur.execute(
                "SELECT start_ts, sum FROM statistics_short_term WHERE metadata_id = ? AND start_ts >= ? ORDER BY start_ts",
                (conso_id, start_ts_key)
            )
            rows_to_update = cur.fetchall()
            if not rows_to_update:
                print(f"⚠️ Aucune tranche 5min trouvée à partir de {row['datetime']} pour {mode_label}")
                continue

            for start_ts_update, sum_val in rows_to_update:
                new_sum = sum_val + int(ecart * 1000)
                cur.execute(
                    "UPDATE statistics_short_term SET sum = ? WHERE metadata_id = ? AND start_ts = ?",
                    (new_sum, conso_id, start_ts_update)
                )
                all_updates.append({
                    "type": mode_label,
                    "level": "5min",
                    "start_ts": start_ts_update,
                    "timestamp": datetime.fromtimestamp(start_ts_update, tz=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    "old": sum_val,
                    "new": new_sum,
                    "delta": ecart
                })
            print(f"✅ Correction appliquée sur {len(rows_to_update)} tranche(s) à partir de {row['datetime'].strftime('%H:%M:%S')}")

        if not has_delta:
            print(f"➡️  Aucun delta 5min pour {typ.upper()}")


# Contrôle de cohérence 5min vs horaire
print("\n🔎 Vérification cohérence cumul 5min vs données horaires :")
for t in ("hp", "hc"):
    conso_id = ids[t]
    hours = hp_hours if t == "hp" else hc_hours
    total_5min_conso = 0.0
    for ts in hours:
        conso_5min = get_actual_tranches(cur, conso_id, ts)
        timestamps = sorted(conso_5min.keys())
        for i in range(1, len(timestamps)):
            delta = conso_5min[timestamps[i]] - conso_5min[timestamps[i - 1]]
            total_5min_conso += delta / 1000
    delta_5min_vs_hourly = round_to_step(total_5min_conso - totaux[t]['conso'])
    print(f"    [{t.upper()}] Conso 5min : {total_5min_conso:.3f} kWh | Horaire : {totaux[t]['conso']:.3f} kWh | Δ : {delta_5min_vs_hourly:+.3f} kWh")

# Récapitulatif global
print("\n📊 Récapitulatif global :")
for t in ("hp", "hc"):
    label = t.upper()
    print(f"    [{label}] Conso : {totaux[t]['conso']:.3f} kWh | Eco : {totaux[t]['eco']:.3f} kWh | Δ : {totaux[t]['delta']:+.3f} kWh")

total_conso = totaux["hp"]["conso"] + totaux["hc"]["conso"]
total_eco = totaux["hp"]["eco"] + totaux["hc"]["eco"]
total_delta = totaux["hp"]["delta"] + totaux["hc"]["delta"]
print(f"\n    [TOTAL] Conso : {total_conso:.3f} kWh | Eco : {total_eco:.3f} kWh | Δ : {total_delta:+.3f} kWh")

conn.commit()
conn.close()

if all_updates:
    df_log = pd.DataFrame(all_updates)
    header = not os.path.exists(CSV_LOG)
    df_log.to_csv(CSV_LOG, mode='a', header=header, index=False)

print(f"\n📦 Corrections historisées : {len(all_updates)} ligne(s)")
