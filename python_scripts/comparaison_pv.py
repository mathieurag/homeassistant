import json
import time
import paho.mqtt.client as mqtt
from datetime import datetime

# --- CONFIGURATION MQTT ---
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_USERNAME = "mqtt"
MQTT_PASSWORD = "mqtt"
MQTT_TOPIC_SIMU = "homeassistant/simulation/solaire"
MQTT_TOPIC_SUIVI = "homeassistant/suivi/solaire"
MQTT_TOPIC_SURPLUS = "sensor/surplus_production"
MQTT_RESULT = "homeassistant/comparaison/solaire"

# --- STRUCTURE ---
data = {
    "simulation": None,
    "suivi": None,
    "surplus": None
}
received = set()

# --- CALLBACKS MQTT ---
def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"❌ Erreur JSON sur {topic} :", e)
        return

    if topic == MQTT_TOPIC_SIMU:
        data["simulation"] = payload
        received.add("simu")
    elif topic == MQTT_TOPIC_SUIVI:
        data["suivi"] = payload
        received.add("suivi")
    elif topic == MQTT_TOPIC_SURPLUS:
        try:
            data["surplus"] = float(msg.payload.decode())
            received.add("surplus")
        except:
            pass

# --- FONCTION COMPARAISON ---
def calculate_ecart(theo, reel):
    ecart = round(reel - theo, 2)
    ecart_pct = round((ecart / theo) * 100, 1) if theo else 0.0
    return ecart, ecart_pct

# --- CONNECTION ET ECOUTE MQTT ---
client = mqtt.Client(client_id="comparaison_reader")
client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.subscribe([(MQTT_TOPIC_SIMU, 0), (MQTT_TOPIC_SUIVI, 0), (MQTT_TOPIC_SURPLUS, 0)])
client.loop_start()

# Attente max 5 secondes
timeout = time.time() + 5
while len(received) < 2 and time.time() < timeout:
    time.sleep(0.1)

client.loop_stop()

# --- EXTRACTION ---
simu = data["simulation"]
reel = data["suivi"]
surplus_reel = data["surplus"]

result = {
    "date": datetime.now().strftime("%Y-%m-%d"),
    "derniere_actualisation": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    "comparaison": {}
}

# --- COMPARAISON SIMULATION VS REALITE ---
if simu and reel:
    comparaisons = [
        ("production", simu.get("production_totale_kwh"), reel.get("entites", {}).get("production", {}).get("total", {}).get("mesure")),
        ("ecs", simu.get("total_ecs_kwh"), reel.get("entites", {}).get("ecs", {}).get("total", {}).get("mesure")),
        ("batterie", simu.get("total_bat_kwh"), reel.get("entites", {}).get("batterie", {}).get("total", {}).get("mesure")),
        ("maison", simu.get("conso_maison_kwh"), reel.get("entites", {}).get("maison", {}).get("total", {}).get("mesure")),
        ("surplus", simu.get("surplus_final_kwh"), surplus_reel),
    ]

    for nom, theo, reel_val in comparaisons:
        if theo is not None and reel_val is not None:
            ecart, ecart_pct = calculate_ecart(theo, reel_val)
            result["comparaison"][nom] = {
                "simulation": round(theo, 2),
                "mesure": round(reel_val, 2),
                "ecart": ecart,
                "ecart_pct": ecart_pct
            }

# --- PUBLICATION RESULTAT FINAL ---
client.publish(MQTT_RESULT, json.dumps(result), qos=0, retain=True)
print("\n[COMPARAISON MQTT PUBLIEE]")
print(json.dumps(result, indent=2))
