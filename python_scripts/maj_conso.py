
import sqlite3
import time
import datetime
import pytz

try:
    database = sqlite3.connect('/homeassistant/home-assistant_v2.db')
except:
    database = sqlite3.connect('home-assistant_v2.db')

error=0
jours=1
row=""

# Calcul de la date choisie à partir de jours:
target_date = datetime.date.today() - datetime.timedelta(days=jours)

# Fuseau horaire local
local_tz = pytz.timezone("Europe/Paris")

# Créer datetime à minuit, puis convertir proprement
dt_naive = datetime.datetime.combine(target_date, datetime.time.min)
dt_local = local_tz.localize(dt_naive, is_dst=None)  # is_dst=None force une erreur si ambigü
ts0 = dt_local.timestamp()
#print(ts0)

# Pour 23h00 locale
dt_end_naive = datetime.datetime.combine(target_date, datetime.time(23, 00, 00))
dt_end_local = local_tz.localize(dt_end_naive, is_dst=None)
tsmax = dt_end_local.timestamp()


print(target_date.strftime("%d/%m/%Y"))

# ---------- Listes d'entités ----------
liste = [
    'sensor.double_clamp_meter_total_energy_a',
    'sensor.lave_vaisselle',
    'sensor.cumulus_kwh',
    'sensor.frigo_kwh',
    'sensor.prise_tv',
    'sensor.lave_linge',
    'sensor.bidirectional_energy_meter_energy_consumed_a',
    'sensor.bidirectional_energy_meter_energy_consumed_b',
    'sensor.sonnette',
    'sensor.em06_b2_this_month_energy',
    'sensor.double_clamp_meter_today_energy_b',
    'sensor.em06_a2_this_month_energy',
    'sensor.disjoncteur_3',
    'sensor.em06_a1_this_month_energy',
    'sensor.lampe_salon_2',
    'sensor.em06_c2_this_month_energy',
    'sensor.prises_rdc_2',
    'sensor.disjoncteur_4',
    #'sensor.prise_5_energie',
    'sensor.energie_borne',
    'sensor.prise_zigbee_3_energy',
]

energie = [
    'sensor.energie_consommee_j_hp',
    'sensor.energie_consommee_j_hc',
    'sensor.em06_02_a1_this_month_energy',
]

surplus = ['sensor.surplus_production_compteur']
charge_batterie = ['sensor.charge_marstek']
decharge_batterie = ['sensor.decharge_marstek']

#print("entité =",liste)

i=0
id_entity=[]
unite_entity=[]

for i in range(len(liste)):
    #print("entité =",liste[i])
    query0 = "SELECT id,unit_of_measurement FROM 'statistics_meta' where statistic_id='" + liste[i] +"'"
    #print("requete=",query0)
    data=database.execute(query0)
    rows=data.fetchall()
    if not rows:
        #print(f"Aucune donnée retournée pour {liste[i]}")
        id_entity.append("")
        unite_entity.append("")
    else:
        for row in rows:
            if row[0] == "":
                print(f"Erreur, valeur vide pour {liste[i]}")
                id_entity.append("")
                unite_entity.append("")
            else:
                id_entity.append(row[0])
                unite_entity.append(row[1])
                #print("id states =", row[0])
    row=""

#for i in range(len(liste)):
#    print(liste[i],":",id_entity[i],"/",unite_entity[i])

i=0
id_energie=[]
unite_energie=[]
for i in range(len(energie)):
    #print("entité =",liste[i])
    query0 = "SELECT id,unit_of_measurement FROM 'statistics_meta' where statistic_id='" + energie[i] +"'"
    #print("requete=",query0)
    data=database.execute(query0)
    rows=data.fetchall()
    if not rows:
        print(f"Aucune donnée retournée pour {energie[i]}")
        id_energie.append("")
        unite_energie.append("")
    else:
        for row in rows:
            if row[0] == "":
                print(f"Erreur, valeur vide pour {energie[i]}")
                id_energie.append("")
                unite_energie.append("")
            else:
                id_energie.append(row[0])
                unite_energie.append(row[1])
                #print("id states =", row[0])
    row=""

#for i in range(len(energie)):
#    print(energie[i],":",id_energie[i],"/",unite_energie[i])

i=0
id_surplus=[]
unite_surplus=[]
for i in range(len(surplus)):
    #print("entité =",liste[i])
    query0 = "SELECT id,unit_of_measurement FROM 'statistics_meta' where statistic_id='" + surplus[i] +"'"
    #print("requete=",query0)
    data=database.execute(query0)
    rows=data.fetchall()
    if not rows:
        #print(f"Aucune donnée retournée pour {surplus[i]}")
        id_surplus.append("")
        unite_surplus.append("")
    else:
        for row in rows:
            if row[0] == "":
                #print(f"Erreur, valeur vide pour {surplus[i]}")
                id_surplus.append("")
                unite_surplus.append("")
            else:
                id_surplus.append(row[0])
                unite_surplus.append(row[1])
                #print("id states =", row[0])
    row=""

i=0
id_charge_batterie=[]
unite_charge_batterie=[]
for i in range(len(charge_batterie)):
    #print("entité =",liste[i])
    query0 = "SELECT id,unit_of_measurement FROM 'statistics_meta' where statistic_id='" + charge_batterie[i] +"'"
    #print("requete=",query0)
    data=database.execute(query0)
    rows=data.fetchall()
    if not rows:
        #print(f"Aucune donnée retournée pour {charge_batterie[i]}")
        id_charge_batterie.append("")
        unite_charge_batterie.append("")
    else:
        for row in rows:
            if row[0] == "":
                #print(f"Erreur, valeur vide pour {charge_batterie[i]}")
                id_charge_batterie.append("")
                unite_charge_batterie.append("")
            else:
                id_charge_batterie.append(row[0])
                unite_charge_batterie.append(row[1])
                #print("id states =", row[0])
    row=""
#for i in range(len(charge_batterie)):
    #print(charge_batterie[i],":",id_charge_batterie[i],"/",unite_charge_batterie[i])
    
i=0
id_decharge_batterie=[]
unite_decharge_batterie=[]
for i in range(len(decharge_batterie)):
    #print("entité =",liste[i])
    query0 = "SELECT id,unit_of_measurement FROM 'statistics_meta' where statistic_id='" + decharge_batterie[i] +"'"
    #print("requete=",query0)
    data=database.execute(query0)
    rows=data.fetchall()
    if not rows:
        #print(f"Aucune donnée retournée pour {decharge_batterie[i]}")
        id_decharge_batterie.append("")
        unite_decharge_batterie.append("")
    else:
        for row in rows:
            if row[0] == "":
                #print(f"Erreur, valeur vide pour {decharge_batterie[i]}")
                id_decharge_batterie.append("")
                unite_decharge_batterie.append("")
            else:
                id_decharge_batterie.append(row[0])
                unite_decharge_batterie.append(row[1])
                #print("id states =", row[0])
    row=""
#for i in range(len(decharge_batterie)):
    #print(decharge_batterie[i],":",id_decharge_batterie[i],"/",unite_decharge_batterie[i])


conso = [0] * 24    
conso_linky = [0] * 24
conso_surplus = [0] * 24
conso_charge_batterie= [0] * 24
conso_decharge_batterie= [0] * 24
delta_conso= [0] * 24

for j in range(0,24):
    for i in range(len(liste)):
        query0 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_entity[i]) +") and start_ts ="+str(ts0+(j-1)*3600)
        query1 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_entity[i]) +") and start_ts ="+str(ts0+(j)*3600)

        data=database.execute(query0)
        for row in data.fetchall():
            if unite_entity[i]=="Wh":
                sum_entity2=round(row[0]/1000,3)
            else:
                sum_entity2=round(row[0],3)
            #print(id_entity[i]," : ",j,"h : ",sum_entity2,"kWh")
        row=""
        
        data=database.execute(query1)
        for row in data.fetchall():
            if unite_entity[i]=="Wh":
                sum_entity=round(row[0]/1000,3)
            else:
                sum_entity=round(row[0],3)
            #print(id_entity[i]," : ",j+1,"h : ",sum_entity,"kWh")
        delta=round(sum_entity-sum_entity2,3)
        #print(id_entity[i]," : ",j,"à",j+1,"h : ",delta,"kWh")
        row=""
        conso[j]=conso[j]+delta
    #print("conso : ",j,"à",j+1,"h : ",round(conso[j],3),"kWh")

    for i in range(len(surplus)):
        query0 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_surplus[i]) +") and start_ts ="+str(ts0+(j-1)*3600)
        query1 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_surplus[i]) +") and start_ts ="+str(ts0+(j)*3600)

        data=database.execute(query0)
        for row in data.fetchall():
            if unite_surplus[i]=="Wh":
                sum_conso2=round(row[0]/1000,3)
            else:
                sum_conso2=round(row[0],3)
            #print(id_surplus[i]," : ",j,"h : ",sum_conso2,"kWh")
        row=""
        
        data=database.execute(query1)
        for row in data.fetchall():
            if unite_surplus[i]=="Wh":
                sum_conso=round(row[0]/1000,3)
            else:
                sum_conso=round(row[0],3)
            #print(id_energie[i]," : ",j+1,"h : ",sum_conso"kWh")
        delta=round(sum_conso-sum_conso2,3)
        #print(id_entity[i]," : ",j,"à",j+1,"h : ",delta,"kWh")
        row=""
        conso_surplus[j]=conso_surplus[j]+delta
    #print("Surplus : ",j,"à",j+1,"h : ",round(conso_surplus[j],3),"kWh")

    for i in range(len(charge_batterie)):
        query0 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_charge_batterie[i]) +") and start_ts ="+str(ts0+(j-1)*3600)
        query1 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_charge_batterie[i]) +") and start_ts ="+str(ts0+(j)*3600)

        data=database.execute(query0)
        for row in data.fetchall():
            if unite_charge_batterie[i]=="Wh":
                sum_conso2=round(row[0]/1000,3)
            else:
                sum_conso2=round(row[0],3)
            #print(id_charge_batterie[i]," : ",j,"h : ",sum_conso2,"kWh")
        row=""
        
        data=database.execute(query1)
        for row in data.fetchall():
            if unite_charge_batterie[i]=="Wh":
                sum_conso=round(row[0]/1000,3)
            else:
                sum_conso=round(row[0],3)
            #print(id_energie[i]," : ",j+1,"h : ",sum_conso"kWh")
        delta=round(sum_conso-sum_conso2,3)
        #print(id_entity[i]," : ",j,"à",j+1,"h : ",delta,"kWh")
        row=""
        conso_charge_batterie[j]=conso_charge_batterie[j]+delta
    #print("charge_batterie : ",j,"à",j+1,"h : ",round(conso_charge_batterie[j],3),"kWh")

    for i in range(len(decharge_batterie)):
        query0 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_decharge_batterie[i]) +") and start_ts ="+str(ts0+(j-1)*3600)
        query1 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_decharge_batterie[i]) +") and start_ts ="+str(ts0+(j)*3600)

        data=database.execute(query0)
        for row in data.fetchall():
            if unite_decharge_batterie[i]=="Wh":
                sum_conso2=round(row[0]/1000,3)
            else:
                sum_conso2=round(row[0],3)
            #print(id_decharge_batterie[i]," : ",j,"h : ",sum_conso2,"kWh")
        row=""
        
        data=database.execute(query1)
        for row in data.fetchall():
            if unite_decharge_batterie[i]=="Wh":
                sum_conso=round(row[0]/1000,3)
            else:
                sum_conso=round(row[0],3)
            #print(id_energie[i]," : ",j+1,"h : ",sum_conso"kWh")
        delta=round(sum_conso-sum_conso2,3)
        #print(id_entity[i]," : ",j,"à",j+1,"h : ",delta,"kWh")
        row=""
        conso_decharge_batterie[j]=conso_decharge_batterie[j]+delta
    #print("decharge_batterie : ",j,"à",j+1,"h : ",round(conso_decharge_batterie[j],3),"kWh")

    for i in range(len(energie)):
        query0 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_energie[i]) +") and start_ts ="+str(ts0+(j-1)*3600)
        query1 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_energie[i]) +") and start_ts ="+str(ts0+(j)*3600)

        data=database.execute(query0)
        for row in data.fetchall():
            if unite_energie[i]=="Wh":
                sum_conso2=round(row[0]/1000,3)
            else:
                sum_conso2=round(row[0],3)
            #print(id_energie[i]," : ",j,"h : ",sum_conso2,"kWh")
        row=""
        
        data=database.execute(query1)
        for row in data.fetchall():
            if unite_energie[i]=="Wh":
                sum_conso=round(row[0]/1000,3)
            else:
                sum_conso=round(row[0],3)
            #print(id_energie[i]," : ",j+1,"h : ",sum_conso"kWh")
        delta=round(sum_conso-sum_conso2,3)
        #print(id_entity[i]," : ",j,"à",j+1,"h : ",delta,"kWh")
        row=""
        conso_linky[j]=conso_linky[j]+delta
    #print("linky : ",j,"à",j+1,"h : ",round(conso_linky[j],3),"kWh")

    delta_conso[j]=conso_linky[j]-conso[j]-conso_surplus[j]-conso_charge_batterie[j]+conso_decharge_batterie[j]

    print("Consommation non suivie : ",j,"à",j+1,"h : ",round(delta_conso[j],3),"kWh")
    if delta_conso[j]<=0.005:
        error=error+1

entry=0
conso_max=0
if error>0:
    print("Consommation négative : ")
    for j in range(0,24):
        if delta_conso[j]<=0.004:
            print("Consommation non suivie : ",j,"à",j+1,"h : ",round(delta_conso[j],3),"kWh")
            conso_max=0
            for i in range(len(liste)):
                query0 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_entity[i]) +") and start_ts ="+str(ts0+(j-1)*3600)
                query1 = "SELECT sum FROM 'statistics' where metadata_id in (" + str(id_entity[i]) +") and start_ts ="+str(ts0+(j)*3600)

                data=database.execute(query0)
                for row in data.fetchall():
                    if unite_entity[i]=="Wh":
                        sum_entity2=round(row[0]/1000,3)
                    else:
                        sum_entity2=round(row[0],3)
                    #print(id_entity[i]," : ",j,"h : ",sum_entity2,"kWh")
                row=""

                data=database.execute(query1)
                for row in data.fetchall():
                    if unite_entity[i]=="Wh":
                        sum_entity=round(row[0]/1000,3)
                    else:
                        sum_entity=round(row[0],3)
                    #print(id_entity[i]," : ",j+1,"h : ",sum_entity,"kWh")
                if round(sum_entity-sum_entity2,3)>conso_max:
                    conso_max=round(sum_entity-sum_entity2,3)
                    max_entite=id_entity[i]
                    range_max_entite=i
                
                #print(j,"h / Conso",id_entity[i],":",round(sum_entity-sum_entity2,3),unite_entity[i])
            
            print("Conso max :",conso_max,"kWh / Entité : ",max_entite)
            if unite_entity[range_max_entite]=="Wh":
                factor=1000
            else:
                factor=1

            if conso_max > delta_conso[j]+0.01 :

                query1 = "UPDATE 'statistics_short_term' set sum=sum"+str(round((delta_conso[j]-0.005)*factor,3))+" where metadata_id in (" + str(id_entity[range_max_entite]) +") and start_ts >="+str(ts0+(j)*3600)
                data=database.execute(query1)
                query1 = "UPDATE 'statistics' set sum=sum"+str(round((delta_conso[j]-0.005)*factor,3))+" where metadata_id in (" + str(id_entity[range_max_entite]) +") and start_ts >="+str(ts0+(j)*3600)
                data=database.execute(query1)
                entry = entry + 1
                print("Conso corrigée:",str(round((delta_conso[j]-0.005),3)),"kWh")
            else:
                print("Conso max inférieure au delta à corriger !",conso_max,"kWh / Delta:",str(round((delta_conso[j]-0.02)*factor,3)),"kWh")
    print("Fin du script : ",entry," entrée(s) modifiée(s)")
    query0 = "commit"
    if entry>0:
        print("Fin du script : ",entry," entrée(s) modifiée(s)")
        data=database.execute(query0)
else:
    print("Fin du script : Pas de données à modifier")

database.close()