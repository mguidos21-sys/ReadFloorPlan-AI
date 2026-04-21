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
st.set_page_config(page_title="Norm.AI - Topografía & CAD", layout="centered")
st.title("🏗️ Lector de Planos y Generador de Poligonales")
st.markdown("Extrae rumbos y distancias automáticamente para generar archivos DXF.")

# --- 2. CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos Gemini 2.5 Flash (Verificado en tu cuenta)
    model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("⚠️ Falta la 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# --- 3. LÓGICA DE DIBUJO CAD (DXF) ---
def generar_dxf_profesional(datos):
    """Crea un archivo DXF con la poligonal y un cuadro técnico."""
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    
    # Dibujar Poligonal
    for tramo in tramos:
        dist = float(tramo.get('distancia', 0))
        # Convertimos el ángulo sugerido por la IA a radianes
        angulo_rad = math.radians(float(tramo.get('angulo_deg', 0)))
        
        # Calcular siguiente punto
        nuevo_punto = puntos[-1] + Vec2(math.cos(angulo_rad) * dist, math.sin(angulo_rad) * dist)
        
        if tramo.get('tipo') == 'curva':
            # El 'bulge' crea el arco en la polilínea (0.4 es una curvatura estándar)
            msp.add_lwpolyline([puntos[-1], nuevo_punto], dxfattribs={'bulge': 0.4})
        else:
            msp.add_line(puntos[-1], nuevo_punto)
        
        puntos.append(nuevo_point)

    # --- GENERAR CUADRO TÉCNICO EN EL CAD ---
    x_tabla, y_tabla = 20, 0  # Posición a la derecha del dibujo
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 0.6}).set_placement((x_tabla, y_tabla + 2))
    
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.35}).set_placement((x_tabla, y_tabla - (i * 0.6)))

    path = "poligonal_norm_ai.dxf"
    doc.saveas(path)
    return path

# --- 4. INTERFAZ DE USUARIO ---
archivo = st.file_uploader("Sube plano o memoria descriptiva (PDF, JPG, PNG)", type=["pdf", "jpg", "png"])

if archivo:
    if st.button("🚀 Procesar Poligonal y Generar CAD", key="btn_analisis_final"):
        
        # Manejo de archivos temporales
        extension = archivo.name.split('.')[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}") as tmp:
            tmp.write(archivo.getvalue())
            tmp_path = tmp.name
        
        try:
            # Subir archivo a Google
            google_file = genai.upload_file(path=tmp_path)
            
            # Lógica de reintentos para evitar ResourceExhausted
            intentos_max = 3
            exito = False
            
            for i in range(intentos_max):
                try:
                    with st.spinner(f"Analizando con Gemini 2.5 (Intento {i+1}/3)..."):
                        prompt = """
                        Actúa como experto topógrafo. Analiza el documento y extrae la poligonal.
                        Busca rumbos, distancias y datos de curvas.
                        Devuelve estrictamente un JSON con este formato:
                        {
                          "tramos": [
                            {"rumbo": "N 10°E", "distancia": 25.0, "tipo": "linea", "angulo_deg": 45},
                            {"rumbo": "S 80°E", "distancia": 12.0, "tipo": "curva", "radio": 5.0, "angulo_deg": -10}
                          ]
                        }
                        """
                        response = model.generate_content([prompt, google_file])
                        
                        # Extraer JSON de la respuesta
                        match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if match:
                            datos_ia = json.loads(match.group())
                            
                            # Generar archivo DXF
                            ruta_dxf = generar_dxf_profesional(datos_ia)
                            
                            st.success("✅ Poligonal procesada correctamente.")
                            
                            # Botón de descarga
                            with open(ruta_dxf, "rb") as f:
                                st.download_button(
                                    label="📥 Descargar Poligonal (.DXF)",
                                    data=f,
                                    file_name="poligonal_norm_ai.dxf",
                                    mime="application/dxf"
                                )
                            
                            st.json(datos_ia) # Mostrar datos para revisión
                            exito = True
                            break
                
                except google.api_core.exceptions.ResourceExhausted:
                    if i < intentos_max - 1:
                        st.warning("⚠️ Límites de Google alcanzados. Esperando 10 segundos...")
                        time.sleep(10)
                    else:
                        st.error("No se pudo completar el análisis por falta de cuota.")
                
                except Exception as e:
                    st.error(f"Error en intento {i+1}: {e}")
                    break

            # Limpiar archivo en la nube
            genai.delete_file(google_file.name)

        except Exception as e:
            st.error(f"Error crítico: {e}")
        
        finally:
            # Borrar archivo temporal local
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# --- PIE DE PÁGINA ---
st.divider()
st.caption("Norm.AI | Daniel González - Arquitectura & Tecnología")
