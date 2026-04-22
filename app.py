import streamlit as st
import google.generativeai as genai
import ezdxf
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
st.title("📐 Generador de Poligonales")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. FILTROS Y MATEMÁTICA ---
def sanitizar_texto(texto):
    if not texto: return "N/A"
    t = str(texto).replace('\n', ' ').strip()
    return re.sub(r'[^\x20-\x7E\xA0-\xFF]', '', t)

def limpiar_numero(valor):
    if valor is None: return 0.0
    numeros = re.findall(r"[-+]?\d*\.\d+|\d+", str(valor).replace(',', '.'))
    return float(numeros[0]) if numeros else 0.0

def interpretar_rumbo_profesional(rumbo_str, ultimo_rad=0.0):
    if not rumbo_str or not isinstance(rumbo_str, str): return ultimo_rad
    r = rumbo_str.upper().replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E')
    
    match = re.search(r'([NS])\s*(\d+)[°\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\s]*([EW])', r)
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

# --- 3. GENERADOR DE DXF (CERO CORRUPCIÓN) ---
def crear_dxf_profesional(datos):
    doc = ezdxf.new('R2010') # Formato universal
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    # --- DIBUJO DE POLIGONAL ---
    current_x, current_y = 0.0, 0.0
    puntos_dwg = [(current_x, current_y)]
    ultimo_rad = 0.0
    
    tramos = datos.get('tramos', [])
    for t in tramos:
        dist = limpiar_numero(t.get('distancia'))
        rumbo_txt = sanitizar_texto(t.get('rumbo', ''))
        rad = interpretar_rumbo_profesional(rumbo_txt, ultimo_rad)
        
        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)
            
            # Dibujamos línea sólida básica (color 7 = blanco/negro por defecto)
            msp.add_line((current_x, current_y), (next_x, next_y), dxfattribs={'color': 7})
            
            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    # Cierre de polígono (SOLO COLOR, NADA DE 'DASHED')
    if len(puntos_dwg) > 2:
        msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1}) # 1 = Rojo

    # --- DIBUJO DE CUADRO TÉCNICO ---
    x_tab = max([p[0] for p in puntos_dwg]) + 15 if len(puntos_dwg) > 1 else 25
    y_tab = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 25
    
    headers = ["TRAMO", "RUMBO", "DIST (m)"]
    col_widths = [10, 25, 15]
    
    for i, h in enumerate(headers):
        msp.add_text(h, dxfattribs={'height': 0.8, 'color': 2}).set_placement((x_tab + sum(col_widths[:i]), y_tab))
    
    y_tab -= 2
    for i, t in enumerate(tramos):
        msp.add_text(f"L{i+1}", dxfattribs={'height': 0.6}).set_placement((x_tab, y_tab))
        msp.add_text(sanitizar_texto(t.get('rumbo')), dxfattribs={'height': 0.6}).set_placement((x_tab + col_widths[0], y_tab))
        msp.add_text(f"{limpiar_numero(t.get('distancia')):.2f}", dxfattribs={'height': 0.6}).set_placement((x_tab + col_widths[0] + col_widths[1], y_tab))
        y_tab -= 1.5

    y_tab -= 4
    msp.add_text(f"PROPIETARIO: {sanitizar_texto(datos.get('propietario'))}", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_tab, y_tab))
    y_tab -= 2
    msp.add_text(f"NOTAS: {sanitizar_texto(datos.get('servidumbres'))}", dxfattribs={'height': 0.5}).set_placement((x_tab, y_tab))

    temp = os.path.join(tempfile.gettempdir(), f"NormAI_{int(time.time())}.dxf")
    doc.saveas(temp)
    return temp

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube la Escritura (PDF)", type=["pdf"])

if archivo:
    if st.button("🚀 Generar Poligonal"):
        try:
            status = st.status("Analizando folios...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            for i in range(len(doc_pdf)):
                p = doc_pdf.load_page(i)
                pix = p.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
                path = os.path.join(tempfile.gettempdir(), f"p_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(path, "JPEG", quality=80)
                google_files.append(genai.upload_file(path=path))
                os.remove(path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1); google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Extract strictly for survey analysis:
            1. 'propietario': Full name.
            2. 'tramos': Array of objects with 'rumbo' (full text: N 00° 00' 00" E) and 'distancia' (number only).
            3. 'servidumbres': Mention any restrictions or water bodies.
            Return JSON.
            """
            
            response = model.generate_content([prompt] + google_files)
            clean_json = response.text[response.text.find('{'):response.text.rfind('}')+1]
            datos = json.loads(clean_json)
            
            ruta = crear_dxf_profesional(datos)
            status.update(label="✅ Poligonal y Cuadro Listos", state="complete")
            
            with open(ruta, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="NormAI_Plano_Ingenieria.dxf")
            
            st.json(datos)
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Fallo en motor: {e}")
            
st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
