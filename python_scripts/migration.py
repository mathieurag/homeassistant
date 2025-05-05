import sqlite3
from tqdm import tqdm

# Paramètres
DB_PATH = "/config/home-assistant_v2.db"
source_id = 167
target_id = 294
ts_limit = 1744653600.0

# Connexion SQLite
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Récupération des données source
cur.execute("""
    SELECT start_ts FROM statistics
    WHERE metadata_id = ? AND start_ts < ?
""", (source_id, ts_limit))

rows_to_process = cur.fetchall()
print(f"🔍 {len(rows_to_process)} lignes à traiter...")

updated = 0
inserted = 0

for (start_ts,) in tqdm(rows_to_process, desc="Migration vers metadata_id=294"):

    # Récupérer les données de l'entité source
    cur.execute("""
        SELECT created_ts, start_ts, mean, min, max, last_reset_ts, state, sum, mean_weight
        FROM statistics
        WHERE metadata_id = ? AND start_ts = ?
    """, (source_id, start_ts))

    data = cur.fetchone()
    if not data:
        continue

    # Vérifie si une ligne existe déjà pour metadata_id 294 et le même start_ts
    cur.execute("""
        SELECT 1 FROM statistics
        WHERE metadata_id = ? AND start_ts = ?
    """, (target_id, start_ts))

    if cur.fetchone():
        # Faire un UPDATE
        cur.execute("""
            UPDATE statistics
            SET
              created_ts = ?,
              mean = ?,
              min = ?,
              max = ?,
              last_reset_ts = ?,
              state = ?,
              sum = ?,
              mean_weight = ?
            WHERE metadata_id = ? AND start_ts = ?
        """, (
            data[0], data[2], data[3], data[4],
            data[5], data[6], data[7], data[8],
            target_id, start_ts
        ))
        updated += 1
    else:
        # Faire un INSERT
        cur.execute("""
            INSERT INTO statistics (
              created_ts, metadata_id, start_ts,
              mean, min, max, last_reset_ts,
              state, sum, mean_weight
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data[0], target_id, data[1], data[2], data[3], data[4],
            data[5], data[6], data[7], data[8]
        ))
        inserted += 1

# Finalisation
conn.commit()
conn.close()

print(f"\n✅ Migration terminée.")
print(f"🔁 {updated} lignes mises à jour.")
print(f"➕ {inserted} lignes insérées.")
