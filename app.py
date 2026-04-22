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

# --- 1. CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Norm.AI - Topografía 2026", layout="wide")
st.title("📐 Extractor de Poligonales (Versión Estable)")

# --- CONFIGURACIÓN DEL MODELO ---
# Usamos exactamente el nombre que aparece en tu consola de Google Cloud
MODELO_ACTIVO = 'gemini-2.0-flash-lite'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# --- 2. LÓGICA DE DIBUJO CAD ---
def generar_dxf(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for t in tramos:
        try:
            d = float(t.get('distancia', 0))
            a = math.radians(float(t.get('angulo_deg', 0)))
            np = puntos[-1] + Vec2(math.cos(a) * d, math.sin(a) * d)
            
            if t.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        except:
            continue

    # Cuadro de datos técnico
    x_tab = 20
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_tab, -(i * 0.7)))

    path = os.path.join(tempfile.gettempdir(), f"poligonal_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 3. PROCESAMIENTO ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura (Hasta 10 páginas)", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Iniciar Extracción de Poligonal"):
        try:
            # Abrimos el PDF
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Analizando {num_pags} páginas con el modelo {MODELO_ACTIVO}...")

            todos_los_tramos = []
            barra_progreso = st.progress(0)
            
            # Prompt de análisis
            prompt = (
                "Extract survey data (bearings/distances). "
                "If no technical data is found, return: {'tramos': []}. "
                "Format: {'tramos': [{'rumbo': 'N 10E', 'distancia': 25.0, 'tipo': 'linea', 'angulo_deg': 45}]}"
            )

            # Procesamos página por página
            for i in range(num_pags):
                with st.spinner(f"Analizando página {i+1} de {num_pags}..."):
                    # 1. Convertir página a imagen LIGERA (1000px max) para no agotar tokens
                    pagina = doc_pdf.load_page(i)
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)) # Resolución balanceada
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img.thumbnail((1000, 1000))
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                        img.save(tmp_img.name, "JPEG", quality=75)
                        tmp_img_path = tmp_img.name

                    # 2. Subir a Google
                    g_file = genai.upload_file(path=tmp_img_path)
                    while g_file.state.name == "PROCESSING":
                        time.sleep(1)
                        g_file = genai.get_file(g_file.name)

                    # 3. Llamar a la IA
                    response = model.generate_content([prompt, g_file])
                    
                    # 4. Extraer JSON
                    match = re.search(r'\{.*\}', response.text, re.DOTALL)
                    if match:
                        try:
                            datos_pag = json.loads(match.group())
                            todos_los_tramos.extend(datos_pag.get('tramos', []))
                        except:
                            pass
                    
                    # Limpieza y espera de 5 segundos para que la cuota de Google se libere
                    genai.delete_file(g_file.name)
                    os.remove(tmp_img_path)
                    
                    barra_progreso.progress((i + 1) / num_pags)
                    time.sleep(5) 

            # RESULTADO FINAL
            if todos_los_tramos:
                st.success(f"✅ ¡Éxito! Se encontraron {len(todos_los_tramos)} tramos.")
                ruta_final = generar_dxf(todos_los_tramos)
                with open(ruta_final, "rb") as f:
                    st.download_button("💾 Descargar DXF para AutoCAD", f, file_name="poligonal_normai.dxf")
                st.json(todos_los_tramos)
            else:
                st.warning("No se encontraron rumbos ni distancias legibles en el documento.")

        except Exception as e:
            st.error(f"Error en el proceso: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
