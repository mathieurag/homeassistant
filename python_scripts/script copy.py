import sqlite3
import datetime
import pytz

# =========================
# CONFIG
# =========================
# Mets ici ta date de début au format "YYYY-MM-DD".
# Exemple: START_DATE = "2025-07-01"
START_DATE = "2025-01-01"      # <-- à personnaliser
END_DATE = "2025-06-01"                # "YYYY-MM-DD" ou None pour "jusqu'à hier"
INCLUDE_TODAY = False          # True pour inclure aujourd'hui comme date de fin si END_DATE=None

# Entités Home Assistant
ENTITY_HP = "sensor.energie_consommee_j_hp"
ENTITY_HC = "sensor.energie_consommee_j_hc"
ENTITY_LINKY = "linky:16127930466069"

# =========================
# Connexion DB
# =========================
try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

database.row_factory = sqlite3.Row

# =========================
# Helpers temps (Europe/Paris)
# =========================
LOCAL_TZ = pytz.timezone("Europe/Paris")

def day_bounds_timestamps(date_obj: datetime.date):
    """Retourne (ts0, tsmax) pour 00:00:00 et 23:00:00 locales du jour donné (heures pleines Linky)."""
    dt0_naive = datetime.datetime.combine(date_obj, datetime.time.min)
    dt0_local = LOCAL_TZ.localize(dt0_naive, is_dst=None)
    ts0 = int(dt0_local.timestamp())

    dt23_naive = datetime.datetime.combine(date_obj, datetime.time(23, 0, 0))
    dt23_local = LOCAL_TZ.localize(dt23_naive, is_dst=None)
    tsmax = int(dt23_local.timestamp())
    return ts0, tsmax

def parse_date_str(s: str) -> datetime.date:
    return datetime.datetime.strptime(s, "%Y-%m-%d").date()

def compute_date_range():
    if not START_DATE:
        # Compatibilité : si rien n'est défini, on corrige hier uniquement
        start_date = datetime.date.today() - datetime.timedelta(days=1)
        end_date = start_date
        return start_date, end_date

    start_date = parse_date_str(START_DATE)

    if END_DATE:
        end_date = parse_date_str(END_DATE)
    else:
        if INCLUDE_TODAY:
            end_date = datetime.date.today()
        else:
            end_date = datetime.date.today() - datetime.timedelta(days=1)

    if end_date < start_date:
        raise ValueError("La date de fin est avant la date de début.")
    return start_date, end_date

# =========================
# Récup IDs metadata
# =========================
def get_meta_id(statistic_id: str):
    cur = database.execute(
        "SELECT id FROM statistics_meta WHERE statistic_id = ?", (statistic_id,)
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Meta non trouvé pour {statistic_id}")
    return row["id"]

id_entity_hp = get_meta_id(ENTITY_HP)
print("entité =", ENTITY_HP, "/ id=", id_entity_hp)

id_entity_hc = get_meta_id(ENTITY_HC)
print("entité =", ENTITY_HC, "/ id=", id_entity_hc)

id_entity_linky = get_meta_id(ENTITY_LINKY)
print("entité =", ENTITY_LINKY, "/ id=", id_entity_linky)

# =========================
# Lectures / calculs
# =========================
def fetch_linky_hours(ts0, tsmax):
    cur = database.execute(
        "SELECT state FROM statistics "
        "WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ? "
        "ORDER BY start_ts ASC",
        (id_entity_linky, ts0, tsmax),
    )
    return [float(r["state"]) for r in cur.fetchall()]

def fetch_series_deltas_hourly(metadata_id, ts0, tsmax):
    ts_old = ts0 - 3600
    cur = database.execute(
        "SELECT sum FROM statistics WHERE metadata_id = ? AND start_ts = ?",
        (metadata_id, ts_old),
    )
    r = cur.fetchone()
    sum_old = float(r["sum"]) if r else 0.0

    cur = database.execute(
        "SELECT state, sum FROM statistics "
        "WHERE metadata_id = ? AND start_ts >= ? AND start_ts <= ? "
        "ORDER BY start_ts ASC",
        (metadata_id, ts0, tsmax),
    )
    deltas = []
    for row in cur.fetchall():
        s = float(row["sum"])
        deltas.append(round(s - sum_old, 0))
        sum_old = s
    return deltas

def split_linky_hp_hc(linky_states_24):
    from array import array
    hc = array('f')
    hp = array('f')

    for heure, val in enumerate(linky_states_24):
        if heure < 5:
            hc.append(round(val, 0)); hp.append(0)
        elif heure == 5:
            hc.append(round(0.13 * val, 0)); hp.append(round(0.87 * val, 0))
        elif heure < 21:
            hp.append(round(val, 0)); hc.append(0)
        elif heure == 21:
            hp.append(round(0.13 * val, 0)); hc.append(round(0.87 * val, 0))
        else:
            hc.append(round(val, 0)); hp.append(0)
    return hc, hp

def apply_delta(metadata_id, ts0, hour_index, delta_wh):
    if delta_wh == 0:
        return
    pivot_ts = ts0 + hour_index * 3600

    q = "UPDATE statistics SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?"
    database.execute(q, (delta_wh, metadata_id, pivot_ts))

    q2 = "UPDATE statistics_short_term SET sum = sum + ? WHERE metadata_id = ? AND start_ts >= ?"
    database.execute(q2, (delta_wh, metadata_id, pivot_ts))

def process_one_day(date_obj: datetime.date):
    ts0, tsmax = day_bounds_timestamps(date_obj)

    # 1) Linky
    linky_vals = fetch_linky_hours(ts0, tsmax)
    if len(linky_vals) != 24:
        print(f"[{date_obj}] ATTENTION: {len(linky_vals)} points Linky (attendu 24). Journée ignorée.")
        return {"ok": False, "reason": "linky_hours_mismatch"}

    hc_linky, hp_linky = split_linky_hp_hc(linky_vals)
    energy_linky_hc = round(sum(hc_linky) / 1000, 2)
    energy_linky_hp = round(sum(hp_linky) / 1000, 2)
    energy_linky = round(energy_linky_hc + energy_linky_hp, 2)
    #print(f"Energie Linky {date_obj}: {energy_linky} kWh (HP: {energy_linky_hp} / HC: {energy_linky_hc})")

    # 2) Mesuré
    hp_deltas = fetch_series_deltas_hourly(id_entity_hp, ts0, tsmax)
    hc_deltas = fetch_series_deltas_hourly(id_entity_hc, ts0, tsmax)
    if len(hp_deltas) != 24 or len(hc_deltas) != 24:
        print(f"[{date_obj}] ATTENTION: HP({len(hp_deltas)})/HC({len(hc_deltas)}) != 24. Journée ignorée.")
        return {"ok": False, "reason": "hp_hc_hours_mismatch"}

    energy_hp_kwh = round(sum(hp_deltas) / 1000, 2)
    energy_hc_kwh = round(sum(hc_deltas) / 1000, 2)
    energy_total_kwh = round(energy_hp_kwh + energy_hc_kwh, 2)
    #print(f"Energie mesurée {date_obj}: {energy_total_kwh} kWh (HP: {energy_hp_kwh} / HC: {energy_hc_kwh})")

    delta_total = round(energy_linky - energy_total_kwh, 2)
    delta_hp_kwh = round(energy_linky_hp - energy_hp_kwh, 2)
    delta_hc_kwh = round(energy_linky_hc - energy_hc_kwh, 2)
    #print(f"Delta {date_obj}: {delta_total} kWh (HP: {delta_hp_kwh} / HC: {delta_hc_kwh})")

    # 3) Application des deltas horaires
    delta_hp_total_wh = 0.0
    delta_hc_total_wh = 0.0
    did_update = False  # <-- NOUVEAU

    for i in range(24):
        d_hc = float(hc_linky[i]) - float(hc_deltas[i])
        d_hp = float(hp_linky[i]) - float(hp_deltas[i])

        if d_hc != 0:
            apply_delta(id_entity_hc, ts0, i, d_hc)
            did_update = True
        if d_hp != 0:
            apply_delta(id_entity_hp, ts0, i, d_hp)
            did_update = True

        delta_hp_total_wh += d_hp
        delta_hc_total_wh += d_hc

    #print("linky_hc", sum(hc_linky), "détails :", hc_linky)
    #print("energy_hc", sum(hc_deltas), "détails :", hc_deltas)
    #print("linky_hp", sum(hp_linky), "détails :", hp_linky)
    #print("energy_hp", sum(hp_deltas), "détails :", hp_deltas)
    #print("delta_hc", delta_hc_total_wh, "Wh")
    #print("delta_hp", delta_hp_total_wh, "Wh")

    # Commit uniquement s'il y a eu des updates
    if did_update:
        database.commit()
        correction = "appliquée"
    else:
        correction = "aucune"

    # Résumé clair
    print(
        f"{date_obj} | "
        f"Linky={energy_linky:.2f} kWh (HP {energy_linky_hp:.2f} / HC {energy_linky_hc:.2f}) | "
        f"Mesuré={energy_total_kwh:.2f} kWh (HP {energy_hp_kwh:.2f} / HC {energy_hc_kwh:.2f}) | "
        f"Δ={delta_total:+.2f} kWh (HP {delta_hp_kwh:+.2f} / HC {delta_hc_kwh:+.2f}) | "
        f"Correction={correction}"
    )

    return {"ok": True}

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    start_date, end_date = compute_date_range()
    print(f"Correction du {start_date} au {end_date} (inclus).")

    current = start_date
    ok_days = 0
    skipped = 0
    while current <= end_date:
        res = process_one_day(current)
        if res and res.get("ok"):
            ok_days += 1
        else:
            skipped += 1
        current += datetime.timedelta(days=1)

    print(f"Terminé. Jours corrigés: {ok_days} | Jours ignorés: {skipped}")
    database.close()
