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

def f32le_from_hex(h: str) -> float:
    try:
        return round(struct.unpack("<f", bytes.fromhex(h[:8]))[0], 2)
    except Exception:
        return 0.0

# --- détection des blocs fiable ---
def detect_blocs(hexdata: str):
    """
    1) Premier bloc = premier '1205'
    2) Bloc suivant = premier '1205' trouvé APRÈS un '42..01' rencontré depuis le début du bloc.
       (S’il n’y a pas de '42..01' tôt le matin, on aura quand même au moins un bloc : le premier.)
    """
    blocs = []
    first_1205 = hexdata.find("1205")
    if first_1205 == -1:
        return blocs
    blocs.append(first_1205)

    pos = first_1205
    while True:
        m_end = re.search(r"42..01", hexdata[pos:], re.IGNORECASE)
        if not m_end:
            break
        end_abs = pos + m_end.end()
        next_1205 = hexdata.find("1205", end_abs)
        if next_1205 == -1:
            break
        blocs.append(next_1205)
        pos = next_1205
    return blocs

def earliest_marker_in_range(hexdata: str, start_idx: int, end_idx: int) -> int:
    """Premier séparateur de créneaux rencontré (080112 ou 080212) dans [start_idx, end_idx)."""
    i1 = hexdata.find("080112", start_idx, end_idx)
    i2 = hexdata.find("080212", start_idx, end_idx)
    c = [i for i in (i1, i2) if i != -1]
    return min(c) if c else -1

# --- Parsing des "générales" (robuste & auto) ---
def parse_generales_stream(general_hex: str, expected_slots: int = 0):
    """
    Cherche un run de fréquences (~50Hz) pour s’aligner (48..52),
    puis N températures (-40..130°C), puis N tensions (60..400V).
    S’aligne au besoin en décalant d’1 octet.
    """
    gb = bytes.fromhex(general_hex)

    def floats_from_bytes_with_offset(b: bytes, offset: int):
        out = []
        i = offset
        end = (len(b) // 4) * 4
        while i + 4 <= end:
            try:
                out.append(struct.unpack("<f", b[i:i+4])[0])
            except Exception:
                out.append(float("nan"))
            i += 4
        return out

    best = (None, None, 0)  # (offset, start_byte, length)
    lo, hi = 48.0, 52.0
    for off in range(4):
        vals = floats_from_bytes_with_offset(gb, off)
        s = 0
        while s < len(vals):
            if lo <= vals[s] <= hi:
                e = s + 1
                while e < len(vals) and lo <= vals[e] <= hi:
                    e += 1
                length = e - s
                if length > best[2]:
                    best = (off, off + 4*s, length)
                s = e
            else:
                s += 1

    off, freq_start_byte, freq_len = best
    if off is None or freq_len == 0:
        return None, None, None

    if expected_slots and abs(freq_len - expected_slots) <= 2:
        freq_len = expected_slots

    # fréquences alignées
    freqs = []
    freqs_bytes = gb[freq_start_byte: freq_start_byte + 4*freq_len]
    for i in range(0, len(freqs_bytes), 4):
        try:
            freqs.append(round(struct.unpack("<f", freqs_bytes[i:i+4])[0], 2))
        except Exception:
            pass

    # températures puis tensions avec contrôle de plausibilité + réalignement
    def next_n_plausible_floats(b: bytes, start_byte: int, n: int, rng):
        vals, p = [], start_byte
        count = 0
        while p + 4 <= len(b) and count < n:
            try:
                v = struct.unpack("<f", b[p:p+4])[0]
            except Exception:
                v = float("nan")
            if rng[0] <= v <= rng[1]:
                vals.append(round(v, 2))
                p += 4
                count += 1
            else:
                p += 1
        return vals, p

    p_after = freq_start_byte + 4*freq_len
    n_guess = expected_slots or 64
    temps, p_after = next_n_plausible_floats(gb, p_after, n_guess, (-40.0, 130.0))
    tens,  p_after = next_n_plausible_floats(gb, p_after, n_guess, (60.0, 400.0))

    if expected_slots:
        temps = temps[:expected_slots]
        tens  = tens[:expected_slots]

    return freqs, temps, tens

# --- parsing principal : dernières valeurs par panneau + dernières générales (temp) ---
def parse_latest_values(bin_path: str):
    hexdata = Path(bin_path).read_bytes().hex()
    blocs = detect_blocs(hexdata)
    print(f"[INFO] {len(blocs)} blocs détectés")

    panneaux = []
    global_panel_id = 1

    # motif d'un slot panneau : V, I, P, [E]
    slot_re = re.compile(
        r"0d([0-9a-fA-F]{8})"        # V
        r"15([0-9a-fA-F]{8})"        # I
        r"1d([0-9a-fA-F]{8})"        # P
        r"(?:25([0-9a-fA-F]{8}))?",  # E (optional)
        re.IGNORECASE
    )

    total_p_global = 0.0
    total_e_global = 0.0

    for i, b_pos in enumerate(blocs, start=1):
        # borne de fin utilisable même sans 42..01
        m_end = re.search(r"42..01", hexdata[b_pos:], re.IGNORECASE)
        if m_end:
            bloc_end_abs = b_pos + m_end.end()
            mode = ""
        else:
            next_block_pos = blocs[i] if i < len(blocs) else len(hexdata)
            bloc_end_abs = next_block_pos
            mode = " (sans 42..01)"

        # début des données (après 080112/080212)
        idx_sep = earliest_marker_in_range(hexdata, b_pos, bloc_end_abs)
        if idx_sep == -1:
            print(f"[DBG] Bloc {i}{mode}: ignoré (pas de 080112/080212).")
            continue

        data_start = idx_sep + 6
        next_block_pos = blocs[i] if i < len(blocs) else len(hexdata)
        bloc_hex = hexdata[data_start:next_block_pos]

        # Nombre de créneaux (sert d’« attendu » pour chaque panneau)
        creneaux = re.findall(r"1205([0-9a-fA-F]{10})", hexdata[b_pos:idx_sep])
        nb_slots = len(creneaux)

        # 1) On localise la fin des slots panneaux (dernier match slot_re)
        last_slot_end = 0
        slots_iter_for_end = list(slot_re.finditer(bloc_hex))
        for m in slots_iter_for_end:
            last_slot_end = max(last_slot_end, m.end())
        if last_slot_end == 0:
            print(f"[DBG] Bloc {i}{mode}: pas de slots panneaux trouvés.")
            continue

        panels_area_hex  = bloc_hex[:last_slot_end]
        general_area_hex = bloc_hex[last_slot_end:]

        # 2) Générales à partir de la queue
        freqs, temps, tens = parse_generales_stream(general_area_hex, expected_slots=nb_slots)
        block_last_temp = temps[-1] if temps else None
        if freqs is not None:
            print(f"[DBG] Bloc {i} générales (auto){mode}: f={len(freqs)} t={len(temps)} v={len(tens)} | T° last={block_last_temp}")

        # 3) DÉMULTIPLEXAGE DES PANNEAUX **SANS séparateurs**
        #    – on récupère tous les matches slots dans panels_area_hex
        all_matches = list(slot_re.finditer(panels_area_hex))
        total_slots_found = len(all_matches)

        pane_hexes = []
        if nb_slots > 0 and total_slots_found >= nb_slots:
            # on coupe en paquets de nb_slots en partant de la fin
            # chaque paquet = un panneau
            nb_panneaux_estime = total_slots_found // nb_slots
            idx = total_slots_found
            for _ in range(nb_panneaux_estime):
                start_m = all_matches[idx - nb_slots]
                end_m   = all_matches[idx - 1]
                pane_hexes.append(panels_area_hex[start_m.start(): end_m.end()])
                idx -= nb_slots
            pane_hexes.reverse()  # remet dans l’ordre naturel
        else:
            # fallback : un seul panneau (au cas où nb_slots == 0 très tôt le matin)
            pane_hexes = [panels_area_hex] if panels_area_hex else []

        # 4) Lecture des dernières valeurs par panneau
        added = 0
        bloc_p_sum = 0.0
        bloc_e_sum = 0.0
        for p_hex in pane_hexes:
            last_v = last_i = last_p = last_e = None
            for m in slot_re.finditer(p_hex or ""):
                v_hex, i_hex, p_hexv, e_hex = m.groups()
                last_v = f32le_from_hex(v_hex)
                last_i = f32le_from_hex(i_hex)
                last_p = f32le_from_hex(p_hexv)
                last_e = f32le_from_hex(e_hex) if e_hex else 0.0

            if last_v is not None:
                panneaux.append({
                    "id": global_panel_id,
                    "tension": last_v,
                    "courant": last_i,
                    "puissance": last_p,
                    "energie": last_e,
                    "temperature": block_last_temp
                })
                global_panel_id += 1
                added += 1
                if isinstance(last_p, (int, float)):
                    bloc_p_sum += last_p
                    total_p_global += last_p
                if isinstance(last_e, (int, float)):
                    bloc_e_sum += last_e
                    total_e_global += last_e

        print(f"[DBG] Bloc {i}{mode}: créneaux OK | panneaux détectés={added} | générales={'oui' if (freqs is not None) else 'non'}")
        if added:
            print(f"   Totaux bloc — Puissance: {round(bloc_p_sum,1)} W | Énergie: {round(bloc_e_sum,2)} kWh")

    # Synthèse globale debug
    if panneaux:
        sumP = round(sum(p['puissance'] for p in panneaux), 1)
        sumE = round(sum(p['energie'] for p in panneaux), 2)
        print("\n--- Synthèse globale ---")
        print(f"Somme des dernières puissances de tous les panneaux : {sumP} W")
        print(f"Somme des dernières énergies de tous les panneaux   : {sumE} kWh")

    total_p = round(sum(p["puissance"] for p in panneaux), 2)
    total_e = round(sum(p["energie"]   for p in panneaux), 2)
    return {"panneaux": panneaux, "total_puissance": total_p, "total_energie": total_e}

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
