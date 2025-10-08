def mifflin_st_jeor(sex, weight_kg, height_cm, age_y):
    return (10*weight_kg + 6.25*height_cm - 5*age_y + (5 if sex.lower().startswith("m") else -161))

ACTIVITY = {"Reposo":1.2,"Ligera":1.375,"Moderada":1.55,"Alta":1.725}

def tee_from_tmb(tmb, activity_key):
    return round(tmb * ACTIVITY.get(activity_key, 1.2))

def kcal_target(tee, objective):
    if objective=="Pérdida": return max(1000, tee - (400 if tee>=1600 else 200))
    if objective=="Ganancia": return tee + 200
    return tee

def macros(kcal, pct_prot, pct_fat, pct_cho, weight_kg, pct_cho_complex=85, fat_split=(10,35,55)):
    # Normalizar porcentajes
    total = pct_prot + pct_fat + pct_cho
    pct_prot = round(100*pct_prot/total); pct_fat = round(100*pct_fat/total); pct_cho = 100 - pct_prot - pct_fat
    g_prot = round((kcal*pct_prot/100)/4,1)
    g_fat  = round((kcal*pct_fat /100)/9,1)
    g_cho  = round((kcal*pct_cho /100)/4,1)
    gkg_prot = round(g_prot/weight_kg,2) if weight_kg else 0.0
    gkg_cho  = round(g_cho/weight_kg,2) if weight_kg else 0.0
    # CHO complejos vs simples
    g_cho_c = round(g_cho*pct_cho_complex/100,1); g_cho_s = round(g_cho - g_cho_c,1)
    # Desglose grasas (sat, poli, mono) en % de fat
    sat, poli, mono = fat_split
    subtotal = max(1, sat+poli+mono)
    sat = pct_fat*sat/subtotal; poli = pct_fat*poli/subtotal; mono = pct_fat - sat - poli
    g_sat  = round((kcal*sat /100)/9,1)
    g_poli = round((kcal*poli/100)/9,1)
    g_mono = round((kcal*mono/100)/9,1)
    return {
        "pct":{"prot":pct_prot,"fat":pct_fat,"cho":pct_cho},
        "g":{"prot":g_prot,"fat":g_fat,"cho":g_cho,"cho_c":g_cho_c,"cho_s":g_cho_s,"sat":g_sat,"poli":g_poli,"mono":g_mono},
        "gkg":{"prot":gkg_prot,"cho":gkg_cho}
    }

def sodium_convert(target_mg, current_mg):
    rem = max(0, target_mg - current_mg)
    salt_g = round(rem/400.0,2)  # 400 mg Na ≈ 1 g NaCl
    tsp = round(salt_g/5.0,2)    # 1 cdta ≈ 5 g
    return {"remaining_mg":rem,"salt_g":salt_g,"tsp":tsp}

def bmi(weight_kg, height_cm):
    h = max(1e-6, height_cm/100)
    return round(weight_kg/(h*h),2)

def homa_ir(glucose_mg_dl, insulin_uU_ml):
    if glucose_mg_dl>0 and insulin_uU_ml>0:
        g_mmol = glucose_mg_dl/18.0
        return round((g_mmol*insulin_uU_ml)/22.5,2)
    return None
