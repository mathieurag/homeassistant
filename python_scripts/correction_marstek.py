#!/usr/bin/env python3
import sqlite3
import datetime
import pytz
import sys

# ---------- Paramètres ----------
entities = ["sensor.charge_marstek", "sensor.decharge_marstek"]
database_path = "/config/home-assistant_v2.db"
local_tz = pytz.timezone("Europe/Paris")
tolerance = 0.001  # kWh
mode = "full"     # short = 5 min, long = 1 h, full = les deux

# ---------- Lecture paramètres CLI ----------
offset_days = 0
apply_changes = True
for arg in sys.argv[1:]:
    if arg.startswith("jour="):
        try:
            offset_days = int(arg.split("=")[1])
        except ValueError:
            pass
    elif arg.startswith("mode="):
        m = arg.split("=")[1].strip().lower()
        if m in ("short", "long", "full"):
            mode = m
    elif arg == "--apply":
        apply_changes = True

# ---------- Connexion ----------
conn = sqlite3.connect(database_path)
cursor = conn.cursor()

# ---------- Fenêtre: journée locale choisie ----------
today_local = datetime.date.today() - datetime.timedelta(days=offset_days)
start_local = local_tz.localize(datetime.datetime.combine(today_local, datetime.time(0,0)))
end_local   = start_local + datetime.timedelta(days=1)

start_ts_day = int(start_local.astimezone(datetime.timezone.utc).timestamp())
end_ts_day   = int(end_local.astimezone(datetime.timezone.utc).timestamp())

print(f"=== Analyse & correction {today_local} (jour={offset_days}, mode={mode}) ===")
print(f"[DEBUG] Local window: {start_local} → {end_local}")
print(f"[DEBUG] UTC window:   {datetime.datetime.fromtimestamp(start_ts_day, tz=datetime.UTC)} → {datetime.datetime.fromtimestamp(end_ts_day, tz=datetime.UTC)}")

def analyse_table(table, step):
    print(f"\n--- Table {table} ---")
    for entity in entities:
        print(f"\n[{entity}]")

        # metadata_id
        cursor.execute("SELECT id FROM statistics_meta WHERE statistic_id=?", (entity,))
        row = cursor.fetchone()
        if not row:
            print("  introuvable dans statistics_meta")
            continue
        metadata_id = row[0]

        # Données du jour
        cursor.execute(f"""
            SELECT start_ts, state, sum
            FROM {table}
            WHERE metadata_id=? AND start_ts>=? AND start_ts<?
            ORDER BY start_ts ASC
        """, (metadata_id, start_ts_day, end_ts_day))
        db_rows = cursor.fetchall()
        db_map = {r[0]: (r[1], r[2]) for r in db_rows}

        if not db_rows:
            print("  aucune donnée trouvée dans cette fenêtre")
            continue

        # Base = dernière valeur avant minuit local
        cursor.execute(f"""
            SELECT state, sum, start_ts
            FROM {table}
            WHERE metadata_id=? AND start_ts<?
            ORDER BY start_ts DESC LIMIT 1
        """, (metadata_id, start_ts_day))
        anchor = cursor.fetchone()
        if anchor:
            prev_state, prev_sum_corr, _ = anchor
            print(f"  Base (avant minuit): state={round(prev_state,3)}, sum={round(prev_sum_corr,3)}")
        else:
            prev_state, prev_sum_corr = None, None
            print("  ⚠ Pas de base avant minuit")

        total_slots = 0
        corrected = 0
        negatives = 0

        # Boucle créneaux
        slot = start_local
        while slot < end_local:
            start = int(slot.astimezone(datetime.timezone.utc).timestamp())
            time_str = slot.strftime("%H:%M")
            total_slots += 1

            if start not in db_map:
                print(f"  {time_str} → ⚠ Données non trouvées")
            else:
                state, sum_db = db_map[start]

                if prev_state is None:  # pas d'ancre dispo
                    print(f"  {time_str} → point de départ sans ancre (state={round(state,3)}, sum={round(sum_db,3)})")
                    prev_state, prev_sum_corr = state, sum_db
                else:
                    delta_sum = sum_db - prev_sum_corr
                    expected_sum = prev_sum_corr + (state - prev_state)
                    diff = expected_sum - sum_db

                    if delta_sum < -tolerance:
                        negatives += 1

                    if abs(diff) >= tolerance:
                        corrected += 1
                        expected_r = round(expected_sum, 3)
                        sum_r = round(sum_db, 3)
                        delta_r = round(delta_sum, 3)
                        diff_r = round(diff, 3)
                        print(f"  {time_str} → Δsum={delta_r} kWh | CORRIGÉ sum={sum_r} → {expected_r} (δ={diff_r})")
                        if apply_changes:
                            cursor.execute(f"""
                                UPDATE {table}
                                SET sum=?
                                WHERE metadata_id=? AND start_ts=?
                            """, (expected_sum, metadata_id, start))
                        prev_sum_corr = expected_sum
                    else:
                        prev_sum_corr = sum_db

                    prev_state = state

            slot += step

        print(f"\n  Résumé {entity} ({table}) : {total_slots} créneaux, {corrected} corrections, {negatives} conso négatives")

# ---------- Lancement selon mode ----------
if mode in ("short", "full"):
    analyse_table("statistics_short_term", datetime.timedelta(minutes=5))
if mode in ("long", "full"):
    analyse_table("statistics", datetime.timedelta(hours=1))

# ---------- Commit ----------
if apply_changes:
    conn.commit()
    print("\n[INFO] Modifications appliquées en base.")
else:
    print("\n[INFO] Mode diagnostic uniquement, aucun commit en base.")

conn.close()
