import sqlite3
import json
import paho.mqtt.publish as publish
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta
import time

# --- CONFIGURATION ---
DB_PATH = "/config/home-assistant_v2.db"
ENTITY_HP = "sensor.energie_consommee_j_hp"
ENTITY_HG = "sensor.energie_consommee_j_hg"
ENTITY_HC = "sensor.energie_consommee_j_hc"
MQTT_HOST = "localhost"
MQTT_USER = "mqtt"
MQTT_PASS = "mqtt"
WH_TO_KWH = 1 / 1000

MAJ_COURANTE_SEULEMENT = True

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

# --- Connexion DB SQLite ---
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

# --- Lecture série MQTT existante ---
def get_existing_series(topic):
    result = {"series": []}
    done = False

    def on_connect(client, userdata, flags, rc):
        client.subscribe(f"{topic}/attributes")

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            if "series" in data and isinstance(data["series"], list):
                result["series"] = data["series"]
        except:
            pass
        nonlocal done
        done = True

    client = mqtt.Client()
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST)
        client.loop_start()
        timeout = 3
        t0 = time.time()
        while not done and time.time() - t0 < timeout:
            time.sleep(0.1)
        client.loop_stop()
    except:
        print(f"⚠️ Impossible de lire {topic}/attributes")
    return result["series"]

# --- Filtrage : période en cours uniquement ---
def get_periode_filtree(granularite):
    now = datetime.now()
    if granularite == "day":
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    elif granularite == "week":
        return now.strftime("%Y-W%W")
    elif granularite == "month":
        return now.strftime("%Y-%m")
    elif granularite == "year":
        return now.strftime("%Y")
    return None

# --- Traitement par granularité ---
def traiter_granularite(nom, config):
    print(f"\n🔁 Traitement {nom.upper()}")
    strftime_fmt = config["strftime"]
    dt_format = config["dt_format"]
    topic = config["topic"]

    periode_a_maj = get_periode_filtree(nom) if MAJ_COURANTE_SEULEMENT else None

    # --- Données SQLite ---
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

    mesures = {}
    for periode, meta_id, energie in cursor.fetchall():
        if periode_a_maj and periode != periode_a_maj:
            continue
        if periode not in mesures:
            mesures[periode] = {"hp": 0, "hc": 0}
        if meta_id == meta_hp:
            mesures[periode]["hp"] = energie * WH_TO_KWH
        else:
            mesures[periode]["hc"] = energie * WH_TO_KWH

    # --- Nouvelle série calculée ---
    nouveaux_points = {}
    for periode, d in mesures.items():
        try:
            if nom == "week":
                annee, semaine = periode.split("-W")
                dt = datetime.strptime(f"{annee}-{semaine}-1", dt_format)
            else:
                dt = datetime.strptime(periode, dt_format)
            ts = int(dt.timestamp() * 1000)
            total = d["hp"] + d["hc"]
            if total > 0:
                taux = round((d["hc"] / total) * 100, 1)
                print(f"📅 {periode} → HC: {d['hc']:.2f} / Total: {total:.2f} → {taux}%")
                nouveaux_points[ts] = taux
        except Exception as e:
            print(f"⚠️ Erreur période {periode} : {e}")

    # --- Fusion avec ancienne série ---
    ancienne = get_existing_series(topic)
    fusion = {int(ts): taux for ts, taux in ancienne if isinstance(ts, (int, float)) and isinstance(taux, (int, float))}

    # Remplacement ou ajout des points nouveaux
    fusion.update(nouveaux_points)

    # --- Publication MQTT ---
    if fusion:
        serie_finale = sorted(fusion.items())
        payload_state = str(serie_finale[-1][1])
        payload_attr = json.dumps({ "series": serie_finale })

        publish.single(f"{topic}/state", payload_state, hostname=MQTT_HOST, auth={"username": MQTT_USER, "password": MQTT_PASS}, retain=True)
        publish.single(f"{topic}/attributes", payload_attr, hostname=MQTT_HOST, auth={"username": MQTT_USER, "password": MQTT_PASS}, retain=True)
        print(f"✅ {nom.capitalize()} publié avec {len(nouveaux_points)} MAJ.")
    else:
        print(f"❌ Aucune donnée disponible pour {nom}")

# --- Exécution pour chaque granularité ---
for nom, config in GRANULARITES.items():
    traiter_granularite(nom, config)
