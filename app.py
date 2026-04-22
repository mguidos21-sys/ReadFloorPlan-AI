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
st.set_page_config(page_title="Norm.AI - Topografía Resiliente", layout="wide")
st.title("📐 Extractor de Poligonales (Optimización Extrema de Cuota)")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos gemini-1.5-flash porque en Tier 1 de pago suele tener 
    # límites de RPM/TPM más estables que la versión 2.0 lite.
    model = genai.GenerativeModel('models/gemini-1.5-flash')
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
archivo_pdf = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Iniciar Procesamiento (Modo Ahorro de Tokens)"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            
            # ESPERA INICIAL para limpiar cualquier cuota residual
            st.info("Esperando 10 segundos para resetear límites de Google...")
            time.sleep(10)

            todos_los_tramos = []
            bar = st.progress(0)

            for i in range(num_pags):
                with st.spinner(f"Analizando página {i+1}..."):
                    pagina = doc_pdf.load_page(i)
                    
                    # RENDERIZADO DE PÁGINA
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    
                    # COMPRESIÓN EXTREMA: Forzamos máximo 1000px de ancho
                    # Esto reduce los tokens de visión drásticamente
                    img.thumbnail((1000, 1000)) 
                    
                    img_path = os.path.join(tempfile.gettempdir(), f"p{i}.jpg")
                    img.save(img_path, "JPEG", quality=70) # Calidad 70 es suficiente

                    # SUBIR Y PROCESAR
                    g_file = genai.upload_file(path=img_path)
                    while g_file.state.name == "PROCESSING":
                        time.sleep(1)
                        g_file = genai.get_file(gf.name)

                    prompt = "Extract survey data (bearings/distances). Output ONLY JSON: {'tramos': [{'rumbo': 'N10E', 'distancia': 25.0, 'tipo': 'linea', 'angulo_deg': 45}]}"
                    
                    try:
                        response = model.generate_content([prompt, g_file])
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos = json.loads(match.group())
                            todos_los_tramos.extend(datos.get('tramos', []))
                    except google.api_core.exceptions.ResourceExhausted:
                        # Si falla por cuota, esperamos un ciclo completo de 60 segundos
                        st.warning(f"⚠️ Cuota agotada en pág {i+1}. Esperando 60 segundos para liberar el minuto de Google...")
                        time.sleep(60)
                        # Reintento tras la espera larga
                        response = model.generate_content([prompt, g_file])
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos = json.loads(match.group())
                            todos_los_tramos.extend(datos.get('tramos', []))

                    # Limpieza y PAUSA PREVENTIVA
                    genai.delete_file(g_file.name)
                    os.remove(img_path)
                    
                    bar.progress((i + 1) / num_pags)
                    # Pausa obligatoria de 5 segundos entre cada página para no saturar
                    time.sleep(5)

            if todos_los_tramos:
                st.success(f"✅ Se extrajeron {len(todos_los_tramos)} tramos.")
                dxf_path = generar_dxf(todos_los_tramos)
                with open(dxf_path, "rb") as f:
                    st.download_button("💾 Descargar DXF", f, file_name="poligonal_normai.dxf")
                st.json(todos_los_tramos)
            else:
                st.warning("No se encontraron datos técnicos en el documento.")

        except Exception as e:
            st.error(f"Error crítico: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
