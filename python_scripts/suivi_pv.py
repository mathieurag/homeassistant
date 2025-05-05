import sqlite3
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import paho.mqtt.publish as publish
from paho.mqtt.subscribe import simple
from time import time

# --- CONFIGURATION ---
DB_PATH = "/config/home-assistant_v2.db"
MQTT_TOPIC = "homeassistant/suivi/solaire"
CORRECTION_PREVISION = 1
MQTT_CONFIG = {
    "hostname": "localhost",
    "port": 1883,
    "client_id": "suivi_pv",
    "retain": True,
    "auth": {
        "username": "mqtt",
        "password": "mqtt"
    }
}

# Paramètres ECS
entite_temp_init = "sensor.sonde_temperature_owon_temperature"
entite_temp_cible = "input_number.tmax_ecs"

# --- CONNEXION DB ---
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# --- OUTILS MQTT  ---

def get_simulation_data_from_mqtt():
    try:
        msg = simple(
            topics=["homeassistant/simulation/solaire"],
            hostname="localhost",
            port=1883,
            auth={'username': 'mqtt', 'password': 'mqtt'},
            retained=True
        )
        return json.loads(msg.payload.decode())
    except Exception as e:
        print("❌ Erreur récupération MQTT :", e)
        return {}

# --- RÉCUPÉRATION DES PRÉVISIONS SIMULÉES ---
simu = get_simulation_data_from_mqtt()

forecast_production = simu.get("production_par_heure", [])
heure_debut = simu.get("heure_debut", 0)
heure_fin = simu.get("heure_fin", heure_debut + len(forecast_production) - 1)

heure_debut = simu.get("heure_debut", 7)
heure_fin = simu.get("heure_fin", heure_debut + len(forecast_production) - 1)

volume_eau_l = simu.get("volume_eau_l",200)
rendement_ecs = simu.get("rendement_ecs",0.95)

# --- OUTILS DB ---

def get_sum_at_local_hour(entity_id, heure):
    dt_local = datetime.now().replace(hour=heure, minute=0, second=0, microsecond=0)
    dt_local = dt_local.replace(tzinfo=ZoneInfo("Europe/Paris"))
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))
    timestamp = int(dt_utc.timestamp())

    cursor.execute("""
        SELECT sum FROM statistics
        JOIN statistics_meta sm ON statistics.metadata_id = sm.id
        WHERE sm.statistic_id = ?
        AND statistics.start_ts = ?
        AND statistics.created_ts >= ?
        LIMIT 1
    """, (entity_id, timestamp, timestamp))  # On s'assure que la donnée est du jour
    row = cursor.fetchone()
    return float(row[0]) if row and row[0] else None

def calculate_ecart(theo, reel):
    ecart = round(reel - theo, 3)
    ecart_pct = round((ecart / theo) * 100, 1) if theo else 0.0
    return ecart, ecart_pct

def get_first_time_threshold_reached(entity_id, ts_start, ts_end, seuil_min):
    cursor.execute("""
        SELECT MIN(s.last_updated_ts)
        FROM states s
        JOIN states_meta sm ON sm.metadata_id = s.metadata_id
        WHERE sm.entity_id = ?
        AND s.last_updated_ts BETWEEN ? AND ?
        AND CAST(s.state AS FLOAT) >= ?
    """, (entity_id, ts_start, ts_end, seuil_min))
    row = cursor.fetchone()
    if row and row[0]:
        return datetime.fromtimestamp(row[0], tz=ZoneInfo("Europe/Paris")).strftime("%H:%M")
    return None

# --- GET STATE ---
def get_state(entity_id, default=0.0):
    cursor.execute("""
        SELECT state FROM states s
        JOIN states_meta sm ON s.metadata_id = sm.metadata_id
        WHERE sm.entity_id = ?
        ORDER BY s.state_id DESC
        LIMIT 1
    """, (entity_id,))
    row = cursor.fetchone()
    if row:
        val = row[0]
        if val and val.lower() not in ("unavailable", "unknown", "null", ""):
            if val.lower() in ("on", "off"):
                return val.lower() == "on"
            try:
                return float(val)
            except:
                pass
    return default


def analyse_entite(id, previsions, unite="Wh"):
    facteur = 1/1000 if unite.lower() == "wh" else 1
    now_hour = datetime.now().hour
    result = {
        "unit": unite,
        "items": {},
        "total": {},
        "debug": {
            "forecast_corrige": previsions
        }
    }

    total_prevision = 0.0
    total_mesure = 0.0

    for heure in range(heure_debut, min(heure_fin + 1, now_hour)):
        index = heure - heure_debut
        prevision = previsions[index] if index < len(previsions) else 0.0

        sum_h = get_sum_at_local_hour(id, heure)
        sum_hm1 = get_sum_at_local_hour(id, heure - 1)
        mesure = round((sum_h - sum_hm1) * facteur, 3) if sum_h and sum_hm1 and sum_h >= sum_hm1 else 0.0

        ecart, ecart_pct = calculate_ecart(prevision, mesure)

        result["items"][f"{heure}h"] = {
            "prevision": round(prevision, 3),
            "mesure": mesure,
            "ecart": ecart,
            "ecart_pct": ecart_pct
        }


        total_prevision += prevision
        total_mesure += mesure

    total_ecart, total_ecart_pct = calculate_ecart(total_prevision, total_mesure)
    rendement = round((total_mesure / total_prevision) * 100, 1) if total_prevision else 0.0

    result["total"] = {
        "prevision": round(total_prevision, 3),
        "mesure": round(total_mesure, 3),
        "ecart": total_ecart,
        "ecart_pct": total_ecart_pct,
        "rendement_reel_vs_prevu": rendement
    }

    return result

result = {
    "date": str(datetime.now().date()),
    "derniere_actualisation": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    "correction_appliquee": CORRECTION_PREVISION,
    "heure_debut": heure_debut,
    "heure_fin": heure_fin,
    "entites": {}
}

def convertir_items_en_series(items: dict, champ: str) -> list:
    date_du_jour = datetime.now().date()
    series = []
    for heure_str, valeurs in items.items():
        heure = int(heure_str.replace("h", ""))
        horodatage = datetime.combine(date_du_jour, datetime.min.time()) + timedelta(hours=heure)
        series.append({
            "x": horodatage.isoformat(),
            "y": round(valeurs.get(champ, 0.0), 3)
        })
    return series

# --- EXTRACTION DES PRÉVISIONS SIMULÉES ---

forecast_production = simu.get("production_par_heure", [])
forecast_ecs = simu.get("ecs_par_heure", [])
forecast_batterie = simu.get("batterie_par_heure", [])
forecast_maison = simu.get("maison_par_heure", [])
forecast_surplus = simu.get("surplus_par_heure", [])


# --- PRODUCTION SOLAIRE ---
result["entites"]["production"] = analyse_entite("sensor.energie_solar_j", forecast_production, "Wh")

# --- ECS ---
result["entites"]["ecs"] = analyse_entite("sensor.cumulus_kwh", forecast_ecs, "kWh")
result["entites"]["ecs"]["T_init"] = simu.get("temp_init", "n/a")
result["entites"]["ecs"]["T_cible"] = 60
result["entites"]["ecs"]["energie_theorique_kwh"] = simu.get("energie_ecs_kwh", 0.0)

# --- BATTERIE ---
result["entites"]["batterie"] = analyse_entite("sensor.esphome_web_a92940_marstek_daily_charging_energy",forecast_batterie,"kWh")

# --- MAISON ---
result["entites"]["maison"] = analyse_entite("sensor.energie_maison", forecast_maison, "kWh")

# --- SURPLUS ---
result["entites"]["surplus"] = analyse_entite("sensor.ecojoko_surplus_de_production", forecast_surplus, "kWh")
result["entites"]["surplus"]["estime_total"] = simu.get("surplus_total_kwh", 0.0)

# --- FINS REELLES ---
ts_now = int(time())
ts_debut = int(datetime.now().replace(hour=heure_debut, minute=0, second=0, microsecond=0).replace(tzinfo=ZoneInfo("Europe/Paris")).timestamp())

# Seuils cibles avec tolérance 1%
temp_cible = get_state("input_number.tmax_ecs", 60.0)
soc_cible = get_state("number.esphome_web_a92940_marstek_charging_cutoff_capacity", 98.0)

temp_seuil = round(temp_cible * 0.99, 2)
soc_seuil = round(soc_cible * 0.99, 2)

ecs_fin_reelle = get_first_time_threshold_reached("sensor.sonde_temperature_owon_temperature", ts_debut, ts_now, temp_seuil)
bat_fin_reelle = get_first_time_threshold_reached("sensor.esphome_web_a92940_marstek_battery_state_of_charge", ts_debut, ts_now, soc_seuil)

print("Prévision simulation ECS :", ecs_fin_reelle)
print("Prévision simulation BAT :", bat_fin_reelle)

result["entites"]["ecs"]["heure_fin_reelle"] = ecs_fin_reelle
result["entites"]["batterie"]["heure_fin_reelle"] = bat_fin_reelle

# --- SIMULATION CONDITIONS REELLES ---

soc_actuel = get_state("sensor.marstek_battery_state_of_charge", 0.0)
temp_ecs_actuelle = get_state("sensor.sonde_temperature_owon_temperature", 30.0)

# Paramètres
rendement_bat = simu.get("rendement_bat", 0.95)
rendement_ecs = simu.get("rendement_ecs", 0.95)
cap_batt_kwh = simu.get("cap_batt_kwh",5.12)
volume_eau = simu.get("volume_eau",200)
puissance_max_batt = simu.get("puissance_max_batt",2400)
puissance_max_ecs = simu.get("puissance_max_ecs",2000)

soc_target = get_state("number.esphome_web_a92940_marstek_charging_cutoff_capacity", 98)
temp_target = get_state("input_number.tmax_ecs", 60)

energie_restante_kwh = get_state("sensor.solcast_pv_forecast_previsions_de_production_restantes_aujourd_hui", 0.0)
prod_simulee = simu.get("production_par_heure", [])
heure_actuelle = datetime.now().hour
minute_now = datetime.now().minute
index_courant = heure_actuelle - heure_debut

puissance_max_batt_kw = puissance_max_batt / 1000
puissance_max_ecs_kw = puissance_max_ecs / 1000
pas = 0.25  # résolution 1h

energie_ecs_restant = max(0, ((volume_eau * 4180 * (temp_target - temp_ecs_actuelle)) / 3600000) / rendement_ecs)
energie_batt_restant = max(0, ((soc_target - soc_actuel) / 100) * cap_batt_kwh / rendement_bat)

# Distribution horaire basée sur simulation
prod_restante = prod_simulee[index_courant:] if index_courant < len(prod_simulee) else []
total_simule = sum(prod_restante)
distribution = [round((p / total_simule) * energie_restante_kwh, 3) if total_simule > 0 else 0 for p in prod_restante]

# Appliquer la quote-part sur l'heure en cours
if len(distribution) > 0:
    distribution[0] = round(distribution[0] * ((60 - minute_now) / 60), 3)

# Estimation boucle
estime_soc = soc_actuel
estime_temp = temp_ecs_actuelle
energie_batt_cumulee = 0.0
energie_ecs_cumulee = 0.0
heure_fin_batt = None
heure_fin_ecs = None

for i, dispo_kwh in enumerate(distribution):
    heure = heure_actuelle + i
    disponible = dispo_kwh

    # Batterie prioritaire
    if energie_batt_restant > 0:
        prise = min(disponible, puissance_max_batt_kw, energie_batt_restant)
        disponible -= prise
        energie_batt_cumulee += prise
        energie_batt_restant -= prise
        estime_soc += prise * rendement_bat * 100 / cap_batt_kwh
        if energie_batt_restant <= 0.01 and not heure_fin_batt:
            heure_fin_batt = heure

    # Ensuite ECS
    if energie_ecs_restant > 0:
        prise = min(disponible, puissance_max_ecs_kw, energie_ecs_restant)
        disponible -= prise
        energie_ecs_cumulee += prise
        energie_ecs_restant -= prise
        estime_temp += (prise * rendement_ecs * 3600000) / (volume_eau * 4180)
        if energie_ecs_restant <= 0.01 and not heure_fin_ecs:
            heure_fin_ecs = heure

# Ajout au résultat
result["entites"]["batterie"]["heure_fin_estimee_recalcul"] = heure_fin_batt
result["entites"]["ecs"]["heure_fin_estimee_recalcul"] = heure_fin_ecs

# Format date ISO pour graph APEX
result["series_batterie_prevu"] = convertir_items_en_series(result["entites"]["batterie"]["items"], "prevision")
result["series_batterie"] = convertir_items_en_series(result["entites"]["batterie"]["items"], "mesure")

result["series_production_prevu"] = convertir_items_en_series(result["entites"]["production"]["items"], "prevision")
result["series_production"] = convertir_items_en_series(result["entites"]["production"]["items"], "mesure")

result["series_maison_prevu"] = convertir_items_en_series(result["entites"]["maison"]["items"], "prevision")
result["series_maison"] = convertir_items_en_series(result["entites"]["maison"]["items"], "mesure")

result["series_ecs_prevu"] = convertir_items_en_series(result["entites"]["ecs"]["items"], "prevision")
result["series_ecs"] = convertir_items_en_series(result["entites"]["ecs"]["items"], "mesure")

result["series_surplus_prevu"] = convertir_items_en_series(result["entites"]["surplus"]["items"], "prevision")
result["series_surplus"] = convertir_items_en_series(result["entites"]["surplus"]["items"], "mesure")

# --- EXPORT MQTT ---
print("\n[SUIVI SOLAIRE + ECS + BATTERIE + MAISON]")
print(json.dumps(result, indent=2, ensure_ascii=False))
publish.single(MQTT_TOPIC, payload=json.dumps(result), **MQTT_CONFIG)
conn.close()
