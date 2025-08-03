import sqlite3
from datetime import datetime, timedelta, timezone
import pytz

# Configuration
DB_PATH = "/config/home-assistant_v2.db"
ENTITY_HP = "sensor.energie_consommee_j_hp"
ENTITY_HC = "sensor.energie_consommee_j_hc"
ENTITY_PROD = "sensor.em06_02_a1_this_month_energy"
ENTITY_SURPLUS = "sensor.surplus_production_kwh"
ENTITY_BATTERY = "sensor.decharge_marstek"
ENTITY_TARGET = "sensor.energie_generale"
TIMEZONE = "Europe/Paris"

START_DATE = datetime(2025, 4, 7, 20, 0)
END_DATE = datetime(2025, 5, 5, 14, 0)

WH_TO_KWH = 1 / 1000

# Connexion DB
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def get_metadata_id(entity_id):
    cursor.execute("SELECT id FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
    r = cursor.fetchone()
    return r[0] if r else None

meta_hp = get_metadata_id(ENTITY_HP)
meta_hc = get_metadata_id(ENTITY_HC)
meta_prod = get_metadata_id(ENTITY_PROD)
meta_surplus = get_metadata_id(ENTITY_SURPLUS)
meta_battery = get_metadata_id(ENTITY_BATTERY)
meta_target = get_metadata_id(ENTITY_TARGET)

if not meta_hp or not meta_hc or not meta_target:
    raise Exception("❌ Une ou plusieurs entités sont introuvables dans statistics_meta.")

tz = pytz.timezone(TIMEZONE)
inserted = 0

current_dt = tz.localize(START_DATE)

print(f"🔁 Insertion heure par heure de {START_DATE} à {END_DATE}")

while current_dt <= tz.localize(END_DATE):
    next_dt = current_dt + timedelta(hours=1)
    ts = int(current_dt.timestamp())-3600
    ts_next = int(next_dt.timestamp())-3600

    # Récupération HP
    cursor.execute("""
        SELECT MAX(sum) - MIN(sum) FROM statistics 
        WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?
    """, (meta_hp, ts, ts_next))
    delta_hp = cursor.fetchone()[0] or 0.0

    # Récupération HC
    cursor.execute("""
        SELECT MAX(sum) - MIN(sum) FROM statistics 
        WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?
    """, (meta_hc, ts, ts_next))
    delta_hc = cursor.fetchone()[0] or 0.0

    # Récupération PROD
    cursor.execute("""
        SELECT MAX(sum) - MIN(sum) FROM statistics 
        WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?
    """, (meta_prod, ts, ts_next))
    delta_prod = cursor.fetchone()[0] or 0.0

    # Récupération SURPLUS
    cursor.execute("""
        SELECT MAX(sum) - MIN(sum) FROM statistics 
        WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?
    """, (meta_surplus, ts, ts_next))
    delta_surplus = cursor.fetchone()[0] or 0.0

    # Récupération SURPLUS
    cursor.execute("""
        SELECT MAX(sum) - MIN(sum) FROM statistics 
        WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ?
    """, (meta_battery, ts, ts_next))
    delta_battery = cursor.fetchone()[0] or 0.0

    delta_total = (delta_hp + delta_hc)*WH_TO_KWH
    delta_conso = delta_prod*WH_TO_KWH - delta_surplus + delta_total + delta_battery

    # 🔍 Affichage des valeurs récupérées
    print(f"🧾 {current_dt.strftime('%Y-%m-%d %H:%M')} → P: {delta_prod*WH_TO_KWH:.3f} kWh, S: {delta_surplus:.3f} kWh, R: {delta_total:.3f} kWh, B: {delta_battery:.3f} kWh, C: {delta_conso:.3f} kWh")

    # Vérifier si ligne déjà existante
    cursor.execute("""
        SELECT 1 FROM statistics WHERE metadata_id = ? AND start_ts = ?
    """, (meta_target, ts))
    if cursor.fetchone():
        current_dt = next_dt
        continue

    # État (remis à zéro à minuit)
    state = delta_conso

    # Dernier sum connu (précédent)
    cursor.execute("""
        SELECT sum FROM statistics 
        WHERE metadata_id = ? AND start_ts < ? 
        ORDER BY start_ts DESC LIMIT 1
    """, (meta_target, ts))
    prev_sum = cursor.fetchone()
    sum_val = (prev_sum[0] if prev_sum else 0.0) + delta_conso

    cursor.execute("""
        INSERT INTO statistics (metadata_id, start_ts, state, sum)
        VALUES (?, ?, ?, ?)
    """, (meta_target, ts, round(state, 3), round(sum_val, 3)))
    inserted += 1

    current_dt = next_dt

conn.commit()
conn.close()

print(f"✅ Insertion terminée : {inserted} ligne(s) ajoutée(s).")
