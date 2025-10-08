# app.py — @nutritionsays · Gestión Nutricional Clínica (UCV)
# UI legible en móvil + cálculos clínicos completos + exportes DOCX/FHIR

from datetime import date
from io import BytesIO
import json
import math

import streamlit as st
import pandas as pd

# DOCX opcional (si falla instalación, la app sigue con MD/FHIR)
try:
    from docx import Document
    from docx.shared import Pt
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

# ========= BRANDING / ESTILO (alto contraste, mobile) =========
BRAND_NAME = "@nutritionsays"
PRIMARY = "#2a145a"      # púrpura oscuro
ACCENT   = "#5e60ce"     # acento
OK       = "#1a936f"
WARN     = "#f8961e"
BAD      = "#d00000"

st.set_page_config(page_title=f"{BRAND_NAME} · Gestión Nutricional", page_icon="🍎", layout="centered")

st.markdown(f"""
<style>
  .stApp {{ background:#f7f7fb; }}
  h1,h2,h3,h4 {{ color:{PRIMARY}; }}
  .brand {{ display:inline-block; padding:6px 12px; border-radius:12px; background:{ACCENT}; color:white; font-weight:700; margin-bottom:6px; }}
  .card {{ border:1px solid #e9e9f3; border-radius:14px; padding:14px; background:white; box-shadow:0 1px 6px rgba(10,10,30,.05); }}
  .muted {{ color:#555; }}
  .kpi {{ font-size:1.25rem; font-weight:700; }}
  @media (max-width: 480px){{
     .stApp {{ padding:.4rem; }}
     h1 {{ font-size:1.35rem; }}
     h2 {{ font-size:1.12rem; }}
     .card {{ padding:10px; }}
  }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"<span class='brand'>{BRAND_NAME}</span>", unsafe_allow_html=True)
st.title("Software de Gestión Nutricional – Consulta Clínica (UCV)")

# ========= CATÁLOGO DE INTERCAMBIOS (base VE; editable) =========
EXCHANGES = {
    "Vegetales": {"kcal":25,"CHO":5,"PRO":2,"FAT":0,"portion":"1 taza crudas / 1/2 taza cocidas"},
    "Frutas": {"kcal":60,"CHO":15,"PRO":0,"FAT":0,"portion":"1 unid pequeña / 1/2 taza picada"},
    "Cereales": {"kcal":80,"CHO":15,"PRO":2,"FAT":1,"portion":"1/2 taza cocidos / 1 rebanada pan"},
    "Leguminosas": {"kcal":100,"CHO":18,"PRO":7,"FAT":1,"portion":"1/2 taza cocidas"},
    "Lácteos descremados": {"kcal":90,"CHO":12,"PRO":8,"FAT":2,"portion":"1 taza leche / yogurt natural"},
    "Proteínas magras": {"kcal":110,"CHO":0,"PRO":21,"FAT":3,"portion":"30 g cocidos"},
    "Grasas saludables": {"kcal":45,"CHO":0,"PRO":0,"FAT":5,"portion":"1 cdita (5 g)"}
}

# ========= UTILIDADES CLÍNICAS =========
ACTIVITY = {"Reposo / cama":1.2,"Ligera (1–3 d/sem)":1.375,"Moderada (3–5 d/sem)":1.55,"Alta (6–7 d/sem)":1.725}

def mifflin_st_jeor(sex, weight_kg, height_cm, age_y):
    return 10*weight_kg + 6.25*height_cm - 5*age_y + (5 if sex.lower().startswith("m") else -161)

def tee_from_tmb(tmb, activity_key): 
    return round(tmb * ACTIVITY.get(activity_key, 1.2))

def kcal_target(tee, objective):
    if objective=="Pérdida de peso": return max(1000, tee - (400 if tee>=1600 else 200))
    if objective=="Ganancia (magro)": return tee + 200
    return tee

def bmi(weight_kg, height_cm):
    h = max(1e-6, height_cm/100); return round(weight_kg/(h*h),2)

def whr(waist_cm, hip_cm):
    return round((waist_cm / hip_cm), 2) if hip_cm>0 else None

def whtr(waist_cm, height_cm):
    return round((waist_cm / height_cm), 2) if height_cm>0 else None

def homa_ir(glucose_mg_dl, insulin_uU_ml):
    if glucose_mg_dl>0 and insulin_uU_ml>0:
        g_mmol = glucose_mg_dl/18.0
        return round((g_mmol*insulin_uU_ml)/22.5,2)
    return None

# Densidad corporal Durnin-Womersley (4 pliegues): coeficientes por sexo/edad
# Fuente clásica: Durnin & Womersley, 1974; Siri 1961 para %grasa.
DW_COEFF = {
    "F": [(17, (1.1549, 0.0678)), (29, (1.1599, 0.0717)), (39, (1.1423, 0.0632)), (49, (1.1333, 0.0612)), (120,(1.1339,0.0645))],
    "M": [(17, (1.1620, 0.0630)), (29, (1.1631, 0.0632)), (39, (1.1422, 0.0544)), (49, (1.1620, 0.0700)), (120,(1.1715,0.0779))]
}
def durnin_womersley_density(sex, age, biceps, triceps, subscap, suprailiac):
    S = max(0.1, biceps + triceps + subscap + suprailiac)  # suma mm
    logS = math.log10(S)
    key = "F" if sex.lower().startswith("f") else "M"
    coeff = None
    for upper, ab in DW_COEFF[key]:
        if age <= upper: coeff = ab; break
    if coeff is None: coeff = DW_COEFF[key][-1][1]
    a, b = coeff
    return a - (b * logS)

def siri_bodyfat_pct(density):
    return round(((4.95/density) - 4.50) * 100, 1)

def sodium_convert(target_mg, current_mg):
    rem = max(0, target_mg - current_mg)
    salt_g = round(rem/400.0,2)  # 400 mg Na ≈ 1 g NaCl
    tsp = round(salt_g/5.0,2)    # 1 cdta ≈ 5 g
    return {"remaining_mg":rem,"salt_g":salt_g,"tsp":tsp}

def macros(kcal, pct_prot, pct_fat, pct_cho, weight_kg, pct_cho_complex=85, fat_split=(10,35,55)):
    total = max(1, pct_prot + pct_fat + pct_cho)
    pct_prot = round(100*pct_prot/total); pct_fat = round(100*pct_fat/total); pct_cho = 100 - pct_prot - pct_fat
    g_prot = round((kcal*pct_prot/100)/4,1)
    g_fat  = round((kcal*pct_fat /100)/9,1)
    g_cho  = round((kcal*pct_cho /100)/4,1)
    gkg_prot = round(g_prot/weight_kg,2) if weight_kg else 0.0
    gkg_cho  = round(g_cho/weight_kg,2) if weight_kg else 0.0
    g_cho_c = round(g_cho*pct_cho_complex/100,1); g_cho_s = round(g_cho - g_cho_c,1)
    sat, poli, mono = fat_split
    subtotal = max(1, sat+poli+mono)
    sat = pct_fat*sat/subtotal; poli = pct_fat*poli/subtotal; mono = pct_fat - sat - poli
    g_sat  = round((kcal*sat /100)/9,1)
    g_poli = round((kcal*poli/100)/9,1)
    g_mono = round((kcal*mono/100)/9,1)
    return {"pct":{"prot":pct_prot,"fat":pct_fat,"cho":pct_cho},
            "g":{"prot":g_prot,"fat":g_fat,"cho":g_cho,"cho_c":g_cho_c,"cho_s":g_cho_s,"sat":g_sat,"poli":g_poli,"mono":g_mono},
            "gkg":{"prot":gkg_prot,"cho":gkg_cho}}

def exchanges_from_kcal(k):
    f = max(1.0, min(2.4, k/2000))
    base = {"Vegetales":4,"Frutas":2,"Cereales":5,"Leguminosas":1,"Lácteos descremados":1,"Proteínas magras":4,"Grasas saludables":4}
    return {g:int(round(v*f)) for g,v in base.items()}

def distribute_by_meal(daily_exchanges):
    split = {"Desayuno":0.25,"Merienda AM":0.10,"Almuerzo":0.30,"Merienda PM":0.10,"Cena":0.25}
    plan = {m:{} for m in split}
    for g, total in daily_exchanges.items():
        for m, frac in split.items():
            plan[m][g] = round(total*frac,1)
    return plan

# ========= SIDEBAR — CAPTURA COMPLETA =========
with st.sidebar:
    with st.form("captura"):
        st.subheader("Paciente")
        paciente = st.text_input("Nombre y apellido")
        sexo = st.selectbox("Sexo biológico", ["Femenino","Masculino"])
        edad = st.number_input("Edad (años)", 1, 120, 30)
        talla_cm = st.number_input("Talla (cm)", 100, 230, 165)
        peso = st.number_input("Peso (kg)", 30.0, 300.0, 75.0, step=0.1)
        actividad = st.selectbox("Actividad", list(ACTIVITY.keys()), index=1)
        objetivo = st.selectbox("Objetivo", ["Pérdida de peso","Mantenimiento","Ganancia (magro)"], index=0)

        with st.expander("Antropometría detallada (opcional)", expanded=False):
            cintura = st.number_input("Circunferencia cintura (cm)", 0.0, 300.0, 0.0, step=0.1)
            cadera  = st.number_input("Circunferencia cadera (cm)", 0.0, 300.0, 0.0, step=0.1)
            # Pliegues (mm) — Durnin-Womersley
            st.caption("Pliegues cutáneos (mm) · Durnin-Womersley: Bíceps, Tríceps, Subescapular, Suprailiaco")
            p_biceps = st.number_input("Bíceps (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_triceps = st.number_input("Tríceps (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_subesc  = st.number_input("Subescapular (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_supra   = st.number_input("Suprailiaco (mm)", 0.0, 60.0, 0.0, step=0.5)
            # BIA opcional
            st.caption("BIA (opcional)")
            bia_fat = st.number_input("% Grasa (BIA)", 0.0, 70.0, 0.0, step=0.1)
            bia_ffm = st.number_input("Masa libre de grasa (kg, BIA)", 0.0, 200.0, 0.0, step=0.1)

        with st.expander("Laboratorios ampliados (opcional)", expanded=False):
            # Glucosa & control
            glicemia = st.number_input("Glucosa (mg/dL)", 0.0, 800.0, 0.0, step=0.1)
            insulina = st.number_input("Insulina (µUI/mL)", 0.0, 1000.0, 0.0, step=0.1)
            hba1c = st.number_input("HbA1c (%)", 0.0, 20.0, 0.0, step=0.1)
            # Lípidos
            tc  = st.number_input("Colesterol total (mg/dL)", 0.0, 500.0, 0.0, step=0.1)
            hdl = st.number_input("HDL (mg/dL)", 0.0, 200.0, 0.0, step=0.1)
            ldl = st.number_input("LDL (mg/dL)", 0.0, 300.0, 0.0, step=0.1)
            tg  = st.number_input("Triglicéridos (mg/dL)", 0.0, 1000.0, 0.0, step=0.1)
            # Renal/Hepático
            creat = st.number_input("Creatinina (mg/dL)", 0.0, 20.0, 0.0, step=0.01)
            urea   = st.number_input("Urea (mg/dL)", 0.0, 300.0, 0.0, step=0.1)
            alt = st.number_input("ALT (U/L)", 0.0, 2000.0, 0.0, step=0.1)
            ast = st.number_input("AST (U/L)", 0.0, 2000.0, 0.0, step=0.1)
            # Hierro / vitaminas / tiroides / inflamación
            hb  = st.number_input("Hemoglobina (g/dL)", 0.0, 25.0, 0.0, step=0.1)
            ferritina = st.number_input("Ferritina (ng/mL)", 0.0, 2000.0, 0.0, step=0.1)
            vitd = st.number_input("Vitamina D 25-OH (ng/mL)", 0.0, 200.0, 0.0, step=0.1)
            b12 = st.number_input("Vitamina B12 (pg/mL)", 0.0, 5000.0, 0.0, step=1.0)
            folato = st.number_input("Folato (ng/mL)", 0.0, 50.0, 0.0, step=0.1)
            tsh = st.number_input("TSH (µUI/mL)", 0.0, 150.0, 0.0, step=0.01)
            crp = st.number_input("PCR/CRP (mg/L)", 0.0, 500.0, 0.0, step=0.1)

        submitted = st.form_submit_button("Aplicar cambios")

# ========= CÁLCULOS =========
imc = bmi(peso, talla_cm)
tmb = max(800, round(mifflin_st_jeor(sexo, peso, talla_cm, edad)))
tee = tee_from_tmb(tmb, actividad)
kcal = kcal_target(tee, objetivo)
whr_v = whr(cintura, cadera) if 'cintura' in locals() else None
whtr_v = whtr(cintura, talla_cm) if 'cintura' in locals() else None
homa = homa_ir(glicemia if 'glicemia' in locals() else 0, insulina if 'insulina' in locals() else 0)

bf_dw = None
if ('p_biceps' in locals() and p_biceps+p_triceps+p_subesc+p_supra)>0:
    dens = durnin_womersley_density(sexo, edad, p_biceps, p_triceps, p_subesc, p_supra)
    bf_dw = siri_bodyfat_pct(dens)

# ========= REQUERIMIENTOS =========
st.subheader("Requerimientos nutricionales")
c1, c2 = st.columns(2)
with c1:
    pct_prot = st.slider("Proteínas (%)", 10, 35, 20)
    pct_fat  = st.slider("Grasas totales (%)", 20, 40, 30)
    pct_cho  = 100 - pct_prot - pct_fat
    st.info(f"Carbohidratos (%) se ajusta a: **{pct_cho}%**")
with c2:
    sat = st.slider("De la grasa total → Saturadas (%)", 0, 15, 10)
    poli = st.slider("De la grasa total → Poliinsat. (%)", 5, 60, 35)
    mono = max(0, 100 - sat - poli); st.info(f"Monoinsat. (%) se ajusta a: **{mono}%**")
pct_cho_complex = st.slider("Dentro de CHO → Complejos (%)", 50, 100, 85)

mac = macros(kcal, pct_prot, pct_fat, pct_cho, peso, pct_cho_complex, fat_split=(sat, poli, mono))

# ========= RESULTADOS (KPIs claros) =========
st.subheader("Resultados y clasificaciones")
cols = st.columns(3)
cols[0].markdown(f"<div class='card'><div class='kpi'>IMC: {imc} kg/m²</div><div class='muted'>OMS: "
                 f"{'Bajo peso' if imc<18.5 else 'Normopeso' if imc<25 else 'Sobrepeso' if imc<30 else 'Obesidad I' if imc<35 else 'Obesidad II' if imc<40 else 'Obesidad III'}</div></div>", unsafe_allow_html=True)
cols[1].markdown(f"<div class='card'><div class='kpi'>TMB: {tmb} kcal</div><div class='muted'>Mifflin-St Jeor</div></div>", unsafe_allow_html=True)
cols[2].markdown(f"<div class='card'><div class='kpi'>GET: {tee} kcal</div><div class='muted'>Actividad: {actividad}</div></div>", unsafe_allow_html=True)

cols2 = st.columns(3)
if whr_v is not None:
    cols2[0].markdown(f"<div class='card'><div class='kpi'>ICC: {whr_v}</div><div class='muted'>Riesgo cardiometabólico ↑ si >0.85 (F) / >0.90 (M)</div></div>", unsafe_allow_html=True)
if whtr_v is not None:
    cols2[1].markdown(f"<div class='card'><div class='kpi'>ICT: {whtr_v}</div><div class='muted'>Riesgo ↑ si ≥0.5 (adultos)</div></div>", unsafe_allow_html=True)
if bf_dw is not None or ('bia_fat' in locals() and bia_fat>0):
    bf_txt = f"{bf_dw}% (pliegues)" if bf_dw is not None else ""
    if 'bia_fat' in locals() and bia_fat>0: bf_txt += f"  ·  {bia_fat}% (BIA)"
    cols2[2].markdown(f"<div class='card'><div class='kpi'>% Grasa: {bf_txt}</div><div class='muted'>Durnin-Womersley + Siri / BIA</div></div>", unsafe_allow_html=True)

# Labs resumen
labs_list = []
if 'glicemia' in locals(): labs_list.append(f"Glucosa {glicemia} mg/dL")
if 'hba1c' in locals(): labs_list.append(f"HbA1c {hba1c}%")
if 'insulina' in locals() and insulina>0: labs_list.append(f"Insulina {insulina} µUI/mL")
if homa is not None: labs_list.append(f"HOMA-IR {homa}")
lipid_txt = []
if 'tc' in locals() and tc>0: lipid_txt.append(f"CT {tc}")
if 'ldl' in locals() and ldl>0: lipid_txt.append(f"LDL {ldl}")
if 'hdl' in locals() and hdl>0: lipid_txt.append(f"HDL {hdl}")
if 'tg' in locals() and tg>0: lipid_txt.append(f"TG {tg}")
st.markdown(f"<div class='card'><b>Laboratorios:</b> {' · '.join(labs_list)}  |  {' · '.join(lipid_txt)}</div>", unsafe_allow_html=True)

# ========= SODIO =========
st.subheader("Sodio")
cna1, cna2, cna3 = st.columns(3)
with cna1: na_obj = st.number_input("Objetivo (mg Na/día)", 500, 5000, 2300, step=50)
with cna2: na_cons = st.number_input("Consumido (mg Na/día)", 0, 5000, 900, step=10)
na_calc = sodium_convert(na_obj, na_cons)
with cna3: st.metric("Na remanente (mg)", na_calc["remaining_mg"])
st.caption(f"≈ {na_calc['salt_g']} g NaCl  ( {na_calc['tsp']} cdtas )  ·  400 mg Na ≈ 1 g NaCl  ·  1 cdta ≈ 5 g")

# ========= PLAN POR INTERCAMBIOS =========
st.subheader("Plan por Intercambios")
daily = exchanges_from_kcal(kcal)
by_meal = distribute_by_meal(daily)

df_plan = pd.DataFrame({
    "Grupo": list(daily.keys()),
    "Raciones/día": list(daily.values()),
    "kcal/ración": [EXCHANGES[g]["kcal"] for g in daily.keys()],
    "CHO": [EXCHANGES[g]["CHO"] for g in daily.keys()],
    "PRO": [EXCHANGES[g]["PRO"] for g in daily.keys()],
    "FAT": [EXCHANGES[g]["FAT"] for g in daily.keys()],
    "Porción ref.": [EXCHANGES[g]["portion"] for g in daily.keys()]
})
st.dataframe(df_plan, use_container_width=True, height=320)

df_meals = []
for m, grupos in by_meal.items():
    r = {"Tiempo": m}; r.update(grupos); df_meals.append(r)
st.dataframe(pd.DataFrame(df_meals), use_container_width=True, height=300)

# ========= ADIME & TEXTO CLÍNICO =========
st.subheader("ADIME")
motivo = st.text_area("Motivo / Resumen del caso")
dx_pes = st.text_area("Diagnóstico(s) PES (NCPT)", placeholder="Problema relacionado con ... evidenciado por ...")
prescripcion = st.text_area("Prescripción Dietética", placeholder="Plan por intercambios individualizado + educación nutricional.")
me_plan = st.text_area("Monitoreo/Evaluación", value="Control 2–4 semanas; peso, cintura, adherencia; labs según caso.")

# ========= EXPORTES =========
def build_docx(payload):
    if not DOCX_AVAILABLE: return None
    doc = Document()
    style = doc.styles["Normal"]; style.font.name = "Calibri"; style.font.size = Pt(11)

    doc.add_heading("HISTORIA CLÍNICA NUTRICIONAL – Nota ADIME", level=1)
    doc.add_paragraph(f"Fecha: {payload['fecha']}   Profesional: {payload['profesional']}   Paciente: {payload['paciente']}")
    # A
    doc.add_heading("Evaluación (A)", level=2)
    for line in payload["A"]:
        doc.add_paragraph(line)
    # D
    doc.add_heading("Diagnóstico (D)", level=2)
    if payload["D"]:
        for pes in payload["D"]: doc.add_paragraph(f"• {pes}")
    else: doc.add_paragraph("—")
    # I
    doc.add_heading("Intervención (I)", level=2); doc.add_paragraph(payload["I"])
    # ME
    doc.add_heading("Monitoreo/Evaluación (ME)", level=2); doc.add_paragraph(payload["ME"])
    # Requerimientos
    doc.add_heading("Requerimientos", level=2)
    m = payload["macros"]
    doc.add_paragraph(f"Energía: {payload['kcal']} kcal/d  ({payload['kcal_kg']} kcal/kg)")
    doc.add_paragraph(f"Proteínas: {m['pct']['prot']}% → {m['g']['prot']} g ({payload['gkg_prot']} g/kg)")
    doc.add_paragraph(f"Grasas: {m['pct']['fat']}% → {m['g']['fat']} g (Sat {m['g']['sat']} g, Poli {m['g']['poli']} g, Mono {m['g']['mono']} g)")
    doc.add_paragraph(f"CHO: {m['pct']['cho']}% → {m['g']['cho']} g (Complejos {m['g']['cho_c']} g, Simples {m['g']['cho_s']} g)")
    # Sodio
    s = payload["sodium"]
    doc.add_paragraph(f"Sodio objetivo: {s['target_mg']} mg; Consumido: {s['current_mg']} mg; Remanente: {s['remaining_mg']} mg  ≈  {s['salt_g']} g NaCl ( {s['tsp']} cdtas )")
    # Intercambios
    doc.add_heading("Intercambios (raciones/día)", level=2)
    table = doc.add_table(rows=1, cols=7)
    hdr = table.rows[0].cells
    for i, h in enumerate(["Grupo","Raciones","kcal","CHO","PRO","FAT","Porción"]): hdr[i].text = h
    for g, r in payload["exchanges"].items():
        row = table.add_row().cells
        row[0].text = g; row[1].text = str(r)
        row[2].text = str(EXCHANGES[g]["kcal"]); row[3].text = str(EXCHANGES[g]["CHO"])
        row[4].text = str(EXCHANGES[g]["PRO"]);  row[5].text = str(EXCHANGES[g]["FAT"])
        row[6].text = EXCHANGES[g]["portion"]
    bio = BytesIO(); doc.save(bio); bio.seek(0); return bio

def fhir_nutrition_order(payload):
    return {
      "resourceType":"NutritionOrder","status":"active","intent":"order","dateTime": payload["fecha"],
      "patient":{"display": payload["paciente"]},"orderer":{"display": payload["profesional"]},
      "oralDiet":{"type":[{"text":"Personalizada"}],
        "nutrient":[
          {"modifier":{"text":"Energy"}, "amount":{"value": payload["kcal"], "unit":"kcal/d"}},
          {"modifier":{"text":"Protein"}, "amount":{"value": payload["macros"]["g"]["prot"], "unit":"g/d"}},
          {"modifier":{"text":"Fat"}, "amount":{"value": payload["macros"]["g"]["fat"], "unit":"g/d"}},
          {"modifier":{"text":"Carbohydrate"}, "amount":{"value": payload["macros"]["g"]["cho"], "unit":"g/d"}}
        ],
        "texture":[{"modifier":{"text":"Normal"}}]
      }
    }

def fhir_nutrition_intake(payload):
    return {
      "resourceType":"NutritionIntake","status":"completed","occurrenceDateTime": payload["fecha"],
      "subject":{"display": payload["paciente"]},
      "consumedItem":[{"type":{"text":"Plan prescrito"},
                       "nutrient":[
                         {"item":{"text":"Protein"}, "amount":{"value": payload["macros"]["g"]["prot"], "unit":"g"}},
                         {"item":{"text":"Fat"}, "amount":{"value": payload["macros"]["g"]["fat"], "unit":"g"}},
                         {"item":{"text":"Carbohydrate"}, "amount":{"value": payload["macros"]["g"]["cho"], "unit":"g"}}
                       ],
                       "amount":{"value": payload["kcal"], "unit":"kcal"}}]
    }

# Payload común
labs_txt = []
if 'glicemia' in locals(): labs_txt.append(f"Glucosa {glicemia} mg/dL")
if 'hba1c' in locals(): labs_txt.append(f"HbA1c {hba1c}%")
if homa is not None: labs_txt.append(f"HOMA-IR {homa}")
labs_txt = " · ".join(labs_txt)

payload_common = {
    "fecha": date.today().isoformat(),
    "profesional": BRAND_NAME,
    "paciente": paciente or "—",
    "kcal": kcal, "kcal_kg": round(kcal/peso,2) if peso else 0.0,
    "gkg_prot": mac["gkg"]["prot"],
    "macros": mac,
    "sodium": {"target_mg": na_obj, "current_mg": na_cons, **na_calc},
    "exchanges": daily,
    "A": [
        f"IMC {imc} kg/m²; TMB {tmb} kcal; GET {tee} kcal.",
        f"ICC {whr_v if whr_v is not None else '—'}; ICT {whtr_v if whtr_v is not None else '—'}; %Grasa {bf_dw if bf_dw is not None else '—'}.",
        f"Labs: {labs_txt}."
    ],
    "D": [p.strip() for p in dx_pes.split("\n") if p.strip()],
    "I": prescripcion or "Plan por intercambios + educación nutricional.",
    "ME": me_plan or "Control 2–4 semanas; peso, cintura, adherencia; labs según caso."
}

# Botones de exporte
st.markdown("---")
colA, colB, colC = st.columns(3)
with colA:
    md_lines = [
        f"# {BRAND_NAME} · Nota ADIME",
        f"**Paciente:** {payload_common['paciente']}  |  **Fecha:** {payload_common['fecha']}",
        f"**IMC:** {imc}  ·  **TMB:** {tmb}  ·  **GET:** {tee}  ·  **Meta:** {kcal} kcal",
        "## Requerimientos",
        f"- Energía: {payload_common['kcal']} Kcal/d  ({payload_common['kcal_kg']} Kcal/kg)",
        f"- Proteínas: {mac['pct']['prot']}% → {mac['g']['prot']} g  ({payload_common['gkg_prot']} g/kg)",
        f"- Grasas: {mac['pct']['fat']}% → {mac['g']['fat']} g  (Sat {mac['g']['sat']} g, Poli {mac['g']['poli']} g, Mono {mac['g']['mono']} g)",
        f"- CHO: {mac['pct']['cho']}% → {mac['g']['cho']} g  (Complejos {mac['g']['cho_c']} g, Simples {mac['g']['cho_s']} g)",
        "## ADIME",
        f"**A:** {'  '.join(payload_common['A'])}",
        f"**D:** {', '.join(payload_common['D']) if payload_common['D'] else '—'}",
        f"**I:** {payload_common['I']}",
        f"**ME:** {payload_common['ME']}"
    ]
    st.download_button("⬇️ Exportar Markdown", "\n".join(md_lines), file_name="adime_nutritionsays.md")

with colB:
    if DOCX_AVAILABLE:
        bio = build_docx(payload_common)
        st.download_button("⬇️ Exportar DOCX", data=bio, file_name="nota_clinica_nutritionsays.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    else:
        st.info("Para DOCX instala 'python-docx' y 'lxml' (revisar requirements.txt).")

with colC:
    st.caption("JSON FHIR (NutritionOrder / NutritionIntake)")
    st.json({"NutritionOrder": fhir_nutrition_order(payload_common),
             "NutritionIntake": fhir_nutrition_intake(payload_common)})
    
st.caption("Soporte clínico para profesionales. Ajustar a juicio clínico y guías locales. © " + BRAND_NAME)
