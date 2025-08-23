# -*- coding: utf-8 -*-
import os, re, json, gzip, sqlite3, subprocess, struct
from pathlib import Path
from datetime import datetime
import paho.mqtt.client as mqtt

# ========= CONFIG =========
DB_PATH    = "/config/home-assistant_v2.db"
MQTT_HOST  = "localhost"
MQTT_USER  = "mqtt"
MQTT_PASS  = "mqtt"
MQTT_TOPIC = "estar/production"

URL = "https://neapi.hoymiles.com/pvm-data/api/0/module/data/down_module_day_data"
SID = 6886470  # <-- à adapter si besoin
WORKDIR = "/config/tmp_hoymiles"
GZ_PATH  = os.path.join(WORKDIR, "hoymiles_data.gz")
BIN_PATH = os.path.join(WORKDIR, "hoymiles_data.bin")

# ========= Utils =========
def ensure_workdir():
    Path(WORKDIR).mkdir(parents=True, exist_ok=True)

def get_token_from_input_text(db_path: str) -> str:
    """
    Récupère le dernier state de input_text.estar_token_input via states_meta -> states,
    puis extrait le token après 'estar_token='.
    """
    q = """
    SELECT s.state
    FROM states s
    JOIN states_meta m ON m.metadata_id = s.metadata_id
    WHERE m.entity_id = 'input_text.estar_token_input'
    ORDER BY s.state_id DESC
    LIMIT 1
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(q)
        row = cur.fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        raise RuntimeError("[ERREUR] Aucun state pour input_text.estar_token_input")

    m = re.search(r"estar_token=([^\s]+)", row[0])
    if not m:
        raise RuntimeError("[ERREUR] Aucun token trouvé dans input_text.estar_token_input")
    return m.group(1)

def curl_download_gz(token: str, date_str: str):
    """
    POST cURL -> GZIP, payload JSON avec date (et SID), header Authorization avec le token.
    """
    payload = json.dumps({"sid": SID, "date": date_str})
    cmd = [
        "curl","-sS","-X","POST", URL, "-o", GZ_PATH, "--data", payload, "--insecure",
        "-H","Accept: application/json, text/plain, */*",
        "-H","Accept-Encoding: gzip, deflate, br, zstd",
        "-H","Content-Type: application/json",
        "-H",f"Authorization: {token}",
        "-H","Origin: https://monitor.estarpower.com",
        "-H","Referer: https://monitor.estarpower.com/",
    ]
    print("[INFO] Téléchargement Hoymiles…")
    subprocess.run(cmd, check=True)

    if not Path(GZ_PATH).exists() or Path(GZ_PATH).stat().st_size < 64:
        raise RuntimeError("[ERREUR] Fichier GZIP vide ou invalide")

def gunzip_to_bin():
    print("[INFO] Décompression…")
    with gzip.open(GZ_PATH, "rb") as f_in, open(BIN_PATH, "wb") as f_out:
        f_out.write(f_in.read())

def f32le_from_hex(h):
    try:
        return round(struct.unpack("<f", bytes.fromhex(h))[0], 2)
    except Exception:
        return 0.0

def detect_blocs(hexdata: str):
    blocs = []
    first_1205 = hexdata.find("1205")
    if first_1205 == -1:
        return []
    blocs.append(first_1205)
    pos = first_1205 + 4
    while True:
        m_end = re.search(r"42..01", hexdata[pos:], re.IGNORECASE)
        if not m_end:
            break
        end_abs = pos + m_end.end()
        next_1205 = hexdata.find("1205", end_abs)
        if next_1205 == -1:
            break
        blocs.append(next_1205)
        pos = next_1205 + 4
    return blocs

def parse_latest_values(bin_path: str):
    """
    Retourne un JSON prêt pour MQTT :
      {
        "panneaux": [
          {"id": 1, "tension": ..., "courant": ..., "puissance": ..., "energie": ..., "temperature": ...},
          ...
        ],
        "total_puissance": ...,
        "total_energie": ...
      }

    Logique:
      * Parcours de tous les blocs. Les panneaux sont numérotés 1..N dans l’ordre d’apparition
        à travers TOUT le fichier (on empile au fur et à mesure).
      * Pour chaque panneau d’un bloc, on prend la DERNIÈRE mesure trouvée (V, I, P, E).
      * La température vient des “générales” du BLOC et est appliquée aux panneaux de CE bloc.
    """
    hexdata = Path(bin_path).read_bytes().hex()

    def heures_from_block(bpos, bloc_end):
        idx_080112 = hexdata.find("080112", bpos, bloc_end)
        if idx_080112 == -1:
            return [], idx_080112
        creneaux_hex = hexdata[bpos:idx_080112]
        heures = []
        for cr in re.findall(r"1205([0-9a-fA-F]{10})", creneaux_hex):
            try:
                hhmm = bytes.fromhex(cr).decode("ascii")
                heures.append(hhmm if re.match(r"^\d{2}:\d{2}$", hhmm) else "??:??")
            except:
                heures.append("??:??")
        return heures, idx_080112

    blocs = detect_blocs(hexdata)
    print(f"[INFO] {len(blocs)} blocs détectés")

    # Accumulateur global de panneaux (1..N)
    all_panels = []
    next_panel_id = 1

    # Totaux globaux (tous panneaux)
    total_p_global = 0.0
    total_e_global = 0.0

    # Regex de slot par panneau
    slot_re = re.compile(
        r"0d([0-9a-fA-F]{8})"        # V
        r"15([0-9a-fA-F]{8})"        # I
        r"1d([0-9a-fA-F]{8})"        # P
        r"(?:25([0-9a-fA-F]{8}))?"   # E (optionnelle)
        r"(?:28010a[0-9a-fA-F]{2})?",  # petit séparateur optionnel
        re.IGNORECASE
    )

    for i, b_pos in enumerate(blocs, start=1):
        # borne de fin du bloc
        m_end = re.search(r"42..01", hexdata[b_pos:], re.IGNORECASE)
        if not m_end:
            print(f"[DBG] Bloc {i}: ignoré (pas de fin).")
            continue
        bloc_end = b_pos + m_end.end()

        # créneaux (facultatif pour ce JSON)
        heures, idx_080112 = heures_from_block(b_pos, bloc_end)
        if idx_080112 == -1:
            print(f"[DBG] Bloc {i}: ignoré (pas 080112).")
            continue

        # fenêtre de données du bloc
        data_start = idx_080112 + 6
        next_block_pos = blocs[i] if i < len(blocs) else len(hexdata)
        bloc_hex = hexdata[data_start:next_block_pos]

        # --- détecter les “générales” (robuste) -> température du bloc
        panels_area_hex = bloc_hex
        general_bytes = b""
        bb = bytes.fromhex(bloc_hex)

        # Header souple : 28 .. 2A XX 01 (accepte 1-2 octets entre 28 et 2A)
        m_hdr = re.search(rb'\x28.{1,2}\x2A([\x00-\xFF])\x01', bb, re.DOTALL)
        if m_hdr:
            xx = m_hdr.group(1)
            start = m_hdr.end()
            tail = bb[start:]
            ends = list(re.finditer(rb'\x42' + re.escape(xx) + rb'\x01', tail))
            if ends:
                end = start + ends[-1].start()
                general_bytes = bb[start:end]
                # réduire la zone panneaux à tout ce qui précède le header
                panels_area_hex = bloc_hex[: m_hdr.start() * 2]

        # calcule la dernière température du bloc (si présentes)
        block_last_temp = None
        if general_bytes:
            gb = general_bytes
            m32 = re.search(rb'\x32([\x00-\xFF])\x01', gb)
            m3a = re.search(rb'\x3A([\x00-\xFF])\x01', gb)
            if m32 and m3a and m32.end() < m3a.start():
                temp_bytes = gb[m32.end():m3a.start()]
            else:
                n = len(gb)
                third = (n // 12) * 4  # multiple de 4
                temp_bytes = gb[third:2*third]

            def floats_from_bytes(bb2: bytes):
                out = []
                for off in range(0, len(bb2), 4):
                    chunk = bb2[off:off+4]
                    if len(chunk) == 4:
                        try:
                            out.append(round(struct.unpack("<f", chunk)[0], 2))
                        except:
                            pass
                return out

            temps = floats_from_bytes(temp_bytes)
            if temps:
                block_last_temp = temps[-1]

        # --- split panneaux dans panels_area_hex (p1/p2)
        sep = re.search(r"(?:2801)?22[0-9a-fA-F]{4}080212[0-9a-fA-F]{4}0a[0-9a-fA-F]{2}",
                        panels_area_hex, re.IGNORECASE)
        if sep:
            pane_hexes = [panels_area_hex[:sep.start()], panels_area_hex[sep.end():]]
        else:
            pane_hexes = [panels_area_hex] if panels_area_hex else []

        # --- lire la dernière mesure de CHAQUE panneau du bloc, puis EMPILER dans all_panels
        added_this_block = 0
        for p_hex in pane_hexes:
            last_v = last_i = last_p = last_e = None
            for m in slot_re.finditer(p_hex or ""):
                v_hex, i_hex, p_hexv, e_hex = m.groups()
                last_v = f32le_from_hex(v_hex)
                last_i = f32le_from_hex(i_hex)
                last_p = f32le_from_hex(p_hexv)
                last_e = f32le_from_hex(e_hex) if e_hex else 0.0

            if last_v is not None:
                panel_obj = {
                    "id": next_panel_id,
                    "tension":   last_v if last_v is not None else 0.0,
                    "courant":   last_i if last_i is not None else 0.0,
                    "puissance": last_p if last_p is not None else 0.0,
                    "energie":   last_e if last_e is not None else 0.0,
                    "temperature": block_last_temp
                }
                all_panels.append(panel_obj)
                # mise à jour totaux globaux
                if isinstance(panel_obj["puissance"], (int, float)):
                    total_p_global += panel_obj["puissance"]
                if isinstance(panel_obj["energie"], (int, float)):
                    total_e_global += panel_obj["energie"]
                next_panel_id += 1
                added_this_block += 1

        print(f"[DBG] Bloc {i}: créneaux={len(heures)} | panneaux={added_this_block} | generales={'oui' if general_bytes else 'non'}")

    # JSON final
    return {
        "panneaux": all_panels,
        "total_puissance": round(total_p_global, 2),
        "total_energie":   round(total_e_global, 2)
    }

def publish_mqtt(payload: dict):
    client = mqtt.Client(protocol=mqtt.MQTTv5)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, 1883, 60)
    client.publish(MQTT_TOPIC, json.dumps(payload), qos=0, retain=False)
    client.disconnect()
    print(f"[OK] Données envoyées sur {MQTT_TOPIC} : {json.dumps(payload, ensure_ascii=False)}")

# ========= Main =========
def main():
    ensure_workdir()

    token = get_token_from_input_text(DB_PATH)
    print("[INFO] Token trouvé :", token, "\n")

    today = datetime.now().strftime("%Y-%m-%d")
    print("[INFO] Date du jour :", today, "\n")

    curl_download_gz(token, today)
    gunzip_to_bin()

    print("[INFO] Parsing…\n")
    payload = parse_latest_values(BIN_PATH)

    publish_mqtt(payload)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[ERREUR]", str(e))
        raise
