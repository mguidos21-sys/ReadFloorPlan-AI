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
st.set_page_config(page_title="Norm.AI - Topografía 2.5", layout="wide")
st.title("📐 Extractor de Poligonales (Modo Ultra-Ligero)")

# MODELO ESTABLE 2026
MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. MATEMÁTICA DE RUMBOS ---
def parsear_rumbo(rumbo_str):
    if not rumbo_str or rumbo_str.lower() == 'none': return None
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

# --- 3. GENERADOR DE DXF ---
def crear_dxf_estable(tramos):
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for i, t in enumerate(tramos):
        try:
            dist = float(t.get('distancia', 0))
            rad = parsear_rumbo(t.get('rumbo', ''))
            if rad is not None and dist > 0:
                p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                if t.get('tipo') == 'curva':
                    msp.add_lwpolyline([puntos[-1], p_final], dxfattribs={'bulge': 0.4, 'color': 3})
                else:
                    msp.add_line(puntos[-1], p_final, dxfattribs={'color': 7})
                puntos.append(p_final)
        except: continue

    # Cuadro de datos
    x_c = 30
    msp.add_text("CUADRO TÉCNICO NORM.AI", dxfattribs={'height': 0.8}).set_placement((x_c, 10))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.5}).set_placement((x_c, 10 - (i+1)*1.5))

    path = os.path.join(tempfile.gettempdir(), f"final_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 4. PROCESAMIENTO ---
archivo = st.file_uploader("Sube el PDF (Análisis multi-página)", type=["pdf"])

if archivo:
    if st.button("🚀 Iniciar Análisis Completo"):
        try:
            status = st.status("Procesando documento...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            # Paso 1: Convertir y Subir cada página por separado (Ligero)
            status.write("📤 Subiendo páginas a la nube...")
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"p{i}.jpg")
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img.save(img_path, "JPEG", quality=70)
                
                g_file = genai.upload_file(path=img_path)
                google_files.append(g_file)
                os.remove(img_path)
            
            # Esperar procesamiento de Google
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1)
                google_files = [genai.get_file(f.name) for f in google_files]

            # Paso 2: Análisis Global
            status.write("🧠 IA Analizando rumbos (esto puede tardar 20-30 seg)...")
            prompt = """Analiza todas las páginas. Busca la descripción técnica de rumbos y distancias.
            Conecta la secuencia de todas las hojas. Devuelve JSON: 
            {"tramos": [{"rumbo": "N 10°E", "distancia": 15.0, "tipo": "linea"}]}"""
            
            # Enviamos el prompt + la lista de todas las imágenes
            response = model.generate_content([prompt] + google_files)
            
            # Paso 3: Generación
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                datos = json.loads(match.group())
                ruta = crear_dxf_estable(datos['tramos'])
                
                status.update(label="✅ ¡Proceso completado!", state="complete")
                st.success(f"Se extrajeron {len(datos['tramos'])} tramos.")
                with open(ruta, "rb") as f:
                    st.download_button("💾 DESCARGAR DXF", f, file_name="poligonal_completa.dxf")
                st.json(datos)
            else:
                status.update(label="❌ No se encontraron datos", state="error")
                st.error("La IA no detectó una tabla de rumbos. Revisa el PDF.")

            # Limpiar Google
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Error crítico: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
