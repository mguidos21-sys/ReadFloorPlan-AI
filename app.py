import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os
import ezdxf  # Librería para crear el CAD
import json
import re

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Poligonal a CAD", layout="centered")
st.title("🏗️ Extractor de Poligonal a DWG/DXF")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Falta API Key.")
    st.stop()

model = genai.GenerativeModel(model_name='models/gemini-2.5-flash')

# --- FUNCIÓN PARA CREAR EL ARCHIVO CAD ---
def crear_dxf(puntos):
    doc = ezdxf.new('R2010')  # Crea un nuevo dibujo DXF
    msp = doc.modelspace()
    
    # Si tenemos puntos, dibujamos la polilínea
    if len(puntos) > 1:
        # Cerramos la poligonal volviendo al primer punto
        puntos.append(puntos[0])
        msp.add_lwpolyline(puntos)
    
    path = "poligonal_generada.dxf"
    doc.saveas(path)
    return path

# --- INTERFAZ ---
uploaded_file = st.file_uploader("Sube el plano de la poligonal", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    if st.button("Generar Poligonal CAD"):
        try:
            with st.spinner("Extrayendo geometría..."):
                # 1. Guardar temporal y subir
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                
                google_file = genai.upload_file(path=tmp_path)

                # 2. PROMPT ESPECÍFICO PARA COORDENADAS
                prompt = (
                    "Analiza la poligonal de este plano. "
                    "Extrae los vértices (x, y) de la poligonal principal. "
                    "Devuelve ÚNICAMENTE un JSON con este formato: {'puntos': [[x1, y1], [x2, y2], ...]} "
                    "Usa números relativos o coordenadas detectadas en el plano."
                )

                response = model.generate_content([prompt, google_file])
                
                # 3. EXTRAER JSON DEL TEXTO (Limpieza de markdown)
                texto_respuesta = response.text
                match = re.search(r'\{.*\}', texto_respuesta, re.DOTALL)
                
                if match:
                    datos = json.loads(match.group())
                    puntos = datos.get('puntos', [])
                    
                    if puntos:
                        # 4. CREAR EL ARCHIVO CAD
                        archivo_cad = crear_dxf(puntos)
                        
                        st.success("✅ Poligonal extraída correctamente.")
                        
                        # 5. BOTÓN DE DESCARGA
                        with open(archivo_cad, "rb") as file:
                            st.download_button(
                                label="💾 Descargar Poligonal (.DXF)",
                                data=file,
                                file_name="poligonal_norm_ai.dxf",
                                mime="application/dxf"
                            )
                        st.info("Nota: El archivo está en formato DXF. Ábrelo en AutoCAD y guárdalo como DWG.")
                    else:
                        st.warning("No se detectaron puntos claros en la imagen.")
                else:
                    st.error("La IA no pudo formatear las coordenadas correctamente.")
                
                # Limpieza
                genai.delete_file(google_file.name)
                os.remove(tmp_path)

        except Exception as e:
            st.error(f"Error: {e}")
