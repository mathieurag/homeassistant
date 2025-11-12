import sqlite3
import time
import datetime
import pytz
import array as arr

try:
    # Ajustez le chemin de la base de données si nécessaire
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

error = 0
jours = 1  # Jour à corriger (J-X)
row = ""

# --- FONCTIONS DE SÉCURISATION ---

def get_hourly_deltas(database, id_entity, ts0):
    """
    Récupère les deltas horaires pour une entité Utility Meter sur 24 heures.
    Retourne le delta dans l'unité du compteur (Wh pour HP/HC, kWh pour HG).
    Sécurise en renvoyant 0 si une entrée horaire est manquante.
    """
    # 1. Récupérer la somme cumulative de l'heure précédente (J-1, 23h00)
    ts_prev_day_end = ts0 - 3600
    sum_old = 0
    data = database.execute(f"SELECT sum FROM 'statistics' where metadata_id = '{id_entity}' and start_ts ='{ts_prev_day_end}'")
    row = data.fetchone()
    if row:
        sum_old = row[0]

    # 2. Récupérer toutes les entrées horaires de la journée (00:00 à 23:00)
    tsmax = ts0 + 23 * 3600
    query = f"SELECT start_ts, sum FROM 'statistics' where metadata_id = '{id_entity}' and start_ts >='{ts0}' and start_ts<='{tsmax}' order by start_ts ASC"
    data = database.execute(query)
    
    # Créer un dictionnaire pour un accès rapide aux "sum" de l'Utility Meter
    # Les valeurs ici sont dans l'unité du compteur (Wh ou kWh)
    meter_sums = {int(row[0]): row[1] for row in data.fetchall()}
    
    # 3. Initialiser les 24 deltas horaires de l'Utility Meter à zéro
    hourly_deltas = arr.array('f', [0.0] * 24)
    
    # 4. Calculer les deltas pour les 24 heures
    for i in range(24):
        ts_current = ts0 + i * 3600 # Timestamp de l'heure 'i'
        
        if ts_current in meter_sums:
            sum_current = meter_sums[ts_current]
            
            # Calculer le delta (Conso de l'heure) dans l'unité du compteur
            delta = round(sum_current - sum_old, 3) # Utilise 3 décimales pour plus de précision si en kWh
            hourly_deltas[i] = delta
            sum_old = sum_current # Mettre à jour l'ancienne somme pour l'heure suivante
            
    return hourly_deltas

# NOTE: La fonction get_meter_energy n'est plus utilisée pour le calcul, mais conservée par sécurité.
def get_meter_energy(database, id_entity, ts0, tsmax):
    """
    Calcule l'énergie totale (en kWh) pour la journée J-1. (Ancienne méthode)
    """
    sum_old = 0
    state_old = 0
    query = "SELECT state,sum FROM 'statistics' where metadata_id = '" + str(id_entity) +"' and (start_ts ='" + str(ts0) + "' or start_ts='" + str(tsmax) + "') order by start_ts DESC"
    data=database.execute(query)
    energy=0
    
    results = data.fetchall()
    if not results:
        return 0.0
        
    for row in results:
        energy = energy + row[1]
        state_old = row[0]
        sum_old = row[1]
        
    return round((energy - 2*sum_old + state_old) / 1000, 2)


# -----------------------------------------------------
# 1. RÉCUPÉRATION DES ID DES ENTITÉS UTILITY METER ET LINKY
# -----------------------------------------------------

ids_to_check = {
    "hp": "sensor.energie_consommee_j_hp",
    "hc": "sensor.energie_consommee_j_hc",
    "hg": "sensor.energie_consommee_j_hg",
    "linky": "linky:16127930466069"
}

id_map = {}
for key, entity in ids_to_check.items():
    query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
    data = database.execute(query0)
    result = data.fetchone()
    if result:
        id_map[key] = result[0]
        #print(f"entité = {entity} / id= {result[0]}")
    else:
        print(f"Erreur : Entité {entity} non trouvée.")
        if key == 'hg' or key == 'linky':
            error = 1

if error:
    print("Arrêt du script en raison d'IDs manquants.")
    database.close()
    exit()

id_entity_hp = id_map['hp']
id_entity_hc = id_map['hc']
id_entity_hg = id_map['hg']
id_entity_linky = id_map['linky']


# -----------------------------------------------------
# 2. CALCUL DES TIME STAMPS
# -----------------------------------------------------

target_date = datetime.date.today() - datetime.timedelta(days=jours)
local_tz = pytz.timezone("Europe/Paris")

dt_naive = datetime.datetime.combine(target_date, datetime.time.min)
dt_local = local_tz.localize(dt_naive, is_dst=None)
ts0 = int(dt_local.timestamp()) # Minuit du jour J-1

dt_end_naive = datetime.datetime.combine(target_date, datetime.time(23, 00, 00))
dt_end_local = local_tz.localize(dt_end_naive, is_dst=None)
tsmax = int(dt_end_local.timestamp()) # 23:00 du jour J-1 (dernière heure complète)


# -----------------------------------------------------
# 3. ANALYSE LINKY ET RÉPARTITION HORAIRE (HP/HC/HG)
# -----------------------------------------------------

query0 = "SELECT state FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts >='" + str(ts0) + "' and start_ts<='" + str(tsmax) + "' order by start_ts ASC"
data = database.execute(query0)

# Initialisation des 24 heures de consommation Linky à 0 Wh
energy_linky_hc_wh_hourly = arr.array('f', [0.0] * 24)
energy_linky_hp_wh_hourly = arr.array('f', [0.0] * 24)
energy_linky_hg_wh_hourly = arr.array('f', [0.0] * 24)

heure = 0
total_linky_wh = 0.0

for row in data.fetchall():
    if heure >= 24:
        break

    conso_wh = round(row[0], 0)
    total_linky_wh += conso_wh

    # Logique de Répartition HP/HC/HG
    if heure < 5:
        energy_linky_hc_wh_hourly[heure] = conso_wh
    elif heure == 5:
        energy_linky_hc_wh_hourly[heure] = round(0.87 * conso_wh, 0)
        energy_linky_hp_wh_hourly[heure] = round(0.13 * conso_wh, 0)
    elif heure >= 15 and heure < 17:
        energy_linky_hg_wh_hourly[heure] = conso_wh
    elif heure < 21:
        energy_linky_hp_wh_hourly[heure] = conso_wh
    elif heure == 21:
        energy_linky_hp_wh_hourly[heure] = round(0.13 * conso_wh, 0)
        energy_linky_hc_wh_hourly[heure] = round(0.87 * conso_wh, 0)
    else:
        energy_linky_hc_wh_hourly[heure] = conso_wh
        
    heure = heure + 1

# Cumul des consommations Linky (en kWh)
energy_linky = round(total_linky_wh / 1000, 2)
energy_linky_hc = round(sum(energy_linky_hc_wh_hourly) / 1000, 2)
energy_linky_hp = round(sum(energy_linky_hp_wh_hourly) / 1000, 2)
energy_linky_hg = round(sum(energy_linky_hg_wh_hourly) / 1000, 2)

if energy_linky > 0 and error == 0: 
    print(f"Energie Linky J-{jours}: {energy_linky} kWh (HP:{energy_linky_hp} / HC:{energy_linky_hc} / HG:{energy_linky_hg})")
else:
    retour = "Energie Linky non trouvée ou erreur ID HG."
    error = 1
    print(retour)


# -----------------------------------------------------
# 4. RÉCUPÉRATION DES DONNÉES UTILITY METER EXISTANTES (SÉCURISÉE)
# -----------------------------------------------------
# [Section 4 modifiée de maj_linky.py]

# -----------------------------------------------------
# 4. RÉCUPÉRATION DES DONNÉES UTILITY METER EXISTANTES (SÉCURISÉE)
# -----------------------------------------------------

# 1. Récupération des deltas horaires des Utility Meters 
# (HG est en kWh, HP/HC sont en Wh)
energy_hp_deltas = get_hourly_deltas(database, id_entity_hp, ts0)
energy_hc_deltas = get_hourly_deltas(database, id_entity_hc, ts0)
energy_hg_deltas = get_hourly_deltas(database, id_entity_hg, ts0)

# 2. Utilisation de la somme des deltas pour déterminer l'énergie mesurée (en kWh)
energy_hp = round(sum(energy_hp_deltas) / 1000, 2)
energy_hc = round(sum(energy_hc_deltas) / 1000, 2)

# Calculer la somme des deltas HG (kWh) et l'appliquer au total pour l'affichage :
energy_hg_sum_deltas_kwh = sum(energy_hg_deltas)

# Si la somme est absurde, forcer la valeur mesurée HG à correspondre au Linky
# (ce qui est l'objectif du script de toute façon).
if energy_hg_sum_deltas_kwh > (energy_linky_hg * 1000): # Si > 3000 kWh (3kWh Linky)
    print("⚠️ Valeur HG mesurée anormale détectée. Forçage à la valeur Linky pour affichage.")
    energy_hg = energy_linky_hg # Force à 3.05 kWh pour que l'affichage soit correct
    # Le delta horaire dans la Section 5 gérera la correction
else:
    energy_hg = round(energy_hg_sum_deltas_kwh, 2)


energy_total = round(energy_hc + energy_hp + energy_hg, 2)
print(f"Energie mesurée J-{jours}: {energy_total} kWh (HP:{energy_hp} / HC:{energy_hc} / HG:{energy_hg})")

# 3. Calcul des deltas totaux (en kWh)
delta = round(energy_linky - energy_total, 2)
delta_hp = round(energy_linky_hp - energy_hp, 2)
delta_hc = round(energy_linky_hc - energy_hc, 2)
delta_hg = round(energy_linky_hg - energy_hg, 2)
print (f"Delta: {delta} kWh (HP:{delta_hp} / HC:{delta_hc} / HG:{delta_hg})")


# -----------------------------------------------------
# 5. CALCUL DES DELTAS HORAIRES ET CORRECTION EN BASE
# -----------------------------------------------------

# Calcul des deltas finaux à appliquer (Linky WH - Meter WH)
# Les tableaux sont garantis à 24 éléments

# HP/HC : Linky (Wh) - Meter (Wh) = Delta (Wh)
delta_hc_final = arr.array('f', [energy_linky_hc_wh_hourly[i] - energy_hc_deltas[i] for i in range(24)])
delta_hp_final = arr.array('f', [energy_linky_hp_wh_hourly[i] - energy_hp_deltas[i] for i in range(24)])

# HG : Linky (Wh) - Meter (kWh * 1000 -> Wh) = Delta (Wh)
delta_hg_final = arr.array('f', [energy_linky_hg_wh_hourly[i] - (energy_hg_deltas[i] * 1000) for i in range(24)])
# -----------------------------------------------------
# 6. APPLICATION DES CORRECTIONS EN BASE DE DONNÉES
# -----------------------------------------------------

query_updates = []
if error == 0:
    for i in range(24):
        delta_hc_wh = delta_hc_final[i]
        delta_hp_wh = delta_hp_final[i]
        delta_hg_wh = delta_hg_final[i]
        ts_start = ts0 + i * 3600

        # Correction HC
        if abs(delta_hc_wh) >= 1: # Correction appliquée si le delta est >= 1 Wh
            query_updates.append((id_entity_hc, delta_hc_wh, ts_start, "Wh"))
            
        # Correction HP
        if abs(delta_hp_wh) >= 1:
            query_updates.append((id_entity_hp, delta_hp_wh, ts_start, "Wh"))

        # Correction HG
        if abs(delta_hg_wh) >= 1:
            # Pour HG, nous enregistrons le delta comme étant en Wh, mais il sera
            # converti en kWh (delta / 1000) lors de l'application.
            query_updates.append((id_entity_hg, delta_hg_wh, ts_start, "kWh"))

    
    # Appliquer toutes les corrections
    for id_ent, delta_val_raw, ts_start, unit_type in query_updates:
        
        delta_val = delta_val_raw
        
        # CONVERSION CRITIQUE POUR HG (si l'entité est en kWh, le delta doit être en kWh)
        if unit_type == "kWh":
            delta_val = round(delta_val_raw / 1000, 3) # Convertir Wh -> kWh (garder 3 décimales)
            
        sign = '+' if delta_val > 0 else ''
        
        # Correction statistics (horaire/long-terme)
        # Afficher l'unité correcte dans le log
        log_unit = "Wh" if unit_type == "Wh" else "kWh"
        
        query_stat = f"UPDATE statistics set sum=sum{sign}{delta_val} where metadata_id='{id_ent}' and start_ts>='{ts_start}'"
        print(f"STAT UPDATE ({id_ent}, {delta_val:.3f} {log_unit}): {query_stat}")
        database.execute(query_stat)
        
        # Correction statistics_short_term (5min)
        query_short = f"UPDATE statistics_short_term set sum=sum{sign}{delta_val} where metadata_id='{id_ent}' and start_ts>='{ts_start}'"
        database.execute(query_short)


    # Récapitulatif
    delta_hp_total = sum(delta_hp_final)
    delta_hc_total = sum(delta_hc_final)
    delta_hg_total = sum(delta_hg_final)
    
    # ... (Le reste du récapitulatif est inchangé)
    print("\n-------------------------------------------")
    print(f"TOTAL DELTA APPLIQUÉ (Wh): HP={delta_hp_total:.0f} | HC={delta_hc_total:.0f} | HG={delta_hg_total:.0f}")
    print("-------------------------------------------")

    retour = f"Delta corrigé:{delta} kWh (HP:{round(delta_hp_total/1000, 2)}/HC:{round(delta_hc_total/1000, 2)}/HG:{round(delta_hg_total/1000, 2)})"
    print(retour)
    
    # Valider la transaction uniquement si des mises à jour ont été exécutées
    if query_updates:
        database.execute("commit")
        print("Transaction validée : corrections appliquées.")
    else:
        print("Aucune correction nécessaire. La base de données n'a pas été modifiée.")

elif error == 1:
    print(retour)

database.close()