import streamlit as st
import google.generativeai as genai
import google.api_core.exceptions
import ezdxf
from ezdxf.math import Vec2
from PIL import Image
import json
import re
import math
import os
import tempfile
import time

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Topografía Pro", layout="wide")
st.title("🏗️ Lector de Planos (Optimizado para Alta Carga)")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Cambiamos al modelo LITE: Tiene límites de tokens mucho más amplios
    MODEL_NAME = 'models/gemini-2.0-flash-lite' 
    model = genai.GenerativeModel(model_name=MODEL_NAME)
else:
    st.error("⚠️ Configura la API Key en Secrets.")
    st.stop()

# --- 2. LÓGICA DE DIBUJO ---
def generar_dxf(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    
    for tramo in tramos:
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

    # Cuadro de rumbos a la derecha
    x_pos = 20
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_pos, -(i * 0.8)))

    path = os.path.join(tempfile.gettempdir(), f"output_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 3. INTERFAZ ---
archivo = st.file_uploader("Sube el plano (PDF, JPG, PNG)", type=["pdf", "jpg", "png"])

if archivo:
    if st.button("🚀 Extraer Poligonal Técnica", key="btn_normai_v2026"):
        ext = archivo.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(archivo.getvalue())
            tmp_path = tmp.name
        
        try:
            # OPTIMIZACIÓN AGRESIVA: 1200px es el punto dulce para ahorrar tokens
            if ext in ['jpg', 'jpeg', 'png']:
                with Image.open(tmp_path) as img:
                    img.thumbnail((1200, 1200))
                    img.save(tmp_path, optimize=True, quality=80)

            st.info("Subiendo a Google AI Cloud...")
            g_file = genai.upload_file(path=tmp_path)
            
            while g_file.state.name == "PROCESSING":
                time.sleep(2)
                g_file = genai.get_file(g_file.name)

            # Prompt minimalista para no gastar tokens
            prompt = "Extract boundary data (bearings/distances). Output ONLY JSON: {'tramos': [{'rumbo': 'N10E', 'distancia': 20.0, 'tipo': 'linea', 'angulo_deg': 45}]}"
            
            intentos = 3
            for i in range(intentos):
                try:
                    with st.spinner(f"Analizando con {MODEL_NAME}..."):
                        response = model.generate_content([prompt, g_file])
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos = json.loads(match.group())
                            dxf_path = generar_dxf(datos)
                            st.success("✅ Poligonal generada correctamente.")
                            with open(dxf_path, "rb") as f:
                                st.download_button("💾 Descargar DXF para AutoCAD", f, file_name="poligonal.dxf")
                            st.json(datos)
                            break
                except google.api_core.exceptions.ResourceExhausted:
                    espera = 45 # Aumentamos a 45 segundos por seguridad
                    st.warning(f"⚠️ El archivo es denso. Liberando cuota en {espera} seg...")
                    time.sleep(espera)
                except Exception as e:
                    st.error(f"Error: {e}")
                    break

            genai.delete_file(g_file.name)
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)


st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
