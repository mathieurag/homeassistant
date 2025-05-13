import sqlite3
import json
from datetime import datetime
import paho.mqtt.publish as publish

# --- CONFIGURATION ---
DB_PATH = "/config/home-assistant_v2.db"
SENSOR_ID = "sensor.previsions_solaires_json"
step_hours = 0.25  # Pas horaire : 15 minutes

# Priorité (True = ECS prioritaire, False = Batterie prioritaire)
PRIORITE_ECS = False

volume_eau_l = 200
temp_init = 43
temp_cible = 60
soc_depart = 25
cap_batterie_kwh = 5.12
puissance_max_ecs = 2000
rendement_ecs = 0.95
rendement_bat = 0.90
surplus_ecs_w = 100
surplus_bat_w = 100
conso_maison_w = 300
epsilon = 0.01

CORRECTION_PV = 0.85  # Correction prévision solaire

# --- CONNEXION DB ---
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# --- CONNEXION MQTT ---
def publish_mqtt(topic, payload):
    publish.single(
        topic,
        payload=json.dumps(payload),
        hostname="localhost",
        port=1883,
        client_id="simu_pv",
        retain=True,
        auth={"username": "mqtt", "password": "mqtt"}
    )

# --- FONCTION D'ETAT ---
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
            try:
                return float(val)
            except:
                pass
    return default

# --- PARAMETRES DYNAMIQUES ---
puissance_max_batt = get_state("number.esphome_web_a92940_marstek_max_charge_power", 2000)
soc_max = get_state("number.esphome_web_a92940_marstek_charging_cutoff_capacity", 98)

# --- CHARGER LES PREVISIONS ---
cursor.execute("""
    SELECT state FROM states s
    JOIN states_meta sm ON s.metadata_id = sm.metadata_id
    WHERE sm.entity_id = ?
    ORDER BY s.state_id DESC
    LIMIT 1
""", (SENSOR_ID,))
row = cursor.fetchone()

if not row or not row[0] or row[0].lower() in ("unavailable", "unknown", "null"):
    print("❌ Donnée indisponible")
    exit(0)

try:
    hourly_production = [float(v.strip()) * CORRECTION_PV for v in row[0].split(",") if v.strip()]
    hourly_production_brute = [float(v.strip()) for v in row[0].split(",") if v.strip()]
    production_brute_kwh = round(sum(hourly_production_brute), 2)
except Exception as e:
    print("❌ Erreur parsing JSON :", e)
    exit(1)

# --- CONVERSION EN PAS DE 15 MIN ---
steps_per_hour = int(1 / step_hours)
production_kwh = []
for val in hourly_production:
    production_kwh.extend([val / steps_per_hour] * steps_per_hour)

# --- CALCULS INITIAUX ---
energie_ecs_kwh = round(((volume_eau_l * 4180 * (temp_cible - temp_init)) / 3600000) / rendement_ecs, 2)
energie_bat_kwh = round(((soc_max - soc_depart) / 100) * cap_batterie_kwh / rendement_bat, 2)
production_totale_kwh = round(sum(production_kwh), 2)

ecs_ok = False
bat_ok = False
ecs_fin = None
bat_fin = None
ecs_consomme = 0.0
bat_consomme = 0.0
surplus_ecs_kwh = 0.0
surplus_bat_kwh = 0.0

hour = 7.0
for prod in production_kwh:
    if hour >= 20:
        break

    prod_step_kwh = prod
    reserve_kwh = (surplus_ecs_w + surplus_bat_w + conso_maison_w) * step_hours / 1000
    dispo_kwh = max(prod_step_kwh - reserve_kwh, 0)
    dispo_wh = dispo_kwh * 1000

    if PRIORITE_ECS:
        if not ecs_ok:
            wh_restant = (energie_ecs_kwh - ecs_consomme) * 1000
            wh_ecs_possible = min(dispo_wh, puissance_max_ecs * step_hours)
            wh_appli = min(wh_ecs_possible, wh_restant)
            ecs_consomme += wh_appli / 1000
            dispo_wh -= wh_appli
            surplus_ecs_kwh += (wh_ecs_possible - wh_appli) / 1000
            if (energie_ecs_kwh - ecs_consomme) < epsilon:
                ecs_ok = True
                ecs_fin = hour
        if ecs_ok and not bat_ok:
            wh_restant_bat = (energie_bat_kwh - bat_consomme) * 1000
            wh_bat_possible = min(dispo_wh, puissance_max_batt * step_hours)
            wh_appli = min(wh_bat_possible, wh_restant_bat)
            bat_consomme += wh_appli / 1000
            surplus_bat_kwh += (wh_bat_possible - wh_appli) / 1000
            if (energie_bat_kwh - bat_consomme) < epsilon:
                bat_ok = True
                bat_fin = hour
    else:
        if not bat_ok:
            wh_restant_bat = (energie_bat_kwh - bat_consomme) * 1000
            wh_bat_possible = min(dispo_wh, puissance_max_batt * step_hours)
            wh_appli = min(wh_bat_possible, wh_restant_bat)
            bat_consomme += wh_appli / 1000
            dispo_wh -= wh_appli
            surplus_bat_kwh += (wh_bat_possible - wh_appli) / 1000
            if (energie_bat_kwh - bat_consomme) < epsilon:
                bat_ok = True
                bat_fin = hour
        if not ecs_ok:
            wh_restant = (energie_ecs_kwh - ecs_consomme) * 1000
            wh_ecs_possible = min(dispo_wh, puissance_max_ecs * step_hours)
            wh_appli = min(wh_ecs_possible, wh_restant)
            ecs_consomme += wh_appli / 1000
            surplus_ecs_kwh += (wh_ecs_possible - wh_appli) / 1000
            if (energie_ecs_kwh - ecs_consomme) < epsilon:
                ecs_ok = True
                ecs_fin = hour

    hour += step_hours

# --- PERTE ET ESTIMATIONS ---
perte_ecs_kwh = round(ecs_consomme * (1 - rendement_ecs), 2)
perte_bat_kwh = round(bat_consomme * (1 - rendement_bat), 2)
temp_ecs_estimee = round(temp_init + (ecs_consomme * rendement_ecs * 3600000) / (volume_eau_l * 4180), 1)
soc_estime = round(soc_depart + (bat_consomme * rendement_bat * 100 / cap_batterie_kwh), 1)
conso_maison_kwh = round(conso_maison_w * (hour - 7.0) / 1000, 2)
surplus_final_kwh = round(production_totale_kwh - ecs_consomme - bat_consomme - conso_maison_kwh, 2)

# Répartition horaire batterie (jusqu'à bat_fin si bat_ok, sinon jusqu'à fin journée)
energie_bat_par_heure = []
prod_totale_bat = 0.0
for i, prod in enumerate(hourly_production):
    heure_actuelle = 7.0 + i * step_hours
    if bat_ok and heure_actuelle > bat_fin:
        energie_bat_par_heure.append(0.0)
    else:
        prod_totale_bat += prod
        energie_bat_par_heure.append(prod)

if prod_totale_bat > 0:
    energie_bat_par_heure = [round(bat_consomme * (p / prod_totale_bat), 3) if p > 0 else 0.0 for p in energie_bat_par_heure]
else:
    energie_bat_par_heure = [0.0] * len(hourly_production)

# Répartition horaire ECS (jusqu'à ecs_fin si ecs_ok, sinon jusqu'à fin journée)
energie_ecs_par_heure = []
prod_totale_ecs = 0.0
for i, prod in enumerate(hourly_production):
    heure_actuelle = 7.0 + i * step_hours
    if ecs_ok and heure_actuelle > ecs_fin:
        energie_ecs_par_heure.append(0.0)
    else:
        prod_totale_ecs += prod
        energie_ecs_par_heure.append(prod)

if prod_totale_ecs > 0:
    energie_ecs_par_heure = [round(ecs_consomme * (p / prod_totale_ecs), 3) if p > 0 else 0.0 for p in energie_ecs_par_heure]
else:
    energie_ecs_par_heure = [0.0] * len(hourly_production)

# --- RESULTATS ---
result = {
    "date": str(datetime.now().date()),
    "derniere_actualisation": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    "temp_init": temp_init,
    "soc_init": soc_depart,
    "production_prevue_kwh": round(production_brute_kwh,1),
    "production_totale_kwh": round(production_totale_kwh,1),
    "energie_ecs_kwh": round(energie_ecs_kwh, 2),
    "energie_bat_kwh": round(energie_bat_kwh, 2),
    "total_ecs_kwh": round(ecs_consomme, 2),
    "total_bat_kwh": round(bat_consomme, 2),
    "ecs_ok": ecs_ok,
    "ecs_fin_heure": round(ecs_fin, 2) if ecs_ok else None,
    "ecs_temp_estimee": temp_ecs_estimee if not ecs_ok else None,
    "bat_ok": bat_ok,
    "bat_fin_heure": round(bat_fin, 2) if bat_ok else None,
    "bat_soc_estime": soc_estime if not bat_ok else None,
    "batterie_par_heure": energie_bat_par_heure,
    "ecs_par_heure": energie_ecs_par_heure,
    "perte_ecs_kwh": perte_ecs_kwh,
    "perte_bat_kwh": perte_bat_kwh,
    "surplus_ecs_kwh": round(surplus_ecs_kwh, 2),
    "surplus_bat_kwh": round(surplus_bat_kwh, 2),
    "conso_maison_kwh": conso_maison_kwh,
    "surplus_final_kwh": surplus_final_kwh
}

print("\n[SIMULATION SOLAIRE TERMINEE]")
print(json.dumps(result, indent=2))

# --- EXPORT MQTT ---
publish_mqtt("homeassistant/simulation/solaire", result)
