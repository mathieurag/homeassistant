import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os

# Configuration
DB_PATH = "/config/home-assistant_v2.db"
CSV_LOG = "/config/corrections_surplus.csv"
ANALYSE_MODE = "since_midnight"  # "last_hour" ou "since_midnight"
SURPLUS_ID = 490
ECOJOKO_ID = 497
min_diff_kwh = 0.001
max_delta_kwh = 1000
rounding_step_kwh = 0.001
LOCAL_TZ = timezone(timedelta(hours=2))

def round_to_step(val, step=rounding_step_kwh):
    return round(round(val / step) * step, 3)

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

def to_utc_ts(ts_local):
    return int(datetime.fromtimestamp(ts_local, tz=LOCAL_TZ).astimezone(timezone.utc).timestamp())

# Connexion DB
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
all_updates = []

now = datetime.now(LOCAL_TZ)
now_ts = int(now.timestamp())
hour_starts = get_hour_starts_to_analyze(now_ts)
placeholders = ','.join('?' for _ in hour_starts)

for ts in hour_starts:
    ts_local = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
    print(f"\n🕓 Analyse prévue : {ts_local:%Y-%m-%d %H:%M:%S}")

    # Lecture données horaires
    cur.execute(
        f"SELECT s1.start_ts, s1.sum, s2.sum FROM statistics s1 "
        f"JOIN statistics s2 ON s1.metadata_id = s2.metadata_id AND s2.start_ts = s1.start_ts - 3600 "
        f"WHERE s1.metadata_id = ? AND s1.start_ts = ?",
        (SURPLUS_ID, ts)
    )
    row_surplus = cur.fetchone()

    cur.execute(
        f"SELECT s1.start_ts, s1.sum, s2.sum FROM statistics s1 "
        f"JOIN statistics s2 ON s1.metadata_id = s2.metadata_id AND s2.start_ts = s1.start_ts - 3600 "
        f"WHERE s1.metadata_id = ? AND s1.start_ts = ?",
        (ECOJOKO_ID, ts)
    )
    row_eco = cur.fetchone()

    if row_surplus and row_eco:
        _, sum_t, sum_t_1 = row_surplus
        _, eco_t, eco_t_1 = row_eco
        conso_delta = sum_t - sum_t_1
        eco_delta = eco_t - eco_t_1
        delta_kwh = round_to_step(eco_delta - conso_delta)

        print(f"    - Surplus Δ : {conso_delta:.3f} kWh")
        print(f"    - Ecojoko Δ : {eco_delta:.3f} kWh")
        print(f"    - Correction à appliquer (horaires) : {delta_kwh:+.3f} kWh")

        # Application de la correction horaire dans la base de données
        if abs(delta_kwh) >= min_diff_kwh:  # Si la correction est significative
            cur.execute(
                "SELECT start_ts, sum FROM statistics "
                "WHERE metadata_id = ? AND start_ts = ?",
                (SURPLUS_ID, ts)
            )
            row_to_update = cur.fetchone()
            if row_to_update:
                old_sum = row_to_update[1]
                new_sum = round(old_sum + delta_kwh, 3)
                print(f"🔍 Mise à jour horaire : ts={ts}, old={old_sum}, new={new_sum}")
                cur.execute(
                    "UPDATE statistics SET sum = ? WHERE metadata_id = ? AND start_ts = ?",
                    (new_sum, SURPLUS_ID, ts)
                )
                print(f"↪️  SQLite rowcount = {cur.rowcount}")
                all_updates.append({
                    "type": "SURPLUS", "level": "horaire",
                    "start_ts": ts,
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    "old": old_sum, "new": new_sum, "delta": delta_kwh
                })
    else:
        print("    ⚠️ Données horaires manquantes pour cette heure.")

    # Vérification 5 minutes
    ts_utc = to_utc_ts(ts)
    surplus_5min = get_actual_tranches(cur, SURPLUS_ID, ts_utc)
    eco_5min = get_actual_tranches(cur, ECOJOKO_ID, ts_utc)
    expected = get_expected_tranches(ts_utc)

    df_rows = []
    for t in expected:
        dt = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(LOCAL_TZ)
        df_rows.append({
            "start_ts": t,
            "datetime": dt,
            "surplus": surplus_5min.get(t),
            "eco": eco_5min.get(t)
        })
    df = pd.DataFrame(df_rows)

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        if pd.isna(row["surplus"]) or pd.isna(prev["surplus"]):
            continue
        if pd.isna(row["eco"]):
            continue

        delta_surplus = row["surplus"] - prev["surplus"]
        delta_eco = row["eco"] - prev["eco"]
        ecart = round_to_step(delta_eco - delta_surplus)

        correction = round_to_step(ecart, step=rounding_step_kwh)
        if abs(correction) < min_diff_kwh:
            continue

        print(f"➡️ Correction globale {correction:+.3f} kWh à partir de {row['datetime'].strftime('%H:%M:%S')} (UTC+2)")
        start_ts_key = int(row["start_ts"])
        # Appliquer la correction à toutes les tranches 5min >= start_ts de la ligne courante
        cur.execute(
            "SELECT start_ts, sum FROM statistics_short_term "
            "WHERE metadata_id = ? AND start_ts >= ? ORDER BY start_ts",
            (SURPLUS_ID, start_ts_key)
        )
        rows_to_update = cur.fetchall()

        for start_ts_update, sum_val in rows_to_update:
            new_sum = round(sum_val + correction, 3)

            print(f"🔍 Mise à jour prévue : ts={start_ts_update}, old={sum_val}, new={new_sum}")
            cur.execute(
                "UPDATE statistics_short_term SET sum = ? WHERE metadata_id = ? AND start_ts = ?",
                (new_sum, SURPLUS_ID, start_ts_update)
            )
            print(f"↪️  SQLite rowcount = {cur.rowcount}")
            all_updates.append({
                "type": "SURPLUS", "level": "5min",
                "start_ts": start_ts_update,
                "timestamp": datetime.fromtimestamp(start_ts_update, tz=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "old": sum_val, "new": new_sum, "delta": correction
            })

# Finalisation
conn.commit()
conn.close()

if all_updates:
    df_log = pd.DataFrame(all_updates)
    header = not os.path.exists(CSV_LOG)
    df_log.to_csv(CSV_LOG, mode='a', header=header, index=False)

print(f"\n📦 Corrections historisées : {len(all_updates)} ligne(s)", flush=True)
