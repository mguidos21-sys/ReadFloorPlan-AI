import streamlit as st
import google.generativeai as genai
import google.api_core.exceptions
import ezdxf
from ezdxf.math import Vec2
import fitz  # PyMuPDF
import json
import re
import math
import os
import tempfile
import time

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Topografía Pro", layout="wide")
st.title("📐 Extractor de Poligonales (Modo Ultra-Estable)")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos Flash-Lite por ser el más rápido y eficiente en cuotas
    model = genai.GenerativeModel('models/gemini-2.0-flash-lite')
else:
    st.error("Configura la API Key.")
    st.stop()

# --- 2. LÓGICA DE DIBUJO ---
def generar_dxf(todos_los_tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for tramo in todos_los_tramos:
        try:
            dist = float(tramo.get('distancia', 0))
            ang = math.radians(float(tramo.get('angulo_deg', 0)))
            np = puntos[-1] + Vec2(math.cos(ang) * dist, math.sin(ang) * dist)
            
            if tramo.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        except: continue

    # Cuadro de rumbos
    x_t = 20
    for i, t in enumerate(todos_los_tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_t, -(i * 0.7)))

    path = os.path.join(tempfile.gettempdir(), "poligonal_final.dxf")
    doc.saveas(path)
    return path

# --- 3. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Iniciar Procesamiento Inteligente"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Analizando {num_pags} páginas una por una para evitar bloqueos de cuota...")

            todos_los_tramos = []
            progreso = st.progress(0)
            
            # PROMPT INDIVIDUAL
            prompt = """
            Analiza esta página de una escritura. Si contiene rumbos y distancias, extráelos.
            Si no hay datos técnicos, devuelve un JSON vacío: {"tramos": []}
            Si hay datos, usa este formato:
            {"tramos": [{"rumbo": "N 10E", "distancia": 25.0, "tipo": "linea", "angulo_deg": 45}]}
            """

            # 4. PROCESAMIENTO PÁGINA POR PÁGINA
            for i in range(num_pags):
                with st.spinner(f"Procesando página {i+1} de {num_pags}..."):
                    # Convertir página a imagen optimizada
                    pagina = doc_pdf.load_page(i)
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(1.1, 1.1)) # Resolución ligera
                    img_path = os.path.join(tempfile.gettempdir(), f"temp_p{i}.jpg")
                    pix.save(img_path)
                    
                    # Subir y procesar individualmente (esto consume pocos tokens por vez)
                    g_file = genai.upload_file(path=img_path)
                    
                    # Espera breve para asegurar que el archivo esté listo
                    while g_file.state.name == "PROCESSING":
                        time.sleep(1)
                        g_file = genai.get_file(g_file.name)
                    
                    # Llamada a la IA para esta página específica
                    response = model.generate_content([prompt, g_file])
                    
                    # Extraer JSON y acumular tramos
                    match = re.search(r'\{.*\}', response.text, re.DOTALL)
                    if match:
                        try:
                            datos_pag = json.loads(match.group())
                            todos_los_tramos.extend(datos_pag.get('tramos', []))
                        except: pass
                    
                    # Limpieza inmediata
                    genai.delete_file(g_file.name)
                    os.remove(img_path)
                    
                    # PEQUEÑA PAUSA de 2 segundos para no saturar el TPM de Google
                    time.sleep(2)
                    progreso.progress((i + 1) / num_pags)

            # 5. RESULTADO FINAL
            if todos_los_tramos:
                st.success(f"✅ Se encontraron {len(todos_los_tramos)} tramos en total.")
                ruta_dxf = generar_dxf(todos_los_tramos)
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 Descargar Poligonal Completa (DXF)", f, file_name="poligonal_normai.dxf")
                st.json(todos_los_tramos)
            else:
                st.warning("No se encontraron rumbos y distancias en ninguna página.")

        except google.api_core.exceptions.ResourceExhausted:
            st.error("🛑 Google sigue limitando la velocidad. Por favor, espera 1 minuto e intenta de nuevo.")
        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
