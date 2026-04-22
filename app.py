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
st.title("📐 Norm.AI: Expedientes (Geometría Segura)")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. FILTROS DE LIMPIEZA ---
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

def interpretar_rumbo_flexible(rumbo_str, rumbo_anterior=None):
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

# --- 3. GENERADOR DE DXF (CERO CORRUPCIÓN) ---
def crear_dxf_integral(datos):
    doc = ezdxf.new('R2010') 
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    puntos = [Vec2(0, 0)]
    ultimo_rad = 0
    
    tramos = datos.get('tramos', [])
    for t in tramos:
        if not isinstance(t, dict): continue
        
        dist = limpiar_numero(t.get('distancia'))
        rumbo_txt = sanitizar_texto(t.get('rumbo', ''))
        
        rad = interpretar_rumbo_flexible(rumbo_txt, ultimo_rad)
        
        if rad is not None and dist > 0:
            p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
            
            # EL ARREGLO: Trazamos líneas simples SIEMPRE. Si es arco, lo ponemos color Verde (3).
            if "ARCO" in rumbo_txt.upper() or str(t.get('tipo', '')).lower() == 'curva':
                msp.add_line(puntos[-1], p_final, dxfattribs={'color': 3, 'layer': 'ARCOS'})
            else:
                msp.add_line(puntos[-1], p_final, dxfattribs={'color': 7, 'layer': 'LINDEROS'})
            
            puntos.append(p_final)
            ultimo_rad = rad

    if len(puntos) > 2:
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'color': 1, 'linetype': 'DASHED', 'layer': 'CIERRE'})

    # --- FICHA TÉCNICA ---
    x_side = max([p.x for p in puntos]) + 15 if len(puntos) > 1 else 30
    y_ref = max([p.y for p in puntos]) if len(puntos) > 1 else 30
    
    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_side, y_ref))
    y_ref -= 5
    
    prop = sanitizar_texto(datos.get('propietario', 'N/A'))
    msp.add_text(f"PROPIETARIO: {prop}", dxfattribs={'height': 0.8}).set_placement((x_side, y_ref))
    
    y_ref -= 6
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_side, y_ref))
    for col in datos.get('colindantes', []):
        y_ref -= 1.8
        txt_col = sanitizar_texto(col)
        msp.add_text(f"- {txt_col}", dxfattribs={'height': 0.6}).set_placement((x_side + 2, y_ref))
    
    y_ref -= 6
    msp.add_text("NOTAS TECNICAS:", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_side, y_ref))
    y_ref -= 2
    serv = sanitizar_texto(datos.get('servidumbres', 'Ninguna'))
    msp.add_text(f"SERVIDUMBRES: {serv}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))
    y_ref -= 1.5
    queb = sanitizar_texto(datos.get('quebradas', 'N/A'))
    msp.add_text(f"ZONAS HIDRICAS: {queb}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))

    y_ref -= 8
    msp.add_text("CUADRO DE RUMBOS", dxfattribs={'height': 1.0, 'color': 4}).set_placement((x_side, y_ref))
    for i, t in enumerate(tramos):
        if not isinstance(t, dict): continue
        y_ref -= 1.3
        dist_limpia = limpiar_numero(t.get('distancia'))
        rumbo_limpio = sanitizar_texto(t.get('rumbo'))
        msp.add_text(f"L{i+1}: {rumbo_limpio} | {dist_limpia}m", dxfattribs={'height': 0.4}).set_placement((x_side + 2, y_ref))

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_Seguro_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube el Expediente PDF", type=["pdf"])

if archivo:
    if st.button("🚀 Procesar Geometría (Modo Seguro)"):
        try:
            status = st.status("Procesando linderos...", expanded=True)
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
            
            response = model.generate_content([prompt] + google_files)
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
