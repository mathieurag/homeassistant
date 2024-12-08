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

entity = "sensor.ecojoko_consommation_temps_reel"
print("entité =",entity)

query0 = "pragma query_only=0"
data=database.execute(query0)

query0 = "SELECT metadata_id FROM 'states_meta' where entity_id='" + entity +"'"
#print("requete=",query0)
data=database.execute(query0)
for row in data.fetchall():
    id_states = row[0]
    print("id state =",id_states)
row=""

query0 = "SELECT id FROM 'statistics_meta' where statistic_id='" + entity +"'"
#print("requete=",query0)
data=database.execute(query0)
for row in data.fetchall():
    id_statistic = row[0]
    print("id statistic =",id_statistic)
row=""

query0 = "SELECT state FROM 'states' where metadata_id='" + str(id_states) +"' and last_updated_ts>" + str(ts0) +" ORDER BY cast(State as int) + 0 ASC LIMIT 1"
#print("requete=",query0)
data=database.execute(query0)
for row in data.fetchall():
    min_state = row[0]
    print("Conso min H24 EM06 =",min_state,"W")
row=""

query0 = "SELECT min,id FROM 'statistics_short_term' where metadata_id='" + str(id_statistic) +"' and start_ts>" + str(ts0) +" ORDER BY CAST(min as int) ASC LIMIT 1"
#print("requete=",query0)
data=database.execute(query0)
for row in data.fetchall():
    min_state = row[0]
    id_num = row[1]
    print("Conso stat short min H24 EM06 =",min_state,"W")
row=""

query0 = "SELECT min,id FROM 'statistics' where metadata_id='" + str(id_statistic) +"' and start_ts>" + str(ts0) +" ORDER BY CAST(min as int) ASC LIMIT 1"
#print("requete=",query0)
data=database.execute(query0)
for row in data.fetchall():
    min_state = row[0]
    id_num = row[1]
    print("Conso stat min H24 EM06 =",min_state,"W")
row=""

query0 = "UPDATE 'statistics' set where cast(min as int) <85 and metadata_id=" + str(id_statistic)

row=""


#STATES :

query = """SELECT
  states_meta.entity_id,
  COUNT(*) AS Count
FROM states
LEFT JOIN states_meta ON (states.metadata_id=states_meta.metadata_id)
GROUP BY states_meta.entity_id
ORDER BY Count DESC
LIMIT 50"""

data=database.execute(query)
Total=0
for row in data.fetchall():
  entity = row[0]
  Num = row[1]
  print(entity," : ",Num)
  Total = Total + Num

print("Total =",Total)

print("")

#TABLE :

query = """SELECT
  SUM(cast(pgsize as int)/1024) kbytes,
  name
FROM dbstat
GROUP BY name
ORDER BY kbytes DESC"""

data=database.execute(query)
Total=0
id=0
for row in data.fetchall():
  table = row[1]
  size = row[0]
  id = id + 1
  if(id <= 3):
    print(table," : ",size," kb")
  Total = Total + size
  
print("")
print("Total =",Total, "kb")

row=""

entity = "sensor.energie_solar_j"
print("entité =",entity)

query0 = "SELECT metadata_id FROM 'states_meta' where entity_id='" + entity +"'"
#print("requete=",query1)
data=database.execute(query0)
for row in data.fetchall():
    id_entity = row[0]
    print("id states =",id_entity)
row=""

query2 = "SELECT COUNT(*) AS Count FROM 'states' where metadata_id='" + str(id_entity) + "' and cast(state as float)>'100'"
#print("requete=",query2)
data=database.execute(query2)
for row in data.fetchall():
    Count = row[0]
    print("Nombre enregistrements =",Count)

row2=""

min=0

if int(Count) > min:
    print(">",min," entrée(s)")
    print("Suppression des données erronnées :")
    
    query5="DELETE FROM 'states' where metadata_id='" + str(id_entity) +"' and cast(state as float)>'100'"
    print(query5)
    data=database.execute(query5)

    row=""
    print("Fin du script : ",Count," entrée(s) supprimée(s)")
    query0 = "commit"
    data=database.execute(query0)
else:
    print("Fin du script : pas de données à supprimer")

database.close()