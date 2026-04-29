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
st.set_page_config(page_title="Norm.AI - Heavy Duty Edition", layout="wide")
st.title("📐 Norm.AI: Análisis de Macro-Escrituras y Remediciones")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. FILTROS MATEMÁTICOS (AHORA CON AZIMUT) ---
def calcular_area(puntos):
    n = len(puntos)
    if n < 3: return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += puntos[i][0] * puntos[j][1]
        area -= puntos[j][0] * puntos[i][1]
    return abs(area) / 2.0

def limpiar_numero(valor):
    if valor is None: return 0.0
    numeros = re.findall(r"[-+]?\d*\.\d+|\d+", str(valor).replace(',', '.'))
    return float(numeros[0]) if numeros else 0.0

def interpretar_rumbo_o_azimut(texto, ultimo_rad=0.0):
    if not texto: return ultimo_rad
    t = str(texto).upper().strip()
    
    # 1. Intento de Azimut (0-360)
    match_az = re.search(r'(\d+)\s*[°º]\s*(\d+)\s*[\'’]\s*(\d+(?:\.\d+)?)?\s*["”]', t)
    if match_az and not any(x in t for x in ['N', 'S', 'E', 'W', 'O']):
        g, m, s = match_az.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        # En topografía Azimut 0 es Norte (eje Y), sentido horario
        return math.radians(90 - dec)

    # 2. Rumbo Tradicional (N 10 E)
    t_norm = t.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E')
    match_r = re.search(r'([NS])\s*(\d+)[°\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\s]*([EW])', t_norm)
    if match_r:
        ns, g, m, s, ew = match_r.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    
    return ultimo_rad

# --- 3. GENERADOR DE DXF ---
def crear_dxf_integral(datos):
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6
    msp = doc.modelspace()

    current_x, current_y = 0.0, 0.0
    puntos_dwg = [(current_x, current_y)]
    ultimo_rad = 0.0

    tramos = datos.get('tramos', [])
    for i, t in enumerate(tramos):
        dist = limpiar_numero(t.get('distancia'))
        r_txt = t.get('rumbo_limpio', '')
        rad = interpretar_rumbo_o_azimut(r_txt, ultimo_rad)

        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)
            
            # Etiqueta de estación
            mid_x, mid_y = (current_x + next_x)/2, (current_y + next_y)/2
            msp.add_text(f"E{i+1}", dxfattribs={'height': 1.0, 'color': 3}).set_placement((mid_x + 0.5, mid_y + 0.5))

            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    if len(puntos_dwg) > 1:
        msp.add_lwpolyline(puntos_dwg, dxfattribs={'color': 7})
        if puntos_dwg[-1] != puntos_dwg[0]:
            msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1})

    # --- FICHA TÉCNICA DINÁMICA ---
    max_x = max([p[0] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    max_y = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    x_ref, y_ref = max_x + 20, max_y + 10

    msp.add_text("PROYECTO: " + datos.get('proyecto', 'Remedición'), dxfattribs={'height': 2.0, 'color': 2}).set_placement((x_ref, y_ref))
    y_ref -= 8
    msp.add_text(f"AREA CALCULADA: {calcular_area(puntos_dwg):,.2f} m2", dxfattribs={'height': 1.5}).set_placement((x_ref, y_ref))
    y_ref -= 10

    # Cuadro de Rumbos Expandible
    msp.add_text("CUADRO TÉCNICO DE ESTACIONES", dxfattribs={'height': 1.2, 'color': 4}).set_placement((x_ref, y_ref))
    y_ref -= 4
    for i, t in enumerate(tramos):
        linea = f"E{i}-{i+1}: {t.get('rumbo_limpio')} | {t.get('distancia')}m"
        msp.add_text(linea, dxfattribs={'height': 0.7}).set_placement((x_ref, y_ref))
        y_ref -= 1.5
        if y_ref < -500: # Nueva columna si es muy largo
            x_ref += 40
            y_ref = max_y - 2

    temp_path = os.path.join(tempfile.gettempdir(), f"Plano_Pro_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Subir Escritura de Gran Escala (PDF)", type=["pdf"])

if archivo:
    if st.button("🚀 Iniciar Procesamiento de Macro-Escritura"):
        try:
            status = st.status("Analizando múltiples folios (esto puede tardar por el volumen de datos)...")
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []

            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)) # Mayor resolución para escrituras viejas
                img_path = os.path.join(tempfile.gettempdir(), f"p_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=80)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)

            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1); google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Eres un experto en ingeniería legal salvadoreña. Esta es una REMEDICIÓN de gran escala.
            TU MISIÓN: Extraer TODAS las estaciones de la descripción técnica sin omitir ninguna.
            
            1. Busca la sección que dice 'DESCRIPCION TECNICA' o 'ESTACION'.
            2. Lista cada tramo en orden: del 1 al 2, del 2 al 3, etc.
            3. Para cada tramo extrae: 'rumbo_limpio' (sea Rumbo o Azimut) y 'distancia'.
            
            JSON ESTRICTO:
            {
              "proyecto": "Nombre del proyecto o propietario",
              "tramos": [
                {"rumbo_limpio": "N 10° 15' 20\\" E", "distancia": 45.50},
                {"rumbo_limpio": "120° 30' 00\\"", "distancia": 12.30}
              ]
            }
            """

            response = model.generate_content([prompt] + google_files)
            datos = json.loads(response.text[response.text.find('{'):response.text.rfind('}')+1])
            
            ruta = crear_dxf_integral(datos)
            status.update(label="✅ Polígono de Gran Escala Generado", state="complete")
            
            with open(ruta, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="Plano_Remedicion_NormAI.dxf")
            
            for f in google_files: genai.delete_file(f.name)
        except Exception as e:
            st.error(f"Error en el procesamiento masivo: {e}")


st.divider()
st.caption("Norm.AI | Arquitectura & Tecnología | Miguel Guidos")
