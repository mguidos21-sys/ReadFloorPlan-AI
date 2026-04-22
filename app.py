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

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Norm.AI - Topografía Pro", layout="wide")
st.title("🏗️ Lector de Planos y Generador de DXF")

# --- 2. CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    
    # IMPORTANTE: Cambiamos al modelo 2.0 que confirmamos que tienes activo
    # Esto elimina el error 404 del modelo 1.5
    MODEL_NAME = 'models/gemini-2.0-flash' 
    model = genai.GenerativeModel(model_name=MODEL_NAME)
else:
    st.error("⚠️ Configura 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# --- 3. LÓGICA DE DIBUJO CAD (DXF) ---
def generar_dxf_profesional(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    
    for tramo in tramos:
        try:
            dist = float(tramo.get('distancia', 0))
            angulo_rad = math.radians(float(tramo.get('angulo_deg', 0)))
            nuevo_punto = puntos[-1] + Vec2(math.cos(angulo_rad) * dist, math.sin(angulo_rad) * dist)
            
            if tramo.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], nuevo_punto], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], nuevo_punto)
            puntos.append(nuevo_point if 'nuevo_point' in locals() else nuevo_punto)
        except:
            continue

    # Cuadro de datos técnicos
    x_tab = 25
    y_tab = 0
    msp.add_text("CUADRO TÉCNICO", dxfattribs={'height': 0.8}).set_placement((x_tab, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_tab, y_tab - (i * 0.8)))

    temp_path = os.path.join(tempfile.gettempdir(), f"poligonal_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ Y PROCESAMIENTO ---
archivo = st.file_uploader("Sube plano o memoria técnica (PDF, JPG, PNG)", type=["pdf", "jpg", "png"])

if archivo:
    if st.button("🚀 Iniciar Análisis de Ingeniería", key="btn_analisis_final_2026"):
        ext = archivo.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(archivo.getvalue())
            tmp_path = tmp.name
        
        try:
            # Optimización de imagen (ahorra cuota de tokens)
            if ext in ['jpg', 'jpeg', 'png']:
                with Image.open(tmp_path) as img:
                    img.thumbnail((1600, 1600))
                    img.save(tmp_path, optimize=True, quality=85)

            # Subida a Google
            st.info(f"Subiendo archivo a Google AI Studio utilizando {MODEL_NAME}...")
            google_file = genai.upload_file(path=tmp_path)
            
            # ESPERA DE PROCESAMIENTO (Evita Error 400)
            with st.spinner("Procesando archivo en los servidores de Google..."):
                while google_file.state.name == "PROCESSING":
                    time.sleep(2)
                    google_file = genai.get_file(google_file.name)
            
            if google_file.state.name != "ACTIVE":
                st.error(f"Error: El archivo no pudo activarse ({google_file.state.name})")
                st.stop()

            # PROMPT
            prompt = """
            Actúa como experto topógrafo. Analiza el documento y extrae la poligonal.
            Busca rumbos, distancias y curvas.
            Devuelve estrictamente un JSON:
            {"tramos": [{"rumbo": "N 10°E", "distancia": 25.0, "tipo": "linea", "angulo_deg": 45}]}
            """
            
            # Bucle de reintentos por cuota
            intentos = 3
            for i in range(intentos):
                try:
                    with st.spinner(f"Analizando geometría (Intento {i+1}/3)..."):
                        response = model.generate_content([prompt, google_file])
                        
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos = json.loads(match.group())
                            ruta_dxf = generar_dxf_profesional(datos)
                            
                            st.success("✅ Poligonal y Cuadro Técnico generados.")
                            with open(ruta_dxf, "rb") as f:
                                st.download_button("💾 Descargar DXF para AutoCAD", f, file_name="poligonal.dxf")
                            st.json(datos)
                            break
                
                except google.api_core.exceptions.ResourceExhausted:
                    # Si la cuota se llena, esperamos 40 segundos (tiempo de seguridad en 2026)
                    st.warning("⚠️ Límite de tokens por minuto alcanzado. Esperando 40 segundos...")
                    time.sleep(40)
                except Exception as e:
                    st.error(f"Error en procesamiento: {e}")
                    break

            genai.delete_file(google_file.name)

        except Exception as e:
            st.error(f"Error crítico: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
