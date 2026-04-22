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
st.set_page_config(page_title="Norm.AI - Topografía y Catastro", layout="wide")
st.title("📐 Norm.AI: Generador de Expedientes Técnicos")

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
    # Traducción de términos salvadoreños a formato internacional
    r = str(rumbo_str).upper().replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E')
    r = r.replace('NORTE', 'N').replace('SUR', 'S')
    
    # Regex flexible para grados, minutos y segundos opcionales
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
def crear_dxf_mejorado(datos):
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    # --- DIBUJO DE POLIGONAL ---
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    for t in tramos:
        try:
            dist = float(t.get('distancia', 0))
            rad = parsear_rumbo_sv(t.get('rumbo'))
            if rad is not None and dist > 0:
                p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                puntos.append(p_final)
        except: continue
    
    ancho_terreno = 0
    if len(puntos) > 1:
        # Polilínea unida
        msp.add_lwpolyline(puntos, dxfattribs={'color': 7, 'layer': 'POLIGONAL'})
        ancho_terreno = max([p.x for p in puntos])
        # Línea de cierre punteada en rojo
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'linetype': 'DASHED', 'color': 1})

    # --- BLOQUE DE INFORMACIÓN (Sidebar) ---
    # Colocamos la info 20 metros a la derecha del punto más lejano del terreno
    x_sidebar = ancho_terreno + 20
    y_ref = 30
    
    # Título y Propietario
    msp.add_text("INFORMACIÓN DEL EXPEDIENTE", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_sidebar, y_ref))
    y_ref -= 5
    propietario = str(datos.get('propietario', 'No detectado'))
    msp.add_text(f"PROPIETARIO: {propietario}", dxfattribs={'height': 0.8}).set_placement((x_sidebar, y_ref))
    
    # Colindantes (Limpieza de formato)
    y_ref -= 8
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_sidebar, y_ref))
    colindantes = datos.get('colindantes', [])
    for i, col in enumerate(colindantes):
        y_ref -= 2
        # Si viene como dict, extraemos solo el texto relevante
        if isinstance(col, dict):
            txt_col = f"{col.get('punto_cardinal', '')}: {col.get('nombre', '')}"
        else:
            txt_col = str(col)
        msp.add_text(f"- {txt_col}", dxfattribs={'height': 0.6}).set_placement((x_sidebar + 2, y_ref))
    
    # Notas Técnicas
    y_ref -= 8
    msp.add_text("NOTAS TÉCNICAS:", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_sidebar, y_ref))
    y_ref -= 3
    msp.add_text(f"SERVIDUMBRES: {datos.get('servidumbres', 'N/A')}", dxfattribs={'height': 0.5}).set_placement((x_sidebar + 2, y_ref))
    y_ref -= 2
    msp.add_text(f"QUEBRADAS/ZONAS HÍDRICAS: {datos.get('quebradas', 'No menciona')}", dxfattribs={'height': 0.5}).set_placement((x_sidebar + 2, y_ref))

    # Cuadro de Rumbos (al final de la sidebar)
    y_ref -= 10
    msp.add_text("CUADRO TÉCNICO", dxfattribs={'height': 1.0, 'color': 4}).set_placement((x_sidebar, y_ref))
    for i, t in enumerate(tramos):
        y_ref -= 1.5
        txt_rumbo = f"L{i+1}: {t.get('rumbo')} | Dist: {t.get('distancia')}m"
        msp.add_text(txt_rumbo, dxfattribs={'height': 0.5}).set_placement((x_sidebar + 2, y_ref))

    path = os.path.join(tempfile.gettempdir(), f"expediente_normai_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo:
    if st.button("🚀 Generar Expediente y Poligonal"):
        try:
            status = st.status("Procesando linderos y datos legales...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            # Subida de páginas
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"page_{i}.jpg")
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img.save(img_path, "JPEG", quality=75)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1)
                google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Analiza estas páginas de escritura y extrae:
            1. 'propietario': Nombre completo.
            2. 'colindantes': Lista clara (Norte, Sur, Este, Oeste).
            3. 'servidumbres': Menciona si existen.
            4. 'quebradas': Menciona si existen cuerpos de agua.
            5. 'tramos': Tabla de rumbos y distancias (N 10E, 15m).
            
            Formato JSON:
            {"propietario": "...", "colindantes": ["Norte: ...", "Sur: ..."], "servidumbres": "...", "quebradas": "...", "tramos": []}
            """
            
            response = model.generate_content([prompt] + google_files)
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            
            if match:
                datos = json.loads(match.group())
                ruta_dxf = crear_dxf_mejorado(datos)
                
                status.update(label="✅ Expediente y Poligonal Generados", state="complete")
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 DESCARGAR DXF INTEGRAL", f, file_name="Plano_Expediente_NormAI.dxf")
                st.json(datos)
            
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Error en el motor: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
