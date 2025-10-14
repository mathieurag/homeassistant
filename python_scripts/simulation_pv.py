# SCRIPT DE SIMULATION SOLAIRE – VERSION CORRIGÉE (par pas)

import sqlite3
import json
from datetime import datetime
import paho.mqtt.publish as publish
from math import ceil

# --- CONFIGURATION ---
DB_PATH = "/config/home-assistant_v2.db"
SENSOR_ID = "sensor.previsions_solaires_json"
step_hours = 0.25  # Pas horaire : 15 minutes

# Priorité (True = ECS prioritaire, False = Batterie prioritaire)
PRIORITE_ECS = False

volume_eau_l = 200
temp_init_config = 30  # par défaut
entite_temp_init = "sensor.sonde_temperature_owon_temperature"
temp_cible = 60
soc_depart = 25
cap_batterie_kwh = 5.12
puissance_max_ecs = 2000
puissance_max_batterie = "number.esphome_web_a92940_marstek_max_charge_power"
rendement_ecs = 0.95
rendement_bat = 0.95
surplus_ecs_w = 0
surplus_bat_w = 0
perte_reseau_bat_w = 50
conso_maison_w = 200
soc_min = 18
conso_maison_nuit_w = 150

epsilon = 0.005
CORRECTION_PV = 1

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# --- MQTT ---
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

# --- PARAMETRES DYNAMIQUES ---

puissance_max_batt = get_state(puissance_max_batterie, 2000)
mode_absent = get_state("input_boolean.mode_absent", False)

# --- CHARGEMENT DES PREVISIONS ---
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

# --- RESTE DU SCRIPT INCHANGE (conserver la logique d’utilisation de `mode_absent`) ---
# Dans la boucle principale, ajouter une condition autour de l’ECS :
# if not mode_absent and not ecs_ok: ...


heure_debut = next((i for i, val in enumerate(hourly_production) if val >= epsilon), 0)
heure_fin = next((i for i in reversed(range(len(hourly_production))) if hourly_production[i] >= epsilon), len(hourly_production) - 1)

hourly_production = hourly_production[heure_debut:heure_fin+1]
hourly_production_brute = hourly_production_brute[heure_debut:heure_fin+1]

heure_actuelle = datetime.now().hour
soc_actuel = get_state("sensor.soc_estime_batterie", 25)
soc_min = get_state("number.esphome_web_a92940_marstek_discharging_cutoff_capacity", 18)
soc_max = get_state("number.esphome_web_a92940_marstek_charging_cutoff_capacity", 98)

if heure_actuelle >= heure_debut:
    now = datetime.now().replace(hour=heure_debut, minute=0, second=0, microsecond=0)
    ts_debut_prod = int(now.timestamp())
    cursor.execute("""
        SELECT state FROM states s
        JOIN states_meta sm ON s.metadata_id = sm.metadata_id
        WHERE sm.entity_id = ?
        AND s.last_updated_ts <= ?
        AND s.state NOT IN ('unknown', 'unavailable')
        ORDER BY s.last_updated_ts DESC
        LIMIT 1
    """, (entite_temp_init, ts_debut_prod))
    row = cursor.fetchone()
    temp_init = float(row[0]) if row else temp_init_config
    temp_init_mode = "mesurée"
else:
    temp_init = temp_init_config
    temp_init_mode = "fixée"

if heure_actuelle < heure_debut:
    heures_avant_prod = heure_debut - heure_actuelle
    conso_kwh = (conso_maison_nuit_w * heures_avant_prod) / 1000
    soc_perdu = (conso_kwh * 100) / cap_batterie_kwh
    soc_depart = max(soc_min, soc_actuel - soc_perdu)
    soc_depart_mode = "estimé"
else:
    now = datetime.now().replace(hour=heure_debut, minute=0, second=0, microsecond=0)
    ts_debut_prod = int(now.timestamp())
    cursor.execute("""
        SELECT state FROM states s
        JOIN states_meta sm ON s.metadata_id = sm.metadata_id
        WHERE sm.entity_id = ?
        AND s.last_updated_ts <= ?
        AND s.state NOT IN ('unknown', 'unavailable')
        ORDER BY s.last_updated_ts DESC
        LIMIT 1
    """, ("sensor.soc_estime_batterie", ts_debut_prod))
    row = cursor.fetchone()
    soc_depart = float(row[0]) if row else soc_actuel
    soc_depart_mode = "mesuré"

soc_depart = round(soc_depart, 1)
energie_bat_kwh = round(((soc_max - soc_depart) / 100) * cap_batterie_kwh / rendement_bat, 2)

print(f"🔋 SOC départ ({soc_depart_mode}) = {soc_depart}% (SOC actuel = {soc_actuel}%)")
print(f"🌡 Température initiale ECS ({temp_init_mode}) = {temp_init}°C")

steps_per_hour = int(1 / step_hours)
production_kwh = []
for val in hourly_production:
    production_kwh.extend([val / steps_per_hour] * steps_per_hour)

production_totale_kwh = round(sum(production_kwh), 2)
energie_ecs_kwh = round(((volume_eau_l * 4180 * (temp_cible - temp_init)) / 3600000) / rendement_ecs, 2)

# --- INITIALISATION DYNAMIQUE ---
ecs_ok = False
bat_ok = False
ecs_fin = None
bat_fin = None
ecs_consomme = 0.0
bat_consomme = 0.0

# --- NOUVELLE APPROCHE PAR PAS ---
ecs_par_pas = []
bat_par_pas = []
maison_par_pas = []
surplus_par_pas = []

hour = float(heure_debut)
for prod in production_kwh:
    prod_step_kwh = prod
    maison_kwh = conso_maison_w * step_hours / 1000
    maison_par_pas.append(maison_kwh)

    reserve_kwh = (surplus_ecs_w + surplus_bat_w + conso_maison_w) * step_hours / 1000
    dispo_kwh = max(prod_step_kwh - reserve_kwh, 0)
    dispo_wh = dispo_kwh * 1000

    wh_appli_ecs = 0.0
    wh_appli_bat = 0.0

    if PRIORITE_ECS:
        if not mode_absent and not ecs_ok:
            wh_restant = (energie_ecs_kwh - ecs_consomme) * 1000
            wh_ecs_possible = min(dispo_wh, puissance_max_ecs * step_hours)
            wh_appli_ecs = min(wh_ecs_possible, wh_restant)
            ecs_consomme += wh_appli_ecs / 1000
            dispo_wh -= wh_appli_ecs
            if (energie_ecs_kwh - ecs_consomme) < epsilon:
                ecs_ok = True
                ecs_fin = hour
        if (ecs_ok or mode_absent) and not bat_ok:
            wh_restant_bat = (energie_bat_kwh - bat_consomme) * 1000
            wh_bat_possible = min(dispo_wh, puissance_max_batt * step_hours)
            wh_appli_bat = min(wh_bat_possible, wh_restant_bat)
            bat_consomme += wh_appli_bat / 1000
            dispo_wh -= wh_appli_bat
            if (energie_bat_kwh - bat_consomme) < epsilon:
                bat_ok = True
                bat_fin = hour
    else:
        if not bat_ok:
            wh_restant_bat = (energie_bat_kwh - bat_consomme) * 1000
            wh_bat_possible = min(dispo_wh, puissance_max_batt * step_hours)
            wh_appli_bat = min(wh_bat_possible, wh_restant_bat)
            bat_consomme += wh_appli_bat / 1000
            dispo_wh -= wh_appli_bat
            if (energie_bat_kwh - bat_consomme) < epsilon:
                bat_ok = True
                bat_fin = hour
        if not mode_absent and not ecs_ok:
            wh_restant = (energie_ecs_kwh - ecs_consomme) * 1000
            wh_ecs_possible = min(dispo_wh, puissance_max_ecs * step_hours)
            wh_appli_ecs = min(wh_ecs_possible, wh_restant)
            ecs_consomme += wh_appli_ecs / 1000
            dispo_wh -= wh_appli_ecs
            if (energie_ecs_kwh - ecs_consomme) < epsilon:
                ecs_ok = True
                ecs_fin = hour

    bat_par_pas.append(wh_appli_bat / 1000)
    ecs_par_pas.append(wh_appli_ecs / 1000)
    surplus_par_pas.append(round(max(dispo_wh / 1000, 0.0), 3))
    hour += step_hours

# --- AGREGER PAR HEURE ---
def agreger_par_heure(liste_par_pas, pas_par_heure):
    heures = ceil(len(liste_par_pas) / pas_par_heure)
    return [round(sum(liste_par_pas[i*pas_par_heure:(i+1)*pas_par_heure]), 3) for i in range(heures)]

pas_par_heure = int(1 / step_hours)
energie_ecs_par_heure = agreger_par_heure(ecs_par_pas, pas_par_heure)
energie_bat_par_heure = agreger_par_heure(bat_par_pas, pas_par_heure)
maison_par_heure = agreger_par_heure(maison_par_pas, pas_par_heure)
surplus_par_heure = agreger_par_heure(surplus_par_pas, pas_par_heure)

# --- ESTIMATIONS ---
perte_ecs_kwh = round(ecs_consomme * (1 - rendement_ecs), 2)
perte_bat_kwh = round(bat_consomme * (1 - rendement_bat), 2)
temp_ecs_estimee = round(temp_init + (ecs_consomme * rendement_ecs * 3600000) / (volume_eau_l * 4180), 1)
soc_estime = round(soc_depart + (bat_consomme * rendement_bat * 100 / cap_batterie_kwh), 1)
conso_maison_kwh = round(sum(maison_par_heure), 2)
surplus_final_kwh = round(sum(surplus_par_heure), 2)

# --- EVOLUTION SOC / TEMP ---

ecs_cumulee = 0.0
bat_cumulee = 0.0
# --- EVOLUTION SOC / TEMP ECS avec pertes dynamiques ---
temperature_ecs_par_heure = []
soc_par_heure = []
ecs_temp = temp_init
soc = soc_depart

for i in range(len(hourly_production)):
    # Gain thermique par l'énergie utilisée pour ECS
    gain = (energie_ecs_par_heure[i] * rendement_ecs * 3_600_000) / (volume_eau_l * 4180)

    # Calcul de la perte selon delta T
    delta_t = max(ecs_temp - get_state("sensor.meter_plus_6b44", 20), 0)  # température intérieure
    perte = (0.001 * delta_t**2 + 0.01 * delta_t)  # en °C/h

    # Mise à jour température et SOC
    ecs_temp = ecs_temp + gain - perte
    temperature_ecs_par_heure.append(round(ecs_temp, 1))

    soc += (energie_bat_par_heure[i] * rendement_bat * 100 / cap_batterie_kwh)
    soc_par_heure.append(round(soc, 1))


# --- EXPORT FINAL ---
result = {
    "date": str(datetime.now().date()),
    "derniere_actualisation": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    "heure_debut": heure_debut,
    "heure_fin": heure_fin,
    "temp_init": temp_init,
    "soc_init": soc_depart,
    "rendement_bat": rendement_bat,
    "rendement_ecs": rendement_ecs,
    "cap_batt_kwh": cap_batterie_kwh,
    "volume_eau_l": volume_eau_l,
    "puissance_max_ecs": puissance_max_ecs,
    "surplus_ecs_w": surplus_ecs_w,
    "surplus_bat_w": surplus_bat_w,
    "perte_reseau_bat_w": perte_reseau_bat_w,
    "conso_maison_w": conso_maison_w,
    "conso_maison_nuit_w": conso_maison_nuit_w,
    "production_prevue_kwh": round(production_brute_kwh, 1),
    "production_totale_kwh": round(production_totale_kwh, 1),
    "production_par_heure": [round(p, 3) for p in hourly_production],
    "energie_ecs_kwh": round(energie_ecs_kwh, 2),
    "total_ecs_kwh": round(ecs_consomme, 2),
    "ecs_par_heure": energie_ecs_par_heure,
    "ecs_ok": ecs_ok,
    "ecs_fin_heure": round(ecs_fin, 2) if ecs_ok else None,
    "ecs_temp_estimee": temp_ecs_estimee if not ecs_ok else None,
    "temperature_ecs_par_heure": temperature_ecs_par_heure,
    "energie_bat_kwh": round(energie_bat_kwh, 2),
    "total_bat_kwh": round(bat_consomme, 2),
    "batterie_par_heure": energie_bat_par_heure,
    "bat_ok": bat_ok,
    "bat_fin_heure": round(bat_fin, 2) if bat_ok else None,
    "bat_soc_estime": soc_estime if not bat_ok else None,
    "soc_par_heure": soc_par_heure,
    "maison_par_heure": maison_par_heure,
    "perte_ecs_kwh": perte_ecs_kwh,
    "perte_bat_kwh": perte_bat_kwh,
    "surplus_ecs_kwh": round(sum(surplus_par_pas), 2),
    "surplus_bat_kwh": 0.0,
    "conso_maison_kwh": conso_maison_kwh,
    "surplus_final_kwh": surplus_final_kwh,
    "surplus_par_heure": surplus_par_heure,
    "surplus_total_kwh": round(surplus_final_kwh, 2),
    "priorite_ecs": PRIORITE_ECS,
    "soc_actuel": round(soc_actuel, 1),
    "soc_depart_mode": soc_depart_mode,
    "conso_estimee_kwh_avant_prod": round(conso_kwh, 2) if heure_actuelle < heure_debut else 0.0,
    "heures_avant_prod": heure_debut - heure_actuelle if heure_actuelle < heure_debut else 0,
    "mode_absent": mode_absent
}

print("\n[SIMULATION SOLAIRE TERMINEE]")
print(json.dumps(result, indent=2))
publish_mqtt("homeassistant/simulation/solaire", result)
