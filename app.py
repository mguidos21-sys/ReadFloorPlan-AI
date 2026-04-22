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

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Topografía Pro", layout="wide")
st.title("🏗️ Lector de Planos (Modo Alta Eficiencia)")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Cambiamos a 1.5 Flash: es el modelo con los límites de tokens más amplios
    # en la mayoría de cuentas de pago actualmente.
    model = genai.GenerativeModel('models/gemini-1.5-flash')
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- LÓGICA CAD ---
def generar_dxf(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    for t in datos.get('tramos', []):
        try:
            d = float(t.get('distancia', 0))
            a = math.radians(float(t.get('angulo_deg', 0)))
            np = puntos[-1] + Vec2(math.cos(a)*d, math.sin(a)*d)
            if t.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        except: continue
    
    # Tabla técnica
    x_off = 20
    for i, t in enumerate(datos.get('tramos', [])):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_off, -(i*0.8)))
        
    path = os.path.join(tempfile.gettempdir(), f"cad_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- PROCESAMIENTO ---
archivo = st.file_uploader("Sube el plano", type=["pdf", "jpg", "png"])

if archivo:
    if st.button("🚀 Procesar Poligonal"):
        ext = archivo.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(archivo.getvalue())
            tmp_path = tmp.name
        
        try:
            # 1. COMPRESIÓN AGRESIVA: Reducimos a 1500px para ahorrar miles de tokens
            if ext in ['jpg', 'jpeg', 'png']:
                with Image.open(tmp_path) as img:
                    img.thumbnail((1500, 1500))
                    img.save(tmp_path, optimize=True, quality=80)

            google_file = genai.upload_file(path=tmp_path)
            while google_file.state.name == "PROCESSING":
                time.sleep(2)
                google_file = genai.get_file(google_file.name)

            prompt = "Analiza la poligonal. Extrae rumbos, distancias y curvas. JSON: {'tramos': [{'rumbo': 'N 10E', 'distancia': 25.0, 'tipo': 'linea', 'angulo_deg': 45}]}"
            
            intentos = 3
            for i in range(intentos):
                try:
                    # Agregamos una configuración para limitar tokens de salida y ahorrar cuota
                    response = model.generate_content(
                        [prompt, google_file],
                        generation_config=genai.types.GenerationConfig(max_output_tokens=1000)
                    )
                    match = re.search(r'\{.*\}', response.text, re.DOTALL)
                    if match:
                        datos = json.loads(match.group())
                        path_dxf = generar_dxf(datos)
                        st.success("✅ Generado.")
                        with open(path_dxf, "rb") as f:
                            st.download_button("💾 Descargar DXF", f, file_name="plano.dxf")
                        break
                except google.api_core.exceptions.ResourceExhausted:
                    # ESPERA EXTENDIDA: A veces Google necesita hasta 45 segundos para resetear el TPM
                    espera = 40 
                    st.warning(f"⚠️ El plano es complejo. Esperando {espera} segundos para liberar cuota...")
                    time.sleep(espera)
                except Exception as e:
                    st.error(f"Error: {e}")
                    break

            genai.delete_file(google_file.name)
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)
st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
