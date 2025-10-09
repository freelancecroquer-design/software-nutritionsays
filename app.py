# app.py — @nutritionsays · Gestión Nutricional (Ambulatorio por defecto, cálculo en vivo)

from datetime import date
from io import BytesIO
import math
import streamlit as st
import pandas as pd

# Exportar DOCX (opcional)
try:
    from docx import Document
    from docx.shared import Pt
    DOCX = True
except Exception:
    DOCX = False

BRAND = "@nutritionsays"
st.set_page_config(page_title=f"{BRAND} · Gestión Nutricional", page_icon="🍎", layout="centered")

# ---------- ESTILOS: sidebar oscuro y selects legibles (control + menú) ----------
st.markdown("""
<style>
/* Main claro */
.stApp, .block-container { background:#ffffff !important; color:#111 !important; }
h1,h2,h3,h4,h5, p, span, label, div, li, th, td { color:#111 !important; }

/* Sidebar oscuro */
section[data-testid="stSidebar"] { background:#1e1e2a !important; border-right:1px solid #141421; }
section[data-testid="stSidebar"] * { color:#f5f6fb !important; }
section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stMarkdown p { color:#e6def7 !important; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] textarea {
  color:#ffffff !important; background:#111223 !important; border:1px solid #3b3b57 !important;
}
section[data-testid="stSidebar"] input::placeholder, section[data-testid="stSidebar"] textarea::placeholder { color:#cbd0ff !important; opacity:.85; }

/* ---- SELECTS (siempre legibles) ---- */
/* Contenedor del select (valor elegido) */
section[data-testid="stSidebar"] div[data-baseweb="select"]>div { color:#ffffff !important; background:#111223 !important; }
section[data-testid="stSidebar"] div[data-baseweb="select"] svg { fill:#ffffff !important; }
/* Menú desplegable */
.stApp [data-baseweb="menu"] {
  background:#1b1d2c !important; color:#ffffff !important;
  border:1px solid #3b3b57 !important; box-shadow:0 4px 14px rgba(0,0,0,.35) !important;
}
.stApp [data-baseweb="menu"] * { color:#ffffff !important; }
.stApp [data-baseweb="menu"] div[role="option"], .stApp [data-baseweb="menu"] li { color:#ffffff !important; }
.stApp [data-baseweb="menu"] div[role="option"]:hover, .stApp [data-baseweb="menu"] li:hover {
  background:#2a2e46 !important;
}

/* Tarjetas y badges */
.card { border:1px solid #e6e6ef; border-radius:14px; padding:14px; background:#fff; box-shadow:0 1px 6px rgba(0,0,0,.06); }
.kpi { font-size:1.12rem; font-weight:700; }
.badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:.82rem; font-weight:700; }
.bg-ok { background:#e7f6ef; color:#106a42; border:1px solid #c7eadb;}
.bg-warn { background:#fff3cd; color:#8a6d1a; border:1px solid #ffe29a;}
.bg-bad { background:#fde2e1; color:#a02c2a; border:1px solid #f6b1af;}
.bg-info{ background:#e7efff; color:#274c9a; border:1px solid #c6d7ff;}
@media (max-width: 480px){ .stApp { padding:.4rem; } h1{font-size:1.36rem;} h2{font-size:1.12rem;} .card{padding:10px;} }
</style>
""", unsafe_allow_html=True)

st.markdown(f"### {BRAND} · Software de Gestión Nutricional")

# ---------- Catálogos ----------
EXCHANGES = {
    "Vegetales": {"kcal":25,"CHO":5,"PRO":2,"FAT":0,"portion":"1 taza crudas / 1/2 taza cocidas"},
    "Frutas": {"kcal":60,"CHO":15,"PRO":0,"FAT":0,"portion":"1 unid pequeña / 1/2 taza picada"},
    "Cereales": {"kcal":80,"CHO":15,"PRO":2,"FAT":1,"portion":"1/2 taza cocidos / 1 rebanada pan"},
    "Leguminosas": {"kcal":100,"CHO":18,"PRO":7,"FAT":1,"portion":"1/2 taza cocidas"},
    "Lácteos descremados": {"kcal":90,"CHO":12,"PRO":8,"FAT":2,"portion":"1 taza leche / yogurt natural"},
    "Proteínas magras": {"kcal":110,"CHO":0,"PRO":21,"FAT":3,"portion":"30 g cocidos"},
    "Grasas saludables": {"kcal":45,"CHO":0,"PRO":0,"FAT":5,"portion":"1 cdita (5 g)"}
}
PAL = {"Muy bajo (sedentario)":1.2, "Ligero":1.4, "Moderado":1.6, "Alto":1.75, "Muy alto":2.0}

# ---------- Utilidades ----------
def mifflin(sex, w, h_cm, age): return 10*w + 6.25*h_cm - 5*age + (5 if sex.lower().startswith("m") else -161)
def harris_benedict(sex, w, h_cm, age):
    if sex.lower().startswith("m"): return 66.47 + (13.75*w) + (5.003*h_cm) - (6.755*age)
    return 655.09 + (9.563*w) + (1.850*h_cm) - (4.676*age)
def tee_ambulatorio(mb, pal, ade_on=False):
    base = mb * pal
    if ade_on: base *= 1.10
    return round(base)
def kcal_target(tee, obj):
    if obj=="Pérdida de peso": return max(1000, tee - (400 if tee>=1600 else 200))
    if obj=="Ganancia (magro)": return tee + 200
    return tee
def bmi(w,hcm):
    if not w or not hcm: return None
    h=max(1e-6, hcm/100); return round(w/(h*h),2)
def whr(waist, hip): return round((waist/hip),2) if waist and hip else None
def whtr(waist, hcm): return round((waist/hcm),2) if waist and hcm else None
DW = {
    "F":[(17,(1.1549,0.0678)),(29,(1.1599,0.0717)),(39,(1.1423,0.0632)),(49,(1.1333,0.0612)),(120,(1.1339,0.0645))],
    "M":[(17,(1.1620,0.0630)),(29,(1.1631,0.0632)),(39,(1.1422,0.0544)),(49,(1.1620,0.0700)),(120,(1.1715,0.0779))]
}
def dw_density(sex, age, biceps, triceps, subesc, supra):
    S=max(0.1,(biceps or 0)+(triceps or 0)+(subesc or 0)+(supra or 0)); logS=math.log10(S)
    key="F" if sex.lower().startswith("f") else "M"
    coeff=None
    for up,ab in DW[key]:
        if age<=up: coeff=ab; break
    if coeff is None: coeff=DW[key][-1][1]
    a,b=coeff; return a-(b*logS)
def siri_pctfat(d): return round(((4.95/d)-4.50)*100,1)
def macros(kcal, pct_prot, pct_fat, pct_cho, w, pct_cho_complex=85, fat_split=(10,35,55)):
    kcal=max(0,int(kcal or 0))
    total=max(1,int(pct_prot)+int(pct_fat)+int(pct_cho))
    pct_prot=round(100*int(pct_prot)/total); pct_fat=round(100*int(pct_fat)/total); pct_cho=100-pct_prot-pct_fat
    g_prot=round((kcal*pct_prot/100)/4,1); g_fat=round((kcal*pct_fat/100)/9,1); g_cho=round((kcal*pct_cho/100)/4,1)
    gkg_prot=round(g_prot/(w or 1),2); gkg_cho=round(g_cho/(w or 1),2)
    g_cho_c=round(g_cho*(pct_cho_complex or 0)/100,1); g_cho_s=round(g_cho-g_cho_c,1)
    sat,poli,mono=fat_split; subtotal=max(1,int(sat)+int(poli)+int(mono))
    sat=pct_fat*int(sat)/subtotal; poli=pct_fat*int(poli)/subtotal; mono=pct_fat-sat-poli
    g_sat=round((kcal*sat/100)/9,1); g_poli=round((kcal*poli/100)/9,1); g_mono=round((kcal*mono/100)/9,1)
    return {"pct":{"prot":pct_prot,"fat":pct_fat,"cho":pct_cho},
            "g":{"prot":g_prot,"fat":g_fat,"cho":g_cho,"cho_c":g_cho_c,"cho_s":g_cho_s,"sat":g_sat,"poli":g_poli,"mono":g_mono},
            "gkg":{"prot":gkg_prot,"cho":gkg_cho}}
def exchanges_from_kcal(k):
    if not k or k<=0: return {g:0 for g in EXCHANGES}
    f=max(1.0, min(2.4, k/2000))
    base={"Vegetales":4,"Frutas":2,"Cereales":5,"Leguminosas":1,"Lácteos descremados":1,"Proteínas magras":4,"Grasas saludables":4}
    return {g:int(round(v*f)) for g,v in base.items()}
def distribute_by_meal(d):
    split={"Desayuno":0.25,"Merienda AM":0.10,"Almuerzo":0.30,"Merienda PM":0.10,"Cena":0.25}
    out={m:{} for m in split}
    for g,tot in d.items():
        for m,fr in split.items(): out[m][g]=round(tot*fr,1)
    return out

# ---------- Sidebar (reactivo en vivo; valores iniciales cómodos) ----------
with st.sidebar:
    st.subheader("Paciente")
    modo = st.selectbox("Modo", ["Ambulatorio (recomendado)"])
    nombre = st.text_input("Nombre y apellido", "")
    sexo = st.selectbox("Sexo biológico", ["Femenino","Masculino"])
    edad = st.number_input("Edad (años)", 1, 120, 30, step=1)
    talla_cm = st.number_input("Talla (cm)", 120, 230, 165)
    peso = st.number_input("Peso (kg)", 30.0, 300.0, 70.0, step=0.1)

    st.caption("Ecuación y PAL")
    eq = st.selectbox("Ecuación de MB", ["Mifflin–St Jeor","Harris–Benedict"])
    pal_key = st.selectbox("PAL (actividad)", list(PAL.keys()), index=2)  # Moderado por defecto
    ade_on = st.checkbox("Añadir ADE/TEF (~10%)", value=False)
    objetivo = st.selectbox("Objetivo", ["Pérdida de peso","Mantenimiento","Ganancia (magro)"], index=1)

    with st.expander("Antropometría (opcional)"):
        cintura = st.number_input("Cintura (cm)", 0.0, 300.0, 0.0, step=0.1)
        cadera  = st.number_input("Cadera (cm)", 0.0, 300.0, 0.0, step=0.1)
        muac    = st.number_input("CB/MUAC (cm)", 0.0, 80.0, 0.0, step=0.1)
        p_bi = st.number_input("Bíceps (mm)", 0.0, 60.0, 0.0, step=0.5)
        p_tri = st.number_input("Tríceps (mm)", 0.0, 60.0, 0.0, step=0.5)
        p_sub = st.number_input("Subescapular (mm)", 0.0, 60.0, 0.0, step=0.5)
        p_sup = st.number_input("Suprailiaco (mm)", 0.0, 60.0, 0.0, step=0.5)
        bia_fat = st.number_input("% Grasa (BIA)", 0.0, 70.0, 0.0, step=0.1)

    with st.expander("Laboratorios (opcional)"):
        glicemia = st.number_input("Glucosa (mg/dL)", 0.0, 800.0, 0.0, step=0.1)
        insulina = st.number_input("Insulina (µUI/mL)", 0.0, 1000.0, 0.0, step=0.1)
        hba1c = st.number_input("HbA1c (%)", 0.0, 20.0, 0.0, step=0.1)
        tc  = st.number_input("Colesterol total (mg/dL)", 0.0, 500.0, 0.0, step=0.1)
        hdl = st.number_input("HDL (mg/dL)", 0.0, 200.0, 0.0, step=0.1)
        ldl = st.number_input("LDL (mg/dL)", 0.0, 300.0, 0.0, step=0.1)
        tg  = st.number_input("Triglicéridos (mg/dL)", 0.0, 1000.0, 0.0, step=0.1)

# ---------- Cálculos en vivo ----------
mb = mifflin(sexo, peso, talla_cm, edad) if eq.startswith("Mifflin") else harris_benedict(sexo, peso, talla_cm, edad)
tee = tee_ambulatorio(mb, PAL[pal_key], ade_on)
kcal = kcal_target(tee, objetivo)

imc = bmi(peso, talla_cm)
icc = whr(cintura, cadera)
ict = whtr(cintura, talla_cm)
pct_grasa_dw=None
if sum([p_bi, p_tri, p_sub, p_sup])>0:
    dens = dw_density(sexo, edad, p_bi, p_tri, p_sub, p_sup)
    pct_grasa_dw = siri_pctfat(dens)

# ---------- Requerimientos (reactivos) ----------
st.header("Requerimientos nutricionales")
use_preset = st.checkbox("Preset rápido (Prot 20%, Grasas 30%, CHO 50%)", value=True)
if use_preset:
    pct_prot, pct_fat, sat, poli, mono, pct_cho_complex = 20, 30, 10, 35, 55, 85
else:
    c1, c2 = st.columns(2)
    with c1:
        pct_prot = st.slider("Proteínas (%)", 10, 35, 20)
        pct_fat  = st.slider("Grasas totales (%)", 20, 40, 30)
    with c2:
        sat = st.slider("De la grasa total → Saturadas (%)", 0, 15, 10)
        poli = st.slider("De la grasa total → Poliinsat. (%)", 5, 60, 35)
        mono = max(0, 100 - sat - poli)
        pct_cho_complex = st.slider("Dentro de CHO → Complejos (%)", 45, 100, 85)

pct_cho = 100 - pct_prot - pct_fat
st.info(f"CHO (%) se ajusta a: **{pct_cho}%** · Monoinsat. (%) se ajusta a: **{max(0,100-sat-poli)}%**")

mac = macros(kcal, pct_prot, pct_fat, pct_cho, peso, pct_cho_complex, fat_split=(sat, poli, max(0,100-sat-poli)))

# ---------- KPIs ----------
st.header("Resultados clínicos")
k = st.columns(3)
k[0].markdown(f"<div class='card'><div class='kpi'>IMC: {imc} kg/m²</div><div>OMS: {'Bajo peso' if imc and imc<18.5 else 'Normopeso' if imc and imc<25 else 'Sobrepeso' if imc and imc<30 else 'Obesidad I' if imc and imc<35 else 'Obesidad II' if imc and imc<40 else 'Obesidad III'}</div></div>", unsafe_allow_html=True)
k[1].markdown(f"<div class='card'><div class='kpi'>MB: {round(mb)} kcal</div><div>TEE (MB×PAL{' + ADE' if ade_on else ''}): {tee} kcal</div></div>", unsafe_allow_html=True)
k[2].markdown(f"<div class='card'><div class='kpi'>Meta calórica: {kcal} kcal</div><div>Proteína: {mac['g']['prot']} g ({mac['gkg']['prot']} g/kg)</div></div>", unsafe_allow_html=True)

k2 = st.columns(3)
k2[0].markdown(f"<div class='card'><div class='kpi'>ICC: {icc if icc is not None else '—'}</div><div>Riesgo ↑ si >0.85 (F) / >0.90 (M)</div></div>", unsafe_allow_html=True)
k2[1].markdown(f"<div class='card'><div class='kpi'>ICT: {ict if ict is not None else '—'}</div><div>Riesgo ↑ si ≥0.5</div></div>", unsafe_allow_html=True)
bf=[]
if pct_grasa_dw is not None: bf.append(f"{pct_grasa_dw}% (pliegues)")
if bia_fat>0: bf.append(f"{bia_fat}% (BIA)")
k2[2].markdown(f"<div class='card'><div class='kpi'>% Grasa: {' · '.join(bf) if bf else '—'}</div><div>Durnin–Womersley + Siri / BIA</div></div>", unsafe_allow_html=True)

# ---------- Intercambios ----------
st.header("Plan por Intercambios")
diario = exchanges_from_kcal(kcal); por_comida = distribute_by_meal(diario)
df_plan = pd.DataFrame({
    "Grupo": list(diario.keys()),
    "Raciones/día": list(diario.values()),
    "kcal/rac": [EXCHANGES[g]["kcal"] for g in diario.keys()],
    "CHO": [EXCHANGES[g]["CHO"] for g in diario.keys()],
    "PRO": [EXCHANGES[g]["PRO"] for g in diario.keys()],
    "FAT": [EXCHANGES[g]["FAT"] for g in diario.keys()],
    "Porción": [EXCHANGES[g]["portion"] for g in diario.keys()]
})
st.dataframe(df_plan, use_container_width=True, height=320)
st.dataframe(pd.DataFrame([{"Tiempo":m, **gr} for m,gr in por_comida.items()]), use_container_width=True, height=300)

# ---------- Exportar PLAN (DOCX) ----------
if DOCX:
    doc = Document(); stl=doc.styles["Normal"]; stl.font.name="Calibri"; stl.font.size=Pt(11)
    doc.add_heading("Plan de alimentación – " + BRAND, 0)
    doc.add_paragraph(f"Paciente: {nombre or '—'}  |  Fecha: {date.today().isoformat()}")
    doc.add_paragraph(f"MB: {round(mb)} kcal  |  TEE: {tee} kcal  |  Meta: {kcal} kcal")
    t=doc.add_table(rows=1, cols=7)
    for i,h in enumerate(["Lista","Raciones","kcal","CHO","PRO","FAT","Porción"]): t.rows[0].cells[i].text=h
    for g,r in diario.items():
        row=t.add_row().cells
        row[0].text=g; row[1].text=str(r); row[2].text=str(EXCHANGES[g]["kcal"])
        row[3].text=str(EXCHANGES[g]["CHO"]); row[4].text=str(EXCHANGES[g]["PRO"])
        row[5].text=str(EXCHANGES[g]["FAT"]); row[6].text=EXCHANGES[g]["portion"]
    bio=BytesIO(); doc.save(bio); bio.seek(0)
    st.download_button("⬇️ Descargar PLAN (DOCX)", data=bio,
        file_name="plan_nutritionsays.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

st.caption("Herramienta de apoyo clínico para profesionales. Ajustar a guías y juicio clínico. © " + BRAND)
