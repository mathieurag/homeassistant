
import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import math

# Configuration
DB_PATH = "/config/home-assistant_v2.db"
CSV_LOG = "/config/corrections_hp_hc.csv"
ANALYSE_MODE = "since_midnight"  # "last_hour" ou "since_midnight"

ids = {
    "hp": 248,
    "hc": 249,
    "eco_hp": 361,
    "eco_hc": 360
}
min_diff_kwh = 0.001
max_delta_kwh = 1.0
rounding_step_kwh = 0.001
LOCAL_TZ = timezone(timedelta(hours=2))

# Fonctions utilitaires
def round_to_step(val, step=rounding_step_kwh):
    return round(round(val / step) * step, 3)

def is_hc_time(ts_local):
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

totaux = {
    "hp": {"eco": 0.0, "conso": 0.0, "delta": 0.0},
    "hc": {"eco": 0.0, "conso": 0.0, "delta": 0.0}
}

for typ in ("hp", "hc"):
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

        totaux[typ]["eco"] += eco_delta
        totaux[typ]["conso"] += conso_delta
        totaux[typ]["delta"] += eco_delta - conso_delta

        print(f"\n🔍 Analyse tranche : {ts_local:%Y-%m-%d %H:%M:%S} ({typ.upper()})")
        print(f"    - Conso Δ : {conso_delta:.3f} kWh")
        print(f"    - Eco   Δ : {eco_delta:.3f} kWh")
        print(f"    - À corriger : {delta_kwh:+.3f} kWh")

        if abs(delta_kwh) < min_diff_kwh:
            print(f"➡️  Ignoré : écart brut < {min_diff_kwh} kWh")
        elif abs(delta_kwh) > max_delta_kwh:
            print(f"⛔ Ignoré : écart > {max_delta_kwh} kWh")
        else:
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

        # ➕ Analyse 5 min (indépendante)
        ts_utc = int(datetime.fromtimestamp(ts, tz=LOCAL_TZ).astimezone(timezone.utc).timestamp())
        conso_5min = get_actual_tranches(cur, conso_id, ts_utc)
        eco_5min = get_actual_tranches(cur, eco_id, ts_utc)
        expected = get_expected_tranches(ts_utc)

        df_rows = []
        for t in expected:
            dt = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(LOCAL_TZ)
            df_rows.append({
                "start_ts": t,
                "datetime": dt,
                "conso": conso_5min.get(t),
                "eco": eco_5min.get(t)
            })
        df = pd.DataFrame(df_rows)

        total_applique = 0.0
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            if pd.isna(row["conso"]) or pd.isna(prev["conso"]) or pd.isna(row["eco"]) or pd.isna(prev["eco"]):
                continue

            delta_conso = (row["conso"] - prev["conso"]) / 1000
            delta_eco = row["eco"] - prev["eco"]
            ecart = round_to_step(delta_eco - delta_conso)

            if abs(ecart) < min_diff_kwh:
                continue

            print(f"➡️ {row['datetime'].strftime('%H:%M:%S')} - ΔConso: {delta_conso:.3f} kWh | ΔEco: {delta_eco:.3f} kWh | Écart: {ecart:+.3f} kWh")
            correction = ecart
            start_ts_key = int(row["start_ts"])
            cur.execute(
                "SELECT sum FROM statistics_short_term WHERE metadata_id = ? AND start_ts = ?",
                (conso_id, start_ts_key)
            )
            result = cur.fetchone()
            if result:
                old_sum = result[0]
                
            cur.execute(
                "SELECT start_ts, sum FROM statistics_short_term WHERE metadata_id = ? AND start_ts >= ? ORDER BY start_ts",
                (conso_id, start_ts_key)
            )
            rows_to_update = cur.fetchall()
            for start_ts_update, sum_val in rows_to_update:
                new_sum = sum_val + int(correction * 1000)
                cur.execute(
                    "UPDATE statistics_short_term SET sum = ? WHERE metadata_id = ? AND start_ts = ?",
                    (new_sum, conso_id, start_ts_update)
                )
                all_updates.append({
                    "type": typ.upper(), "level": "5min",
                    "start_ts": start_ts_update,
                    "timestamp": datetime.fromtimestamp(start_ts_update, tz=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    "old": sum_val, "new": new_sum, "delta": correction
                })

                total_applique += correction
                all_updates.append({
                    "type": typ.upper(), "level": "5min", "start_ts": start_ts_key,
                    "timestamp": row["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                    "old": old_sum, "new": new_sum, "delta": correction
                })

print("\n📊 Récapitulatif global :")
for t in ("hp", "hc"):
    label = t.upper()
    print(f"    [{label}] Conso : {totaux[t]['conso']:.3f} kWh | Eco : {totaux[t]['eco']:.3f} kWh | Δ : {totaux[t]['delta']:+.3f} kWh")

# Totaux cumulés
total_conso = totaux["hp"]["conso"] + totaux["hc"]["conso"]
total_eco = totaux["hp"]["eco"] + totaux["hc"]["eco"]
total_delta = totaux["hp"]["delta"] + totaux["hc"]["delta"]
print(f"\n    [TOTAL] Conso : {total_conso:.3f} kWh | Eco : {total_eco:.3f} kWh | Δ : {total_delta:+.3f} kWh")

# Finalisation
conn.commit()
conn.close()

if all_updates:
    df_log = pd.DataFrame(all_updates)
    header = not os.path.exists(CSV_LOG)
    df_log.to_csv(CSV_LOG, mode='a', header=header, index=False)

print(f"\n📦 Corrections historisées : {len(all_updates)} ligne(s)")
