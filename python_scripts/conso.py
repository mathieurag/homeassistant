import sqlite3
import json
from datetime import datetime
import paho.mqtt.publish as publish

# --- CONFIGURATION ---
DB_PATH = "/config/home-assistant_v2.db"
MQTT_HOST = "localhost"
MQTT_USER = "mqtt"
MQTT_PASS = "mqtt"
START_DATE = datetime(2024, 1, 1)
WH_TO_KWH = 1 / 1000

# --- Entités à analyser ---
ENTITIES = {
    "production": ("sensor.em06_02_a1_this_month_energy", "Wh"),
    "charge_batterie": ("sensor.charge_marstek", "kWh"),
    "decharge_batterie": ("sensor.decharge_marstek", "kWh"),
    "reseau_hc": ("sensor.energie_consommee_j_hc", "Wh"),
    "reseau_hp": ("sensor.energie_consommee_j_hp", "Wh"),
    "surplus": ("sensor.surplus_production_kwh", "kWh"),
    "linky": ("linky:16127930466069", "Wh")
}

# --- Granularités à traiter ---
GRANULARITES = {
    
    "month": {
        "strftime": "%Y-%m",
        "dt_format": "%Y-%m",
        "topic": "homeassistant/consommation/mois"
    },
    "year": {
        "strftime": "%Y",
        "dt_format": "%Y",
        "topic": "homeassistant/consommation/annee"
    },
    "day": {
        "strftime": "%Y-%m-%d",
        "dt_format": "%Y-%m-%d",
        "topic": "homeassistant/consommation/jour"
    },
    "week": {
        "strftime": "%Y-W%W",
        "dt_format": "%Y-W%W",
        "topic": "homeassistant/consommation/semaine"
    }
}

# --- Obtenir les metadata_id ---
def get_metadata_ids(cursor):
    ids = {}
    for nom, (entity, unit) in ENTITIES.items():
        cursor.execute("SELECT id FROM statistics_meta WHERE statistic_id = ?", (entity,))
        res = cursor.fetchone()
        if res:
            ids[nom] = res[0]
    return ids

# --- Analyse principale ---
def analyser_granularite(cursor, granularite, config, metadata_ids):
    print(f"\n🔎 Analyse {granularite.upper()}")
    strftime_fmt = config["strftime"]
    topic = config["topic"]

    placeholders = ','.join(['?'] * len(metadata_ids.values()))
    cursor.execute(f"""
        SELECT 
            strftime('{strftime_fmt}', datetime(start_ts, 'unixepoch')) as periode,
            metadata_id,
            MAX(sum) - MIN(sum)
        FROM statistics
        WHERE metadata_id IN ({placeholders})
        GROUP BY periode, metadata_id
        ORDER BY periode
    """, tuple(metadata_ids.values()))

    data = {}
    for periode, meta_id, energie in cursor.fetchall():
        if periode not in data:
            data[periode] = {}
        for nom, id_ in metadata_ids.items():
            if meta_id == id_:
                unit = ENTITIES[nom][1]
                value = energie if unit == "kWh" else energie * WH_TO_KWH
                data[periode][nom] = round(value, 3)

    series = []
    for periode, valeurs in sorted(data.items()):
        try:
            if granularite == "week":
                year, week = map(int, periode.split("-W"))
                periode_dt = datetime.strptime(f"{year}-W{week}-1", "%Y-W%W-%w")
                START_DATE = datetime(2025, 1, 1)
            else:
                periode_dt = datetime.strptime(periode, config["dt_format"])
        except ValueError:
            continue
        try:
            if granularite == "day" or granularite == "week":
                START_DATE = datetime(2025, 1, 1)
            else:
                START_DATE = datetime(2024, 1, 1)
        except ValueError:
            continue
        if periode_dt < START_DATE:
            continue

        reseau_hc = valeurs.get("reseau_hc", 0)
        reseau_hp = valeurs.get("reseau_hp", 0)
        reseau = valeurs.get("linky", 0)
        hphc = round(reseau_hc/ (reseau) * 100, 1) if reseau else 0
        batterie = valeurs.get("decharge_batterie", 0)
        prod = valeurs.get("production", 0)
        surplus = valeurs.get("surplus", 0)
        solaire = max(0, prod - surplus)
        total = solaire + batterie + reseau

        pct = {
            "solaire": round(solaire / total * 100, 1) if total else 0,
            "batterie": round(batterie / total * 100, 1) if total else 0,
            "reseau": round(reseau / total * 100, 1) if total else 0,
            "autoconso": round(solaire / prod * 100, 1) if prod else 0,
            "autonomie": round((solaire + batterie)/ (solaire + batterie + reseau) * 100, 1) if solaire else 0,
            "hphc": round(reseau_hc/ (reseau) * 100, 1) if reseau else 0
        }

        ligne = f"  📅 {periode} : P={prod:.1f}kWh; SP={surplus:.1f}kWh; SC={solaire:.1f}kWh; B={batterie:.1f}kWh; R={reseau:.1f}kWh; T={total:.1f}kWh"
        print(ligne)

        series.append({
            "x": periode,
            "prod": round(prod, 1),
            "surplus": round(surplus, 1),
            "solaire": round(solaire, 1),
            "batterie": round(batterie, 1),
            "reseau": round(reseau, 1),
            "total": round(total, 1),
            "pct": pct
        })

    payload = {
        "series": series,
        "friendly_name": f"Consommation {granularite.capitalize()}",
    }

    # Publier l’état et les attributs

    publish.single(topic, json.dumps(payload), hostname=MQTT_HOST,
                   auth={"username": MQTT_USER, "password": MQTT_PASS}, retain=True)



    print(f"✅ Données publiées pour {granularite} → {len(series)} périodes.")

# --- Exécution principale ---
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
metadata_ids = get_metadata_ids(cursor)

for g, conf in GRANULARITES.items():
    analyser_granularite(cursor, g, conf, metadata_ids)

conn.close()
