import sqlite3
import datetime
import pytz

# ---------- Paramètres ----------
jours = 1                     # J-1
DEBUG_HOUR = None             # ex: 11 pour 11h→12h, ou None pour désactiver

# ---------- Connexion ----------
try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

error = 0
row = ""

# ---------- Date / Heure (locale -> timestamps UTC en secondes) ----------
target_date = datetime.date.today() - datetime.timedelta(days=jours)
local_tz = pytz.timezone("Europe/Paris")

dt_naive = datetime.datetime.combine(target_date, datetime.time.min)
dt_local = local_tz.localize(dt_naive, is_dst=None)
ts0 = int(dt_local.timestamp())  # 00:00 local -> UTC epoch

dt_end_naive = datetime.datetime.combine(target_date, datetime.time(23, 0, 0))
dt_end_local = local_tz.localize(dt_end_naive, is_dst=None)
tsmax = int(dt_end_local.timestamp())

print(target_date.strftime("%d/%m/%Y"))

# ---------- Listes d'entités ----------
liste = [
    'sensor.double_clamp_meter_total_energy_a',
    'sensor.lave_vaisselle',
    'sensor.cumulus_kwh',
    'sensor.frigo_kwh',
    'sensor.prise_tv',
    'sensor.lave_linge',
    'sensor.bidirectional_energy_meter_energy_consumed_a',
    'sensor.bidirectional_energy_meter_energy_consumed_b',
    'sensor.sonnette',
    'sensor.em06_b2_this_month_energy',
    'sensor.double_clamp_meter_today_energy_b',
    'sensor.em06_a2_this_month_energy',
    'sensor.disjoncteur_3',
    'sensor.em06_a1_this_month_energy',
    'sensor.lampe_salon_2',
    'sensor.em06_c2_this_month_energy',
    'sensor.prises_rdc_2',
    'sensor.disjoncteur_4',
    #'sensor.prise_5_energie',
    'sensor.energie_borne',
    'sensor.prise_zigbee_3_energy',
]

energie = [
    'sensor.energie_consommee_j_hg',
    'sensor.energie_consommee_j_hp',
    'sensor.energie_consommee_j_hc',
    'sensor.em06_02_a1_this_month_energy',
]

surplus = ['sensor.surplus_production_compteur']
charge_batterie = ['sensor.charge_marstek']
decharge_batterie = ['sensor.decharge_marstek']

# ---------- Helpers ----------
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
    if metadata_id is None:
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
    return round(v1 - v0, 4)

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

# ---------- Accumulateurs horaires ----------
conso = [0.0] * 24
conso_linky = [0.0] * 24
conso_surplus = [0.0] * 24
conso_charge_batterie = [0.0] * 24
conso_decharge_batterie = [0.0] * 24
delta_conso = [0.0] * 24

# ---------- Calculs par heure ----------
for j in range(0, 24):
    ts_start = ts0 + (j - 1) * 3600
    ts_end   = ts0 + j * 3600

    for i in range(len(liste)):
        conso[j] += get_delta(id_entity[i], unite_entity[i], ts_start, ts_end)

    for i in range(len(surplus)):
        conso_surplus[j] += get_delta(id_surplus[i], unite_surplus[i], ts_start, ts_end)

    for i in range(len(charge_batterie)):
        conso_charge_batterie[j] += get_delta(id_charge_batterie[i], unite_charge_batterie[i], ts_start, ts_end)

    for i in range(len(decharge_batterie)):
        conso_decharge_batterie[j] += get_delta(id_decharge_batterie[i], unite_decharge_batterie[i], ts_start, ts_end)

    for i in range(len(energie)):
        conso_linky[j] += get_delta(id_energie[i], unite_energie[i], ts_start, ts_end)

    delta_conso[j] = round(
        conso_linky[j] - conso[j] - conso_surplus[j] - conso_charge_batterie[j] + conso_decharge_batterie[j], 3
    )

    print("Consommation non suivie : ", j, "à", j+1, "h : ", round(delta_conso[j], 3), "kWh")
    if delta_conso[j] >= 0.005 or delta_conso[j] < 0:
        error += 1

    if DEBUG_HOUR is not None and j == DEBUG_HOUR:
        print(f"\n--- Détail {j}h → {j+1}h ---")
        for i in range(len(liste)):
            d = get_delta(id_entity[i], unite_entity[i], ts_start, ts_end)
            print(f"{liste[i]:40s} : {d:8.4f} kWh")
        print(f"Total suivi        : {round(conso[j],4)} kWh")
        print(f"Linky (energie)    : {round(conso_linky[j],4)} kWh")
        print(f"Surplus            : {round(conso_surplus[j],4)} kWh")
        print(f"Charge batterie    : {round(conso_charge_batterie[j],4)} kWh")
        print(f"Décharge batterie  : {round(conso_decharge_batterie[j],4)} kWh")
        print(f"Delta (non suivi)  : {round(delta_conso[j],4)} kWh")

# ---------- Correction ----------
entry = 0
conso_max = 0.0

if error > 0:
    print("Consommation non suivie importante : ")
    for j in range(0, 24):
        if delta_conso[j] > 0.1 or delta_conso[j] < 0:
            print("Consommation non suivie : ", j, "à", j+1, "h : ", round(delta_conso[j], 3), "kWh")

            conso_max = 0.0
            max_entite = None
            range_max_entite = None
            ts_start = ts0 + (j - 1) * 3600
            ts_end   = ts0 + j * 3600

            for i in range(len(liste)):
                d = get_delta(id_entity[i], unite_entity[i], ts_start, ts_end)
                if d > conso_max:
                    conso_max = d
                    max_entite = id_entity[i]
                    range_max_entite = i

            print("Conso max :", conso_max, "kWh / Entité : ", max_entite)

            if range_max_entite is not None and unite_entity[range_max_entite] == "Wh":
                factor = 1000
            else:
                factor = 1

            if delta_conso[j] >= 0.8 or delta_conso[j] <= -0.8:
                print(f"Delta trop important à : {j} h: {delta_conso[j]:.3f} kWh")
                continue

            if delta_conso[j] < 0:
                val = round((delta_conso[j] - 0.005) * factor, 3)
            else:
                val = round((0.005 - delta_conso[j]) * factor, 3)

            # Vérification pour éviter une conso négative
            d = get_delta(id_entity[range_max_entite], unite_entity[range_max_entite], ts_start, ts_end)
            if d + (val / factor) < 0:
                val = -d * factor
                print(f"⚠️ Correction limitée pour éviter conso négative (conso={d:.3f} kWh)")

            ts_cut = int(ts0 + j * 3600)
            if max_entite is not None:
                q1 = f"UPDATE statistics_short_term SET sum = sum + {val} WHERE metadata_id = {max_entite} AND start_ts >= {ts_cut}"
                database.execute(q1)
                q2 = f"UPDATE statistics SET sum = sum + {val} WHERE metadata_id = {max_entite} AND start_ts >= {ts_cut}"
                database.execute(q2)
                entry += 1
                signe = "+" if val >= 0 else "-"
                print(f"Correction appliquée: heure {j}→{j+1}, delta={delta_conso[j]:.3f} kWh, correction={signe}{abs(val)/factor:.3f} kWh")

    if entry > 0:
        #database.commit()
        print("Fin du script : ", entry, " entrée(s) modifiée(s)")
    else:
        print("Fin du script : 0 entrée modifiée (aucune correction applicable)")
else:
    print("Fin du script : Pas de données à modifier")

# ---------- Vérification des consommations négatives ----------
print("\n--- Vérification des consommations négatives ---")
for j in range(0, 24):
    ts_start = ts0 + (j - 1) * 3600
    ts_end   = ts0 + j * 3600

    for i in range(len(liste)):
        d = get_delta(id_entity[i], unite_entity[i], ts_start, ts_end)
        if d < 0:
            print(f"⚠️  Conso négative détectée : {liste[i]} sur {j}h→{j+1}h = {d:.4f} kWh")

database.close()
