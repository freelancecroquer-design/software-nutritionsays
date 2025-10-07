import streamlit as st
import pandas as pd
from datetime import date
from io import BytesIO

# import docx en try/except para no romper si falla el build
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
    # Verificación simple de 100%
    total = p_prot + p_grasa + p_cho
    if total != 100:
        # Normalizamos proporcionalmente
        p_prot = int(round(100 * p_prot / total))
        p_grasa = int(round(100 * p_grasa / total))
        p_cho = 100 - p_prot - p_grasa

    g_prot = round((kcal * p_prot / 100) / 4, 1)
    g_grasa = round((kcal * p_grasa / 100) / 9, 1)
    g_cho = round((kcal * p_cho / 100) / 4, 1)

    gkg_prot = round(g_prot / peso, 2) if peso else 0.0
    gkg_cho = round(g_cho / peso, 2) if peso else 0.0

    # CHO complejos vs simples
    g_cho_complejos = round(g_cho * (p_cho_complejo/100), 1)
    g_cho_simples = round(g_cho - g_cho_complejos, 1)
    return {
        "porc": {"prot": p_prot, "grasa": p_grasa, "cho": p_cho},
        "g": {"prot": g_prot, "grasa": g_grasa, "cho": g_cho, "cho_c": g_cho_complejos, "cho_s": g_cho_simples},
        "gkg": {"prot": gkg_prot, "cho": gkg_cho}
    }

def grasas_detalle(kcal: int, p_grasa_total: int, p_sat: int, p_poli: int, p_mono: int):
    # Ajuste a 100% dentro del % de grasa
    subtotal = p_sat + p_poli + p_mono
    if subtotal == 0:  # evitar div/0
        p_sat, p_poli, p_mono = 30, 35, 35
        subtotal = 100
    p_sat = p_grasa_total * p_sat / 100
    p_poli = p_grasa_total * p_poli / 100
    p_mono = p_grasa_total - p_sat - p_poli

    g_sat = round((kcal * p_sat / 100) / 9, 1)
    g_poli = round((kcal * p_poli / 100) / 9, 1)
    g_mono = round((kcal * p_mono / 100) / 9, 1)
    return {"sat": g_sat, "poli": g_poli, "mono": g_mono,
            "p_sat": round(p_sat,1), "p_poli": round(p_poli,1), "p_mono": round(p_mono,1)}

def sodio_conversion(mg_objetivo: int, mg_consumido: int):
    # mg Na remanente
    rem = max(0, mg_objetivo - mg_consumido)
    # 400 mg Na ≈ 1 g NaCl  (según tu plantilla)
    g_nacl = round(rem / 400.0, 2)
    cdtas = round(g_nacl / 5.0, 2)  # 1 cdta ~ 5 g
    return {"remanente_mg_na": rem, "g_nacl": g_nacl, "cdtas": cdtas}

# ====== Sidebar (form para móvil sin re-renders) ======
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

# ====== Datos de cálculo ======
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

# ====== Configuración de Requerimientos (como tus plantillas) ======
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
    p_mono = 100 - p_sat - p_poli
    st.info(f"Monoinsat. (%) se ajusta a: **{p_mono}%**")

p_cho_complejo = st.slider("Dentro de los CHO → Complejos (%)", 50, 100, 85)

mac = macros_from_percent(kcal, p_prot, p_grasa, p_cho, peso, p_cho_complejo)
g_grasas_det = grasas_detalle(kcal, mac["porc"]_
