# app.py — @nutritionsays · Gestión Nutricional Clínica (UCV)

import json
from datetime import date
from io import BytesIO

import streamlit as st
import pandas as pd

# ---- DOCX opcional (si falla la instalación, la app sigue funcionando) ----
try:
    from docx import Document
    from docx.shared import Pt
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

# =========================
# BRANDING & LAYOUT
# =========================
BRAND_NAME = "@nutritionsays"
PRIMARY = "#240046"
ACCENT = "#b9b1ff"

st.set_page_config(
    page_title=f"{BRAND_NAME} · Gestión Nutricional",
    page_icon="🍎",
    layout="centered"
)

st.markdown(
    f"""
    <style>
      .stApp {{ background:#faf9ff; }}
      h1,h2,h3,h4 {{ color:{PRIMARY}; }}
      .brand {{
        display:inline-block; padding:6px 12px; border-radius:12px;
        background:{ACCENT}; color:#111; font-weight:700; margin-bottom:6px;
      }}
      .box {{ border:1px solid #ececec; border-radius:14px; padding:12px; background:#fff; }}
      .soft {{ color:#555; }}
      /* Mobile tweaks */
      @media (max-width: 480px){{
        .stApp {{ padding:.5rem; }}
        h1 {{ font-size:1.4rem; }}
        h2 {{ font-size:1.1rem; }}
        .box {{ padding:10px; }}
      }}
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(f"<span class='brand'>{BRAND_NAME}</span>", unsafe_allow_html=True)
st.title("Software de Gestión Nutricional – Consulta Clínica (UCV)")

# =========================
# CATÁLOGO DE INTERCAMBIOS (base VE, editable)
# =========================
EXCHANGES = {
    "Vegetales": {"kcal":25,"CHO":5,"PRO":2,"FAT":0,
                  "portion":"1 taza crudas / 1/2 taza cocidas",
                  "examples":["lechuga","espinaca","brócoli","chayota"]},
    "Frutas": {"kcal":60,"CHO":15,"PRO":0,"FAT":0,
               "portion":"1 unid pequeña / 1/2 taza picada",
               "examples":["manzana","mandarina","lechoza 3/4 tz"]},
    "Cereales": {"kcal":80,"CHO":15,"PRO":2,"FAT":1,
                 "portion":"1/2 taza cocidos / 1 rebanada pan",
                 "examples":["arroz 1/2 tz","pasta 1/2 tz","arepa 1/3 unid (50 g)","pan 1 reb"]},
    "Leguminosas": {"kcal":100,"CHO":18,"PRO":7,"FAT":1,
                    "portion":"1/2 taza cocidas",
                    "examples":["caraotas","lentejas","frijol bayo"]},
    "Lácteos descremados": {"kcal":90,"CHO":12,"PRO":8,"FAT":2,
                            "portion":"1 taza leche / yogurt natural",
                            "examples":["leche 1 tz","yogurt natural 1 tz"]},
    "Proteínas magras": {"kcal":110,"CHO":0,"PRO":21,"FAT":3,
                         "portion":"30 g cocidos",
                         "examples":["pollo sin piel","pavo","pescado blanco","atún agua 1/2 lata"]},
    "Grasas saludables": {"kcal":45,"CHO":0,"PRO":0,"FAT":5,
                          "portion":"1 cdita (5 g)",
                          "examples":["aceite 1 cdita","aguacate 1/8 unid","nueces 6"]}
}

# =========================
# UTILIDADES CLÍNICAS
# =========================
ACTIVITY = {"Reposo / cama":1.2,"Ligera (1–3 d/sem)":1.375,"Moderada (3–5 d/sem)":1.55,"Alta (6–7 d/sem)":1.725}

def mifflin_st_jeor(sex, weight_kg, height_cm, age_y):
    return 10*weight_kg + 6.25*height_cm - 5*age_y + (5 if sex.lower().startswith("m") else -161)

def tee_from_tmb(tmb, activity_key): return round(tmb * ACTIVITY.get(activity_key, 1.2))

def kcal_target(tee, objective):
    if objective=="Pérdida de peso": return max(1000, tee - (400 if tee>=1600 else 200))
    if objective=="Ganancia (magro)": return tee + 200
    return tee

def bmi(weight_kg, height_cm):
    h = max(1e-6, height_cm/100); return round(weight_kg/(h*h),2)

def homa_ir(glucose_mg_dl, insulin_uU_ml):
    if glucose_mg_dl>0 and insulin_uU_ml>0:
        g_mmol = glucose_mg_dl/18.0
        return round((g_mmol*insulin_uU_ml)/22.5,2)
    return None

def macros(kcal, pct_prot, pct_fat, pct_cho, weight_kg, pct_cho_complex=85, fat_split=(10,35,55)):
    # normaliza a 100%
    total = max(1, pct_prot + pct_fat + pct_cho)
    pct_prot = round(100*pct_prot/total); pct_fat = round(100*pct_fat/total); pct_cho = 100 - pct_prot - pct_fat
    g_prot = round((kcal*pct_prot/100)/4,1)
    g_fat  = round((kcal*pct_fat /100)/9,1)
    g_cho  = round((kcal*pct_cho /100)/4,1)
    gkg_prot = round(g_prot/weight_kg,2) if weight_kg else 0.0
    gkg_cho  = round(g_cho/weight_kg,2) if weight_kg else 0.0
    # CHO complejos vs simples
    g_cho_c = round(g_cho*pct_cho_complex/100,1); g_cho_s = round(g_cho - g_cho_c,1)
    # grasas: repartir dentro del % de grasa total
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

def exchanges_from_kcal(k):
    # heurística base (ajustable a tus tablas)
    f = max(1.0, min(2.2, k/2000))
    base = {"Vegetales":4,"Frutas":2,"Cereales":5,"Leguminosas":1,"Lácteos descremados":1,"Proteínas magras":4,"Grasas saludables":4}
    return {g:int(round(v*f)) for g,v in base.items()}

def distribute_by_meal(daily_exchanges):
    split = {"Desayuno":0.25,"Merienda AM":0.10,"Almuerzo":0.30,"Merienda PM":0.10,"Cena":0.25}
    plan = {m:{} for m in split}
    for g, total in daily_exchanges.items():
        for m, frac in split.items():
            plan[m][g] = round(total*frac,1)
    return plan

# =========================
# IMPORTAR EXCEL DE INTERCAMBIOS (opcional)
# =========================
def load_catalog_from_excel(file) -> dict:
    """
    Columnas esperadas: Grupo, Nombre, kcal, CHO, PRO, FAT, Porcion, Equivalencia, Comentario
    Retorna dict con promedios por 'Grupo' (para sustituir EXCHANGES si quieres).
    """
    try:
        df = pd.read_excel(file)
        df.columns = [c.strip().lower() for c in df.columns]
        cat = {}
        for g, sub in df.groupby("grupo"):
            s = sub[["kcal","cho","pro","fat"]].astype(float).mean().to_dict()
            cat[g] = {
                "kcal": round(s.get("kcal",0),1),
                "CHO": round(s.get("cho",0),1),
                "PRO": round(s.get("pro",0),1),
                "FAT": round(s.get("fat",0),1),
                "portion": str(sub["porcion"].iloc[0]) if "porcion" in sub else "",
                "examples": list(sub["nombre"][:5]) if "nombre" in sub else []
            }
        return cat
    except Exception:
        return {}

# =========================
# SIDEBAR – Datos y Configuración
# =========================
with st.sidebar:
    with st.form("datos"):
        st.subheader("Paciente")
        paciente = st.text_input("Nombre y apellido")
        sexo = st.selectbox("Sexo biológico", ["Femenino","Masculino"])
        edad = st.number_input("Edad (años)", 1, 120, 30)
        talla_cm = st.number_input("Talla (cm)", 100, 230, 165)
        peso = st.number_input("Peso (kg)", 30.0, 300.0, 75.0, step=0.1)
        actividad = st.selectbox("Actividad", list(ACTIVITY.keys()), index=1)
        objetivo = st.selectbox("Objetivo", ["Pérdida de peso","Mantenimiento","Ganancia (magro)"], index=0)

        st.markdown("---")
        st.subheader("Laboratorios (opcional)")
        glicemia = st.number_input("Glicemia (mg/dL)", 0.0, 2000.0, 0.0, step=0.1)
        insulina = st.number_input("Insulina (µUI/mL)", 0.0, 2000.0, 0.0, step=0.1)
        hba1c = st.number_input("HbA1c (%)", 0.0, 20.0, 0.0, step=0.1)

        st.markdown("---")
        st.subheader("Catálogo de intercambios")
        xls = st.file_uploader("Cargar Excel de intercambios (opcional)", type=["xlsx","xls"])

        submitted = st.form_submit_button("Aplicar cambios")

# Sustituir catálogo si suben Excel
if xls is not None:
    newcat = load_catalog_from_excel(xls)
    if newcat: EXCHANGES.update(newcat)

# =========================
# CÁLCULOS BASE
# =========================
tmb = max(800, round(mifflin_st_jeor(sexo, peso, talla_cm, edad)))
tee = tee_from_tmb(tmb, actividad)
kcal = kcal_target(tee, objetivo)
imc = bmi(peso, talla_cm)
homa = homa_ir(glicemia, insulina)

labs_txt = f"Glicemia: {glicemia} mg/dL; Insulina: {insulina} µUI/mL; HbA1c: {hba1c}%"
if homa is not None:
    labs_txt += f"; HOMA-IR: {homa}"

st.subheader("Resumen antropométrico y de cálculo")
st.markdown(
    f"""
    <div class='box'>
      <b>IMC:</b> {imc} kg/m² · <b>TMB:</b> {tmb} kcal · <b>GET:</b> {tee} kcal · <b>Meta:</b> {kcal} kcal
      <br><span class='soft'>{labs_txt}</span>
    </div>
    """,
    unsafe_allow_html=True
)

# =========================
# REQUERIMIENTOS (como en tus plantillas)
# =========================
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
    mono = max(0, 100 - sat - poli)
    st.info(f"Monoinsat. (%) se ajusta a: **{mono}%**")
pct_cho_complex = st.slider("Dentro de CHO → Complejos (%)", 50, 100, 85)

mac = macros(kcal, pct_prot, pct_fat, pct_cho, peso, pct_cho_complex, fat_split=(sat, poli, mono))

st.markdown("**Cálculo automático:**")
st.write(
    f"- Proteínas: {mac['pct']['prot']}% → **{mac['g']['prot']} g**  (≈ **{mac['gkg']['prot']} g/kg**)\n"
    f"- Grasas totales: {mac['pct']['fat']}% → **{mac['g']['fat']} g**  "
    f"• Sat: **{mac['g']['sat']} g** • Poli: **{mac['g']['poli']} g** • Mono: **{mac['g']['mono']} g**\n"
    f"- CHO: {mac['pct']['cho']}% → **{mac['g']['cho']} g**  "
    f"• Complejos: **{mac['g']['cho_c']} g** • Simples: **{mac['g']['cho_s']} g**"
)

# =========================
# SODIO
# =========================
st.subheader("Conversión de sodio")
cna1, cna2, cna3 = st.columns(3)
with cna1:
    na_obj = st.number_input("Objetivo (mg Na/día)", 500, 5000, 2300, step=50)
with cna2:
    na_cons = st.number_input("Consumido (mg Na/día)", 0, 5000, 900, step=10)
na_calc = sodium_convert(na_obj, na_cons)
with cna3:
    st.metric("Na remanente (mg)", na_calc["remaining_mg"])
st.write(f"**Equivalencia:** 400 mg Na ≈ 1 g NaCl; 1 cdta ≈ 5 g → **{na_calc['salt_g']} g NaCl ({na_calc['tsp']} cdtas)**")

# =========================
# HISTORIA & ADIME
# =========================
st.subheader("Historia dietética y ADIME")
motivo = st.text_area("Motivo de consulta / Resumen del caso")
diagnosticos_medicos = st.text_area("Diagnósticos médicos actuales")
tratamiento_medico = st.text_area("Tratamiento médico")
tratamiento_nutri = st.text_area("Tratamiento nutricional previo/actual")
objetivos_nutri = st.text_area("Objetivos nutricionales")
recordatorio_24h = st.text_area("Recordatorio 24 h (Preparación / Ingredientes / Cantidad por comidas)", height=140)
analisis_cualitativo = st.text_area("Análisis cualitativo (conductas, horarios, preferencias/rechazos)")
prescripcion_dietetica = st.text_area("Prescripción Dietética (resumen operativo)")
sugerencias = st.text_area("Sugerencias y comentarios")
dx_pes = st.text_area("Diagnóstico(s) PES (NCPT)", placeholder="Problema relacionado con ... evidenciado por ...")

# =========================
# INTERCAMBIOS: Sugerencia y distribución
# =========================
st.subheader("Plan por Intercambios (sugerido)")
daily = exchanges_from_kcal(kcal)
by_meal = distribute_by_meal(daily)

df_plan = pd.DataFrame({
    "Grupo": list(daily.keys()),
    "Raciones/día": list(daily.values()),
    "kcal/rac": [EXCHANGES[g]["kcal"] if g in EXCHANGES else "" for g in daily.keys()],
    "Porción": [EXCHANGES[g]["portion"] if g in EXCHANGES else "" for g in daily.keys()],
    "Ejemplos": [", ".join(EXCHANGES[g]["examples"]) if g in EXCHANGES else "" for g in daily.keys()],
})
st.dataframe(df_plan, use_container_width=True, height=320)

df_meals = []
for m, grupos in by_meal.items():
    r = {"Tiempo": m}
    r.update(grupos)
    df_meals.append(r)
st.dataframe(pd.DataFrame(df_meals), use_container_width=True, height=300)

# =========================
# EXPORTES: DOCX + FHIR + MD
# =========================
def build_docx(kind, payload):
    if not DOCX_AVAILABLE: return None
    doc = Document()
    style = doc.styles["Normal"]; style.font.name = "Calibri"; style.font.size = Pt(11)
    doc.add_heading(f"HISTORIA CLÍNICA NUTRICIONAL – {kind.upper()}", level=1)
    doc.add_paragraph(f"Fecha: {payload['fecha']}   Profesional: {payload['profesional']}   Paciente: {payload['paciente']}")
    # A
    doc.add_heading("Evaluación (A)", level=2)
    doc.add_paragraph(payload["evaluation"])
    # D
    doc.add_heading("Diagnóstico (D)", level=2)
    if payload["pes_list"]:
        for pes in payload["pes_list"]:
            doc.add_paragraph(f"• {pes}")
    else:
        doc.add_paragraph("—")
    # I
    doc.add_heading("Intervención (I)", level=2)
    doc.add_paragraph(payload["prescription"])
    # ME
    doc.add_heading("Monitoreo/Evaluación (ME)", level=2)
    doc.add_paragraph(payload["monitoring"])
    # Requerimientos
    doc.add_heading("Requerimientos", level=2)
    m = payload["macros"]
    doc.add_paragraph(f"Energía: {payload['kcal']} kcal/d  ({payload['kcal_kg']} kcal/kg)")
    doc.add_paragraph(f"Proteínas: {m['pct']['prot']}% → {m['g']['prot']} g ({payload['gkg_prot']} g/kg)")
    doc.add_paragraph(f"Grasas: {m['pct']['fat']}% → {m['g']['fat']} g (Sat {m['g']['sat']} g, Poli {m['g']['poli']} g, Mono {m['g']['mono']} g)")
    doc.add_paragraph(f"CHO: {m['pct']['cho']}% → {m['g']['cho']} g (Complejos {m['g']['cho_c']} g, Simples {m['g']['cho_s']} g)")
    # Sodio
    s = payload["sodium"]
    doc.add_paragraph(f"Sodio objetivo: {s['target_mg']} mg; Consumido: {s['current_mg']} mg; Remanente: {s['remaining_mg']} mg")
    doc.add_paragraph(f"≈ {s['salt_g']} g NaCl ( {s['tsp']} cdtas )")
    bio = BytesIO(); doc.save(bio); bio.seek(0); return bio

def fhir_nutrition_order(payload):
    return {
      "resourceType":"NutritionOrder",
      "status":"active","intent":"order","dateTime": payload["fecha"],
      "patient":{"display": payload["paciente"]},
      "orderer":{"display": payload["profesional"]},
      "oralDiet":{
        "type":[{"text": payload["diet_type"]}],
        "nutrient":[
          {"modifier":{"text":"Energy"}, "amount":{"value": payload["kcal"], "unit":"kcal/d"}},
          {"modifier":{"text":"Protein"}, "amount":{"value": payload["macros"]["g"]["prot"], "unit":"g/d"}},
          {"modifier":{"text":"Fat"}, "amount":{"value": payload["macros"]["g"]["fat"], "unit":"g/d"}},
          {"modifier":{"text":"Carbohydrate"}, "amount":{"value": payload["macros"]["g"]["cho"], "unit":"g/d"}}
        ],
        "texture":[{"modifier":{"text": payload.get("texture","Normal")}}],
        "excludeFoodModifier":[{"text": e} for e in payload.get("exclusions",[])]
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

# Payload común para exportes
common = {
    "fecha": date.today().isoformat(),
    "paciente": paciente or "—",
    "profesional": BRAND_NAME,
    "kcal": kcal, "kcal_kg": round(kcal/peso,2) if peso else 0.0,
    "gkg_prot": mac["gkg"]["prot"],
    "macros": mac,
    "sodium": {"target_mg": na_obj, "current_mg": na_cons, **na_calc}
}

doc_payload = {
    **common,
    "diet_type": "Personalizada",
    "texture": "Normal",
    "evaluation": f"IMC {imc} kg/m²; TMB {tmb} kcal; GET {tee} kcal; "
                  f"Labs: {labs_txt}. Dieta habitual: {recordatorio_24h}",
    "pes_list": [p.strip() for p in dx_pes.split("\n") if p.strip()],
    "prescription": prescripcion_dietetica or "Plan por intercambios + educación nutricional.",
    "monitoring": "Control en 2–4 semanas; métricas: peso, cintura, adherencia; labs según caso.",
    "exclusions": []
}

# UI Exportes
st.markdown("---")
colA, colB, colC = st.columns(3)

with colA:
    md_lines = [
        f"# {BRAND_NAME} · Nota ADIME",
        f"**Paciente:** {common['paciente']}  |  **Fecha:** {common['fecha']}",
        f"**IMC:** {imc} kg/m²  ·  **TMB:** {tmb}  ·  **GET:** {tee}  ·  **Meta:** {kcal} kcal",
        "## Requerimientos",
        f"- Energía: {common['kcal']} Kcal/d  ({common['kcal_kg']} Kcal/kg)",
        f"- Proteínas: {mac['pct']['prot']}% → {mac['g']['prot']} g  ({common['gkg_prot']} g/kg)",
        f"- Grasas: {mac['pct']['fat']}% → {mac['g']['fat']} g  (Sat {mac['g']['sat']} g, Poli {mac['g']['poli']} g, Mono {mac['g']['mono']} g)",
        f"- CHO: {mac['pct']['cho']}% → {mac['g']['cho']} g  (Complejos {mac['g']['cho_c']} g, Simples {mac['g']['cho_s']} g)",
        "## ADIME",
        f"**A:** {doc_payload['evaluation']}",
        f"**D:** {', '.join(doc_payload['pes_list']) if doc_payload['pes_list'] else '—'}",
        f"**I:** {doc_payload['prescription']}",
        f"**ME:** {doc_payload['monitoring']}"
    ]
    st.download_button("⬇️ Exportar Markdown", "\n".join(md_lines), file_name="adime_nutritionsays.md")

with colB:
    if DOCX_AVAILABLE:
        bio = build_docx("Inicial/Control", doc_payload)
        st.download_button(
            "⬇️ Exportar DOCX",
            data=bio,
            file_name="nota_clinica_nutritionsays.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        st.info("Para DOCX instala 'python-docx' y 'lxml' (revisar requirements.txt).")

with colC:
    order_json = fhir_nutrition_order(doc_payload)
    intake_json = fhir_nutrition_intake(common)
    with st.expander("🔎 Ver JSON FHIR (NutritionOrder / NutritionIntake)"):
        st.json({"NutritionOrder": order_json, "NutritionIntake": intake_json})

st.caption("Este software es apoyo clínico para profesionales. Ajusta a juicio clínico y guías locales. © " + BRAND_NAME)
