# app.py — @nutritionsays · Gestión Nutricional Clínica (UCV)
# Añadido: Harris–Benedict, FA (actividad), FE (estrés), FD (desnutrición), ADE/TEF (10%),
# método directo 25–35 kcal/kg, kcal/kg por peso de referencia (actual/ideal/ajustado).

from datetime import date
from io import BytesIO
import json, math

import streamlit as st
import pandas as pd

# DOCX opcional
try:
    from docx import Document
    from docx.shared import Pt
    DOCX = True
except Exception:
    DOCX = False

BRAND = "@nutritionsays"
st.set_page_config(page_title=f"{BRAND} · Gestión Nutricional", page_icon="🍎", layout="centered")

# ===================== ESTILO =====================
st.markdown("""
<style>
.stApp, .block-container { background:#ffffff !important; color:#111 !important; }
h1,h2,h3,h4,h5, p, span, label, div, li, th, td { color:#111 !important; }
/* Sidebar oscuro morado (legible) */
section[data-testid="stSidebar"] { background:#1e1e2a !important; border-right:1px solid #141421; }
section[data-testid="stSidebar"] * { color:#f5f6fb !important; }
section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stMarkdown p { color:#e6def7 !important; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] textarea {
  color:#ffffff !important; background:#111223 !important; border:1px solid #3b3b57 !important;
}
section[data-testid="stSidebar"] input::placeholder, section[data-testid="stSidebar"] textarea::placeholder { color:#cbd0ff !important; opacity:.85; }
[data-baseweb="select"] * { color:inherit !important; }
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

# ===================== Intercambios =====================
EXCHANGES = {
    "Vegetales": {"kcal":25,"CHO":5,"PRO":2,"FAT":0,"portion":"1 taza crudas / 1/2 taza cocidas"},
    "Frutas": {"kcal":60,"CHO":15,"PRO":0,"FAT":0,"portion":"1 unid pequeña / 1/2 taza picada"},
    "Cereales": {"kcal":80,"CHO":15,"PRO":2,"FAT":1,"portion":"1/2 taza cocidos / 1 rebanada pan"},
    "Leguminosas": {"kcal":100,"CHO":18,"PRO":7,"FAT":1,"portion":"1/2 taza cocidas"},
    "Lácteos descremados": {"kcal":90,"CHO":12,"PRO":8,"FAT":2,"portion":"1 taza leche / yogurt natural"},
    "Proteínas magras": {"kcal":110,"CHO":0,"PRO":21,"FAT":3,"portion":"30 g cocidos"},
    "Grasas saludables": {"kcal":45,"CHO":0,"PRO":0,"FAT":5,"portion":"1 cdita (5 g)"}
}

# ===================== Utilidades =====================
ACTIVITY = {"VM/Conectado":1.1,"Reposo en cama":1.2,"Deambula (ligera)":1.3,"Ligera (1–3 d/sem)":1.375,"Moderada (3–5 d/sem)":1.55,"Alta (6–7 d/sem)":1.725}
STRESS = {  # FE de tu hoja
    "Infección leve-moderada/sepsis":1.3, "Cirugía menor":1.1, "Cirugía mayor":1.2,
    "Trauma huesos largos":1.25, "Politrauma":1.45, "TCE":1.6, "Neurocrítico/ACV":1.15,
    "Quemados (<40% SCQ)":1.4, "Quemados (≥40% SCQ)":1.8, "EII activa":1.35,
    "Cáncer/Neumonía":1.2, "Postoperatorio cáncer":1.25, "Cáncer avanzado agresivo":1.4,
    "Desnutrición moderada o grave":1.0  # se maneja con FD, aquí neutro
}
MALNUT = {"Sin FD":1.0, "Aplicar FD por desnutrición (0.7)":0.7}  # FD de tu nota
def mifflin(sex, w, h_cm, age): return 10*w + 6.25*h_cm - 5*age + (5 if sex.lower().startswith("m") else -161)
def harris_benedict(sex, w, h_cm, age):
    if sex.lower().startswith("m"): return 66.47 + (13.75*w) + (5.003*h_cm) - (6.755*age)
    return 655.09 + (9.563*w) + (1.850*h_cm) - (4.676*age)

def tee_from_factors(mb, ade_on, fa, fe, fd):
    base = mb*(1.1 if ade_on else 1.0)  # ADE/TEF 10%
    return round(base * fa * fe * fd)

def kcal_target(tee, obj): return max(1000, tee - (400 if tee>=1600 else 200)) if obj=="Pérdida de peso" else (tee+200 if obj=="Ganancia (magro)" else tee)
def bmi(w,hcm): h=max(1e-6, hcm/100); return round(w/(h*h),2)
def whr(waist, hip): return round((waist/hip),2) if hip>0 else None
def whtr(waist, hcm): return round((waist/hcm),2) if hcm>0 else None
def homa_ir(gmgdl, ins): 
    if gmgdl>0 and ins>0: return round(((gmgdl/18.0)*ins)/22.5,2)
    return None

# Durnin–Womersley (4 pliegues) + Siri
DW = {
    "F":[(17,(1.1549,0.0678)),(29,(1.1599,0.0717)),(39,(1.1423,0.0632)),(49,(1.1333,0.0612)),(120,(1.1339,0.0645))],
    "M":[(17,(1.1620,0.0630)),(29,(1.1631,0.0632)),(39,(1.1422,0.0544)),(49,(1.1620,0.0700)),(120,(1.1715,0.0779))]
}
def dw_density(sex, age, biceps, triceps, subesc, supra):
    S=max(0.1,biceps+triceps+subesc+supra); logS=math.log10(S)
    key="F" if sex.lower().startswith("f") else "M"; coeff=None
    for up,ab in DW[key]:
        if age<=up: coeff=ab; break
    if coeff is None: coeff=DW[key][-1][1]
    a,b=coeff; return a-(b*logS)
def siri_pctfat(d): return round(((4.95/d)-4.50)*100,1)

def sodium_convert(target_mg, current_mg):
    rem=max(0,target_mg-current_mg); salt_g=round(rem/400.0,2); tsp=round(salt_g/5.0,2)
    return {"remaining_mg":rem,"salt_g":salt_g,"tsp":tsp}

def macros(kcal, pct_prot, pct_fat, pct_cho, w, pct_cho_complex=85, fat_split=(10,35,55)):
    total=max(1,pct_prot+pct_fat+pct_cho)
    pct_prot=round(100*pct_prot/total); pct_fat=round(100*pct_fat/total); pct_cho=100-pct_prot-pct_fat
    g_prot=round((kcal*pct_prot/100)/4,1); g_fat=round((kcal*pct_fat/100)/9,1); g_cho=round((kcal*pct_cho/100)/4,1)
    gkg_prot=round(g_prot/w,2) if w else 0.0; gkg_cho=round(g_cho/w,2) if w else 0.0
    g_cho_c=round(g_cho*pct_cho_complex/100,1); g_cho_s=round(g_cho-g_cho_c,1)
    sat,poli,mono=fat_split; subtotal=max(1,sat+poli+mono)
    sat=pct_fat*sat/subtotal; poli=pct_fat*poli/subtotal; mono=pct_fat-sat-poli
    g_sat=round((kcal*sat/100)/9,1); g_poli=round((kcal*poli/100)/9,1); g_mono=round((kcal*mono/100)/9,1)
    return {"pct":{"prot":pct_prot,"fat":pct_fat,"cho":pct_cho},
            "g":{"prot":g_prot,"fat":g_fat,"cho":g_cho,"cho_c":g_cho_c,"cho_s":g_cho_s,"sat":g_sat,"poli":g_poli,"mono":g_mono},
            "gkg":{"prot":gkg_prot,"cho":gkg_cho}}

def exchanges_from_kcal(k):
    f=max(1.0, min(2.4, k/2000))
    base={"Vegetales":4,"Frutas":2,"Cereales":5,"Leguminosas":1,"Lácteos descremados":1,"Proteínas magras":4,"Grasas saludables":4}
    return {g:int(round(v*f)) for g,v in base.items()}
def distribute_by_meal(d):
    split={"Desayuno":0.25,"Merienda AM":0.10,"Almuerzo":0.30,"Merienda PM":0.10,"Cena":0.25}
    out={m:{} for m in split}
    for g,tot in d.items():
        for m,fr in split.items(): out[m][g]=round(tot*fr,1)
    return out

# Estimaciones adicionales
def ibw_hamwi(sex, height_cm):
    inches_over_5ft = max(0.0, (height_cm - 152.4) / 2.54)
    if sex.lower().startswith("m"):
        return 48.0 + 2.7*inches_over_5ft
    return 45.5 + 2.2*inches_over_5ft

def peso_ajustado_obesidad(actual, ibw): return ibw + 0.25*(actual - ibw)
def ama_area(muac_cm, triceps_mm):
    if muac_cm and triceps_mm:
        tsf_cm = triceps_mm/10.0
        return round(((muac_cm - math.pi*tsf_cm)**2) / (4*math.pi), 2)
    return None

# Labs → badges
def badge(text, level="info"):
    cls = {"ok":"bg-ok","warn":"bg-warn","bad":"bg-bad","info":"bg-info"}.get(level, "bg-info")
    return f"<span class='badge {cls}'>{text}</span>"

def interp_labs(sex, labs):
    out=[]
    g=labs.get("glu",0)
    if g>0: out.append(("Glucosa", g, badge("Baja","warn") if g<70 else badge("Normal","ok") if g<100 else badge("Prediabetes","warn") if g<126 else badge("Diabetes","bad")))
    a1c=labs.get("a1c",0)
    if a1c>0: out.append(("HbA1c", a1c, badge("Normal","ok") if a1c<5.7 else badge("Prediabetes","warn") if a1c<6.5 else badge("Diabetes","bad")))
    if labs.get("homa") is not None: out.append(("HOMA-IR", labs["homa"], badge("Aceptable","ok") if labs["homa"]<2.5 else badge("↑ Resistencia","warn")))
    ldl=labs.get("ldl",0); hdl=labs.get("hdl",0); tg=labs.get("tg",0); tc=labs.get("tc",0)
    if ldl>0: out.append(("LDL", ldl, badge("Deseable","ok") if ldl<100 else badge("Alto","bad")))
    if hdl>0:
        low = 40 if sex.lower().startswith("m") else 50
        out.append(("HDL", hdl, badge("Protector","ok") if hdl>=low else badge("Bajo","bad")))
    if tg>0: out.append(("TG", tg, badge("Normal","ok") if tg<150 else badge("Alto","bad")))
    if tc>0: out.append(("CT", tc, badge("Deseable","ok") if tc<200 else badge("Alto","bad")))
    creat=labs.get("creat",0)
    if creat>0:
        hi=1.3 if sex.lower().startswith("m") else 1.1; lo=0.5
        out.append(("Creatinina", creat, badge("Normal","ok") if lo<=creat<=hi else badge("Alta","bad") if creat>hi else badge("Baja","warn")))
    alt=labs.get("alt",0); ast=labs.get("ast",0)
    if alt>0: out.append(("ALT", alt, badge("Normal","ok") if alt<=40 else badge("Alta","bad")))
    if ast>0: out.append(("AST", ast, badge("Normal","ok") if ast<=40 else badge("Alta","bad")))
    hb=labs.get("hb",0)
    if hb>0:
        lo = 13.5 if sex.lower().startswith("m") else 12.0
        hi = 17.5 if sex.lower().startswith("m") else 16.0
        out.append(("Hemoglobina", hb, badge("Normal","ok") if lo<=hb<=hi else badge("Baja","bad") if hb<lo else badge("Alta","warn")))
    ferr=labs.get("ferr",0)
    if ferr>0:
        lo = 24 if sex.lower().startswith("m") else 12
        hi = 336 if sex.lower().startswith("m") else 150
        out.append(("Ferritina", ferr, badge("Normal","ok") if lo<=ferr<=hi else badge("Baja","bad") if ferr<lo else badge("Alta","warn")))
    vitd=labs.get("vitd",0)
    if vitd>0: out.append(("Vit D", vitd, badge("Deficiencia","bad") if vitd<20 else badge("Insuficiente","warn") if vitd<30 else badge("Suficiente","ok")))
    b12=labs.get("b12",0)
    if b12>0: out.append(("B12", b12, badge("Baja","bad") if b12<200 else badge("Alta","warn") if b12>900 else badge("Normal","ok")))
    tsh=labs.get("tsh",0)
    if tsh>0: out.append(("TSH", tsh, badge("Normal","ok") if 0.4<=tsh<=4.0 else badge("Alterada","warn")))
    urea=labs.get("urea",0)
    if urea>0: out.append(("Urea", urea, badge("Normal","ok") if 15<=urea<=45 else badge("Alterada","warn")))
    crp=labs.get("crp",0)
    if crp>0: out.append(("PCR", crp, badge("Aceptable","ok") if crp<=5 else badge("Alta","bad")))
    return out

# ===================== SIDEBAR =====================
with st.sidebar:
    with st.form("cap"):
        st.subheader("Paciente")
        nombre = st.text_input("Nombre y apellido")
        sexo = st.selectbox("Sexo biológico", ["Femenino","Masculino"])
        edad = st.number_input("Edad (años)", 1, 120, 30)
        talla_cm = st.number_input("Talla (cm)", 100, 230, 165)
        peso = st.number_input("Peso (kg)", 30.0, 300.0, 75.0, step=0.1)

        st.caption("Ecuación y factores energéticos")
        eq = st.selectbox("Ecuación de MB", ["Mifflin–St Jeor","Harris–Benedict"])
        ade_on = st.checkbox("Incluir ADE / efecto térmico (~10%)", value=True)
        fa = st.selectbox("FA (actividad)", list(ACTIVITY.keys()), index=2)
        fe = st.selectbox("FE (estrés/enfermedad)", list(STRESS.keys()), index=0)
        fd = st.selectbox("FD (desnutrición)", list(MALNUT.keys()), index=0)

        objetivo = st.selectbox("Objetivo", ["Pérdida de peso","Mantenimiento","Ganancia (magro)"], index=0)

        with st.expander("Antropometría", expanded=True):
            peso_usual = st.number_input("Peso usual (kg)", 0.0, 400.0, 0.0, step=0.1)
            cintura = st.number_input("Cintura (cm)", 0.0, 300.0, 0.0, step=0.1)
            cadera  = st.number_input("Cadera (cm)", 0.0, 300.0, 0.0, step=0.1)
            muac    = st.number_input("CB/MUAC (cm)", 0.0, 80.0, 0.0, step=0.1)
            st.caption("Pliegues (mm) — Durnin–Womersley")
            p_bi = st.number_input("Bíceps (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_tri = st.number_input("Tríceps (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_sub = st.number_input("Subescapular (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_sup = st.number_input("Suprailiaco (mm)", 0.0, 60.0, 0.0, step=0.5)
            bia_fat = st.number_input("% Grasa (BIA)", 0.0, 70.0, 0.0, step=0.1)

        with st.expander("Laboratorios", expanded=True):
            glicemia = st.number_input("Glucosa (mg/dL)", 0.0, 800.0, 0.0, step=0.1)
            insulina = st.number_input("Insulina (µUI/mL)", 0.0, 1000.0, 0.0, step=0.1)
            hba1c = st.number_input("HbA1c (%)", 0.0, 20.0, 0.0, step=0.1)
            tc  = st.number_input("Colesterol total (mg/dL)", 0.0, 500.0, 0.0, step=0.1)
            hdl = st.number_input("HDL (mg/dL)", 0.0, 200.0, 0.0, step=0.1)
            ldl = st.number_input("LDL (mg/dL)", 0.0, 300.0, 0.0, step=0.1)
            tg  = st.number_input("Triglicéridos (mg/dL)", 0.0, 1000.0, 0.0, step=0.1)
            creat = st.number_input("Creatinina (mg/dL)", 0.0, 20.0, 0.0, step=0.01)
            urea   = st.number_input("Urea (mg/dL)", 0.0, 300.0, 0.0, step=0.1)
            alt = st.number_input("ALT (U/L)", 0.0, 2000.0, 0.0, step=0.1)
            ast = st.number_input("AST (U/L)", 0.0, 2000.0, 0.0, step=0.1)
            hb  = st.number_input("Hemoglobina (g/dL)", 0.0, 25.0, 0.0, step=0.1)
            ferr = st.number_input("Ferritina (ng/mL)", 0.0, 2000.0, 0.0, step=0.1)
            vitd = st.number_input("Vitamina D 25-OH (ng/mL)", 0.0, 200.0, 0.0, step=0.1)
            b12 = st.number_input("Vitamina B12 (pg/mL)", 0.0, 5000.0, 0.0, step=1.0)
            fol = st.number_input("Folato (ng/mL)", 0.0, 50.0, 0.0, step=0.1)
            tsh = st.number_input("TSH (µUI/mL)", 0.0, 150.0, 0.0, step=0.01)
            crp = st.number_input("PCR/CRP (mg/L)", 0.0, 500.0, 0.0, step=0.1)

        submitted = st.form_submit_button("Aplicar cambios")

# ===================== Cálculos base =====================
imc = bmi(peso, talla_cm)
icc = whr(cintura, cadera) if cadera>0 else None
ict = whtr(cintura, talla_cm) if talla_cm>0 else None
homa = homa_ir(glicemia, insulina)

pct_grasa_dw = None
if (p_bi+p_tri+p_sub+p_sup)>0:
    dens = dw_density(sexo, edad, p_bi, p_tri, p_sub, p_sup)
    pct_grasa_dw = siri_pctfat(dens)

# MB por ecuación
mb = mifflin(sexo, peso, talla_cm, edad) if eq.startswith("Mifflin") else harris_benedict(sexo, peso, talla_cm, edad)
# TEE con factores (tu hoja): RCT = MB x FA x FE x FD (con ADE 10% si aplica)
tee = tee_from_factors(mb, ade_on, ACTIVITY[fa], STRESS[fe], MALNUT[fd])
kcal = kcal_target(tee, objetivo)

# IBW / PAJ
ibw = ibw_hamwi(sexo, talla_cm)
pari = 100*(peso/ibw) if ibw>0 else 0
paj = peso_ajustado_obesidad(peso, ibw) if (imc>=30 or pari>=120) else None

# ===================== Requerimientos y macros =====================
st.header("Requerimientos nutricionales")
preset = st.checkbox("Usar preset de tu hoja (Prote 25% · Grasas 30% {7/10/13} · CHO compl 45%)", value=False)
if preset:
    pct_prot, pct_fat, sat, poli, mono, pct_cho_complex = 25, 30, 7, 10, 13, 45
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

# Método directo (25–35 kcal/kg) y kcal/kg de referencia
st.subheader("Método directo y kcal/kg")
ref_weight_choice = st.selectbox("Peso de referencia para kcal/kg", ["Peso actual","Peso ideal (Hamwi)","Peso ajustado (si aplica)"])
ref_w = peso if ref_weight_choice=="Peso actual" else (ibw if ref_weight_choice.startswith("Peso ideal") else (paj if paj else peso))
direct_rows = []
for kk in [25,26,27,28,29,30,35]:
    direct_rows.append({"kcal/kg":kk,"Total kcal/d": round(kk*ref_w)})
st.table(pd.DataFrame(direct_rows))

pp1, pp2, pp3 = st.columns(3)
with pp1: comidas = st.slider("Nº de comidas (3–7)", 3, 7, 5)
with pp2:
    default_gkg = float(mac["gkg"]["prot"]) if mac["gkg"]["prot"] else 1.2
    prot_gkg_obj = st.number_input("Proteína objetivo (g/kg)", min_value=0.8, max_value=3.0, value=float(max(0.8,min(3.0,default_gkg))), step=0.1)
with pp3:
    agua_l = st.number_input("Agua (L/día)", min_value=0.5, max_value=5.0, value=round(max(1.5,min(3.5,peso*0.03)),2), step=0.1)

# ===================== KPIs =====================
st.header("Resultados clínicos")
k = st.columns(3)
k[0].markdown(f"<div class='card'><div class='kpi'>IMC: {imc} kg/m²</div><div>OMS: {'Bajo peso' if imc<18.5 else 'Normopeso' if imc<25 else 'Sobrepeso' if imc<30 else 'Obesidad I' if imc<35 else 'Obesidad II' if imc<40 else 'Obesidad III'}</div></div>", unsafe_allow_html=True)
k[1].markdown(f"<div class='card'><div class='kpi'>MB ({eq.split('–')[0]}): {round(mb)} kcal</div><div>TEE (FA·FE·FD{'+ADE' if ade_on else ''}): {tee} kcal</div></div>", unsafe_allow_html=True)
k[2].markdown(f"<div class='card'><div class='kpi'>Meta calórica: {kcal} kcal</div><div>kcal/kg ref.: {round(kcal/ref_w,2)} kcal/kg</div></div>", unsafe_allow_html=True)

k2 = st.columns(3)
if icc is not None: k2[0].markdown(f"<div class='card'><div class='kpi'>ICC: {icc}</div><div>Riesgo ↑ si >0.85 (F) / >0.90 (M)</div></div>", unsafe_allow_html=True)
if ict is not None: k2[1].markdown(f"<div class='card'><div class='kpi'>ICT: {ict}</div><div>Riesgo ↑ si ≥0.5 (adultos)</div></div>", unsafe_allow_html=True)
bf=[]
if pct_grasa_dw is not None: bf.append(f"{pct_grasa_dw}% (pliegues)")
if bia_fat>0: bf.append(f"{bia_fat}% (BIA)")
k2[2].markdown(f"<div class='card'><div class='kpi'>% Grasa: {' · '.join(bf) if bf else '—'}</div><div>Durnin–Womersley + Siri / BIA</div></div>", unsafe_allow_html=True)

# IBW / PAJ / AMA
est_cols = st.columns(3)
est_cols[0].markdown(f"<div class='card'><div class='kpi'>IBW Hamwi: {round(ibw,1)} kg</div><div>PARI: {round(pari,1)}%</div></div>", unsafe_allow_html=True)
est_cols[1].markdown(f"<div class='card'><div class='kpi'>Peso ajustado: {round(paj,1) if paj else '—'} kg</div><div>Aplica si IMC≥30 o PARI≥120%</div></div>", unsafe_allow_html=True)
ama = ama_area(muac, p_tri)
est_cols[2].markdown(f"<div class='card'><div class='kpi'>AMA: {ama if ama is not None else '—'} cm²</div><div>MUAC & pliegue tríceps</div></div>", unsafe_allow_html=True)

# ===================== Interpretación de laboratorios =====================
st.header("Laboratorios – interpretación")
lab_int = interp_labs(sexo, {"glu":glicemia,"a1c":hba1c,"homa":homa,"ldl":ldl,"hdl":hdl,"tg":tg,"tc":tc,
                              "creat":creat,"alt":alt,"ast":ast,"hb":hb,"ferr":ferr,"vitd":vitd,"b12":b12,"tsh":tsh,"urea":urea,"crp":crp})
if lab_int:
    for name, val, flag in lab_int:
        st.markdown(f"- **{name}: {val}**  {flag}", unsafe_allow_html=True)
else:
    st.info("Ingrese valores para ver interpretación y rangos.")

# ===================== Sodio =====================
st.header("Sodio")
cna1, cna2, cna3 = st.columns(3)
with cna1: na_obj = st.number_input("Objetivo (mg Na/día)", 500, 5000, 2300, step=50)
with cna2: na_cons = st.number_input("Consumido (mg Na/día)", 0, 5000, 900, step=10)
na_calc = sodium_convert(na_obj, na_cons)
with cna3: st.metric("Na remanente (mg)", na_calc["remaining_mg"])
st.caption(f"≈ {na_calc['salt_g']} g NaCl ( {na_calc['tsp']} cdtas ) · 400 mg Na ≈ 1 g NaCl · 1 cdta ≈ 5 g")

# ===================== Intercambios =====================
st.header("Plan por Intercambios")
diario = exchanges_from_kcal(kcal)
por_comida = distribute_by_meal(diario)
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

# ===================== ADIME & exportes =====================
st.header("ADIME")
motivo = st.text_area("Motivo / Resumen")
dx_pes = st.text_area("Diagnóstico(s) PES (NCPT)", placeholder="Problema relacionado con ... evidenciado por ...")
presc = st.text_area("Prescripción Dietética", placeholder="Plan por intercambios individualizado + educación nutricional.")
me = st.text_area("Monitoreo/Evaluación", value="Control 2–4 semanas; peso, cintura, adherencia; labs según caso.")

def _table_dist(doc, por_comida, diario):
    cols=["Lista","Desayuno","Merienda AM","Almuerzo","Merienda PM","Cena","Total"]
    t=doc.add_table(rows=1, cols=len(cols))
    for i,h in enumerate(cols): t.rows[0].cells[i].text=h
    for g in diario.keys():
        row=t.add_row().cells; row[0].text=g; tot=0
        for j,m in enumerate(["Desayuno","Merienda AM","Almuerzo","Merienda PM","Cena"], start=1):
            val=por_comida[m].get(g,0); row[j].text=str(val); tot += float(val)
        row[-1].text=str(round(tot,1))
    return t

def _menu_demo(por_comida):
    opciones={
        "Cereales": ["arepa mediana","arroz 1 ½ tz","pasta 1 ½ tz","pan 2–3 rebanadas"],
        "Proteínas magras": ["pollo/pescado 1 trozo","carne magra 1 trozo","huevo 2 unid","atún ½ lata"],
        "Vegetales": ["ensalada cruda mixta","crema de vegetales","salteado brócoli/zanahoria"],
        "Frutas": ["manzana/mandarina/lechoza","cambur ½ unid","melón/fresas 1 tz"],
        "Lácteos descremados": ["leche 1 tz","yogurt natural ¾ tz"],
        "Grasas saludables": ["aguacate","aceite 1 cdita","semillas 1 cda"]
    }
    out={}
    for m in ["Desayuno","Merienda AM","Almuerzo","Merienda PM","Cena"]:
        a=[]; b=[]
        for g,r in por_comida[m].items():
            if r and g in opciones:
                a.append(opciones[g][0]); 
                if len(opciones[g])>1: b.append(opciones[g][1])
        out[m]={"Día 1":"; ".join(a) or "—","Día 2":"; ".join(b) or "—"}
    return out

def build_docx_plan(payload, diario, por_comida):
    if not DOCX: return None
    doc=Document(); stl=doc.styles["Normal"]; stl.font.name="Calibri"; stl.font.size=Pt(11)
    doc.add_heading("Plan de alimentación y recomendaciones nutricionales", 0)
    doc.add_paragraph(payload["paciente"]).runs[0].bold=True
    doc.add_heading("Diagnóstico nutricional", 1); doc.add_paragraph(payload["diag"] or "—")
    doc.add_heading("Datos energéticos", 1)
    t=doc.add_table(rows=0, cols=2)
    for k,v in [("MB/TEE/Meta", f"{payload['mb']} / {payload['tee']} / {payload['kcal']} kcal"),
                ("kcal/kg ref.", f"{payload['kcalkg']} kcal/kg ({payload['refw']} kg)")]:
        row=t.add_row().cells; row[0].text=k; row[1].text=str(v)
    doc.add_heading("Listas de intercambios – totales",1)
    tb=doc.add_table(rows=1, cols=7)
    for i,h in enumerate(["Lista","Raciones","kcal","CHO","PRO","FAT","Porción"]): tb.rows[0].cells[i].text=h
    for g,r in diario.items():
        row=tb.add_row().cells
        row[0].text=g; row[1].text=str(r)
        row[2].text=str(EXCHANGES[g]["kcal"]); row[3].text=str(EXCHANGES[g]["CHO"])
        row[4].text=str(EXCHANGES[g]["PRO"]); row[5].text=str(EXCHANGES[g]["FAT"]); row[6].text=EXCHANGES[g]["portion"]
    doc.add_heading("Distribución por tiempos de comida",1); _table_dist(doc, por_comida, diario)
    demo=_menu_demo(por_comida)
    doc.add_heading("Menú ejemplo (2 días)",1)
    for m in ["Desayuno","Merienda AM","Almuerzo","Merienda PM","Cena"]:
        p=doc.add_paragraph(); p.add_run(m).bold=True
        doc.add_paragraph(f"Día 1: {demo[m]['Día 1']}"); doc.add_paragraph(f"Día 2: {demo[m]['Día 2']}")
    doc.add_paragraph(BRAND).runs[0].bold=True
    bio=BytesIO(); doc.save(bio); bio.seek(0); return bio

def build_docx_adime(payload):
    if not DOCX: return None
    doc=Document(); stl=doc.styles["Normal"]; stl.font.name="Calibri"; stl.font.size=Pt(11)
    doc.add_heading("HISTORIA CLÍNICA NUTRICIONAL – Nota ADIME",1)
    doc.add_paragraph(f"Fecha: {payload['fecha']}   Profesional: {BRAND}   Paciente: {payload['paciente']}")
    doc.add_heading("Evaluación (A)",2); 
    for line in payload["A"]: doc.add_paragraph(line)
    doc.add_heading("Diagnóstico (D)",2)
    if payload["D"]: 
        for pes in payload["D"]: doc.add_paragraph("• "+pes)
    else: doc.add_paragraph("—")
    doc.add_heading("Intervención (I)",2); doc.add_paragraph(payload["I"])
    doc.add_heading("Monitoreo/Evaluación (ME)",2); doc.add_paragraph(payload["ME"])
    m=payload["macros"]; doc.add_heading("Requerimientos",2)
    doc.add_paragraph(f"Energía: {payload['kcal']} kcal/d  ({payload['kcal_kg']} kcal/kg)")
    doc.add_paragraph(f"Proteínas: {m['pct']['prot']}% → {m['g']['prot']} g ({payload['gkg_prot']} g/kg)")
    doc.add_paragraph(f"Grasas: {m['pct']['fat']}% → {m['g']['fat']} g (Sat {m['g']['sat']} g, Poli {m['g']['poli']} g, Mono {m['g']['mono']} g)")
    doc.add_paragraph(f"CHO: {m['pct']['cho']}% → {m['g']['cho']} g (Compl {m['g']['cho_c']} g / Simp {m['g']['cho_s']} g)")
    s=payload["sodium"]; doc.add_paragraph(f"Sodio objetivo: {s['target_mg']} mg; Consumido: {s['current_mg']} mg; Remanente: {s['remaining_mg']} mg  ≈  {s['salt_g']} g NaCl ( {s['tsp']} cdtas )")
    bio=BytesIO(); doc.save(bio); bio.seek(0); return bio

def fhir_order(payload):
    return {"resourceType":"NutritionOrder","status":"active","intent":"order","dateTime": payload["fecha"],
            "patient":{"display": payload["paciente"]},"orderer":{"display": BRAND},
            "oralDiet":{"type":[{"text":"Personalizada"}],
                "nutrient":[{"modifier":{"text":"Energy"},"amount":{"value": payload["kcal"],"unit":"kcal/d"}},
                            {"modifier":{"text":"Protein"},"amount":{"value": payload["macros"]["g"]["prot"],"unit":"g/d"}},
                            {"modifier":{"text":"Fat"},"amount":{"value": payload["macros"]["g"]["fat"],"unit":"g/d"}},
                            {"modifier":{"text":"Carbohydrate"},"amount":{"value": payload["macros"]["g"]["cho"],"unit":"g/d"}}]}}

def fhir_intake(payload):
    return {"resourceType":"NutritionIntake","status":"completed","occurrenceDateTime": payload["fecha"],
            "subject":{"display": payload["paciente"]},
            "consumedItem":[{"type":{"text":"Plan prescrito"},
                             "nutrient":[{"item":{"text":"Protein"},"amount":{"value": payload["macros"]["g"]["prot"],"unit":"g"}},
                                         {"item":{"text":"Fat"},"amount":{"value": payload["macros"]["g"]["fat"],"unit":"g"}},
                                         {"item":{"text":"Carbohydrate"},"amount":{"value": payload["macros"]["g"]["cho"],"unit":"g"}}],
                             "amount":{"value": payload["kcal"], "unit":"kcal"}}]}

# Descargas
st.markdown("---")
tipo = st.radio("Documento a generar", ["Plan de alimentación (@nutritionsays)","Nota ADIME"], index=0, horizontal=True)

common = {"fecha": date.today().isoformat(), "paciente": nombre or "—",
          "kcal": kcal, "kcal_kg": round(kcal/(ref_w or 1),2),
          "gkg_prot": mac["gkg"]["prot"], "macros": mac,
          "sodium": {"target_mg": na_obj if 'na_obj' in locals() else 2300,
                     "current_mg": na_cons if 'na_cons' in locals() else 900,
                     **sodium_convert(na_obj if 'na_obj' in locals() else 2300, na_cons if 'na_cons' in locals() else 900)}}

if tipo=="Plan de alimentación (@nutritionsays)":
    plan = build_docx_plan({
        "paciente": nombre or "—", "mb": round(mb), "tee": tee, "kcal": kcal,
        "kcalkg": round(kcal/(ref_w or 1),2), "refw": round(ref_w,1),
        "diag": dx_pes
    }, diario, por_comida)
    if DOCX:
        st.download_button("⬇️ Descargar PLAN (DOCX editable)", data=plan,
            file_name="plan_nutritionsays.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    else:
        st.info("Instala 'python-docx' y 'lxml' para exportar DOCX.")
else:
    adime = build_docx_adime({
        **common,
        "A":[f"MB {round(mb)} kcal; TEE {tee} kcal (FA {ACTIVITY[fa]} · FE {STRESS[fe]} · FD {MALNUT[fd]} {'+ ADE 10%' if ade_on else ''}).",
             f"Meta {kcal} kcal; kcal/kg ref. {round(kcal/(ref_w or 1),2)}.",
             f"IMC {imc} kg/m²; ICC {icc if icc is not None else '—'}; ICT {ict if ict is not None else '—'};",
             f"%Grasa: {(str(pct_grasa_dw)+'% (pliegues)') if pct_grasa_dw is not None else '—'} {'· '+str(bia_fat)+'% (BIA)' if bia_fat>0 else ''}.",
             "Labs: " + " · ".join([s for s in [
                f"Glucosa {glicemia} mg/dL" if glicemia>0 else None,
                f"HbA1c {hba1c}%" if hba1c>0 else None,
                f"HOMA-IR {homa}" if homa is not None else None] if s])],
        "D":[p.strip() for p in (dx_pes or "").split("\n") if p.strip()],
        "I": presc or "Plan por intercambios + educación.",
        "ME": me or "Control 2–4 semanas."
    })
    if DOCX:
        st.download_button("⬇️ Descargar ADIME (DOCX)", data=adime,
            file_name="adime_nutritionsays.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    else:
        st.info("Instala 'python-docx' y 'lxml' para exportar DOCX.")

st.caption("Herramienta de apoyo clínico para profesionales. Ajustar a juicio clínico y guías locales. © " + BRAND)
