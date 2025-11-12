import requests
import datetime
import sqlite3
import pytz
import calendar
import sys
import os

# --- CONFIGURATION (Non modifiée) ---
API_KEY = 'b80b9f5433dba8cd'
USER_BDPV = 'matrag'
BDPV_URL_BASE = f"https://www.bdpv.fr/webservice/majProd/expeditionProd_v3.php?util={USER_BDPV}&apiKey={API_KEY}&source=homeassistant&typeReleve=onduleur"
MAX_DELTA_WH = 25000         # 25 kWh (25000 Wh) : Seuil de sécurité journalier maximum
LOCAL_TZ = pytz.timezone("Europe/Paris")
ID_STATISTIC_CUMUL = 'sensor.em06_02_a1_this_month_energy' 
DATABASE_PATH = '/config/home-assistant_v2.db' 
SEND_TO_BDPV = True
# ----------------------------------

# --- Fonctions BDD (Logique de lecture en Wh maintenue) ---

def get_db_connection(path):
    try:
        return sqlite3.connect(path)
    except Exception as e:
        return None

def get_metadata_id(database, statistic_id):
    query = f"SELECT id FROM 'statistics_meta' WHERE statistic_id = '{statistic_id}'"
    data = database.execute(query)
    meta_id_row = data.fetchone()
    if meta_id_row: return meta_id_row[0]
    return None

def get_index_by_timestamp(database, meta_id, ts_target):
    """ Récupère la valeur 'sum'. Hypothèse: 'sum' est déjà en Wh. """
    try:
        query = f"""
            SELECT sum 
            FROM 'statistics' 
            WHERE metadata_id = {meta_id} 
            ORDER BY ABS(start_ts - {ts_target}) 
            LIMIT 1
        """
        data = database.execute(query)
        row = data.fetchone()
        
        if row and row[0] is not None:
            # La base est en Wh, donc on prend la valeur entière.
            return round(row[0]) 
        return None
    except Exception as e:
        return None

def get_latest_cumulative_index(database, meta_id):
    return get_index_by_timestamp(database, meta_id, int(datetime.datetime.now().timestamp()))

def get_previous_day_index(database, meta_id):
    dt_24h_ago = datetime.datetime.now() - datetime.timedelta(hours=24)
    ts_24h_ago = int(dt_24h_ago.timestamp())
    
    return get_index_by_timestamp(database, meta_id, ts_24h_ago)

def get_index_by_month_start(database, meta_id, date: datetime.date):
    dt_local = LOCAL_TZ.localize(datetime.datetime.combine(date, datetime.time.min))
    ts_target = int(dt_local.timestamp())
    
    return get_index_by_timestamp(database, meta_id, ts_target)

def get_min_max_dates(database, meta_id):
    try:
        query = f"""
            SELECT MIN(start_ts), MAX(start_ts) 
            FROM 'statistics' 
            WHERE metadata_id = {meta_id}
        """
        data = database.execute(query)
        min_ts, max_ts = data.fetchone()
        
        if min_ts is None or max_ts is None: return None, None

        min_dt = datetime.datetime.fromtimestamp(min_ts, tz=pytz.utc).astimezone(LOCAL_TZ)
        max_dt = datetime.datetime.fromtimestamp(max_ts, tz=pytz.utc).astimezone(LOCAL_TZ)
        
        return min_dt.date(), max_dt.date()
    except Exception as e:
        return None, None

def calculate_monthly_production(conn, meta_id, min_date, max_date):
    """ Calcule la production mensuelle. Prod_kwh est retourné en kWh. """
    monthly_data = {}
    
    start_year = min_date.year
    start_month = min_date.month
    end_year = max_date.year
    end_month = max_date.month + 1 

    current_date = datetime.date(start_year, start_month, 1)

    while True:
        if current_date.year > end_year or (current_date.year == end_year and current_date.month > end_month):
            break

        date_start = current_date
        index_start = get_index_by_month_start(conn, meta_id, date_start)
        
        if date_start.month == 12:
            date_end = datetime.date(date_start.year + 1, 1, 1)
        else:
            date_end = datetime.date(date_start.year, date_start.month + 1, 1)
            
        index_end = get_index_by_month_start(conn, meta_id, date_end)

        if index_start is None:
            pass
        elif index_end is None:
            index_end = get_latest_cumulative_index(conn, meta_id)

        if index_start is not None and index_end is not None and index_end >= index_start:
            prod_wh = index_end - index_start
            # Le calcul est toujours en Wh.
            prod_kwh = prod_wh / 1000 # Retourne la production en kWh (float)
            
            month_name = date_start.strftime("%Y-%m")
            monthly_data[month_name] = prod_kwh
        
        if current_date.month == 12:
            current_date = datetime.date(current_date.year + 1, 1, 1)
        else:
            current_date = datetime.date(current_date.year, current_date.month + 1, 1)
            
    return monthly_data

def send_to_bdpv(index_value):
    full_url = f"{BDPV_URL_BASE}&index={int(index_value)}"
    try:
        response = requests.get(full_url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"codeRetour": "-99", "texteRetour": f"Erreur HTTP: {e}"}

# --- Fonction Main ---

def main():
    conn = get_db_connection(DATABASE_PATH)
    if not conn: sys.exit(1)

    meta_id = get_metadata_id(conn, ID_STATISTIC_CUMUL)
    if meta_id is None:
        print(f"ALERT: Statistique ID non trouvée pour {ID_STATISTIC_CUMUL}. Arrêt.")
        conn.close()
        sys.exit(1)

    min_date, max_date = get_min_max_dates(conn, meta_id)
    if min_date is None:
        print("ALERT: Aucune donnée de statistique trouvée dans la base.")
        conn.close()
        sys.exit(1)
        
    # 1. Calcul de l'historique mensuel
    print("## 📊 Historique Mensuel de Production (Déduite de la BDD)")
    monthly_prods = calculate_monthly_production(conn, meta_id, min_date, max_date)
    
    # Affichage du tableau (UNITÉ CORRIGÉE ICI)
    print("-" * 40)
    print("{:<10} {:>10}".format("Mois", "Prod (kWh)"))
    print("-" * 40)
    for month, prod in monthly_prods.items():
        # Prod est en kWh (float). On affiche avec 2 décimales.
        print("{:<10} {:>10.2f}".format(month, prod)) 
    print("-" * 40)

    # 2. Récupération des Index pour l'envoi et la sécurité
    new_index_cumul = get_latest_cumulative_index(conn, meta_id)
    last_index = get_previous_day_index(conn, meta_id)
    conn.close()

    if new_index_cumul is None or last_index is None:
        print("ALERT BDPV: Index cumulé actuel ou précédent est non trouvé. Arrêt.")
        sys.exit(1)

    # 3. Vérification de la sécurité (Delta)
    delta = new_index_cumul - last_index # Delta en Wh
    
    # UNITÉ CORRIGÉE ICI: Calcul pour l'affichage lisible
    delta_kwh = round(delta / 1000, 2) 

    print("\n## 🔒 Vérification de Sécurité")
    print(f"Index Total Actuel : {new_index_cumul} Wh")
    print(f"Index Précédent (24h) : {last_index} Wh")
    # Affichage corrigé en kWh
    print(f"Delta de Production : {delta_kwh} kWh") 

    # Vérification 1: Index croissant
    if new_index_cumul <= last_index:
        print("BDPV INFO: Index non croissant ou inchangé. Envoi ignoré.")
        return
    
    # Vérification 2: Delta < Seuil de sécurité
    if delta > MAX_DELTA_WH:
        # La valeur de 'delta' (en Wh) est comparée à MAX_DELTA_WH (25000 Wh).
        print(f"BDPV ALERT: Delta journalier ({delta} Wh) > Seuil de sécurité ({MAX_DELTA_WH} Wh). Envoi annulé.")
        return

    # 4. Envoi conditionnel à BDPV
    print("\n## 🚀 Envoi API BDPV")
    if SEND_TO_BDPV:
        print(f"BDPV INFO: Envoi de l'index {new_index_cumul} Wh...")
        response_json = send_to_bdpv(new_index_cumul)
        
        print(f"BDPV Réponse: Code {response_json.get('codeRetour')}: {response_json.get('texteRetour')}")
    else:
        print("BDPV TEST MODE: L'envoi API est ignoré (SEND_TO_BDPV est False).")
        print(f"Si l'envoi était actif, la valeur {new_index_cumul} Wh aurait été envoyée.")
        
if __name__ == "__main__":
    main()