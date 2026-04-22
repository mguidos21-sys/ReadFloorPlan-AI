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
st.title("📐 Generador de Poligonal")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. FILTROS MATEMÁTICOS ---
def sanitizar_texto(texto):
    if not texto: return "N/A"
    t = str(texto)
    t = re.sub(r'[\n\r\t]+', ' ', t)
    t = re.sub(r'[^\x20-\x7E\xA0-\xFF]', '', t)
    return t.strip()

def limpiar_numero(valor):
    if valor is None: return 0.0
    numeros = re.findall(r"[-+]?\d*\.\d+|\d+", str(valor).replace(',', '.'))
    if numeros: return float(numeros[0])
    return 0.0

def interpretar_rumbo_flexible(rumbo_str, rumbo_anterior=0.0):
    if not rumbo_str or not isinstance(rumbo_str, str): return rumbo_anterior
    
    r = rumbo_str.upper()
    r = r.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E')
    r = r.replace('NORTE', 'N').replace('SUR', 'S')
    
    match = re.search(r'([NS])\s*(\d+)[°°º\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\s]*([EW])', r)
    if match:
        ns, g, m, s, ew = match.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return rumbo_anterior

# --- 3. GENERADOR DE DXF ---
def crear_dxf_integral(datos):
    doc = ezdxf.new('R2000') 
    doc.header['$INSUNITS'] = 6 
    
    doc.layers.add('POLIGONAL', color=7)
    doc.layers.add('TEXTOS_LEGALES', color=2)
    doc.layers.add('TEXTOS_DATOS', color=4)
    doc.layers.add('SEGURIDAD', color=1)
    
    msp = doc.modelspace()
    
    current_x, current_y = 0.0, 0.0
    puntos_2d = [(current_x, current_y)]
    ultimo_rad = 0.0
    
    tramos = datos.get('tramos', [])
    for t in tramos:
        if not isinstance(t, dict): continue
        
        dist = limpiar_numero(t.get('distancia'))
        rumbo_txt = sanitizar_texto(t.get('rumbo', ''))
        
        rad = interpretar_rumbo_flexible(rumbo_txt, ultimo_rad)
        
        if rad is not None and dist > 0.0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)
            
            puntos_2d.append((next_x, next_y))
            current_x, current_y = next_x, next_y
            ultimo_rad = rad

    if len(puntos_2d) > 1:
        msp.add_lwpolyline(puntos_2d, dxfattribs={'layer': 'POLIGONAL'}, close=True)
        max_x = max([p[0] for p in puntos_2d])
        max_y = max([p[1] for p in puntos_2d])
    else:
        msp.add_lwpolyline([(0,0), (10,0), (10,10), (0,10)], dxfattribs={'layer': 'SEGURIDAD'}, close=True)
        msp.add_text("ERROR: NO SE ENCONTRARON RUMBOS VALIDOS", dxfattribs={'height': 1.0, 'layer': 'SEGURIDAD'}).set_placement((0, -2))
        max_x, max_y = 10, 10

    x_side = max_x + 15
    y_ref = max_y if max_y > 30 else 30
    
    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 1.5, 'layer': 'TEXTOS_LEGALES'}).set_placement((x_side, y_ref))
    y_ref -= 5
    
    prop = sanitizar_texto(datos.get('propietario', 'N/A'))
    msp.add_text(f"PROPIETARIO: {prop}", dxfattribs={'height': 0.8, 'layer': 'TEXTOS_DATOS'}).set_placement((x_side, y_ref))
    
    y_ref -= 6
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.0, 'layer': 'TEXTOS_LEGALES'}).set_placement((x_side, y_ref))
    for col in datos.get('colindantes', []):
        y_ref -= 1.8
        msp.add_text(f"- {sanitizar_texto(col)}", dxfattribs={'height': 0.6, 'layer': 'TEXTOS_DATOS'}).set_placement((x_side + 2, y_ref))
    
    y_ref -= 6
    msp.add_text("NOTAS TECNICAS:", dxfattribs={'height': 1.0, 'layer': 'TEXTOS_LEGALES'}).set_placement((x_side, y_ref))
    y_ref -= 2
    msp.add_text(f"SERVIDUMBRES: {sanitizar_texto(datos.get('servidumbres', 'Ninguna'))}", dxfattribs={'height': 0.5, 'layer': 'TEXTOS_DATOS'}).set_placement((x_side + 2, y_ref))
    y_ref -= 1.5
    msp.add_text(f"ZONAS HIDRICAS: {sanitizar_texto(datos.get('quebradas', 'N/A'))}", dxfattribs={'height': 0.5, 'layer': 'TEXTOS_DATOS'}).set_placement((x_side + 2, y_ref))

    y_ref -= 8
    msp.add_text("CUADRO DE RUMBOS", dxfattribs={'height': 1.0, 'layer': 'TEXTOS_LEGALES'}).set_placement((x_side, y_ref))
    for i, t in enumerate(tramos):
        if not isinstance(t, dict): continue
        y_ref -= 1.3
        dist_limpia = limpiar_numero(t.get('distancia'))
        rumbo_limpio = sanitizar_texto(t.get('rumbo'))
        msp.add_text(f"L{i+1}: {rumbo_limpio} | {dist_limpia}m", dxfattribs={'height': 0.4, 'layer': 'TEXTOS_DATOS'}).set_placement((x_side + 2, y_ref))

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube el Expediente PDF", type=["pdf"])

if archivo:
    if st.button("🚀 Procesar (Sistema Anti-Caídas)"):
        try:
            status = st.status("Preparando archivos...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"page_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=75)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1); google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Extrae estrictamente en formato JSON:
            1. 'propietario'
            2. 'colindantes' (array de strings)
            3. 'servidumbres' y 'quebradas'
            4. 'tramos' (array de objetos con 'rumbo' y 'distancia').
            NO agregues unidades a la distancia, solo el numero.
            """
            
            # --- SISTEMA DE REINTENTOS PARA EVITAR EL ERROR 503 ---
            max_intentos = 3
            response = None
            
            for intento in range(max_intentos):
                try:
                    status.update(label=f"Conectando con Google... (Intento {intento + 1}/3)")
                    response = model.generate_content([prompt] + google_files)
                    break # Si funciona, sale del bucle
                except Exception as e:
                    if "503" in str(e) and intento < max_intentos - 1:
                        status.update(label=f"Servidor ocupado. Reintentando en 5 segundos...")
                        time.sleep(5)
                    else:
                        raise e # Si es otro error o se acabaron los intentos, muestra la falla real
            
            if response is None:
                raise Exception("No se pudo obtener respuesta de Google después de 3 intentos.")

            status.update(label="Analizando resultados...")
            text = response.text
            clean_json = text[text.find('{'):text.rfind('}')+1]
            datos = json.loads(clean_json)
            
            ruta_dxf = crear_dxf_integral(datos)
            
            status.update(label="✅ DXF Generado Exitosamente", state="complete")
            with open(ruta_dxf, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="NormAI_Plano.dxf")
            
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Fallo en motor: {e}")
            
st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
