import sqlite3
import json
import paho.mqtt.publish as publish
from datetime import datetime, timedelta

# --- CONFIGURATION ---
DB_PATH = "/config/home-assistant_v2.db"
ENTITY_HP = "sensor.energie_consommee_j_hp"
ENTITY_HC = "sensor.energie_consommee_j_hc"
MQTT_HOST = "localhost"
MQTT_USER = "mqtt"
MQTT_PASS = "mqtt"
WH_TO_KWH = 1 / 1000

# 🔁 Choisir True pour n'analyser que les périodes actuelles
MODE_COURANT_SEULEMENT = True

# --- GRANULARITÉS ---
GRANULARITES = {
    "day": {
        "strftime": "%Y-%m-%d",
        "dt_format": "%Y-%m-%d",
        "topic": "homeassistant/sensor/taux_hc_day"
    },
    "week": {
        "strftime": "%Y-W%W",
        "dt_format": "%Y-%W-%w",
        "topic": "homeassistant/sensor/taux_hc_week"
    },
    "month": {
        "strftime": "%Y-%m",
        "dt_format": "%Y-%m",
        "topic": "homeassistant/sensor/taux_hc_month"
    },
    "year": {
        "strftime": "%Y",
        "dt_format": "%Y",
        "topic": "homeassistant/sensor/taux_hc_year"
    }
}

# --- Connexion DB ---
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def get_metadata_id(entity_id):
    cursor.execute("SELECT id FROM statistics_meta WHERE statistic_id = ?", (entity_id,))
    r = cursor.fetchone()
    return r[0] if r else None

meta_hp = get_metadata_id(ENTITY_HP)
meta_hc = get_metadata_id(ENTITY_HC)
if not meta_hp or not meta_hc:
    raise Exception("Entité HP/HC non trouvée")

# --- Générer période(s) à filtrer ---
def get_periode_filtree(granularite):
    now = datetime.now()
    if granularite == "day":
        return [(now - timedelta(days=1)).strftime("%Y-%m-%d")]
    elif granularite == "week":
        return [now.strftime("%Y-W%W")]
    elif granularite == "month":
        return [now.strftime("%Y-%m")]
    elif granularite == "year":
        return [now.strftime("%Y")]
    return []

# --- Traitement par granularité ---
def traiter_granularite(nom, config):
    strftime_fmt = config["strftime"]
    dt_format = config["dt_format"]
    topic = config["topic"]

    print(f"\n🔍 Traitement {nom.upper()}...")

    cursor.execute(f"""
        SELECT 
            strftime('{strftime_fmt}', datetime(start_ts, 'unixepoch')) as periode,
            metadata_id,
            MAX(sum) - MIN(sum)
        FROM statistics
        WHERE metadata_id IN (?, ?)
        GROUP BY periode, metadata_id
        ORDER BY periode
    """, (meta_hp, meta_hc))

    periode_filtree = get_periode_filtree(nom) if MODE_COURANT_SEULEMENT else None
    data = {}
    for periode, meta_id, energie in cursor.fetchall():
        if periode_filtree and periode not in periode_filtree:
            continue
        if periode not in data:
            data[periode] = {"hp": 0, "hc": 0}
        if meta_id == meta_hp:
            data[periode]["hp"] = energie * WH_TO_KWH
        else:
            data[periode]["hc"] = energie * WH_TO_KWH

    # --- Génération de la série [timestamp, taux HC%] ---
    series = []
    for p_str, d in data.items():
        try:
            if nom == "week":
                annee, semaine = p_str.split("-W")
                dt = datetime.strptime(f"{annee}-{semaine}-1", dt_format)
            else:
                dt = datetime.strptime(p_str, dt_format)
            ts = int(dt.timestamp() * 1000)
            total = d["hp"] + d["hc"]
            if total > 0:
                taux = round((d["hc"] / total) * 100, 1)
                print(f"📅 {p_str} → HC: {d['hc']:.1f} / Total: {total:.1f} → {taux}%")
                series.append([ts, taux])
        except Exception as e:
            print(f"⚠️ Erreur sur {p_str} : {e}")

    # --- Publication MQTT ---
    if series:
        series.sort()
        payload_state = str(series[-1][1])
        payload_attr = json.dumps({ "series": series })

        publish.single(f"{topic}/state", payload_state, hostname=MQTT_HOST, auth={"username": MQTT_USER, "password": MQTT_PASS}, retain=True)
        publish.single(f"{topic}/attributes", payload_attr, hostname=MQTT_HOST, auth={"username": MQTT_USER, "password": MQTT_PASS}, retain=True)
        print(f"✅ Données {nom} publiées.")
    else:
        print(f"❌ Aucune donnée {nom} trouvée.")

# --- Boucle sur les granularités ---
for nom, config in GRANULARITES.items():
    traiter_granularite(nom, config)
