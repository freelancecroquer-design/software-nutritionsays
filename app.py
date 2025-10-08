# app.py — @nutritionsays · Gestión Nutricional Clínica (UCV)
# Forzado de tema claro (alto contraste) + captura clínica completa + exportes

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

# ========== FIX VISUAL (tema claro y texto oscuro forzado) ==========
st.markdown("""
<style>
/* Forzar tema claro y colores de texto */
:root {
  --background-color: #ffffff !important;
  --secondary-background-color: #f7f7fb !important;
  --text-color: #111111 !important;
  --secondary-text-color: #222222 !important;
  --primary-color: #2a145a !important;
}
html, body, .stApp, .block-container { background:#ffffff !important; color:#111 !important; }
[data-testid="stSidebar"] { background:#f7f7fb !important; border-right:1px solid #ececf5; }
[data-testid="stSidebar"] *,
[data-testid="stMarkdownContainer"], label, p, span, div, li, th, td, h1, h2, h3, h4, h5 { color:#111 !important; }
input, textarea, select { color:#111 !important; }
input::placeholder, textarea::placeholder { color:#333 !important; opacity:.8; }

/* Componentes BaseWeb (selects, sliders, etc.) */
[data-baseweb="select"] * { color:#111 !important; }
[data-baseweb="input"] *  { color:#111 !important; }
.stNumberInput input, .stTextInput input { color:#111 !important; }

/* Tarjetas */
.card { border:1px solid #e6e6ef; border-radius:14px; padding:14px; background:#fff; box-shadow:0 1px 6px rgba(0,0,0,.06); }
.kpi { font-size:1.15rem; font-weight:700; }

/* Móvil */
@media (max-width: 480px){
  .stApp { padding:.4rem; }
  h1 { font-size:1.36rem; }
  h2 { font-size:1.12rem; }
  .card { padding:10px; }
}
</style>
""", unsafe_allow_html=True)

st.markdown(f"### {BRAND} · Software de Gestión Nutricional")

# ========== Intercambios base (VE) ==========
EXCHANGES = {
    "Vegetales": {"kcal":25,"CHO":5,"PRO":2,"FAT":0,"portion":"1 taza crudas / 1/2 taza cocidas"},
    "Frutas": {"kcal":60,"CHO":15,"PRO":0,"FAT":0,"portion":"1 unid pequeña / 1/2 taza picada"},
    "Cereales": {"kcal":80,"CHO":15,"PRO":2,"FAT":1,"portion":"1/2 taza cocidos / 1 rebanada pan"},
    "Leguminosas": {"kcal":100,"CHO":18,"PRO":7,"FAT":1,"portion":"1/2 taza cocidas"},
    "Lácteos descremados": {"kcal":90,"CHO":12,"PRO":8,"FAT":2,"portion":"1 taza leche / yogurt natural"},
    "Proteínas magras": {"kcal":110,"CHO":0,"PRO":21,"FAT":3,"portion":"30 g cocidos"},
    "Grasas saludables": {"kcal":45,"CHO":0,"PRO":0,"FAT":5,"portion":"1 cdita (5 g)"}
}

# ========== Utilidades clínicas ==========
ACTIVITY = {"Reposo / cama":1.2,"Ligera (1–3 d/sem)":1.375,"Moderada (3–5 d/sem)":1.55,"Alta (6–7 d/sem)":1.725}
def mifflin(sex, w, h_cm, age): return 10*w + 6.25*h_cm - 5*age + (5 if sex.lower().startswith("m") else -161)
def tee_from_tmb(tmb, act_key): return round(tmb * ACTIVITY.get(act_key, 1.2))
def kcal_target(tee, obj): return max(1000, tee - (400 if tee>=1600 else 200)) if obj=="Pérdida de peso" else (tee+200 if obj=="Ganancia (magro)" else tee)
def bmi(w,hcm): h=max(1e-6, hcm/100); return round(w/(h*h),2)
def whr(waist, hip): return round((waist/hip),2) if hip>0 else None
def whtr(waist, hcm): return round((waist/hcm),2) if hcm>0 else None
def homa_ir(gmgdl, ins): 
    if gmgdl>0 and ins>0: return round(((gmgdl/18.0)*ins)/22.5,2)
    return None

# Durnin-Womersley + Siri
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

# ========== SIDEBAR (expandido) ==========
with st.sidebar:
    with st.form("cap"):
        st.subheader("Paciente")
        nombre = st.text_input("Nombre y apellido")
        sexo = st.selectbox("Sexo biológico", ["Femenino","Masculino"])
        edad = st.number_input("Edad (años)", 1, 120, 30)
        talla_cm = st.number_input("Talla (cm)", 100, 230, 165)
        peso = st.number_input("Peso (kg)", 30.0, 300.0, 75.0, step=0.1)
        actividad = st.selectbox("Actividad", list(ACTIVITY.keys()), index=1)
        objetivo = st.selectbox("Objetivo", ["Pérdida de peso","Mantenimiento","Ganancia (magro)"], index=0)

        with st.expander("Antropometría detallada (opcional)", expanded=True):
            peso_usual = st.number_input("Peso usual (kg)", 0.0, 400.0, 0.0, step=0.1)
            peso_max = st.number_input("Peso máximo (kg)", 0.0, 400.0, 0.0, step=0.1)
            peso_min = st.number_input("Peso mínimo (kg)", 0.0, 400.0, 0.0, step=0.1)

            cintura = st.number_input("Circunferencia cintura (cm)", 0.0, 300.0, 0.0, step=0.1)
            cadera  = st.number_input("Circunferencia cadera (cm)", 0.0, 300.0, 0.0, step=0.1)

            st.caption("Pliegues (mm) — Durnin-Womersley: Bíceps, Tríceps, Subescapular, Suprailiaco")
            p_bi = st.number_input("Bíceps (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_tri = st.number_input("Tríceps (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_sub = st.number_input("Subescapular (mm)", 0.0, 60.0, 0.0, step=0.5)
            p_sup = st.number_input("Suprailiaco (mm)", 0.0, 60.0, 0.0, step=0.5)

            st.caption("BIA (opcional)")
            bia_fat = st.number_input("% Grasa (BIA)", 0.0, 70.0, 0.0, step=0.1)
            bia_ffm = st.number_input("Masa libre de grasa (kg, BIA)", 0.0, 200.0, 0.0, step=0.1)

        with st.expander("Laboratorios ampliados (opcional)", expanded=True):
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

# ========== Cálculos ==========
imc = bmi(peso, talla_cm)
tmb = max(800, round(mifflin(sexo, peso, talla_cm, edad)))
tee = tee_from_tmb(tmb, actividad)
kcal = kcal_target(tee, objetivo)
icc = whr(cintura, cadera) if 'cintura' in locals() else None
ict = whtr(cintura, talla_cm) if 'cintura' in locals() else None
homa = homa_ir(glicemia if 'glicemia' in locals() else 0, insulina if 'insulina' in locals() else 0)

pct_grasa_dw = None
if ('p_bi' in locals() and (p_bi+p_tri+p_sub+p_sup)>0):
    dens = dw_density(sexo, edad, p_bi, p_tri, p_sub, p_sup)
    pct_grasa_dw = siri_pctfat(dens)

# ========== Requerimientos ==========
st.header("Requerimientos nutricionales")
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

# ========== KPIs ==========
st.header("Resultados clínicos")
k = st.columns(3)
k[0].markdown(f"<div class='card'><div class='kpi'>IMC: {imc} kg/m²</div><div>OMS: {'Bajo peso' if imc<18.5 else 'Normopeso' if imc<25 else 'Sobrepeso' if imc<30 else 'Obesidad I' if imc<35 else 'Obesidad II' if imc<40 else 'Obesidad III'}</div></div>", unsafe_allow_html=True)
k[1].markdown(f"<div class='card'><div class='kpi'>TMB: {tmb} kcal</div><div>Mifflin–St Jeor</div></div>", unsafe_allow_html=True)
k[2].markdown(f"<div class='card'><div class='kpi'>GET: {tee} kcal</div><div>Meta: {kcal} kcal</div></div>", unsafe_allow_html=True)

k2 = st.columns(3)
if icc is not None: k2[0].markdown(f"<div class='card'><div class='kpi'>ICC: {icc}</div><div>Riesgo ↑ si >0.85 (F) / >0.90 (M)</div></div>", unsafe_allow_html=True)
if ict is not None: k2[1].markdown(f"<div class='card'><div class='kpi'>ICT: {ict}</div><div>Riesgo ↑ si ≥0.5 (adultos)</div></div>", unsafe_allow_html=True)
if pct_grasa_dw is not None or ('bia_fat' in locals() and bia_fat>0):
    txt=[]; 
    if pct_grasa_dw is not None: txt.append(f"{pct_grasa_dw}% (pliegues)")
    if 'bia_fat' in locals() and bia_fat>0: txt.append(f"{bia_fat}% (BIA)")
    k2[2].markdown(f"<div class='card'><div class='kpi'>% Grasa: {' · '.join(txt)}</div><div>Durnin–Womersley + Siri / BIA</div></div>", unsafe_allow_html=True)

labs = []
if 'glicemia' in locals(): labs.append(f"Glucosa {glicemia} mg/dL")
if 'hba1c' in locals(): labs.append(f"HbA1c {hba1c}%")
if homa is not None: labs.append(f"HOMA-IR {homa}")
lip = []
for lbl,val in [("CT", 'tc'), ("LDL",'ldl'), ("HDL",'hdl'), ("TG",'tg')]:
    if val in locals() and locals()[val]>0: lip.append(f"{lbl} {locals()[val]}")
st.markdown(f"<div class='card'><b>Laboratorios:</b> {' · '.join(labs)}  |  {' · '.join(lip)}</div>", unsafe_allow_html=True)

# ========== Sodio ==========
st.header("Sodio")
cna1, cna2, cna3 = st.columns(3)
with cna1: na_obj = st.number_input("Objetivo (mg Na/día)", 500, 5000, 2300, step=50)
with cna2: na_cons = st.number_input("Consumido (mg Na/día)", 0, 5000, 900, step=10)
na_calc = sodium_convert(na_obj, na_cons)
with cna3: st.metric("Na remanente (mg)", na_calc["remaining_mg"])
st.caption(f"≈ {na_calc['salt_g']} g NaCl ( {na_calc['tsp']} cdtas ) · 400 mg Na ≈ 1 g NaCl · 1 cdta ≈ 5 g")

# ========== Parámetros del plan ==========
st.header("Parámetros del plan")
pp1, pp2, pp3 = st.columns(3)
with pp1: comidas = st.slider("Nº de comidas (3–7)", 3, 7, 5)
with pp2: prot_gkg_obj = st.number_input("Proteína objetivo (g/kg)", 0.8, 3.0, max(1.2,float(mac["gkg"]["prot"])), step=0.1)
with pp3: agua_l = st.number_input("Agua (L/día)", 0.5, 5.0, round(max(1.5,min(3.5,peso*0.03)),2), step=0.1)
objetivo_texto = st.text_input("Objetivo del plan", value=("recomposición corporal" if "Ganancia" in objetivo else objetivo.lower()))
otras = st.text_area("Aclaratorias (opcional)", placeholder="Restricción de azúcares, control de saturadas, ↑fibra…")

# ========== Intercambios ==========
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

# ========== ADIME ==========
st.header("ADIME")
motivo = st.text_area("Motivo / Resumen")
dx_pes = st.text_area("Diagnóstico(s) PES (NCPT)", placeholder="Problema relacionado con ... evidenciado por ...")
presc = st.text_area("Prescripción Dietética", placeholder="Plan por intercambios individualizado + educación nutricional.")
me = st.text_area("Monitoreo/Evaluación", value="Control 2–4 semanas; peso, cintura, adherencia; labs según caso.")

# ========== Exportes ==========
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
    doc.add_paragraph("Comienza tu plan nutricional nutritivo y variado")
    doc.add_paragraph(payload["paciente"]).runs[0].bold=True
    doc.add_heading("Diagnóstico nutricional", 1); doc.add_paragraph(payload["diag"] or "—")
    doc.add_heading("Datos antropométricos", 1)
    t=doc.add_table(rows=0, cols=2)
    kv=[("Peso actual", f"{payload['peso']} kg"),("Talla", f"{payload['talla']} m"),("IMC", f"{payload['imc']} kg/m²"),
        ("Cintura", f"{payload['cintura']} cm"),("Cadera", f"{payload['cadera']} cm"),("ICC", payload["icc"]),
        ("ICT", payload["ict"]),("% Grasa", payload["pct_grasa"]),("Peso usual", payload["p_usual"]),
        ("Peso máx", payload["p_max"]),("Peso mín", payload["p_min"])]
    for k,v in kv: 
        row=t.add_row().cells; row[0].text=str(k); row[1].text=str(v)
    for c in t.columns[0].cells:
        if c.paragraphs and c.paragraphs[0].runs: c.paragraphs[0].runs[0].bold=True
    doc.add_heading("Características del plan",1)
    bullets=[f"Número de comidas: {payload['comidas']}",
             f"Calorías: {payload['kcal']} Kcal/d",
             f"Proteína objetivo: {payload['prot_gkg']} g/kg (≈ {payload['prot_g']} g/d)",
             f"Sal: {payload['salt_g']} g NaCl/d (≈ {payload['tsp']} cdtas)",
             f"Agua: {payload['agua_l']} L/día",
             f"Objetivo: {payload['objetivo']}"]
    if payload["otras"]: bullets.append(f"Otras: {payload['otras']}")
    for b in bullets: doc.add_paragraph("• "+b)
    doc.add_heading("Listas de intercambios – raciones totales",1)
    tb=doc.add_table(rows=1, cols=7)
    for i,h in enumerate(["Lista","Raciones","kcal","CHO","PRO","FAT","Porción"]): tb.rows[0].cells[i].text=h
    for g,r in diario.items():
        row=tb.add_row().cells
        row[0].text=g; row[1].text=str(r)
        row[2].text=str(EXCHANGES[g]["kcal"]); row[3].text=str(EXCHANGES[g]["CHO"])
        row[4].text=str(EXCHANGES[g]["PRO"]); row[5].text=str(EXCHANGES[g]["FAT"]); row[6].text=EXCHANGES[g]["portion"]
    doc.add_heading("Distribución por tiempos de comida",1); _table_dist(doc, por_comida, diario)
    doc.add_heading("Menú ejemplo (2 días)",1)
    demo=_menu_demo(por_comida)
    for m in ["Desayuno","Merienda AM","Almuerzo","Merienda PM","Cena"]:
        p=doc.add_paragraph(); p.add_run(m).bold=True
        doc.add_paragraph(f"Día 1: {demo[m]['Día 1']}"); doc.add_paragraph(f"Día 2: {demo[m]['Día 2']}")
    doc.add_paragraph(""); doc.add_paragraph(BRAND).runs[0].bold=True
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
    doc.add_paragraph(f"CHO: {m['pct']['cho']}% → {m['g']['cho']} g (Complejos {m['g']['cho_c']} g, Simples {m['g']['cho_s']} g)")
    s=payload["sodium"]; doc.add_paragraph(f"Sodio objetivo: {s['target_mg']} mg; Consumido: {s['current_mg']} mg; Remanente: {s['remaining_mg']} mg  ≈  {s['salt_g']} g NaCl ( {s['tsp']} cdtas )")
    bio=BytesIO(); doc.save(bio); bio.seek(0); return bio

def fhir_order(payload):
    return {"resourceType":"NutritionOrder","status":"active","intent":"order","dateTime": payload["fecha"],
            "patient":{"display": payload["paciente"]},"orderer":{"display": BRAND},
            "oralDiet":{"type":[{"text":"Personalizada"}],
                "nutrient":[{"modifier":{"text":"Energy"},"amount":{"value": payload["kcal"],"unit":"kcal/d"}},
                            {"modifier":{"text":"Protein"},"amount":{"value": payload["macros"]["g"]["prot"],"unit":"g/d"}},
                            {"modifier":{"text":"Fat"},"amount":{"value": payload["macros"]["g"]["fat"],"unit":"g/d"}},
                            {"modifier":{"text":"Carbohydrate"},"amount":{"value": payload["macros"]["g"]["cho"],"unit":"g/d"}}],
                "texture":[{"modifier":{"text":"Normal"}}] } }

def fhir_intake(payload):
    return {"resourceType":"NutritionIntake","status":"completed","occurrenceDateTime": payload["fecha"],
            "subject":{"display": payload["paciente"]},
            "consumedItem":[{"type":{"text":"Plan prescrito"},
                             "nutrient":[{"item":{"text":"Protein"},"amount":{"value": payload["macros"]["g"]["prot"],"unit":"g"}},
                                         {"item":{"text":"Fat"},"amount":{"value": payload["macros"]["g"]["fat"],"unit":"g"}},
                                         {"item":{"text":"Carbohydrate"},"amount":{"value": payload["macros"]["g"]["cho"],"unit":"g"}}],
                             "amount":{"value": payload["kcal"], "unit":"kcal"}}]}

# Payloads y descargas
st.markdown("---")
tipo = st.radio("Documento a generar", ["Plan de alimentación (@nutritionsays)","Nota ADIME"], index=0, horizontal=True)

bf_txt=[]
if pct_grasa_dw is not None: bf_txt.append(f"{pct_grasa_dw}% (pliegues)")
if 'bia_fat' in locals() and bia_fat>0: bf_txt.append(f"{bia_fat}% (BIA)")
bf_txt=" · ".join(bf_txt) if bf_txt else "—"

common = {"fecha": date.today().isoformat(), "paciente": nombre or "—",
          "kcal": kcal, "kcal_kg": round(kcal/peso,2) if peso else 0.0,
          "gkg_prot": macros(kcal, pct_prot, pct_fat, 100-pct_prot-pct_fat, peso)["gkg"]["prot"],
          "macros": mac, "sodium": {"target_mg": na_obj, "current_mg": na_cons, **na_calc}}

payload_plan = {"paciente": nombre or "—", "peso": float(peso), "talla": round(talla_cm/100,2), "imc": imc,
                "cintura": cintura if 'cintura' in locals() else "—", "cadera": cadera if 'cadera' in locals() else "—",
                "icc": icc if icc is not None else "—", "ict": ict if ict is not None else "—",
                "pct_grasa": bf_txt, "p_usual": peso_usual or "—", "p_max": peso_max or "—", "p_min": peso_min or "—",
                "comidas": int(comidas), "kcal": int(kcal), "prot_gkg": float(prot_gkg_obj),
                "prot_g": mac["g"]["prot"], "salt_g": common["sodium"]["salt_g"], "tsp": common["sodium"]["tsp"],
                "agua_l": float(agua_l), "objetivo": objetivo_texto, "otras": otras, "diag": dx_pes}

col1, col2 = st.columns(2)
with col1:
    if tipo=="Plan de alimentación (@nutritionsays)":
        plan = build_docx_plan(payload_plan, diario, por_comida)
        if DOCX:
            st.download_button("⬇️ Descargar PLAN (DOCX editable)", data=plan,
                file_name="plan_nutritionsays.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            st.info("Instala 'python-docx' y 'lxml' para exportar DOCX.")
    else:
        adime = build_docx_adime({
            **common,
            "A":[f"IMC {imc} kg/m²; TMB {tmb} kcal; GET {tee} kcal.",
                 f"ICC {icc if icc is not None else '—'}; ICT {ict if ict is not None else '—'}; %Grasa {bf_txt}.",
                 "Labs: " + " · ".join([s for s in [
                    f"Glucosa {glicemia} mg/dL" if 'glicemia' in locals() else None,
                    f"HbA1c {hba1c}%" if 'hba1c' in locals() else None,
                    f"HOMA-IR {homa}" if homa is not None else None] if s])],
            "D":[p.strip() for p in dx_pes.split("\n") if p.strip()],
            "I": presc or "Plan por intercambios + educación.",
            "ME": me or "Control 2–4 semanas."
        })
        if DOCX:
            st.download_button("⬇️ Descargar ADIME (DOCX)", data=adime,
                file_name="adime_nutritionsays.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        else:
            st.info("Instala 'python-docx' y 'lxml' para exportar DOCX.")

with col2:
    st.caption("JSON FHIR (NutritionOrder / NutritionIntake)")
    st.json({"NutritionOrder": fhir_order(common), "NutritionIntake": fhir_intake(common)})

st.caption("Herramienta de apoyo clínico para profesionales. Ajustar a juicio clínico y guías locales. © " + BRAND)
