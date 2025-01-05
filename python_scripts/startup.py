import sqlite3

try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

import time
import datetime
error=0
jours=1
row=""

entity = "sensor.energie_consommee_j_hp"

query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
#print("requete=",query1)
data=database.execute(query0)
for row in data.fetchall():
    id_entity_hp = row[0]

print("entité =",entity,"/ id=",id_entity_hp)
row=""
entity = "sensor.energie_consommee_j_hc"

query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
#print("requete=",query1)
data=database.execute(query0)
for row in data.fetchall():
    id_entity_hc = row[0]

print("entité =",entity,"/ id=",id_entity_hc)

entity = "linky:16127930466069"

row=""
query0 = "SELECT id FROM 'statistics_meta' where statistic_id like '" + entity +"'"
#print("requete=",query1)
data=database.execute(query0)
for row in data.fetchall():
    id_entity_linky = row[0]

print("entité =",entity,"/ id=",id_entity_linky)

yesterday = datetime.date.fromtimestamp(time.time()-24*3600*jours)
dt0 = datetime.datetime(year=yesterday.year, month=yesterday.month, day=yesterday.day)
ts0 = datetime.datetime.timestamp(dt0)
tsmax = ts0 + 23*3600

print(yesterday)

#print (dt0)
#print (ts0)
#print (tsmax)


#Analyse sur la journée des deltas :

query0 = "SELECT state FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts >='" + str(ts0) + "' and start_ts<='" + str(tsmax) + "' order by start_ts ASC"
#print("requete=",query1)
data=database.execute(query0)

row=""
heure=0
energy_linky_hc=0
energy_linky_hp=0

for row in data.fetchall():
    
    if heure<5:
        energy_linky_hc=energy_linky_hc+row[0]
    elif heure==5:
        energy_linky_hc=energy_linky_hc+(0.13*row[0])
        energy_linky_hp=energy_linky_hp+(0.87*row[0])
    elif heure<21:
        energy_linky_hp=energy_linky_hp+row[0]
    elif heure==21:
        energy_linky_hp=energy_linky_hp+(0.13*row[0])
        energy_linky_hc=energy_linky_hc+(0.87*row[0])
    else:
        energy_linky_hc=energy_linky_hc+row[0]
    heure=heure+1

energy_linky = round((energy_linky_hc+energy_linky_hp) / 1000,2)
energy_linky_hc=round(energy_linky_hc/1000,2)
energy_linky_hp=round(energy_linky_hp/1000,2)

if energy_linky >0 : 
    print("Energie Linky J-",jours,":",energy_linky,"kWh","(HP:",energy_linky_hp,"/HC:",energy_linky_hc,")")
else:
    print("Energie Linky J-",jours,":",energy_linky,"kWh","(HP:",energy_linky_hp,"/HC:",energy_linky_hc,")")
    retour="Energie Linky NOK"
    error=1
    print(retour)

#Récupération des données HP/HC en base
sum_old=0
state_old=0

data=database.execute("SELECT state,sum FROM 'statistics' where metadata_id = '" + str(id_entity_hp) +"' and (start_ts ='" + str(ts0) + "' or start_ts='" + str(tsmax) + "') order by start_ts DESC")
row=""
energy_hp=0
for row in data.fetchall():
    energy_hp = energy_hp + row[1]
    state_old=row[0]
    sum_old=row[1]
energy_hp = round((energy_hp-2*sum_old+state_old) / 1000,2)

sum_old=0
state_old=0

data=database.execute("SELECT state,sum FROM 'statistics' where metadata_id = '" + str(id_entity_hc) +"' and (start_ts ='" + str(ts0) + "' or start_ts='" + str(tsmax) + "') order by start_ts DESC")
row=""
energy_hc=0

for row in data.fetchall():
    energy_hc = energy_hc + row[1]
    state_old=row[0]
    sum_old=row[1]

energy_hc = round((energy_hc-2*sum_old+state_old) / 1000,2)
energy_total = round(energy_hc + energy_hp,2)
print("Energie mesurée J-",jours,":",energy_total,"kWh","(HP:",energy_hp,"/HC:",energy_hc,")")

delta=round(energy_linky-energy_total,2)
delta_hp=round(energy_linky_hp-energy_hp,2)
delta_hc=round(energy_linky_hc-energy_hc,2)
print ("Delta:",delta,"kWh","(HP:",delta_hp,"/HC:",delta_hc,")")

if delta==0:
    error=1
    retour="Pas de données à modifier"

#Analyse heure / heure :

query0 = "SELECT state FROM 'statistics' where metadata_id = '" + str(id_entity_linky) +"' and start_ts >='" + str(ts0) + "' and start_ts<='" + str(tsmax) + "' order by start_ts ASC"
#print("requete=",query0)
data=database.execute(query0)

row=""
heure=0

import array as arr

energy_linky_hc = arr.array('f')
energy_linky_hp = arr.array('f')
heure_array= arr.array('i')

for row in data.fetchall():
    if heure<5:
        energy_linky_hc.append(round(row[0],0))
        energy_linky_hp.append(0)
    elif heure==5:
        energy_linky_hc.append(round(0.13*row[0],0))
        energy_linky_hp.append(round(0.87*row[0],0))
    elif heure<21:
        energy_linky_hp.append(round(row[0],0))
        energy_linky_hc.append(0)
    elif heure==21:
        energy_linky_hp.append(round(0.13*row[0],0))
        energy_linky_hc.append(round(0.87*row[0],0))
    else:
        energy_linky_hc.append(round(row[0],0))
        energy_linky_hp.append(0)
    
    heure_array.append(heure)
    heure=heure+1


ts_old=ts0-3600
sum_old=0
data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_hp) +"' and start_ts ='" + str(ts_old) + "'")
for row in data.fetchall():
    sum_old=row[0]

query0 = "SELECT state,sum FROM 'statistics' where metadata_id = '" + str(id_entity_hp) +"' and start_ts >='" + str(ts0) + "' and start_ts<='" + str(tsmax) + "' order by start_ts ASC"
#print("requete=",query0)
data=database.execute(query0)

row=""
heure=0

import array as arr
# creating array of float
energy_hp = arr.array('f')
heure_array= arr.array('i')

for row in data.fetchall():
    energy_hp.append(round(row[1]-sum_old,0))
    sum_old=row[1]
    heure_array.append(heure)
    heure=heure+1

ts_old=ts0-3600
sum_old=0
data=database.execute("SELECT sum FROM 'statistics' where metadata_id = '" + str(id_entity_hc) +"' and start_ts ='" + str(ts_old) + "'")
for row in data.fetchall():
    sum_old=row[0]

query0 = "SELECT state,sum FROM 'statistics' where metadata_id = '" + str(id_entity_hc) +"' and start_ts >='" + str(ts0) + "' and start_ts<='" + str(tsmax) + "' order by start_ts ASC"
#print("requete=",query0)
data=database.execute(query0)

row=""
heure=0

import array as arr
# creating array of float
energy_hc = arr.array('f')
heure_array= arr.array('i')

for row in data.fetchall():
    energy_hc.append(round(row[1]-sum_old,0))
    sum_old=row[1]
    heure_array.append(heure)
    heure=heure+1

#Calcul des deltas
delta_hc = arr.array('f')
delta_hp = arr.array('f')

energy_linky_hc_total=0
energy_linky_hp_total=0
energy_hc_total=0
energy_hp_total=0
delta_hp_total=0
delta_hc_total=0

query=""
if error==0:
    for i in range(0, 24):
        energy_linky_hc_total=energy_linky_hc_total+energy_linky_hc[i]
        energy_linky_hp_total=energy_linky_hp_total+energy_linky_hp[i]
        energy_hc_total=energy_hc_total+energy_hc[i]
        energy_hp_total=energy_hp_total+energy_hp[i]
        delta_hc.append(energy_linky_hc[i]-energy_hc[i])
        delta_hp.append(energy_linky_hp[i]-energy_hp[i])
        delta_hc_total=delta_hc_total+delta_hc[i]
        delta_hp_total=delta_hp_total+delta_hp[i]

        if delta_hc[i]>0:
            query="UPDATE statistics set sum=sum+"+str(delta_hc[i])+" where metadata_id='"+str(id_entity_hc)+"' and start_ts>=" + str(ts0+i*3600)
            print(query)
            data=database.execute(query)
            query="UPDATE statistics_short_term set sum=sum+"+str(delta_hc[i])+" where metadata_id='"+str(id_entity_hc)+"' and start_ts>=" + str(ts0+i*3600)
            data=database.execute(query)    
        elif delta_hc[i]<0:
            query="UPDATE statistics set sum=sum"+str(delta_hc[i])+" where metadata_id='"+str(id_entity_hc)+"' and start_ts>=" + str(ts0+i*3600)    
            print(query)
            data=database.execute(query)
            query="UPDATE statistics_short_term set sum=sum+"+str(delta_hc[i])+" where metadata_id='"+str(id_entity_hc)+"' and start_ts>=" + str(ts0+i*3600)
            data=database.execute(query)
        if delta_hp[i]>0:
            query="UPDATE statistics set sum=sum+"+str(delta_hp[i])+" where metadata_id='"+str(id_entity_hp)+"' and start_ts>=" + str(ts0+i*3600)
            print(query)
            data=database.execute(query)
            query="UPDATE statistics_short_term set sum=sum+"+str(delta_hp[i])+" where metadata_id='"+str(id_entity_hp)+"' and start_ts>=" + str(ts0+i*3600)
            data=database.execute(query)
        elif delta_hp[i]<0:
            query="UPDATE statistics set sum=sum"+str(delta_hp[i])+" where metadata_id='"+str(id_entity_hp)+"' and start_ts>=" + str(ts0+i*3600)
            print(query)
            data=database.execute(query)
            query="UPDATE statistics_short_term set sum=sum+"+str(delta_hp[i])+" where metadata_id='"+str(id_entity_hp)+"' and start_ts>=" + str(ts0+i*3600)
            data=database.execute(query)

    print("linky_hc",energy_linky_hc_total,"détails :",energy_linky_hc)
    print("energy_hc",energy_hc_total,"détails :",energy_hc)
    print("linky_hp",energy_linky_hp_total,"détails :",energy_linky_hp)
    print("energy_hp",energy_hp_total,"détails :",energy_hp)
    print("delta_hc",delta_hc_total,"détails :",delta_hc)
    print("delta_hp",delta_hp_total,"détails :",delta_hp)

if query=="":
    retour="Pas de données à modifier"
    print(retour)
elif error==1:
    print(retour)
else:
    retour= "Delta corrigé:"+str(delta)+" kWh (HP:"+str(round(delta_hp_total/1000,2))+"/HC:"+str(round(delta_hc_total/1000,2))+")"
    print(retour)
    data=database.execute("commit")



database.close()
