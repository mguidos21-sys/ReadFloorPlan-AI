import streamlit as st
import google.generativeai as genai
import ezdxf
from ezdxf.math import Vec2
import fitz  # PyMuPDF
from PIL import Image
import json
import re
import math
import os
import tempfile
import time

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Topografía Profesional", layout="wide")
st.title("📐 Norm.AI: Expediente Técnico y Análisis de Cierre")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. CÁLCULOS TÉCNICOS ---
def calcular_area(puntos):
    """Calcula el área de un polígono usando la fórmula de Shoelace"""
    n = len(puntos)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += puntos[i][0] * puntos[j][1]
        area -= puntos[j][0] * puntos[i][1]
    return abs(area) / 2.0

def interpretar_rumbo_sv(rumbo_str, ultimo_rad=0.0):
    if not rumbo_str or not isinstance(rumbo_str, str): return ultimo_rad
    r = rumbo_str.upper().strip()
    if r in ['N', 'NORTE']: return math.pi / 2
    if r in ['S', 'SUR']: return 3 * math.pi / 2
    if r in ['E', 'ESTE', 'ORIENTE']: return 0.0
    if r in ['W', 'OESTE', 'PONIENTE']: return math.pi
    r_norm = r.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E')
    r_norm = r_norm.replace('NORTE', 'N').replace('SUR', 'S')
    match = re.search(r'([NS])\s*(\d+)[°\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\s]*([EW])', r_norm)
    if match:
        ns, g, m, s, ew = match.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return ultimo_rad

# --- 3. GENERADOR DE DXF PROFESIONAL ---
def crear_dxf_integral(datos):
    doc = ezdxf.new('R2010') 
    doc.header['$INSUNITS'] = 6 
    msp = doc.modelspace()
    
    # --- GEOMETRÍA ---
    current_x, current_y = 0.0, 0.0
    puntos_dwg = [(current_x, current_y)]
    ultimo_rad = 0.0
    tramos = datos.get('tramos', [])
    
    for t in tramos:
        dist = float(re.sub(r'[^\d.]', '', str(t.get('distancia', 0))))
        rumbo_txt = str(t.get('rumbo_limpio', t.get('rumbo_texto', '')))
        rad = interpretar_rumbo_sv(rumbo_txt, ultimo_rad)
        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)
            msp.add_line((current_x, current_y), (next_x, next_y), dxfattribs={'color': 7})
            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    # Error de cierre
    tiene_error_cierre = False
    if len(puntos_dwg) > 2:
        dist_cierre = math.sqrt((puntos_dwg[-1][0])**2 + (puntos_dwg[-1][1])**2)
        if dist_cierre > 0.01:
            msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1})
            tiene_error_cierre = True

    # --- FICHA TÉCNICA SECCIONADA ---
    max_x = max([p[0] for p in puntos_dwg]) + 15
    y_ref = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 30
    
    # 1. Encabezado y Dueño
    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 1.5, 'color': 2}).set_placement((max_x, y_ref))
    y_ref -= 5
    msp.add_text(f"PROPIETARIO ACTUAL: {datos.get('propietario', 'N/A')}", dxfattribs={'height': 0.8}).set_placement((max_x, y_ref))
    y_ref -= 3
    msp.add_text(f"REMEDICIÓN: {datos.get('remedicion', 'No se menciona')}", dxfattribs={'height': 0.6, 'color': 3}).set_placement((max_x, y_ref))

    # 2. Áreas
    y_ref -= 6
    area_calc = calcular_area(puntos_dwg)
    msp.add_text("DATOS DE SUPERFICIE:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((max_x, y_ref))
    y_ref -= 2.5
    msp.add_text(f"AREA SEGUN ESCRITURA: {datos.get('area_escritura', 'N/A')}", dxfattribs={'height': 0.6}).set_placement((max_x + 2, y_ref))
    y_ref -= 1.8
    msp.add_text(f"AREA CALCULADA (CAD): {area_calc:,.2f} m2", dxfattribs={'height': 0.6, 'color': 4}).set_placement((max_x + 2, y_ref))

    # 3. Cuadro de Rumbos
    y_ref -= 8
    msp.add_text("CUADRO DE RUMBOS:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((max_x, y_ref))
    y_ref -= 2.5
    for i, t in enumerate(tramos):
        msp.add_text(f"L{i+1}: {t.get('rumbo_limpio')} | {t.get('distancia')} m", dxfattribs={'height': 0.45}).set_placement((max_x + 2, y_ref))
        y_ref -= 1.3

    # 4. LEYENDA TECNICA (Explicación línea roja)
    if tiene_error_cierre:
        y_ref -= 6
        msp.add_text("NOTA DE CIERRE TOPOGRAFICO:", dxfattribs={'height': 0.8, 'color': 1}).set_placement((max_x, y_ref))
        y_ref -= 2
        leyenda = [
            "La linea roja indica el error de cierre de la escritura.",
            "No es un error del programa, sino una discrepancia",
            "matematica en los rumbos y distancias del documento legal."
        ]
        for linea in leyenda:
            msp.add_text(linea, dxfattribs={'height': 0.4, 'color': 7}).set_placement((max_x + 2, y_ref))
            y_ref -= 1.2

    temp_path = os.path.join(tempfile.gettempdir(), f"Plano_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube el PDF", type=["pdf"])
if archivo:
    if st.button("🚀 Generar Expediente"):
        try:
            status = st.status("Analizando legalidad y geometría...")
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"f_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=75)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1); google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Extract in SPANISH:
            1. 'propietario': Current legal owner (check inheritance/traspasos).
            2. 'remedicion': Did the property undergo a 'remedición'? (Yes/No and date).
            3. 'area_escritura': Total area mentioned in the deed (m2 or varas2).
            4. 'tramos': Array with 'rumbo_limpio' and 'distancia'.
            Return JSON.
            """
            response = model.generate_content([prompt] + google_files)
            datos = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
            ruta = crear_dxf_integral(datos)
            status.update(label="✅ Expediente Finalizado", state="complete")
            with open(ruta, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="Plano_Final.dxf")
            st.json(datos)
            for f in google_files: genai.delete_file(f.name)
        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
