import sqlite3

try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

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

query2 = "SELECT COUNT(*) AS Count FROM 'states' where metadata_id='" + str(id_entity) + "' and cast(state as float)>'30'"
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
    
    query5="DELETE FROM 'states' where metadata_id='" + str(id_entity) +"' and cast(state as float)>'30'"
    print(query5)
    data=database.execute(query5)

    row=""
    print("Fin du script : ",Count," entrée(s) supprimée(s)")
    query0 = "commit"
    data=database.execute(query0)
else:
    print("Fin du script : pas de données à supprimer")

database.close()