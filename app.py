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
st.markdown("Extrae rumbos, distancias y curvas para generar archivos CAD automáticamente.")

# --- 2. CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos Gemini 2.0 Flash por su estabilidad y velocidad
    model = genai.GenerativeModel('models/gemini-2.0-flash')
else:
    st.error("⚠️ Configura 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# --- 3. LÓGICA DE DIBUJO CAD (DXF) ---
def generar_dxf_profesional(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    
    # Dibujar Poligonal
    for tramo in tramos:
        try:
            dist = float(tramo.get('distancia', 0))
            angulo_rad = math.radians(float(tramo.get('angulo_deg', 0)))
            
            # Calcular siguiente punto (Coordenadas relativas)
            nuevo_punto = puntos[-1] + Vec2(math.cos(angulo_rad) * dist, math.sin(angulo_rad) * dist)
            
            if tramo.get('tipo') == 'curva':
                # El bulge de 0.5 crea un semicírculo; 0.4 es una curva común
                msp.add_lwpolyline([puntos[-1], nuevo_punto], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], nuevo_punto)
            
            puntos.append(nuevo_punto)
        except Exception as e:
            continue

    # --- GENERAR CUADRO DE DATOS TÉCNICOS ---
    x_t, y_t = puntos[-1].x + 10, puntos[-1].y  # Posición de la tabla
    msp.add_text("CUADRO TÉCNICO", dxfattribs={'height': 0.8}).set_placement((x_t, y_t + 2))
    
    for i, t in enumerate(tramos):
        txt = f"Lado {i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_t, y_t - (i * 0.7)))

    temp_path = os.path.join(tempfile.gettempdir(), "poligonal_normai.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ Y PROCESAMIENTO ---
archivo = st.file_uploader("Sube plano o memoria (PDF, JPG, PNG)", type=["pdf", "jpg", "png"])

if archivo:
    if st.button("🚀 Iniciar Análisis Técnico", key="btn_analisis_vfinal"):
        
        # 1. Guardar archivo localmente para subirlo a Google
        ext = archivo.name.split('.')[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(archivo.getvalue())
            tmp_path = tmp.name
        
        try:
            # 2. Subir archivo a la API de Google
            st.info("Subiendo archivo a Google AI Studio...")
            google_file = genai.upload_file(path=tmp_path)
            
            # 3. ESPERA CRÍTICA (Evita el Error 400)
            with st.spinner("Google está procesando el archivo..."):
                while google_file.state.name == "PROCESSING":
                    time.sleep(2)
                    google_file = genai.get_file(google_file.name)
            
            if google_file.state.name != "ACTIVE":
                st.error(f"Fallo al procesar archivo: {google_file.state.name}")
                st.stop()

            # 4. LLAMADA A LA IA CON REINTENTOS
            prompt = """
            Actúa como experto topógrafo. Analiza el documento y extrae la poligonal.
            Identifica rumbos, distancias y curvas.
            Devuelve ÚNICAMENTE un JSON con este formato exacto:
            {
              "tramos": [
                {"rumbo": "N 10°E", "distancia": 25.0, "tipo": "linea", "angulo_deg": 45},
                {"rumbo": "S 80°E", "distancia": 12.0, "tipo": "curva", "radio": 5.0, "angulo_deg": -10}
              ]
            }
            """
            
            intentos = 3
            for i in range(intentos):
                try:
                    with st.spinner(f"Analizando geometría (Intento {i+1})..."):
                        response = model.generate_content([prompt, google_file])
                        
                        # Limpiar y parsear JSON
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos = json.loads(match.group())
                            
                            # 5. GENERAR DXF
                            path_dxf = generar_dxf_profesional(datos)
                            
                            st.success("✅ Análisis y dibujo completados.")
                            
                            # Botón de Descarga
                            with open(path_dxf, "rb") as f:
                                st.download_button(
                                    label="💾 Descargar DXF para AutoCAD",
                                    data=f,
                                    file_name="poligonal_generada.dxf",
                                    mime="application/dxf"
                                )
                            st.json(datos)
                            break
                        else:
                            st.error("La IA no devolvió un formato válido.")
                
                except google.api_core.exceptions.ResourceExhausted:
                    st.warning("Cuota llena. Esperando reintento...")
                    time.sleep(10)
                except Exception as e:
                    st.error(f"Error en intento: {e}")
                    break

            # Limpiar archivo de la nube
            genai.delete_file(google_file.name)

        except Exception as e:
            st.error(f"Error crítico: {e}")
        finally:
            # Borrar archivo temporal local
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# --- PIE DE PÁGINA ---
st.divider()
st.caption("Norm.AI -  Miguel Guidos - Arquitectura & Tecnología | 2026")
