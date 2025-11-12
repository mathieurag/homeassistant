import sqlite3
import time
import datetime
import pytz

try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

error = 0
jours = 1
DELTA_MIN = 0.03
DELTA_NEGATIF_MIN = 0.005  # Seuil pour les deltas négatifs (toute valeur négative sera corrigée)

# ---------- Fonctions de lecture pour la robustesse ----------
def normalize_unit(unit):
    if unit is None:
        return "kWh"
    u = str(unit).strip().lower()
    return "Wh" if u == "wh" else "kWh"

def to_kwh(val, unit):
    if val is None:
        return None
    return round(val / 1000.0, 4) if unit == "Wh" else round(val, 3)

def get_meta(stat_id):
    q = "SELECT id, unit_of_measurement FROM statistics_meta WHERE statistic_id = ?"
    rows = database.execute(q, (stat_id,)).fetchall()
    if not rows:
        return None, "kWh"
    mid, unit = rows[0][0], normalize_unit(rows[0][1])
    return mid, unit

def get_sum_exact(metadata_id, ts):
    if metadata_id is None or metadata_id == "":
        return None
    q = "SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?"
    r = database.execute(q, (metadata_id, int(ts))).fetchone()
    return r[0] if (r and r[0] is not None) else None

def get_delta(metadata_id, unit, ts_start, ts_end):
    s0 = get_sum_exact(metadata_id, ts_start)
    s1 = get_sum_exact(metadata_id, ts_end)
    if s0 is None or s1 is None:
        return 0.0
    v0 = to_kwh(s0, unit)
    v1 = to_kwh(s1, unit)
    if v1 < v0 and abs(v1 - v0) < 0.1:
        return 0.0
    return round(v1 - v0, 4)

# ---------- Calcul de la date choisie à partir de jours ----------
target_date = datetime.date.today() - datetime.timedelta(days=jours)
local_tz = pytz.timezone("Europe/Paris")
dt_naive = datetime.datetime.combine(target_date, datetime.time.min)
dt_local = local_tz.localize(dt_naive, is_dst=None)
ts0 = dt_local.timestamp()
dt_end_naive = datetime.datetime.combine(target_date, datetime.time(23, 00, 00))
dt_end_local = local_tz.localize(dt_end_naive, is_dst=None)
tsmax = dt_end_local.timestamp()
print(target_date.strftime("%d/%m/%Y"))

# ---------- Listes d'entités ----------
liste = [
    'sensor.double_clamp_meter_total_energy_a', 'sensor.lave_vaisselle', 'sensor.cumulus_kwh',
    'sensor.frigo_kwh', 'sensor.prise_tv', 'sensor.lave_linge',
    'sensor.bidirectional_energy_meter_energy_consumed_a', 'sensor.bidirectional_energy_meter_energy_consumed_b',
    'sensor.sonnette', 'sensor.em06_b2_this_month_energy',
    'sensor.double_clamp_meter_today_energy_b', 'sensor.em06_a2_this_month_energy',
    'sensor.disjoncteur_3', 'sensor.em06_a1_this_month_energy',
    'sensor.lampe_salon_2', 'sensor.em06_c2_this_month_energy',
    'sensor.prises_rdc_2', 'sensor.disjoncteur_4', 'sensor.energie_borne', 'sensor.prise_zigbee_3_energy',
]
energie = [
    'sensor.energie_consommee_j_hg', 'sensor.energie_consommee_j_hp', 'sensor.energie_consommee_j_hc',
    'sensor.em06_02_a1_this_month_energy',
]
surplus = ['sensor.surplus_production_compteur']
charge_batterie = ['sensor.charge_marstek']
decharge_batterie = ['sensor.decharge_marstek']

# ---------- Récupération meta ----------
id_entity, unite_entity = [], []
for sid in liste:
    mid, unit = get_meta(sid)
    id_entity.append(mid)
    unite_entity.append(unit)

id_energie, unite_energie = [], []
for sid in energie:
    mid, unit = get_meta(sid)
    id_energie.append(mid)
    unite_energie.append(unit)
    if mid is None:
        print(f"⚠️ Entité Linky/Energie manquante: {sid}")

id_surplus, unite_surplus = [], []
for sid in surplus:
    mid, unit = get_meta(sid)
    id_surplus.append(mid)
    unite_surplus.append(unit)

id_charge_batterie, unite_charge_batterie = [], []
for sid in charge_batterie:
    mid, unit = get_meta(sid)
    id_charge_batterie.append(mid)
    unite_charge_batterie.append(unit)

id_decharge_batterie, unite_decharge_batterie = [], []
for sid in decharge_batterie:
    mid, unit = get_meta(sid)
    id_decharge_batterie.append(mid)
    unite_decharge_batterie.append(unit)

conso = [0] * 24
conso_linky = [0] * 24
conso_surplus = [0] * 24
conso_charge_batterie = [0] * 24
conso_decharge_batterie = [0] * 24
delta_conso = [0] * 24

# ---------- Calculs par heure ----------
for j in range(0, 24):
    ts_start_delta = ts0 + (j - 1) * 3600
    ts_end_delta = ts0 + j * 3600

    for i in range(len(liste)):
        conso[j] += get_delta(id_entity[i], unite_entity[i], ts_start_delta, ts_end_delta)

    for i in range(len(surplus)):
        conso_surplus[j] += get_delta(id_surplus[i], unite_surplus[i], ts_start_delta, ts_end_delta)

    for i in range(len(charge_batterie)):
        conso_charge_batterie[j] += get_delta(id_charge_batterie[i], unite_charge_batterie[i], ts_start_delta, ts_end_delta)

    for i in range(len(decharge_batterie)):
        conso_decharge_batterie[j] += get_delta(id_decharge_batterie[i], unite_decharge_batterie[i], ts_start_delta, ts_end_delta)

    for i in range(len(energie)):
        conso_linky[j] += get_delta(id_energie[i], unite_energie[i], ts_start_delta, ts_end_delta)

    delta_conso[j] = round(conso_linky[j] - conso[j] - conso_surplus[j] - conso_charge_batterie[j] + conso_decharge_batterie[j], 3)

    # Détection des deltas à corriger : soit > DELTA_MIN, soit négatifs
    if round(abs(delta_conso[j]), 3) >= DELTA_MIN or delta_conso[j] < 0:
        error += 1
        print(f"Consommation non suivie : {j} à {j+1}h : {round(delta_conso[j], 3)} kWh ==> à corriger")
    else:
        print(f"Consommation non suivie : {j} à {j+1}h : {round(delta_conso[j], 3)} kWh")

# ---------- Correction ----------
entry = 0
if error > 0:
    print("Corrections en cours :")
    for j in range(0, 24):
        if round(abs(delta_conso[j]), 3) >= DELTA_MIN or delta_conso[j] < 0:
            print(f"Consommation non suivie : {j} à {j+1}h : {round(delta_conso[j], 3)} kWh")

            ts_start_delta = ts0 + (j - 1) * 3600
            ts_end_delta = ts0 + j * 3600

            conso_max_kwh = 0.0
            max_entite = None
            range_max_entite = None

            for i in range(len(liste)):
                d_kwh = get_delta(id_entity[i], unite_entity[i], ts_start_delta, ts_end_delta)
                if d_kwh > conso_max_kwh:
                    conso_max_kwh = d_kwh
                    max_entite = id_entity[i]
                    range_max_entite = i

            if max_entite is None:
                print("⚠️ Aucune entité à corriger (conso max = 0). SKIP.")
                continue

            print(f"Conso max : {round(conso_max_kwh, 3)} kWh / Entité ID : {max_entite}")

            is_wh_unit = unite_entity[range_max_entite] == "Wh"
            factor = 1000 if is_wh_unit else 1

            # Calcul de la correction pour atteindre un delta de 0.005 kWh
            target_delta_kwh = 0.005
            delta_correction_kwh = delta_conso[j] - target_delta_kwh

            val_raw = delta_correction_kwh * factor

            # Vérification de la consommation négative
            if conso_max_kwh + (val_raw / factor) < 0:
                val_raw = -conso_max_kwh * factor
                print(f"⚠️ Correction limitée pour éviter conso négative. Correction finale appliquée: {round(val_raw/factor, 3)} kWh")

            if is_wh_unit:
                val_final = int(round(val_raw, 0))
            else:
                val_final = round(val_raw, 3)

            # Gestion du signe pour la requête SQL
            signe_op = "+" if val_final >= 0 else "-"
            abs_val_final = abs(val_final)

            if abs_val_final > 0:
                ts_update_start = int(ts0 + j * 3600)
                q1 = f"UPDATE statistics_short_term SET sum = sum {signe_op} {abs_val_final} WHERE metadata_id = {max_entite} AND start_ts >= {ts_update_start}"
                database.execute(q1)
                q2 = f"UPDATE statistics SET sum = sum {signe_op} {abs_val_final} WHERE metadata_id = {max_entite} AND start_ts >= {ts_update_start}"
                database.execute(q2)
                entry += 1
                print(f"Correction appliquée: heure {j}→{j+1}, delta={delta_conso[j]:.3f} kWh, correction={signe_op}{round(abs_val_final/factor, 3)} kWh")
            else:
                print(f"Correction nécessaire, mais delta final après ajustement est négligeable (0). SKIP.")

    if entry > 0:
        print(f"Fin du script : {entry} entrée(s) modifiée(s)")
        database.commit()  # Laissé en commentaire pour test
    else:
        print("Fin du script : Aucune correction appliquée (deltas trop faibles ou conso négative)")
else:
    print("Fin du script : Pas de données à modifier")

database.close()
