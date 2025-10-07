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
    g_poli = round((kcal * p_p_*_
