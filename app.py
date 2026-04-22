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
st.title("📐 Extractor de Poligonales (Modo Resiliente)")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos Flash-Lite: es el que tiene los límites de tokens más generosos por minuto
    model = genai.GenerativeModel('models/gemini-2.0-flash-lite')
else:
    st.error("Configura la API Key en los Secrets.")
    st.stop()

# --- 2. LÓGICA DE DIBUJO ---
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
        except: continue
    
    path = os.path.join(tempfile.gettempdir(), f"output_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 3. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura (9+ páginas)", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Iniciar Procesamiento por Lotes"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Analizando {num_pags} páginas con gestión de cuota activa...")

            todos_los_tramos = []
            bar = st.progress(0)

            for i in range(num_pags):
                with st.spinner(f"Procesando página {i+1}..."):
                    pagina = doc_pdf.load_page(i)
                    
                    # ESTRATEGIA 1: Intentar extraer texto primero (Ahorra 99% de cuota)
                    texto_pag = pagina.get_text().strip()
                    
                    content_to_send = []
                    if len(texto_pag) > 100: # Si hay texto real suficiente
                        content_to_send.append(f"PÁGINA {i+1} (TEXTO):\n{texto_pag}")
                    else:
                        # ESTRATEGIA 2: Si es escaneo, enviar imagen OPTIMIZADA (pequeña)
                        pix = pagina.get_pixmap(matrix=fitz.Matrix(1.0, 1.0)) # 1.0 es el mínimo legible
                        img_path = os.path.join(tempfile.gettempdir(), f"p{i}.jpg")
                        pix.save(img_path)
                        g_file = genai.upload_file(path=img_path)
                        while g_file.state.name == "PROCESSING":
                            time.sleep(1)
                            g_file = genai.get_file(g_file.name)
                        content_to_send.append(g_file)
                    
                    # PROMPT TÉCNICO
                    prompt = "Extract survey data (bearings/distances). If no technical data found, return empty JSON: {'tramos': []}. Else: {'tramos': [{'rumbo': 'N 10E', 'distancia': 25.0, 'tipo': 'linea', 'angulo_deg': 45}]}"
                    
                    try:
                        response = model.generate_content([prompt] + content_to_send)
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos = json.loads(match.group())
                            todos_los_tramos.extend(datos.get('tramos', []))
                    except google.api_core.exceptions.ResourceExhausted:
                        st.warning(f"⚠️ Cuota saturada en pág {i+1}. Esperando 30 segundos...")
                        time.sleep(30)
                        # Reintento único
                        response = model.generate_content([prompt] + content_to_send)
                        # ... lógica de match similar ...
                    
                    # Limpieza y PAUSA DE SEGURIDAD
                    if 'g_file' in locals():
                        genai.delete_file(g_file.name)
                    
                    bar.progress((i + 1) / num_pags)
                    time.sleep(3) # Pausa obligatoria entre páginas para no "llenar el vaso"

            if todos_los_tramos:
                st.success(f"✅ Poligonal de {len(todos_los_tramos)} tramos extraída.")
                dxf_path = generar_dxf(todos_los_tramos)
                with open(dxf_path, "rb") as f:
                    st.download_button("💾 Descargar DXF", f, file_name="poligonal_final.dxf")
                st.json(todos_los_tramos)
            else:
                st.warning("No se detectaron datos técnicos. Asegúrate de que los rumbos sean legibles.")

        except Exception as e:
            st.error(f"Error crítico: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
