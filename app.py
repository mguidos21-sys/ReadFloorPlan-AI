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
st.set_page_config(page_title="Norm.AI - Topografía & Catastro", layout="wide")
st.title("📐 Norm.AI: Análisis Técnico-Legal ")

# Modelo estable para Tier 1
MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. TRADUCTOR DE RUMBOS (Soporta N, S, Poniente, Oriente) ---
def parsear_rumbo_sv(rumbo_str):
    if not rumbo_str or not isinstance(rumbo_str, str): return None
    r = rumbo_str.upper().replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E')
    r = r.replace('NORTE', 'N').replace('SUR', 'S')
    
    match = re.search(r'([NS])\s*(\d+)[°°º]?\s*(\d+)\'?\s*(?:(\d+(?:\.\d+)?)\s*")?\s*([EW])', r)
    if match:
        ns, g, m, s, ew = match.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return None

# --- 3. GENERADOR DE DXF PROFESIONAL ---
def crear_dxf_profesional(datos):
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    # POLIGONAL UNIDA (LWPOLYLINE)
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    
    if isinstance(tramos, list):
        for t in tramos:
            if not isinstance(t, dict): continue
            try:
                dist = float(t.get('distancia', 0))
                rad = parsear_rumbo_sv(t.get('rumbo'))
                if rad is not None and dist > 0:
                    p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                    puntos.append(p_final)
            except: continue
    
    ancho_dibujo = 20
    if len(puntos) > 1:
        msp.add_lwpolyline(puntos, dxfattribs={'color': 7, 'layer': 'LINDEROS'})
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'color': 1, 'linetype': 'DASHED'})
        ancho_dibujo = max([p.x for p in puntos]) + 15

    # FICHA TÉCNICA LEGAL (Sidebar)
    x_side = ancho_dibujo
    y_ref = 30
    
    msp.add_text("FICHA TÉCNICA - NORM.AI", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_side, y_ref))
    y_ref -= 5
    msp.add_text(f"PROPIETARIO: {str(datos.get('propietario', 'No detectado'))}", dxfattribs={'height': 0.8}).set_placement((x_side, y_ref))
    
    y_ref -= 8
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_side, y_ref))
    colindantes = datos.get('colindantes', [])
    if isinstance(colindantes, list):
        for col in colindantes:
            y_ref -= 2
            msp.add_text(f"- {str(col)}", dxfattribs={'height': 0.6}).set_placement((x_side + 2, y_ref))
    
    y_ref -= 8
    msp.add_text("NOTAS Y RESTRICCIONES:", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_side, y_ref))
    y_ref -= 3
    msp.add_text(f"SERVIDUMBRES: {str(datos.get('servidumbres', 'Ninguna'))}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))
    y_ref -= 2
    msp.add_text(f"ZONAS HÍDRICAS: {str(datos.get('quebradas', 'No menciona'))}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))

    y_ref -= 10
    msp.add_text("CUADRO DE RUMBOS", dxfattribs={'height': 1.0, 'color': 4}).set_placement((x_side, y_ref))
    if isinstance(tramos, list):
        for i, t in enumerate(tramos):
            if not isinstance(t, dict): continue
            y_ref -= 1.5
            txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
            msp.add_text(txt, dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))

    temp_path = os.path.join(tempfile.gettempdir(), f"normai_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube la Escritura (PDF completo)", type=["pdf"])

if archivo:
    if st.button("🚀 Procesar Expediente"):
        try:
            status = st.status("Analizando linderos y datos legales...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"pg_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=75)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1)
                google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Extract from this deed:
            1. 'propietario': TITULAR.
            2. 'colindantes': Neighbors (N, S, E, W).
            3. 'servidumbres': Paso, agua, luz.
            4. 'quebradas': Water bodies.
            5. 'tramos': Array of objects with 'rumbo', 'distancia'.
            
            Return ONLY a valid JSON object. No conversation before or after.
            """
            
            response = model.generate_content([prompt] + google_files)
            
            # EXTRACCIÓN ROBUSTA DE JSON
            # Buscamos la primera '{' y la última '}'
            text_response = response.text
            start_idx = text_response.find('{')
            end_idx = text_response.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                clean_json = text_response[start_idx:end_idx+1]
                datos = json.loads(clean_json)
                
                ruta_dxf = crear_dxf_profesional(datos)
                status.update(label="✅ Expediente Listo", state="complete")
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 DESCARGAR DXF", f, file_name="Expediente_NormAI.dxf")
                st.json(datos)
            else:
                st.error("No se detectó un formato de datos válido.")
            
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Fallo en el motor: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
