import sqlite3

try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

import time
import datetime
import pytz

error=0
jours=1
row=""

entity = "sensor.surplus_production_compteur"

query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
#print("requete=",query1)
data=database.execute(query0)
for row in data.fetchall():
    id_entity_surplus = row[0]

print("entité =",entity,"/ id=",id_entity_surplus)
row=""

entity = "linky_prod:16127930466069"

query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
#print("requete=",query1)
data=database.execute(query0)
for row in data.fetchall():
    id_entity_linky = row[0]

print("entité =",entity,"/ id=",id_entity_linky)

# Calcul de la date choisie à partir de jours:
target_date = datetime.date.today() - datetime.timedelta(days=jours)

# Fuseau horaire local
local_tz = pytz.timezone("Europe/Paris")

# Créer datetime à minuit, puis convertir proprement
dt_naive = datetime.datetime.combine(target_date, datetime.time.min)
dt_local = local_tz.localize(dt_naive, is_dst=None)  # is_dst=None force une erreur si ambigü
ts0 = dt_local.timestamp()

# Pour 23h00 locale
dt_end_naive = datetime.datetime.combine(target_date, datetime.time(23, 00, 00))
dt_end_local = local_tz.localize(dt_end_naive, is_dst=None)
tsmax = dt_end_local.timestamp()

#yesterday = datetime.date.fromtimestamp(time.time()-24*3600*jours)
#dt0 = datetime.datetime(year=yesterday.year, month=yesterday.month, day=yesterday.day)
#ts0 = datetime.datetime.timestamp(dt0)
#tsmax = ts0 + 23*3600
#print(ts0)
#print(tsmax)

#Analyse sur la journée des deltas :

energy_surplus=0
energy_surplus_old=0
error=0

data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts='" + str(tsmax) + "'")
for row in data.fetchall():
    energy_surplus=row[0]
if energy_surplus==0:
    error=1

data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts ='" + str(ts0-3600)+"'")
for row in data.fetchall():
    energy_surplus_old=row[0]

energy_surplus=energy_surplus-energy_surplus_old

energy_linky=0
energy_linky_old=0

data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts='" + str(tsmax) + "'")
#print("SELECT sum FROM 'statistics' where metadata_id = '",str(id_entity_linky),"' and start_ts='",str(tsmax),"'")
for row in data.fetchall():
    energy_linky=row[0]
if energy_linky==0:
    error=1

data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts ='" + str(ts0-3600)+"'")
for row in data.fetchall():
    energy_linky_old=row[0]


energy_linky=round((energy_linky-energy_linky_old)/1000,4)

print("Linky",round(energy_linky,4),"kWh")
print("Surplus",round(energy_surplus,4),"kWh")
print("Delta",round(energy_surplus-energy_linky,4),"kWh")
delta=round(energy_surplus-energy_linky,4)

energy_surplus = []
energy_linky = []
delta_energie = []

energy_linky_total=0
energy_surplus_total=0
delta_energie_total=0
commit=0
if error==0:
    if delta==0:
        retour="Pas de données à modifier : delta journalier = 0"

    for i in range(0, 24):
        #Analyse heure / heure :

        #Surplus
        data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts ='" + str(ts0+i*3600)+"'")
        for row in data.fetchall():
            sum=row[0]
        data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_surplus) +"' and start_ts ='" + str(ts0+(i-1)*3600)+"'")
        for row in data.fetchall():
            sum_old=row[0]

        energy_surplus.append(round(sum-sum_old,3))

        #linky
        data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts ='" + str(ts0+i*3600)+"'")
        for row in data.fetchall():
            sum=row[0]

        #linky
        data = database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts ='" + str(ts0+(i-1)*3600)+"'")
        for row in data.fetchall():
            sum_old=row[0]

        energy_linky.append(round((sum-sum_old)/1000,3))

        #Calcul des deltas

        delta_energie.append(round(energy_linky[i]-energy_surplus[i],3))

        energy_linky_total=energy_linky_total+energy_linky[i]
        energy_surplus_total=energy_surplus_total+energy_surplus[i]
        delta_energie_total=delta_energie_total+delta_energie[i]

        if delta_energie[i]>0:
            query="UPDATE statistics set sum=sum+"+str(delta_energie[i])+" where metadata_id='"+str(id_entity_surplus)+"' and start_ts>=" + str(ts0+i*3600)
            print(query)
            data=database.execute(query)
            query="UPDATE statistics_short_term set sum=sum+"+str(delta_energie[i])+" where metadata_id='"+str(id_entity_surplus)+"' and start_ts>=" + str(ts0+i*3600)
            data=database.execute(query)
            commit=1
        elif delta_energie[i]<0:
            query="UPDATE statistics set sum=sum"+str(delta_energie[i])+" where metadata_id='"+str(id_entity_surplus)+"' and start_ts>=" + str(ts0+i*3600)
            print(query)
            data=database.execute(query)
            query="UPDATE statistics_short_term set sum=sum"+str(delta_energie[i])+" where metadata_id='"+str(id_entity_surplus)+"' and start_ts>=" + str(ts0+i*3600)
            data=database.execute(query)
            commit=1

    print("Linky :",round(energy_linky_total,3),"détails :",energy_linky)
    print("Surplus :",round(energy_surplus_total,3),"détails :",energy_surplus)
    print("Delta :",round(delta_energie_total,3),"détails :",delta_energie)

    if commit==1:
        data=database.execute("commit")
        retour= "Delta corrigé:"+str(delta_energie)+" kWh (HP:"+str(round(delta_energie_total/1000,2))+")"
else:
    retour= "Pas de données à J-"+jours

print(retour)


database.close()
