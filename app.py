import streamlit as st
import google.generativeai as genai
import google.api_core.exceptions
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
st.set_page_config(page_title="Norm.AI - Topografía Pro", layout="wide")
st.title("📐 Extractor de Poligonales (Versión Producción)")

# --- MODELO ESTÁNDAR DE PRODUCCIÓN ---
# gemini-1.5-flash es el modelo más estable para cuentas de pago.
MODEL_NAME = 'gemini-1.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODEL_NAME)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- DIAGNÓSTICO: LISTAR MODELOS (Solo si falla) ---
def listar_modelos_disponibles():
    st.write("🔍 Buscando modelos disponibles en tu cuenta...")
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        st.write("Modelos que puedes usar:", models)
    except Exception as e:
        st.error(f"No se pudo obtener la lista: {e}")

# --- 2. LÓGICA CAD ---
def generar_dxf(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    for t in tramos:
        try:
            d = float(t.get('distancia', 0))
            # Ángulo en radianes para AutoCAD
            a = math.radians(float(t.get('angulo_deg', 0)))
            np = puntos[-1] + Vec2(math.cos(a) * d, math.sin(a) * d)
            if t.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        except: continue
    
    path = os.path.join(tempfile.gettempdir(), f"pol_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 3. PROCESAMIENTO ---
archivo_pdf = st.file_uploader("Sube el PDF (9 páginas)", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Iniciar Análisis con Gemini 1.5"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Analizando {num_pags} páginas...")

            todos_los_tramos = []
            progreso = st.progress(0)
            
            # Prompt optimizado
            prompt = "Extract survey bearings and distances. Return ONLY JSON: {'tramos': [{'rumbo': 'N10E', 'distancia': 25.0, 'tipo': 'linea', 'angulo_deg': 45}]}"

            for i in range(num_pags):
                with st.spinner(f"Página {i+1}..."):
                    pagina = doc_pdf.load_page(i)
                    # Bajamos la resolución un poco más para asegurar que NO gastes tokens de más
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img.thumbnail((1000, 1000))
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        img.save(tmp.name, "JPEG", quality=75)
                        tmp_path = tmp.name

                    # Subir y Procesar
                    g_file = genai.upload_file(path=tmp_path)
                    while g_file.state.name == "PROCESSING":
                        time.sleep(1)
                        g_file = genai.get_file(g_file.name)

                    # LLAMADA A LA IA
                    response = model.generate_content([prompt, g_file])
                    match = re.search(r'\{.*\}', response.text, re.DOTALL)
                    if match:
                        try:
                            datos = json.loads(match.group())
                            todos_los_tramos.extend(datos.get('tramos', []))
                        except: pass
                    
                    genai.delete_file(g_file.name)
                    os.remove(tmp_path)
                    
                    progreso.progress((i + 1) / num_pags)
                    time.sleep(3) # Pausa para flujo de cuota

            if todos_los_tramos:
                st.success(f"✅ Se encontraron {len(todos_los_tramos)} tramos.")
                ruta = generar_dxf(todos_los_tramos)
                with open(ruta, "rb") as f:
                    st.download_button("💾 Descargar DXF", f, file_name="poligonal_normai.dxf")
                st.json(todos_los_tramos)
            else:
                st.warning("No se detectaron datos técnicos.")

        except Exception as e:
            st.error(f"Error detectado: {e}")
            # Si el error es un 404, mostramos qué modelos sí funcionan
            if "404" in str(e):
                listar_modelos_disponibles()

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
