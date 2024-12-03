import sqlite3

try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

import time
import datetime

dt = datetime.datetime.today()
ts = datetime.datetime.timestamp(dt)

today = datetime.date.fromtimestamp(time.time())

dt0 = datetime.datetime(year=today.year, month=today.month, day=today.day)
ts0 = datetime.datetime.timestamp(dt0)

row=""

entity = "sensor.ecojoko_consommation_reseau"
print("entité =",entity)

query0 = "SELECT id FROM 'statistics_meta' where statistic_id='" + entity +"'"
#print("requete=",query1)
data=database.execute(query0)
for row in data.fetchall():
    id_entity = row[0]
    print("id statistics =",id_entity)
row=""

query2 = "SELECT COUNT(*) AS Count FROM 'statistics' where metadata_id='" + str(id_entity) + "' and start_ts<" + str(ts0)
#print("requete=",query2)
data=database.execute(query2)
for row in data.fetchall():
    Count = row[0]
    print("Nombre enregistrements =",Count)

row2=""

min=0

if int(Count) > min:
    print(">",min," entrée(s)")
    print("Suppression des données :")
    
    query5="DELETE FROM 'statistics' where metadata_id='" + str(id_entity) +"' and start_ts<" + str(ts0)
    print(query5)
    data=database.execute(query5)

    query5="DELETE FROM 'statistics_short_term' where metadata_id='" + str(id_entity) +"' and start_ts<" + str(ts0)
    print(query5)
    data=database.execute(query5)
    
    query5="UPDATE 'statistics' set sum=state where metadata_id='" + str(id_entity) +"'"
    print(query5)
    data=database.execute(query5)
    
    query5="UPDATE 'statistics_short_term' set sum=state where metadata_id='" + str(id_entity) +"'"
    print(query5)
    data=database.execute(query5)
        
    row=""
    print("Fin du script : ",Count," entrée(s) supprimée(s)")
    query0 = "commit"
    data=database.execute(query0)
else:
    print("Fin du script : pas de données à supprimer")

database.close()