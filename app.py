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
st.title("📐 Generador de Poligonal")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. LÓGICA DE GEOMETRÍA ---
def parsear_rumbo_sv(rumbo_str):
    if not rumbo_str or str(rumbo_str).lower() == 'none': return None
    r = str(rumbo_str).upper().replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E')
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

# --- 3. GENERADOR DE PLANO (DXF) ---
def crear_dxf_blindado(datos):
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    # --- DIBUJO DE POLIGONAL ---
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    
    # Validamos que 'tramos' sea una lista
    if isinstance(tramos, list):
        for t in tramos:
            # AQUÍ ESTÁ EL ARREGLO AL ERROR 'STR' OBJECT HAS NO ATTRIBUTE 'GET'
            if not isinstance(t, dict): continue 
            
            try:
                dist = float(t.get('distancia', 0))
                rad = parsear_rumbo_sv(t.get('rumbo'))
                if rad is not None and dist > 0:
                    p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                    
                    if t.get('tipo') == 'curva':
                        msp.add_lwpolyline([puntos[-1], p_final], dxfattribs={'bulge': 0.4, 'color': 3})
                    else:
                        msp.add_line(puntos[-1], p_final, dxfattribs={'color': 7})
                    puntos.append(p_final)
            except: continue
    
    ancho_max = max([p.x for p in puntos]) if len(puntos) > 1 else 0
    if len(puntos) > 1:
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'linetype': 'DASHED', 'color': 1})

    # --- BLOQUE DE INFORMACIÓN (Sidebar) ---
    x_sidebar = ancho_max + 20
    y_ref = 30
    
    msp.add_text("EXPEDIENTE TÉCNICO - NORM.AI", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_sidebar, y_ref))
    y_ref -= 5
    msp.add_text(f"PROPIETARIO: {datos.get('propietario', 'No detectado')}", dxfattribs={'height': 0.8}).set_placement((x_sidebar, y_ref))
    
    y_ref -= 8
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_sidebar, y_ref))
    
    colindantes = datos.get('colindantes', [])
    if isinstance(colindantes, list):
        for col in colindantes:
            y_ref -= 2
            txt_col = str(col) # Convertimos a string por seguridad
            msp.add_text(f"- {txt_col}", dxfattribs={'height': 0.6}).set_placement((x_sidebar + 2, y_ref))
    
    y_ref -= 8
    msp.add_text("RESTRICCIONES:", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_sidebar, y_ref))
    y_ref -= 3
    msp.add_text(f"SERVIDUMBRES: {datos.get('servidumbres', 'N/A')}", dxfattribs={'height': 0.5}).set_placement((x_sidebar + 2, y_ref))
    y_ref -= 2
    msp.add_text(f"QUEBRADAS: {datos.get('quebradas', 'N/A')}", dxfattribs={'height': 0.5}).set_placement((x_sidebar + 2, y_ref))

    temp_file = os.path.join(tempfile.gettempdir(), f"plano_{int(time.time())}.dxf")
    doc.saveas(temp_file)
    return temp_file

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo:
    if st.button("🚀 Generar Poligonal y Datos"):
        try:
            status = st.status("Procesando información...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"p_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=75)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1)
                google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Extract from this property deed:
            1. 'propietario': Name.
            2. 'colindantes': List of neighbors (N, S, E, W).
            3. 'servidumbres' & 'quebradas': Mention if any.
            4. 'tramos': List of dicts with 'rumbo', 'distancia', 'tipo'.
            
            JSON format:
            {"propietario": "...", "colindantes": ["..."], "servidumbres": "...", "quebradas": "...", "tramos": [{"rumbo": "...", "distancia": 0.0, "tipo": "linea"}]}
            """
            
            response = model.generate_content([prompt] + google_files)
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            
            if match:
                datos = json.loads(match.group())
                ruta_dxf = crear_dxf_blindado(datos)
                status.update(label="✅ Proceso finalizado", state="complete")
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 DESCARGAR DXF", f, file_name="Plano_NormAI.dxf")
                st.json(datos)
            
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Error en el motor: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
