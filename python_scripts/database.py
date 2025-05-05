import sqlite3

try:
  database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
  database = sqlite3.connect('home-assistant_v2.db')

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

with open("/config/custom_stats.md", "w") as f:
  f.write("| Entité | Nombre |\n")
  f.write("|--------|--------|\n")

  for row in data.fetchall():
    entity = row[0]
    Num = row[1]
    print(entity," : ",Num)
    f.write(f"| {entity} | {Num} |\n")
    Total = Total + Num

  print("Total =",Total)
  f.write(f"| **Total** | **{Total}** |\n")
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

database.close()