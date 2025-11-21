import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import math
from zoneinfo import ZoneInfo

# Configuration
DB_PATH = "/config/home-assistant_v2.db"
CSV_LOG = "/config/corrections_hp_hc_hg.csv" 
ANALYZE_MODE = "since_midnight"

# Mode de correction 5 minutes.
ANALYZE_5MIN_MODE = "since_midnight" 

DEBUG_5MIN = False 

# IDs des entités (Utility Meter et EcoJoko)
ids = {
    "hp": 248,
    "hc": 249,
    "hg": 1291,
    # NOUVEL ID UNIQUE ECOJOKO
    "eco_reseau": 39 
}
all_types = ("hp", "hc", "hg") 

min_diff_kwh = 0.0001
max_delta_kwh = 10.0
rounding_step_kwh = 0.001

# FIXE: Robustesse au changement d'heure grâce à ZoneInfo('Europe/Paris')
LOCAL_TZ_NAME = 'Europe/Paris' 
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME) 

# MAPPING DES UNITÉS EN Wh
UNIT_MULTIPLIER = {
    ids["hp"]: 1,     # HP est en Wh (Multiplicateur 1)
    ids["hc"]: 1,     # HC est en Wh (Multiplicateur 1)
    ids["hg"]: 1000, # HG est en kWh (Multiplicateur 1000 pour obtenir des Wh)
}

# --- Fonctions de Temps (MISES À JOUR SELON VOTRE NOUVEAU TARIF) ---

def is_hc_time(ts_local):
    # 0h-6h = HC
    return ts_local.hour >= 0 and ts_local.hour < 6

def is_hg_time(ts_local):
    # 15h-17h = HG
    return ts_local.hour >= 15 and ts_local.hour < 17

def get_active_tarif(ts_local):
    if is_hc_time(ts_local):
        return "hc"
    if is_hg_time(ts_local):
        return "hg"
    # 17h-0h = HP
    return "hp"

# --- Fonctions utilitaires (Inch.) ---

def round_to_step(val, step=rounding_step_kwh):
    return round(round(val / step) * step, 3)

def get_expected_tranches(start_ts):
    return [start_ts + 300 * i for i in range(12)]

def get_actual_tranches(cursor, metadata_id, start_ts):
    cursor.execute(
        "SELECT start_ts, sum FROM statistics_short_term "
        "WHERE metadata_id = ? AND start_ts >= ? AND start_ts < ?",
        (metadata_id, start_ts, start_ts + 3600)
    )
    return {r[0]: r[1] for r in cursor.fetchall()}

def get_hour_starts_to_analyze(now_ts):
    if ANALYZE_MODE == "last_hour":
        last_hour = int(now_ts // 3600) * 3600 - 3600
        return [last_hour]
    elif ANALYZE_MODE == "since_midnight":
        dt_now = datetime.fromtimestamp(now_ts, tz=LOCAL_TZ)
        midnight = dt_now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=LOCAL_TZ)
        midnight_ts = int(midnight.timestamp())
        current_hour_ts = int(now_ts // 3600) * 3600
        return list(range(midnight_ts, current_hour_ts, 3600))
    else:
        raise ValueError(f"Mode d'analyse inconnu : {ANALYZE_MODE}")


# --- Connexion et Analyse ---

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
all_updates = []

now = datetime.now(LOCAL_TZ)
now_ts = int(now.timestamp())
all_hour_starts = sorted(get_hour_starts_to_analyze(now_ts))

totaux = {t: {"eco": 0.0, "conso": 0.0, "delta": 0.0} for t in all_types}


# --- BOUCLE PRINCIPALE (CORRECTION HORAIRE) - DELTA APPLIQUÉ UNIQUEMENT À statistics ---
for ts in all_hour_starts:
    ts_local = datetime.fromtimestamp(ts, tz=LOCAL_TZ) 
    active_typ = get_active_tarif(ts_local) 
    
    print(f"\n🕒 Heure analysée : {ts_local:%Y-%m-%d %H:%M:%S} [{active_typ.upper()}]") 

    for typ in all_types:
        
        if typ != active_typ:
            continue

        # NOUVEAU: Utiliser l'ID unique EcoJoko (39)
        eco_source_id = ids["eco_reseau"] 

        conso_id = ids[typ]
        conso_unit_mult = UNIT_MULTIPLIER.get(conso_id, 1)

        # Récupération des données Utility Meter
        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (conso_id, ts))
        conso_now = cur.fetchone()
        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (conso_id, ts - 3600))
        conso_prev = cur.fetchone()
        
        # Récupération des données EcoJoko (ID 39)
        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (eco_source_id, ts))
        eco_now = cur.fetchone()
        cur.execute("SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?", (eco_source_id, ts - 3600))
        eco_prev = cur.fetchone()

        if eco_now and eco_prev and conso_now and conso_prev:
            
            # Calcul du delta conso (en kWh)
            conso_delta_base_unit = conso_now[0] - conso_prev[0]
            conso_delta = (conso_delta_base_unit * conso_unit_mult) / 1000 
            
            # CORRECTION: ID 39 est en kWh, donc pas de division par 1000 ici.
            eco_delta = eco_now[0] - eco_prev[0] 
            
            delta_kwh_raw = eco_delta - conso_delta
            delta_kwh = round_to_step(delta_kwh_raw)

            totaux[typ]["eco"] += eco_delta
            totaux[typ]["conso"] += conso_delta
            totaux[typ]["delta"] += delta_kwh_raw

            
            if abs(delta_kwh) < min_diff_kwh:
                print(f" ➡️ {typ.upper()} : ΔC {conso_delta:.3f} kWh / ΔE {eco_delta:.3f} kWh✅")
            #elif abs(delta_kwh) > max_delta_kwh:
                #print(f" ⛔ {typ.upper()} : Écart trop grand ({delta_kwh:+.3f} kWh) | ΔC {conso_delta:.3f} / ΔE {eco_delta:.3f}. Ignoré.")
            else:
                
                # Détermination de la valeur de correction finale (dans l'unité du compteur)
                if conso_unit_mult == 1000:
                    # Si l'entité est en kWh (ex: HG), on utilise le float directement (delta_kwh)
                    delta_final_update = delta_kwh 
                else:
                    # Si l'entité est en Wh (ex: HP/HC), on convertit en int pour l'unité Wh
                    delta_final_update = int(delta_kwh * 1000 / conso_unit_mult)

                cur.execute("SELECT start_ts, sum FROM statistics WHERE metadata_id=? AND start_ts >= ? ORDER BY start_ts", (conso_id, ts))
                future = cur.fetchall()
                
                for start_ts_f, sum_f in future:
                    # Propagation dans statistics (Horaire)
                    new_sum = sum_f + delta_final_update 
                    cur.execute("UPDATE statistics SET sum=? WHERE metadata_id=? AND start_ts=?", (new_sum, conso_id, start_ts_f))
                    
                    ts_local_f = datetime.fromtimestamp(start_ts_f, tz=LOCAL_TZ)
                    all_updates.append({
                        "type": typ.upper(), "level": "hourly", "start_ts": start_ts_f,
                        "timestamp": ts_local_f.strftime("%Y-%m-%d %H:%M:%S"),
                        "old": sum_f, "new": new_sum, "delta": delta_kwh
                    })
                print(f" ⚠️ Correction {typ.upper()} (horaire) appliquée : {delta_kwh:+.3f} kWh (ΔC {conso_delta:.3f} / ΔE {eco_delta:.3f}) sur {len(future)} tranches statistiques")
        else:
            missing = []
            if not eco_now or not eco_prev: missing.append("EcoJoko")
            if not conso_now or not conso_prev: missing.append("Meter")
            
            ts_prev_local = datetime.fromtimestamp(ts - 3600, tz=LOCAL_TZ)
            
            print(f" ❌ Pas de données ({', '.join(missing)}) pour {typ.upper()} à {ts_local:%H:%M:%S} (vs {ts_prev_local:%H:%M:%S}). SKIP.")


# ----------------------------------------------------------------------------------
# --- BOUCLE DE CORRECTION 5 MINUTES ---
# ----------------------------------------------------------------------------------
dt_now_local = datetime.fromtimestamp(now_ts, tz=LOCAL_TZ)
dt_current_hour_start_local = dt_now_local.replace(minute=0, second=0, microsecond=0)
current_hour_ts = int(dt_current_hour_start_local.timestamp())

# Déterminer les heures à analyser pour la correction 5min
if ANALYZE_5MIN_MODE == "since_midnight":
    dt_midnight = dt_now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts_5min_loop = int(dt_midnight.timestamp())
    # Exclusion de l'heure en cours
    end_ts_5min_loop = current_hour_ts 
    hours_to_check = list(range(start_ts_5min_loop, end_ts_5min_loop, 3600))
else: # 'current_hour'
    hours_to_check = [current_hour_ts - 3600]
    
print(f"\n--- Démarrage de la correction 5 minutes ({ANALYZE_5MIN_MODE}) pour {len(hours_to_check)} heure(s) ---")

for current_hour_ts in hours_to_check:
    dt_hour_local = datetime.fromtimestamp(current_hour_ts, tz=LOCAL_TZ)
    print(f" 🕒 Correction 5min : {dt_hour_local:%H:%M}")
    
    for typ in all_types:
        
        # NOUVEAU: Utiliser l'ID unique EcoJoko (39)
        eco_source_id = ids["eco_reseau"] 
        conso_id = ids[typ]
        conso_unit_mult = UNIT_MULTIPLIER.get(conso_id, 1)

        conso_5min = get_actual_tranches(cur, conso_id, current_hour_ts)
        eco_5min = get_actual_tranches(cur, eco_source_id, current_hour_ts)
        expected = get_expected_tranches(current_hour_ts)

        df_rows = []
        for t in expected:
            dt_local = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(LOCAL_TZ)
            df_rows.append({"start_ts": t, "datetime": dt_local, "conso": conso_5min.get(t), "eco": eco_5min.get(t)})
        df = pd.DataFrame(df_rows)

        has_delta = False
        # Début de la boucle à i=1 pour inclure le delta T1 - T0
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            
            ts_5min = int(row["start_ts"])
            ts_local_5min = datetime.fromtimestamp(ts_5min, tz=timezone.utc).astimezone(LOCAL_TZ)
            active_typ_5min = get_active_tarif(ts_local_5min)

            if typ != active_typ_5min:
                continue

            # Vérification de la validité de la ligne et de la ligne précédente
            if pd.isna(row["conso"]) or pd.isna(prev["conso"]) or pd.isna(row["eco"]) or pd.isna(prev["eco"]):
                continue

            # Calcul du delta conso (en kWh)
            conso_delta_base_unit = row["conso"] - prev["conso"] 
            conso_delta = (conso_delta_base_unit * conso_unit_mult) / 1000 
            
            # CORRECTION: ID 39 est en kWh, donc pas de division par 1000 ici.
            delta_eco = row["eco"] - prev["eco"] 
            
            ecart_raw = delta_eco - conso_delta
            ecart = round_to_step(ecart_raw) 

            if abs(ecart) < min_diff_kwh:
                continue

            has_delta = True

            mode_label = typ.upper()
            start_ts_key = int(row["start_ts"])

            # Détermination de la valeur de correction finale (dans l'unité du compteur)
            if conso_unit_mult == 1000:
                # Si l'entité est en kWh (ex: HG), on utilise le float directement (ecart en kWh)
                delta_final_update = ecart 
            else:
                # Si l'entité est en Wh (ex: HP/HC), on convertit en int pour l'unité Wh
                delta_final_update = int(ecart * 1000 / conso_unit_mult)

            cur.execute(
                "SELECT start_ts, sum FROM statistics_short_term WHERE metadata_id = ? AND start_ts = ?",
                (conso_id, start_ts_key)
            )
            initial_row_to_update = cur.fetchone()
            
            if not initial_row_to_update:
                continue 

            start_ts_update = initial_row_to_update[0]
            sum_val = initial_row_to_update[1]
            
            # Propagation dans statistics_short_term (5min)
            cur.execute("UPDATE statistics_short_term SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (delta_final_update, conso_id, start_ts_update))
            
            # RÉ-INCLUSION : Propagation dans statistics (Horaire) pour garantir la persistance 5min
            cur.execute("UPDATE statistics SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?", (delta_final_update, conso_id, start_ts_update))

            all_updates.append({
                "type": mode_label, "level": "5min", "start_ts": start_ts_update,
                "timestamp": datetime.fromtimestamp(start_ts_update, tz=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "old": sum_val, "new": sum_val + delta_final_update, "delta": ecart
            })
            
            print(f"  ⚠️ Correction 5min {mode_label} appliquée : {row['datetime']:%H:%M:%S} (Δ: {ecart:+.3f} kWh)✅")

        if not has_delta:
            print(f"  ➡️ Aucun delta 5min détecté pour {typ.upper()}.")


# --- Vérification cohérence et Récap (inchangé) ---

print("\n\n--- 🔎 Bilan de Cohérence (5min vs Horaire) ---")
for t in all_types:
    conso_id = ids[t]
    
    hours = [ts for ts in all_hour_starts if get_active_tarif(datetime.fromtimestamp(ts, tz=LOCAL_TZ)) == t]
    
    total_5min_conso = 0.0
    for ts in hours:
        conso_5min = get_actual_tranches(cur, conso_id, ts)
        timestamps = sorted(conso_5min.keys())
        for i in range(1, len(timestamps)):
            delta_base_unit = conso_5min[timestamps[i]] - conso_5min[timestamps[i - 1]]
            conso_unit_mult = UNIT_MULTIPLIER.get(conso_id, 1)
            # Convertir la base (Wh/kWh) en kWh pour le total
            total_5min_conso += (delta_base_unit * conso_unit_mult) / 1000 
    
    hourly_conso = totaux[t].get('conso', 0.0) 
    delta_5min_vs_hourly = round_to_step(total_5min_conso - hourly_conso)
    
    status_icon = "⚠️" if abs(delta_5min_vs_hourly) > min_diff_kwh else "✅"
    
    print(f" [{t.upper()}] Δ Incohérence HA : {delta_5min_vs_hourly:+.3f} kWh{status_icon}")


print("\n--- 📊 Récapitulatif Correction Globale (EcoJoko vs Meter) ---")
total_conso = sum(totaux[t]["conso"] for t in all_types)
total_eco = sum(totaux[t]["eco"] for t in all_types)
total_delta = sum(totaux[t]["delta"] for t in all_types)

for t in all_types:
    label = t.upper()
    delta = totaux[t]['delta']
    status_icon = "⚠️" if abs(delta) > min_diff_kwh else "✅"
    print(f" [{label}] Corrigé : {totaux[t]['conso']:.3f} kWh | Source : {totaux[t]['eco']:.3f} kWh | Δ Final : {delta:+.3f} kWh{status_icon}")

status_icon_total = "⚠️" if abs(total_delta) > min_diff_kwh else "✅"
print(f"\n [TOTAL] Corrigé : {total_conso:.3f} kWh | Source : {total_eco:.3f} kWh | Δ Final : {total_delta:+.3f} kWh{status_icon_total}")


# Sécuriser le commit
if all_updates:
    conn.commit()
    print("Transaction validée (commit) : corrections appliquées.")
    df_log = pd.DataFrame(all_updates)
    header = not os.path.exists(CSV_LOG)
    df_log.to_csv(CSV_LOG, mode='a', header=header, index=False)

conn.close()

print(f"\n📦 Corrections historisées : {len(all_updates)} ligne(s) dans {CSV_LOG}")