import streamlit as st
import pandas as pd
from datetime import date
from io import BytesIO

# Import DOCX de forma segura (si falla, la app sigue con Markdown)
try:
    from docx import Document
    from docx.shared import Pt
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

# ====== BRANDING ======
BRAND_NAME = "@nutritionsays"
PRIMARY = "#240046"
ACCENT = "#b9b1ff"

st.set_page_config(page_title=f"{BRAND_NAME} · Gestión Nutricional", page_icon="🍎", layout="centered")

st.markdown(
    f"""
    <style>
    .stApp {{ background: #faf9ff; }}
    h1,h2,h3,h4 {{ color:{PRIMARY}; }}
    .brand {{ display:inline-block; padding:6px 10px; border-radius:10px; background:{ACCENT}; color:#111; font-weight:600; }}
    .box {{ border:1px solid #eee; border-radius:12px; padding:12px; background:#fff; }}
    @media (max-width: 480px){{
      .stApp {{ padding: .5rem; }}
      h1 {{ font-size:1.4rem; }}
      h2 {{ font-size:1.1rem; }}
      .box {{ padding: 8px; }}
    }}
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(f"<span class='brand'>{BRAND_NAME}</span>", unsafe_allow_html=True)
st.title("Software de Gestión Nutricional – Consulta Clínica (UCV)")

# ====== Utilidades ======
ACT_FACTORS = {
    "Reposo / cama": 1.2,
    "Ligera (1–3 d/sem)": 1.375,
    "Moderada (3–5 d/sem)": 1.55,
    "Alta (6–7 d/sem)": 1.725
}

def mifflin_st_jeor(sexo: str, peso: float, talla_cm: float, edad: int) -> float:
    if sexo.lower().startswith("m"):
        return 10*peso + 6.25*talla_cm - 5*edad + 5
    return 10*peso + 6.25*talla_cm - 5*edad - 161

def homa_ir(glucosa_mg_dl: float, insulina_ui_ml: float):
    try:
        if glucosa_mg_dl > 0 and insulina_ui_ml > 0:
            g_mmol = glucosa_mg_dl / 18.0
            return (g_mmol * insulina_ui_ml) / 22.5
    except Exception:
        pass
    return None

def kcal_objetivo(GET: int, objetivo: str):
    if objetivo == "Pérdida de peso":
        return max(1000, round(GET - (400 if GET >= 1600 else 200)))
    if objetivo == "Mantenimiento":
        return round(GET)
    if objetivo == "Ganancia (magro)":
        return round(GET + 200)
    return round(GET)

def macros_from_percent(kcal: int, p_prot: int, p_grasa: int, p_cho: int, peso: float, p_cho_complejo: int):
    total = p_prot + p_grasa + p_cho
    if total != 100:
        p_prot = int(round(100 * p_prot / total))
        p_grasa = int(round(100 * p_grasa / total))
        p_cho = 100 - p_prot - p_grasa

    g_prot = round((kcal * p_prot / 100) / 4, 1)
    g_grasa = round((kcal * p_grasa / 100) / 9, 1)
    g_cho = round((kcal * p_cho / 100) / 4, 1)

    gkg_prot = round(g_prot / peso, 2) if peso else 0.0
    gkg_cho  = round(g_cho  / peso, 2) if peso else 0.0

    g_cho_complejos = round(g_cho * (p_cho_complejo/100), 1)
    g_cho_simples   = round(g_cho - g_cho_complejos, 1)

    return {
        "porc": {"prot": p_prot, "grasa": p_grasa, "cho": p_cho},
        "g": {"prot": g_prot, "grasa": g_grasa, "cho": g_cho, "cho_c": g_cho_complejos, "cho_s": g_cho_simples},
        "gkg": {"prot": gkg_prot, "cho": gkg_cho}
    }

def grasas_detalle(kcal: int, p_grasa_total: int, p_sat: int, p_poli: int, p_mono: int):
    subtotal = p_sat + p_poli + p_mono
    if subtotal == 0:  # evitar div/0
        p_sat, p_poli, p_mono = 30, 35, 35
        subtotal = 100
    # Reparto dentro del % de grasa total
    p_sat  = p_grasa_total * p_sat  / 100
    p_poli = p_grasa_total * p_poli / 100
    p_mono = p_grasa_total - p_sat - p_poli

    g_sat  = round((kcal * p_sat  / 100) / 9, 1)
    g_poli = round((kcal * p_poli / 100) / 9, 1)
    g_mono = round((kcal * p_mono / 100) / 9, 1)
    return {
        "sat": g_sat, "poli": g_poli, "mono": g_mono,
        "p_sat": round(p_sat,1), "p_poli": round(p_poli,1), "p_mono": round(p_mono,1)
    }

def sodio_conversion(mg_objetivo: int, mg_consumido: int):
    rem = max(0, mg_objetivo - mg_consumido)
    g_nacl = round(rem / 400.0, 2)      # 400 mg Na ≈ 1 g NaCl
    cdtas = round(g_nacl / 5.0, 2)      # 1 cdta ≈ 5 g
    return {"remanente_mg_na": rem, "g_nacl": g_nacl, "cdtas": cdtas}

# ====== Sidebar (form para evitar reruns en móvil) ======
with st.sidebar:
    with st.form("datos"):
        st.subheader("Paciente")
        paciente = st.text_input("Nombre y apellido")
        sexo = st.selectbox("Sexo biológico", ["Femenino","Masculino"])
        edad = st.number_input("Edad (años)", 1, 120, 30)
        talla_cm = st.number_input("Talla (cm)", 100, 230, 165)
        peso = st.number_input("Peso (kg)", 30.0, 300.0, 75.0, step=0.1)
        act = st.selectbox("Actividad", list(ACT_FACTORS.keys()), index=1)
        objetivo = st.selectbox("Objetivo", ["Pérdida de peso","Mantenimiento","Ganancia (magro)"], index=0)

        st.markdown("---")
        st.subheader("Laboratorios (opcional)")
        glicemia = st.number_input("Glicemia (mg/dL)", 0.0, 2000.0, 0.0, step=0.1)
        insulina = st.number_input("Insulina (µUI/mL)", 0.0, 2000.0, 0.0, step=0.1)
        hba1c = st.number_input("HbA1c (%)", 0.0, 20.0, 0.0, step=0.1)

        submitted = st.form_submit_button("Aplicar cambios")

# ====== Cálculos base ======
tmb = max(800, round(mifflin_st_jeor(sexo, peso, talla_cm, edad)))
get = max(tmb, round(tmb * ACT_FACTORS.get(act, 1.2)))
kcal = kcal_objetivo(get, objetivo)
imc = round(peso / (talla_cm/100)**2, 2)
homa = homa_ir(glicemia, insulina)

labs_txt = f"Glicemia: {glicemia} mg/dL; Insulina: {insulina} µUI/mL; HbA1c: {hba1c}%"
if homa is not None:
    labs_txt += f"; HOMA-IR: {round(homa,2)}"

st.subheader("Resumen antropométrico y de cálculo")
st.markdown(
    f"""
    <div class='box'>
    <b>IMC:</b> {imc} kg/m² · <b>TMB:</b> {tmb} kcal · <b>GET:</b> {get} kcal · <b>Meta:</b> {kcal} kcal
    <br><span style='color:#555'>{labs_txt}</span>
    </div>
    """, unsafe_allow_html=True
)

# ====== Requerimientos (como en tus plantillas) ======
st.subheader("Requerimientos nutricionales (formato de tus plantillas)")
c1, c2 = st.columns(2)
with c1:
    p_prot = st.slider("Proteínas (%)", 10, 35, 20)
    p_grasa = st.slider("Grasas totales (%)", 20, 40, 30)
    p_cho = 100 - p_prot - p_grasa
    st.info(f"Carbohidratos (%) se ajusta a: **{p_cho}%**")
with c2:
    p_sat = st.slider("De la grasa total → Saturadas (%)", 0, 15, 10)
    p_poli = st.slider("De la grasa total → Poliinsat. (%)", 5, 60, 35)
    p_mono = max(0, 100 - p_sat - p_poli)
    st.info(f"Monoinsat. (%) se ajusta a: **{p_mono}%**")

p_cho_complejo = st.slider("Dentro de los CHO → Complejos (%)", 50, 100, 85)

mac = macros_from_percent(kcal, p_prot, p_grasa, p_cho, peso, p_cho_complejo)
# >>> FIX del error de paréntesis y key:
g_grasas_det = grasas_detalle(kcal, mac["porc"]["grasa"], p_sat, p_poli, p_mono)

st.markdown("**Cálculo automático:**")
st.write(
    f"- Proteínas: {mac['porc']['prot']}% → **{mac['g']['prot']} g**  (≈ **{mac['gkg']['prot']} g/kg**)\n"
    f"- Grasas totales: {mac['porc']['grasa']}% → **{mac['g']['grasa']} g**  "
    f"• Sat: **{g_grasas_det['sat']} g** • Poli: **{g_grasas_det['poli']} g** • Mono: **{g_grasas_det['mono']} g**\n"
    f"- CHO: {mac['porc']['cho']}% → **{mac['g']['cho']} g**  "
    f"• Complejos: **{mac['g']['cho_c']} g** • Simples: **{mac['g']['cho_s']} g**"
)

# ====== Conversión de Sodio ======
st.subheader("Conversión de sodio (como en tu plantilla)")
cna1, cna2, cna3 = st.columns(3)
with cna1:
    na_obj = st.number_input("Objetivo (mg Na/día)", 500, 5000, 2300, step=50)
with cna2:
    na_cons = st.number_input("Consumido (mg Na/día)", 0, 5000, 900, step=10)
calc_na = sodio_conversion(na_obj, na_cons)
with cna3:
    st.metric("Na remanente (mg)", calc_na["remanente_mg_na"])
st.write(f"**Equivalencia:** 1 mEq Na = 23 mg Na · 400 mg Na ≈ 1 g NaCl**")
st.write(f"**Sal (NaCl):** {calc_na['g_nacl']} g  →  **{calc_na['cdtas']} cdtas** (1 cdta ~ 5 g)")

# ====== Historia dietética & ADIME (inputs clave) ======
st.subheader("Historia dietética y ADIME")
motivo = st.text_area("Motivo de consulta / Resumen del caso")
diagnosticos_medicos = st.text_area("Diagnósticos médicos actuales")
tratamiento_medico = st.text_area("Tratamiento médico")
tratamiento_nutri = st.text_area("Tratamiento nutricional")
objetivos_nutri = st.text_area("Objetivos nutricionales")
recordatorio_24h = st.text_area("Recordatorio 24 h (Preparación / Ingredientes / Cantidad por comidas)", height=150)
analisis_cualitativo = st.text_area("Análisis cualitativo (conductas, horarios, preferencia/rechazos)")
prescripcion_dietetica = st.text_area("Prescripción Dietética")
sugerencias = st.text_area("Sugerencias y comentarios")

# ====== Export .docx según Plantillas (Primera vez / Control) ======
def build_docx_primera_vez(payload: dict) -> BytesIO:
    doc = Document()
    style = doc.styles["Normal"]; style.font.name = "Calibri"; style.font.size = Pt(11)

    doc.add_heading("HISTORIA CLÍNICA NUTRICIONAL – PRIMERA VEZ", level=1)
    doc.add_paragraph(f"Historia Nº: ____________     Fecha de evaluación: {payload['fecha']}")
    doc.add_heading("DATOS PERSONALES:", level=2)
    doc.add_paragraph(f"Nombre y Apellido: {payload['paciente']}")
    doc.add_paragraph(f"CI: V-__________      Edad: {payload['edad']} años      Sexo: {payload['sexo']}")
    doc.add_paragraph("Dirección: __________________________   Teléfono: __________   Correo: __________")

    doc.add_heading("MOTIVO DE CONSULTA:", level=2); doc.add_paragraph(payload["motivo"])
    doc.add_heading("RESUMEN DEL CASO:", level=2); doc.add_paragraph(payload["resumen"])
    doc.add_heading("DIAGNÓSTICOS MÉDICOS ACTUALES:", level=2); doc.add_paragraph(payload["dx_med"])
    doc.add_heading("TRATAMIENTO ACTUAL:", level=2)
    doc.add_paragraph(f"Médico: {payload['tto_med']}"); doc.add_paragraph(f"Nutricional: {payload['tto_nutri']}")

    doc.add_heading("Objetivos nutricionales:", level=2); doc.add_paragraph(payload["obj_nutri"])

    doc.add_heading("RECORDATORIO DE 24 HORAS", level=2)
    table = doc.add_table(rows=1, cols=3); hdr = table.rows[0].cells
    hdr[0].text = "Preparación"; hdr[1].text = "Ingredientes"; hdr[2].text = "Cantidad"
    table.add_row().cells[0].text = payload["r24h"]
    doc.add_paragraph("Aporte Calórico aproximado: ____ Kcal")
    doc.add_paragraph("Total PAVB: ____ g   |  Total CHO complejos: ____ g   |  Total CHO simples: ____ g   |  Total Grasas: ____ g")

    doc.add_heading("ANÁLISIS CUALITATIVO:", level=2); doc.add_paragraph(payload["analisis"])

    doc.add_heading("DATOS ANTROPOMÉTRICOS:", level=2)
    doc.add_paragraph(f"Peso Actual: {payload['peso']} kg     Talla: {payload['talla_m']} m     IMC: {payload['imc']} kg/m²")
    doc.add_paragraph("Circ. Cintura: ___ cm    Circ. Cadera: ___ cm    ICC: ___    %Grasa: ___")

    doc.add_heading("LABORATORIOS:", level=2); doc.add_paragraph(payload["labs"])

    doc.add_heading("DIAGNÓSTICO NUTRICIONAL:", level=2); doc.add_paragraph("________________________________________")

    doc.add_heading("REQUERIMIENTOS NUTRICIONALES:", level=2)
    doc.add_paragraph(f"Energía: {payload['kcal']} Kcal/día   |   Kcal/Kg: {payload['kcal_kg']}")
    doc.add_paragraph(f"Proteínas: {payload['p_prot']}%  → {payload['g_prot']} g  ( {payload['gkg_prot']} g/kg )")
    doc.add_paragraph(f"Grasas totales: {payload['p_grasa']}% → {payload['g_grasa']} g")
    doc.add_paragraph(f"  - Saturadas: {payload['g_sat']} g   - Poli: {payload['g_poli']} g   - Mono: {payload['g_mono']} g")
    doc.add_paragraph(f"Carbohidratos (totales): {payload['p_cho']}% → {payload['g_cho']} g")
    doc.add_paragraph(f"  - CHO complejos: {payload['g_cho_c']} g   - CHO simples: {payload['g_cho_s']} g")

    doc.add_heading("PRESCRIPCIÓN DIETÉTICA:", level=2); doc.add_paragraph(payload["prescripcion"])

    doc.add_heading("CONVERSIÓN DE SODIO:", level=2)
    doc.add_paragraph("1 mEq Na ----- 23 mg Na")
    doc.add_paragraph(f"{payload['na_obj']} mg Na – {payload['na_cons']} mg Na = {payload['na_rem']} mg Na")
    doc.add_paragraph("400 mg Na ----- 1 g NaCl")
    doc.add_paragraph(f"{payload['na_rem']} mg Na ----- {payload['g_nacl']} g NaCl  (≈ {payload['cdtas']} cdtas de sal)")
    doc.add_paragraph("Distribuir la sal diaria en todas las preparaciones del día.")

    doc.add_heading("Sugerencias y comentarios:", level=2); doc.add_paragraph(payload["sugerencias"])

    bio = BytesIO(); doc.save(bio); bio.seek(0); return bio

def build_docx_control(payload: dict) -> BytesIO:
    doc = Document()
    style = doc.styles["Normal"]; style.font.name = "Calibri"; style.font.size = Pt(11)

    doc.add_heading("HISTORIA CLÍNICA NUTRICIONAL – CONTROL", level=1)
    doc.add_paragraph(f"Historia Nº: ____________     Fecha de evaluación: {payload['fecha']}")
    doc.add_heading("DATOS PERSONALES:", level=2)
    doc.add_paragraph(f"Nombre y Apellido: {payload['paciente']}")
    doc.add_paragraph(f"Edad: {payload['edad']} años      Sexo: {payload['sexo']}")

    doc.add_heading("RECORDATORIO DE 24 HORAS", level=2)
    table = doc.add_table(rows=1, cols=3); hdr = table.rows[0].cells
    hdr[0].text = "Preparación"; hdr[1].text = "Ingredientes"; hdr[2].text = "Cantidad"
    table.add_row().cells[0].text = payload["r24h"]
    doc.add_paragraph("Aporte Calórico aproximado: ____ Kcal")
    doc.add_paragraph("Total PAVB: ____ g   |  Total CHO complejos: ____ g   |  Total CHO simples: ____ g   |  Total Grasas: ____ g")

    doc.add_heading("LABORATORIOS:", level=2); doc.add_paragraph(payload["labs"])

    doc.add_heading("Evaluación antropométrica:", level=2)
    doc.add_paragraph(f"Peso Actual: {payload['peso']} kg   |   Talla: {payload['talla_m']} m   |   IMC: {payload['imc']} kg/m²")

    doc.add_heading("Requerimientos Nutricionales:", level=2)
    doc.add_paragraph(f"Energía {payload['kcal']} Kcal/día   |   Kcal/Kg {payload['kcal_kg']}")
    doc.add_paragraph(f"Proteínas {payload['p_prot']}% → {payload['g_prot']} g  ({payload['gkg_prot']} g/kg)")
    doc.add_paragraph(f"Grasas totales {payload['p_grasa']}% → {payload['g_grasa']} g  (Sat {payload['g_sat']} g, Poli {payload['g_poli']} g, Mono {payload['g_mono']} g)")
    doc.add_paragraph(f"CHO {payload['p_cho']}% → {payload['g_cho']} g  (Complejos {payload['g_cho_c']} g, Simples {payload['g_cho_s']} g)")

    doc.add_heading("Diagnóstico nutricional:", level=2); doc.add_paragraph("_____________________________")
    doc.add_heading("Objetivos nutricionales planteados:", level=2); doc.add_paragraph(payload["obj_nutri"])
    doc.add_paragraph("Objetivo | En proceso | Resuelto")
    doc.add_paragraph("________ | __________ | ________")

    doc.add_heading("Prescripción Dietética:", level=2); doc.add_paragraph(payload["prescripcion"])
    doc.add_heading("Sugerencias y comentarios:", level=2); doc.add_paragraph(payload["sugerencias"])

    bio = BytesIO(); doc.save(bio); bio.seek(0); return bio

# ====== Payload común para export ======
payload = {
    "fecha": date.today().isoformat(),
    "paciente": st.session_state.get("paciente", "") or "—",
    "edad": int(edad),
    "sexo": sexo,
    "peso": float(peso),
    "talla_m": round(talla_cm/100, 2),
    "imc": imc,
    "kcal": kcal,
    "kcal_kg": round(kcal / peso, 2) if peso else 0.0,
    "p_prot": mac["porc"]["prot"], "p_grasa": mac["porc"]["grasa"], "p_cho": mac["porc"]["cho"],
    "g_prot": mac["g"]["prot"], "gkg_prot": mac["gkg"]["prot"],
    "g_grasa": mac["g"]["grasa"],
    "g_sat": g_grasas_det["sat"], "g_poli": g_grasas_det["poli"], "g_mono": g_grasas_det["mono"],
    "g_cho": mac["g"]["cho"], "g_cho_c": mac["g"]["cho_c"], "g_cho_s": mac["g"]["cho_s"],
    "labs": labs_txt,
    "motivo": motivo,
    "resumen": motivo,  # si quieres separar, agrega otro campo para "Resumen"
    "dx_med": diagnosticos_medicos,
    "tto_med": tratamiento_medico,
    "tto_nutri": tratamiento_nutri,
    "obj_nutri": objetivos_nutri,
    "r24h": recordatorio_24h,
    "analisis": analisis_cualitativo,
    "prescripcion": prescripcion_dietetica,
    "sugerencias": sugerencias,
    "na_obj": na_obj,
    "na_cons": na_cons,
    "na_rem": calc_na["remanente_mg_na"],
    "g_nacl": calc_na["g_nacl"],
    "cdtas": calc_na["cdtas"],
}

st.markdown("---")
tipo_doc = st.radio("Tipo de documento a generar", ["Primera vez", "Control"], horizontal=True)
col1, col2 = st.columns(2)

with col1:
    md = [
        f"# {BRAND_NAME} · Informe Nutricional ({tipo_doc})",
        f"**Paciente:** {payload['paciente']}  |  **Fecha:** {payload['fecha']}",
        f"**IMC:** {payload['imc']} kg/m²  ·  **TMB:** {tmb}  ·  **GET:** {get}  ·  **Meta:** {kcal} kcal",
        "## Requerimientos",
        f"- Energía: {payload['kcal']} Kcal/d  ({payload['kcal_kg']} Kcal/kg)",
        f"- Proteínas: {payload['p_prot']}% → {payload['g_prot']} g  ({payload['gkg_prot']} g/kg)",
        f"- Grasas: {payload['p_grasa']}% → {payload['g_grasa']} g  (Sat {payload['g_sat']} g, Poli {payload['g_poli']} g, Mono {payload['g_mono']} g)",
        f"- CHO: {payload['p_cho']}% → {payload['g_cho']} g  (Complejos {payload['g_cho_c']} g, Simples {payload['g_cho_s']} g)"
    ]
    st.download_button("⬇️ Exportar Markdown", "\n".join(md), file_name="informe_nutritionsays.md")

with col2:
    if DOCX_AVAILABLE:
        if tipo_doc == "Primera vez":
            bio = build_docx_primera_vez(payload)
            fname = "historia_clinica_primera_vez_nutritionsays.docx"
        else:
            bio = build_docx_control(payload)
            fname = "historia_clinica_control_nutritionsays.docx"
        st.download_button(
            "⬇️ Exportar DOCX",
            data=bio,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        st.info("Exportar a DOCX no disponible: verifica 'python-docx' y 'lxml' en requirements.txt.")
