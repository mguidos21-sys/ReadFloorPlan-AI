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
st.markdown("Extracción técnica de rumbos, distancias y curvas para AutoCAD.")

# --- 2. CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos Gemini 1.5 Flash o 2.0 Flash por estabilidad en procesamiento de archivos
    model = genai.GenerativeModel('models/gemini-1.5-flash')
else:
    st.error("⚠️ Configura 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# --- 3. LÓGICA DE DIBUJO CAD (DXF) ---
def generar_dxf_profesional(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    
    # Dibujar la geometría de la poligonal
    for tramo in tramos:
        try:
            dist = float(tramo.get('distancia', 0))
            # Ángulo convertido de la interpretación de la IA
            angulo_rad = math.radians(float(tramo.get('angulo_deg', 0)))
            
            # Calcular siguiente vértice
            nuevo_punto = puntos[-1] + Vec2(math.cos(angulo_rad) * dist, math.sin(angulo_rad) * dist)
            
            if tramo.get('tipo') == 'curva':
                # El bulge define la curvatura del arco
                msp.add_lwpolyline([puntos[-1], nuevo_punto], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], nuevo_punto)
            
            puntos.append(nuevo_punto)
        except:
            continue

    # --- GENERAR CUADRO DE DATOS TÉCNICOS ---
    # Posicionamos el cuadro a la derecha de la poligonal
    x_offset = max([p.x for p in puntos]) + 10 if puntos else 20
    y_offset = 0
    
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 0.8}).set_placement((x_offset, 5))
    
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_offset, y_offset))
        y_offset -= 0.8

    temp_dxf = os.path.join(tempfile.gettempdir(), "poligonal_normai.dxf")
    doc.saveas(temp_dxf)
    return temp_dxf

# --- 4. INTERFAZ Y PROCESAMIENTO ---
archivo = st.file_uploader("Sube plano o memoria técnica (PDF, JPG, PNG)", type=["pdf", "jpg", "png"])

if archivo:
    if st.button("🚀 Iniciar Análisis de Ingeniería", key="btn_analisis_vfinal"):
        
        # Guardar archivo temporal
        ext = archivo.name.split('.')[-1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(archivo.getvalue())
            tmp_path = tmp.name
        
        try:
            # OPTIMIZACIÓN: Si es imagen, reducimos peso para ahorrar cuota de tokens
            if ext in ['jpg', 'jpeg', 'png']:
                with Image.open(tmp_path) as img:
                    img.thumbnail((1800, 1800))
                    img.save(tmp_path, optimize=True, quality=85)

            # Subir a Google
            st.info("Subiendo archivo a Google AI Studio...")
            google_file = genai.upload_file(path=tmp_path)
            
            # ESPERA DE PROCESAMIENTO (Evita Error 400)
            with st.spinner("Esperando que la IA procese el documento..."):
                while google_file.state.name == "PROCESSING":
                    time.sleep(2)
                    google_file = genai.get_file(google_file.name)
            
            if google_file.state.name != "ACTIVE":
                st.error(f"Error en archivo: {google_file.state.name}")
                st.stop()

            # PROMPT TÉCNICO
            prompt = """
            Actúa como un experto en topografía y catastro. 
            Analiza el documento y extrae la poligonal principal.
            Identifica rumbos, distancias y datos de curvas (radio, longitud).
            Devuelve estrictamente un JSON con este formato:
            {
              "tramos": [
                {"rumbo": "N 10°E", "distancia": 25.0, "tipo": "linea", "angulo_deg": 45},
                {"rumbo": "S 80°E", "distancia": 12.0, "tipo": "curva", "radio": 5.0, "angulo_deg": -10}
              ]
            }
            """
            
            # Bucle de reintentos por cuota
            intentos = 3
            for i in range(intentos):
                try:
                    with st.spinner(f"Analizando (Intento {i+1}/3)..."):
                        response = model.generate_content([prompt, google_file])
                        
                        # Parsear JSON
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos = json.loads(match.group())
                            
                            # Generar DXF
                            path_dxf = generar_dxf_profesional(datos)
                            
                            st.success("✅ Geometría y Cuadro Técnico generados.")
                            
                            # Botón de Descarga
                            with open(path_dxf, "rb") as f:
                                st.download_button(
                                    label="💾 Descargar DXF para AutoCAD",
                                    data=f,
                                    file_name="poligonal_normai.dxf",
                                    mime="application/dxf"
                                )
                            st.json(datos)
                            break
                        else:
                            st.error("La IA no pudo estructurar los datos. Intenta con una imagen más clara.")
                            break
                
                except google.api_core.exceptions.ResourceExhausted:
                    if i < intentos - 1:
                        # Si la cuota está llena, esperamos más tiempo para liberar tokens
                        st.warning("⚠️ Límite de tokens alcanzado. Esperando 25 segundos para continuar...")
                        time.sleep(25)
                    else:
                        st.error("🛑 Cuota de Google agotada. Por favor, intenta comprimir el plano.")
                
                except Exception as e:
                    st.error(f"Error en procesamiento: {e}")
                    break

            # Limpiar nube
            genai.delete_file(google_file.name)

        except Exception as e:
            st.error(f"Error crítico: {e}")
        finally:
            # Limpiar servidor local
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# --- PIE DE PÁGINA ---
st.divider()
st.caption("Norm.AI | Miguel Guidos - Arquitectura & Tecnología 2026")
