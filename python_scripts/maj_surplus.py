import sqlite3
import time
import datetime
import pytz

try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

error=0
jours=1
row=""

# ----------------- 1. Identification des Entités -----------------
entity = "sensor.surplus_production_compteur"

query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
data=database.execute(query0)
id_entity_surplus = None
for row in data.fetchall():
    id_entity_surplus = row[0]

if id_entity_surplus:
    print("entité =",entity,"/ id=",id_entity_surplus)
else:
    print(f"Erreur: Entité {entity} non trouvée.")
    error=1

entity = "linky_prod:16127930466069"

query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
data=database.execute(query0)
id_entity_linky = None
for row in data.fetchall():
    id_entity_linky = row[0]

if id_entity_linky:
    print("entité =",entity,"/ id=",id_entity_linky)
else:
    print(f"Erreur: Entité {entity} non trouvée.")
    error=1
    
row=""

# ----------------- 2. Calcul des Timestamps -----------------
target_date = datetime.date.today() - datetime.timedelta(days=jours)
print("Date=",target_date)

local_tz = pytz.timezone("Europe/Paris")

dt_naive = datetime.datetime.combine(target_date, datetime.time.min)
dt_local = local_tz.localize(dt_naive, is_dst=None)
ts0 = dt_local.timestamp()

dt_end_naive = datetime.datetime.combine(target_date, datetime.time(23, 00, 00))
dt_end_local = local_tz.localize(dt_end_naive, is_dst=None)
tsmax = dt_end_local.timestamp()

# ----------------- 3. Analyse Globale (Journalière) -----------------

energy_surplus=0
energy_surplus_old=0
energy_linky=0
energy_linky_old=0
error=0

if id_entity_surplus:
    # Lecture Surplus (supposé en kWh)
    data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts='" + str(tsmax) + "'")
    for row in data.fetchall():
        energy_surplus=row[0]
    data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts ='" + str(ts0-3600)+"'")
    for row in data.fetchall():
        energy_surplus_old=row[0]
    energy_surplus = round(energy_surplus - energy_surplus_old, 4)
else:
    error=1

if id_entity_linky:
    # Lecture Linky (supposé en Wh -> Conversion en kWh)
    data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts='" + str(tsmax) + "'")
    for row in data.fetchall():
        energy_linky=row[0]
    data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts ='" + str(ts0-3600)+"'")
    for row in data.fetchall():
        energy_linky_old=row[0]
    energy_linky=round((energy_linky-energy_linky_old)/1000,4)
else:
    error=1

print("Linky",round(energy_linky,4),"kWh")
print("Surplus",round(energy_surplus,4),"kWh")
delta=round(energy_surplus-energy_linky,4)
print("Delta",delta,"kWh")


# ----------------- 4. Analyse et Correction Horaire -----------------
energy_surplus_hourly = []
energy_linky_hourly = []
delta_energie_hourly = []

energy_linky_total=0
energy_surplus_total=0
delta_energie_total=0
commit=0
retour="Fin du script."

if error==0:
    if abs(delta) < 0.0001:
        retour="Pas de données à modifier : delta journalier négligeable."
    else:

        for i in range(0, 24):
            # Calcul des timestamps pour la tranche [i-1h -> i]
            ts_start_delta = ts0 + (i-1)*3600
            ts_end_delta   = ts0 + i*3600

            # Surplus (kWh)
            sum_surplus = 0
            sum_old_surplus = 0
            data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts ='" + str(ts_end_delta)+"'")
            for row in data.fetchall():
                sum_surplus=row[0]
            data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts ='" + str(ts_start_delta)+"'")
            for row in data.fetchall():
                sum_old_surplus=row[0]
            energy_surplus_hourly.append(round(sum_surplus-sum_old_surplus,3))

            # Linky (Wh -> kWh)
            sum_linky = 0
            sum_old_linky = 0
            data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts ='" + str(ts_end_delta)+"'")
            for row in data.fetchall():
                sum_linky=row[0]
            data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts ='" + str(ts_start_delta)+"'")
            for row in data.fetchall():
                sum_old_linky=row[0]
            energy_linky_hourly.append(round((sum_linky-sum_old_linky)/1000,3))

            # Calcul des deltas (Linky - Surplus, en kWh)
            delta_energie = round(energy_linky_hourly[i]-energy_surplus_hourly[i],3)
            delta_energie_hourly.append(delta_energie)
            
            energy_linky_total+=energy_linky_hourly[i]
            energy_surplus_total+=energy_surplus_hourly[i]
            delta_energie_total+=delta_energie_hourly[i]

            # Si le delta est significatif (correction nécessaire)
            if abs(delta_energie) > 0.0001:
                commit=1
                
                # Le delta est en kWh (float). On utilise la valeur elle-même.
                val_correction = round(delta_energie, 4) # Garder une précision raisonnable
                
                # Assurer le bon signe pour l'opération SQL
                signe_op = "+" if val_correction >= 0 else "" 
                
                ts_update_start = str(ts0+i*3600)

                # --- CORRECTION DE L'INJECTION SQL ---
                # Surplus est en kWh (float), on injecte la valeur float
                
                # UPDATE statistics
                query_stat = f"UPDATE statistics set sum=sum{signe_op}{val_correction} where metadata_id='{str(id_entity_surplus)}' and start_ts>={ts_update_start}"
                print(query_stat)
                database.execute(query_stat)
                
                # UPDATE statistics_short_term
                query_short = f"UPDATE statistics_short_term set sum=sum{signe_op}{val_correction} where metadata_id='{str(id_entity_surplus)}' and start_ts>={ts_update_start}"
                database.execute(query_short)


        print("Linky :",round(energy_linky_total,3),"détails :",energy_linky_hourly)
        print("Surplus :",round(energy_surplus_total,3),"détails :",energy_surplus_hourly)
        print("Delta :",round(delta_energie_total,3),"détails :",delta_energie_hourly)

        if commit==1:
            database.execute("commit")
            retour= f"Delta corrigé: {round(delta_energie_total,3)} kWh. Détails: {delta_energie_hourly}"
        else:
            retour = "Aucune modification nécessaire après l'analyse horaire."

else:
    retour= f"Erreur critique: Entité(s) manquante(s) ou pas de données Linky/Surplus à J-{jours}"

print(retour)

database.close()