import streamlit as st
import math
from datetime import date
from io import BytesIO
from docx import Document
from docx.shared import Pt, Inches
import pandas as pd

# =========================
# BRANDING @nutritionsays
# =========================
BRAND_NAME = "@nutritionsays"
PRIMARY = "#240046"
ACCENT = "#b9b1ff"

st.set_page_config(
    page_title=f"{BRAND_NAME} · Gestión Nutricional",
    page_icon="🍎",
    layout="wide"
)

# Pequeño estilo
st.markdown(
    f"""
    <style>
    .stApp {{ background-color: #faf9ff; }}
    h1,h2,h3,h4 {{ color: {PRIMARY}; }}
    .brand-badge {{
        display:inline-block; padding:6px 10px; border-radius:10px;
        background:{ACCENT}; color:#111; font-weight:600; margin-bottom:8px;
    }}
    .muted {{ color:#555; font-size:0.9rem; }}
    .box {{ border:1px solid #eee; border-radius:12px; padding:12px; background:#fff; }}
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(f"<span class='brand-badge'>{BRAND_NAME}</span>", unsafe_allow_html=True)
st.title("Software de Gestión Nutricional – Consulta Clínica")

# =========================
# UTILIDADES CLÍNICAS
# =========================
def mifflin_st_jeor(sexo: str, peso: float, talla_cm: float, edad: int):
    # peso kg, talla cm, edad años
    if sexo.lower().startswith("m"):  # masculino
        return 10*peso + 6.25*talla_cm - 5*edad + 5
    else:
        return 10*peso + 6.25*talla_cm - 5*edad - 161

ACT_FACTORS = {
    "Reposo / cama": 1.2,
    "Ligera (caminar 1-3 d/sem)": 1.375,
    "Moderada (3-5 d/sem)": 1.55,
    "Alta (6-7 d/sem)": 1.725
}

def homa_ir(glicemia_mg_dl: float, insulina_ui_ml: float):
    # Convierte mg/dL a mmol/L (÷18), HOMA-IR = glucosa (mmol/L) * insulina / 22.5
    if not glicemia_mg_dl or not insulina_ui_ml:
        return None
    g_mmol = glicemia_mg_dl / 18.0
    return (g_mmol * insulina_ui_ml) / 22.5

# =========================
# LISTAS DE INTERCAMBIOS (simplificadas)
# Valores aproximados por ración • Ajustables
# =========================
EXCHANGES = {
    "Verduras": {"kcal":25,"CHO":5,"PRO":2,"GRASA":0,
                 "porcion":"1 taza crudas o 1/2 taza cocidas",
                 "ejemplos":"lechuga, espinaca, brócoli, calabacín"},
    "Frutas": {"kcal":60,"CHO":15,"PRO":0,"GRASA":0,
               "porcion":"1 unidad pequeña o 1/2 taza picada",
               "ejemplos":"manzana, pera, naranja, fresas"},
    "Cereales/Harinas": {"kcal":80,"CHO":15,"PRO":2,"GRASA":1,
               "porcion":"1/2 taza cocidos o 1 tajada pan",
               "ejemplos":"arroz, pasta, arepa 1/3 unid, pan 1 rebanada"},
    "Lácteos descremados": {"kcal":90,"CHO":12,"PRO":8,"GRASA":0-3,
               "porcion":"1 taza leche descremada o yogurt natural",
               "ejemplos":"leche 1 taza, yogurt natural 1 taza"},
    "Proteínas magras": {"kcal":110,"CHO":0,"PRO":21,"GRASA":3,
               "porcion":"30 g cocidos",
               "ejemplos":"pollo sin piel, pavo, merluza, claras"},
    "Grasas saludables": {"kcal":45,"CHO":0,"PRO":0,"GRASA":5,
               "porcion":"1 cda pequeña (5 g)",
               "ejemplos":"aceite de oliva 1 cdita, aguacate 1/8 unid, nueces 6"},
    "Azúcares/ultraprocesados": {"kcal":60,"CHO":15,"PRO":0,"GRASA":0,
               "porcion":"variable (evitar/limitar)",
               "ejemplos":"refrescos, golosinas, bollería"}
}

# Distribución por tiempo de comida (puedes ajustar)
MEAL_SPLIT = {
    "Desayuno": 0.25,
    "Merienda AM": 0.10,
    "Almuerzo": 0.30,
    "Merienda PM": 0.10,
    "Cena": 0.25
}

def kcal_plan(GET, objetivo):
    if objetivo == "Pérdida de peso":
        return round(GET - 400) if GET >= 1600 else round(GET - 200)
    if objetivo == "Mantenimiento":
        return round(GET)
    if objetivo == "Ganancia (magro)":
        return round(GET + 200)
    return round(GET)

def raciones_sugeridas(kcal_total: int):
    """
    Reparto muy simple de raciones objetivo por día (puedes afinarlo):
    - Vegetales altos (≥4), frutas 2-3, cereales 4-6, proteínas 3-5, grasas 3-5, lácteos 1-2
    Escala según kcal_total.
    """
    f = max(1.0, min(2.0, kcal_total/2000))  # factor 1x a 2x aprox
    base = {
        "Verduras": 4,
        "Frutas": 2,
        "Cereales/Harinas": 5,
        "Proteínas magras": 4,
        "Grasas saludables": 4,
        "Lácteos descremados": 1
    }
    return {k: max(0, round(v*f)) for k,v in base.items()}

def distribuir_por_comida(raciones_dia: dict):
    """
    Distribuye raciones por tiempos de comida usando MEAL_SPLIT.
    Resultado: dict[meal][grupo] = raciones
    """
    plan = {meal:{} for meal in MEAL_SPLIT}
    for grupo, total in raciones_dia.items():
        for meal, frac in MEAL_SPLIT.items():
            plan[meal][grupo] = round(total*frac, 1)
    return plan

def recomendaciones(dm2: bool, hta: bool, obesidad: bool):
    recs = []
    if dm2:
        recs += [
            "Fraccionar ingestas (3 comidas + 1–2 meriendas) para estabilidad glucémica.",
            "Priorizar carbohidratos complejos y fibra (verduras, legumbres, granos integrales).",
            "Aumentar proteína magra en cada tiempo de comida para saciedad.",
            "Limitar azúcares libres y ultraprocesados; bebidas sin azúcar.",
            "Actividad física combinada: 150–300 min/sem de aeróbico + 2 días fuerza."
        ]
    if hta:
        recs += [
            "Plan tipo DASH: alto en verduras/frutas, lácteos descremados y grasas saludables.",
            "Sodio < 2 g/día (≈5 g de sal); evitar ultraprocesados.",
            "Hidratación adecuada; limitar alcohol."
        ]
    if obesidad:
        recs += [
            "Déficit calórico moderado y progresivo; evitar restricciones extremas.",
            "Sueño 7–9 h y manejo de estrés (impactan apetito/hormonas).",
            "Actividad física adaptada a tolerancia y articulaciones (bajo impacto)."
        ]
    if not recs:
        recs.append("Plan balanceado, variado y suficiente; movimiento diario y sueño reparador.")
    return recs

def adime_plantilla(datos):
    # Plantilla simple (puedes personalizar PES manualmente en campo de texto)
    d = datos
    dx = d.get("diagnostico_pes","(Completar PES individual)")
    return {
        "Valoración (A)": f"Motivo: {d.get('motivo','—')}. 24h: {d.get('recall','—')}. "
                          f"IMC: {d.get('imc','—')} kg/m². Labs clave: {d.get('labs','—')}.",
        "Diagnóstico (D)": dx,
        "Intervención (I)": "Plan por intercambios individualizado + educación nutricional.",
        "Monitoreo (M)": "Peso, perímetros, adherencia, glucemias/lípidos según caso.",
        "Evaluación (E)": "Ajustes por síntomas, tolerancia, metas y resultados de control."
    }

def build_docx(payload):
    doc = Document()
    # Estilos básicos
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(11)

    doc.add_heading(f"{BRAND_NAME} · Informe Nutricional", level=1)
    doc.add_paragraph(f"Paciente: {payload['paciente']} • Fecha: {payload['fecha']}")
    doc.add_paragraph(f"Profesional: {payload['profesional']} (Lic. Nutricionista-Dietista UCV)")

    doc.add_heading("Resumen antropométrico", level=2)
    doc.add_paragraph(f"Sexo: {payload['sexo']} | Edad: {payload['edad']} años | Talla: {payload['talla_cm']} cm | Peso: {payload['peso']} kg")
    doc.add_paragraph(f"IMC: {payload['imc']} kg/m² | TMB: {payload['tmb']} kcal | GET: {payload['get']} kcal | Meta kcal: {payload['kcal_obj']} kcal")

    doc.add_heading("ADIME", level=2)
    for k,v in payload['adime'].items():
        doc.add_paragraph(f"{k}: {v}")

    doc.add_heading("Plan por Intercambios (raciones/día)", level=2)
    table = doc.add_table(rows=1, cols=7)
    hdr = table.rows[0].cells
    hdr[0].text = "Grupo"
    hdr[1].text = "Raciones"
    hdr[2].text = "kcal/rac"
    hdr[3].text = "CHO"
    hdr[4].text = "PRO"
    hdr[5].text = "GRASA"
    hdr[6].text = "Porción/ejemplos"
    for g, r in payload['raciones_dia'].items():
        row = table.add_row().cells
        row[0].text = g
        row[1].text = str(r)
        row[2].text = str(EXCHANGES[g]["kcal"])
        row[3].text = str(EXCHANGES[g]["CHO"])
        row[4].text = str(EXCHANGES[g]["PRO"])
        row[5].text = str(EXCHANGES[g]["GRASA"])
        row[6].text = f"{EXCHANGES[g]['porcion']} | {EXCHANGES[g]['ejemplos']}"

    doc.add_heading("Distribución por comidas (raciones)", level=2)
    for meal, grupos in payload['plan_comidas'].items():
        doc.add_paragraph(f"{meal}: " + "; ".join([f"{g} {v}" for g,v in grupos.items()]))

    doc.add_heading("Recomendaciones", level=2)
    for r in payload['recs']:
        doc.add_paragraph(f"• {r}")

    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio

# =========================
# UI – SIDEBAR (entrada)
# =========================
with st.sidebar:
    st.subheader("Datos del paciente")
    paciente = st.text_input("Nombre del paciente")
    sexo = st.selectbox("Sexo biológico", ["Femenino","Masculino"])
    edad = st.number_input("Edad (años)", 1, 120, 30)
    talla_cm = st.number_input("Talla (cm)", 100, 230, 165)
    peso = st.number_input("Peso (kg)", 30.0, 300.0, 75.0, step=0.1)
    act = st.selectbox("Actividad", list(ACT_FACTORS.keys()), index=1)
    objetivo = st.selectbox("Objetivo", ["Pérdida de peso","Mantenimiento","Ganancia (magro)"], index=0)

    st.markdown("---")
    st.subheader("Comorbilidades")
    dm2 = st.checkbox("Diabetes tipo 2")
    hta = st.checkbox("Hipertensión arterial")
    obesidad = st.checkbox("Obesidad")

    st.markdown("---")
    st.subheader("Laboratorios (opcional)")
    glicemia = st.number_input("Glicemia (mg/dL)", 0.0, 1000.0, 0.0, step=0.1)
    insulina = st.number_input("Insulina (µUI/mL)", 0.0, 1000.0, 0.0, step=0.1)
    hba1c = st.number_input("HbA1c (%)", 0.0, 20.0, 0.0, step=0.1)

# =========================
# UI – MAIN
# =========================
colA, colB = st.columns([2,1])
with colA:
    st.subheader("Motivo de consulta / Historia breve")
    motivo = st.text_area("Anamnesis breve", height=120, placeholder="Motivo principal, antecedentes relevantes, síntomas, medicación…")

    st.subheader("Recordatorio 24 h (opcional)")
    recall = st.text_area("Descripción 24 h", height=140, placeholder="Desayuno, almuerzo, cena, snacks, bebidas…")

with colB:
    st.subheader("Diagnóstico PES (texto libre)")
    dx_pes = st.text_area("PES (opcional)", height=140, placeholder="Ej: Ingesta energética superior a lo recomendado relacionada con... evidenciado por...")

st.markdown("----")

# Cálculos
tmb = round(mifflin_st_jeor(sexo, peso, talla_cm, edad))
get = round(tmb * ACT_FACTORS[act])
kcal_obj = kcal_plan(get, objetivo)
imc = round(peso / (talla_cm/100)**2, 2)
homa = homa_ir(glicemia, insulina)
labs_txt = f"Glicemia: {glicemia} mg/dL; Insulina: {insulina} µUI/mL; HbA1c: {hba1c}%"
if homa: labs_txt += f"; HOMA-IR: {round(homa,2)}"

st.subheader("Resumen antropométrico y de cálculo")
st.markdown(
    f"""
    <div class='box'>
    <b>IMC:</b> {imc} kg/m² · <b>TMB:</b> {tmb} kcal · <b>GET:</b> {get} kcal · <b>Meta calórica:</b> {kcal_obj} kcal
    <br><span class='muted'>{labs_txt}</span>
    </div>
    """,
    unsafe_allow_html=True
)

# Plan por intercambios
raciones_dia = raciones_sugeridas(kcal_obj)
plan_comidas = distribuir_por_comida(raciones_dia)
recs = recomendaciones(dm2, hta, obesidad)

st.subheader("Plan por Intercambios (raciones/día)")
df_plan = pd.DataFrame({
    "Grupo": list(raciones_dia.keys()),
    "Raciones/día": list(raciones_dia.values()),
    "kcal/ración": [EXCHANGES[g]["kcal"] for g in raciones_dia.keys()],
    "Porción referencial": [EXCHANGES[g]["porcion"] for g in raciones_dia.keys()],
    "Ejemplos": [EXCHANGES[g]["ejemplos"] for g in raciones_dia.keys()],
})
st.dataframe(df_plan, use_container_width=True)

st.subheader("Distribución por comidas (raciones aproximadas)")
df_meals = []
for meal, grupos in plan_comidas.items():
    row = {"Tiempo": meal}
    row.update(grupos)
    df_meals.append(row)
st.dataframe(pd.DataFrame(df_meals), use_container_width=True)

st.subheader("Recomendaciones personalizadas")
for r in recs:
    st.markdown(f"- {r}")

# ADIME
datos_adime = {
    "motivo": motivo,
    "recall": recall,
    "imc": imc,
    "labs": labs_txt,
    "diagnostico_pes": dx_pes
}
adime = adime_plantilla(datos_adime)

with st.expander("Ver ADIME (plantilla)"):
    for k,v in adime.items():
        st.markdown(f"**{k}**: {v}")

# Export
payload = {
    "paciente": paciente or "—",
    "fecha": date.today().isoformat(),
    "profesional": BRAND_NAME,
    "sexo": sexo,
    "edad": edad,
    "talla_cm": talla_cm,
    "peso": peso,
    "imc": imc,
    "tmb": tmb,
    "get": get,
    "kcal_obj": kcal_obj,
    "adime": adime,
    "raciones_dia": raciones_dia,
    "plan_comidas": plan_comidas,
    "recs": recs
}

st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    # Markdown
    md_lines = []
    md_lines.append(f"# {BRAND_NAME} · Informe Nutricional")
    md_lines.append(f"**Paciente:** {payload['paciente']}  \n**Fecha:** {payload['fecha']}")
    md_lines.append(f"**Profesional:** {payload['profesional']} (Nutricionista-Dietista UCV)")
    md_lines.append("## Antropometría y cálculos")
    md_lines.append(f"- IMC: {imc} kg/m²  \n- TMB: {tmb} kcal  \n- GET: {get} kcal  \n- Meta: {kcal_obj} kcal")
    md_lines.append("## ADIME")
    for k,v in adime.items(): md_lines.append(f"- **{k}:** {v}")
    md_lines.append("## Intercambios (raciones/día)")
    for g, r in raciones_dia.items():
        md_lines.append(f"- {g}: {r} (kcal/rac {EXCHANGES[g]['kcal']}) – Porción: {EXCHANGES[g]['porcion']}")
    md_lines.append("## Distribución por comidas")
    for meal, grupos in plan_comidas.items():
        md_lines.append(f"- **{meal}:** " + "; ".join([f"{g} {v}" for g,v in grupos.items()]))
    md_lines.append("## Recomendaciones")
    for r in recs: md_lines.append(f"- {r}")
    md_text = "\n".join(md_lines)

    st.download_button("⬇️ Exportar Markdown", md_text, file_name="informe_nutritionsays.md")

with col2:
    # DOCX
    bio = build_docx(payload)
    st.download_button("⬇️ Exportar DOCX", data=bio, file_name="informe_nutritionsays.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

st.caption("Este software es apoyo clínico para profesionales de la salud. Ajusta a juicio clínico y guías locales vigentes.")
