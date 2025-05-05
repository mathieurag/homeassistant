import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import math

# Configuration
DB_PATH = "/config/home-assistant_v2.db"
CSV_LOG = "/config/corrections_surplus.csv"
ANALYSE_MODE = "last_hour"  # "last_hour" ou "since_midnight"
ANALYSE_MODE = "since_midnight"  # "last_hour" ou "since_midnight"
SURPLUS_ID = 490
ECOJOKO_ID = 497
min_diff_kwh = 0.01
max_delta_kwh = 1000
rounding_step_kwh = 0.01
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

# Connexion DB
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
all_updates = []

now = datetime.now(LOCAL_TZ)
now_ts = int(now.timestamp())
hour_starts = get_hour_starts_to_analyze(now_ts)
placeholders = ','.join('?' for _ in hour_starts)

cur.execute(
    f"SELECT s1.start_ts, s1.sum, s2.sum FROM statistics s1 "
    f"JOIN statistics s2 ON s1.metadata_id = s2.metadata_id AND s2.start_ts = s1.start_ts - 3600 "
    f"WHERE s1.metadata_id = ? AND s1.start_ts IN ({placeholders}) ORDER BY s1.start_ts",
    (SURPLUS_ID, *hour_starts)
)
surplus_data = cur.fetchall()

if not surplus_data:
    print("\n⚠️ Aucune donnée disponible dans 'statistics' pour le surplus sur la période analysée.")

cur.execute(
    f"SELECT s1.start_ts, s1.sum, s2.sum FROM statistics s1 "
    f"JOIN statistics s2 ON s1.metadata_id = s2.metadata_id AND s2.start_ts = s1.start_ts - 3600 "
    f"WHERE s1.metadata_id = ? AND s1.start_ts IN ({placeholders})",
    (ECOJOKO_ID, *hour_starts)
)
eco_data = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

if not eco_data:
    print("⚠️ Aucune donnée disponible dans 'statistics' pour Ecojoko sur la période analysée.")

for ts, sum_t, sum_t_1 in surplus_data:
    ts_local = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
    print(f"\n🕓 Analyse prévue : {ts_local:%Y-%m-%d %H:%M:%S}")

    if ts not in eco_data:
        print(f"❌ Données manquantes pour Ecojoko à cette heure → comparaison impossible.")
        continue

    eco_t, eco_t_1 = eco_data[ts]

    conso_delta = (sum_t - sum_t_1)
    eco_delta = eco_t - eco_t_1
    delta_kwh = round_to_step(eco_delta - conso_delta)
    delta_rest = delta_kwh

    print(f"    - Surplus Δ : {conso_delta:.3f} kWh")
    print(f"    - Ecojoko Δ : {eco_delta:.3f} kWh")
    print(f"    - Correction à appliquer : {delta_kwh:+.3f} kWh")

    actual = get_actual_tranches(cur, SURPLUS_ID, ts)
    expected = get_expected_tranches(ts)
    df_rows = []
    for t in expected:
        dt = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(LOCAL_TZ)
        df_rows.append({"start_ts": t, "datetime": dt, "sum": actual.get(t)})
    df = pd.DataFrame(df_rows)

    corrections = []

    if abs(delta_kwh) < min_diff_kwh:
        print(f"➡️  Ignoré : écart < {min_diff_kwh} kWh")
        continue
    if abs(delta_kwh) > max_delta_kwh:
        print(f"⛔ Ignoré : écart > {max_delta_kwh} kWh (suspect)")
        continue

    # Correction horaire
    cur.execute("SELECT start_ts, sum FROM statistics WHERE metadata_id=? AND start_ts >= ? ORDER BY start_ts", (SURPLUS_ID, ts))
    future = cur.fetchall()
    for start_ts_f, sum_f in future:
        new_sum = round(sum_f + delta_kwh, 3)
        cur.execute("UPDATE statistics SET sum=? WHERE metadata_id=? AND start_ts=?", (new_sum, SURPLUS_ID, start_ts_f))
        ts_local_f = datetime.fromtimestamp(start_ts_f, tz=LOCAL_TZ)
        all_updates.append({
            "type": "SURPLUS", "level": "hourly", "start_ts": start_ts_f,
            "timestamp": ts_local_f.strftime("%Y-%m-%d %H:%M:%S"),
            "old": sum_f, "new": new_sum, "delta": delta_kwh
        })

    print(f"✅ Correction horaire appliquée : {delta_kwh:+.3f} kWh")

    total_applique = 0.0

    if delta_kwh > 0:
        part = math.ceil((delta_kwh / 12) / rounding_step_kwh) * rounding_step_kwh
        part = round_to_step(part)
        needed = math.ceil(delta_kwh / part)
        for i in range(min(needed, len(df))):
            row = df.iloc[i]
            if pd.isna(row["sum"]): continue
            if delta_rest < rounding_step_kwh: break

            sum_now = row["sum"]
            prev_sum = df.iloc[i - 1]["sum"] if i > 0 and not pd.isna(df.iloc[i - 1]["sum"]) else sum_now
            delta_avant = (sum_now - prev_sum)

            new_sum = round(sum_now + part, 3)
            cur.execute("UPDATE statistics_short_term SET sum=? WHERE metadata_id=? AND start_ts=?",
                        (new_sum, SURPLUS_ID, row["start_ts"]))

            delta_apres = (new_sum - prev_sum)
            corrections.append(f"        • {row['datetime'].strftime('%H:%M')} → Δ: {delta_avant:.3f} → {delta_apres:.3f} kWh (+{part:.3f})")

            total_applique += part
            delta_rest -= part
            all_updates.append({
                "type": "SURPLUS", "level": "5min",
                "start_ts": row["start_ts"],
                "timestamp": row["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                "old": sum_now, "new": new_sum, "delta": part
            })

    else:
        for i, row in df.iterrows():
            if pd.isna(row["sum"]): continue
            sum_now = row["sum"]
            prev_sum = df.iloc[i - 1]["sum"] if i > 0 and not pd.isna(df.iloc[i - 1]["sum"]) else sum_now
            delta_avant = (sum_now - prev_sum)

            if delta_avant <= 0:
                corrections.append(f"        • {row['datetime'].strftime('%H:%M')} → Δ: {delta_avant:.3f} kWh → Ignorée (déjà nulle ou négative)")
                continue

            max_possible = round_to_step(delta_avant)
            correction = min(abs(delta_rest), max_possible)
            correction = round_to_step(correction)

            if correction <= 0:
                continue

            corr = -correction
            new_sum = round(sum_now + corr, 3)
            cur.execute("UPDATE statistics_short_term SET sum=? WHERE metadata_id=? AND start_ts=?",
                        (new_sum, SURPLUS_ID, row["start_ts"]))
            delta_apres = (new_sum - prev_sum)

            corrections.append(f"        • {row['datetime'].strftime('%H:%M')} → Δ: {delta_avant:.3f} → {delta_apres:.3f} kWh ({corr:+.3f})")

            total_applique += corr
            delta_rest -= correction

            all_updates.append({
                "type": "SURPLUS", "level": "5min",
                "start_ts": row["start_ts"],
                "timestamp": row["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                "old": sum_now, "new": new_sum, "delta": corr
            })

            if abs(delta_rest) < rounding_step_kwh:
                break

    if abs(total_applique) > 0:
        print(f"✅ Correction 5min appliquée : {total_applique:+.3f} kWh")
    else:
        print(f"❗ Impossible d’appliquer {delta_kwh:+.3f} kWh sans générer de consommation incohérente.")

    for c in corrections:
        print(c)

# Finalisation
conn.commit()
conn.close()

if all_updates:
    df_log = pd.DataFrame(all_updates)
    header = not os.path.exists(CSV_LOG)
    df_log.to_csv(CSV_LOG, mode='a', header=header, index=False)

print(f"\n📦 Corrections historisées : {len(all_updates)} ligne(s)", flush=True)

