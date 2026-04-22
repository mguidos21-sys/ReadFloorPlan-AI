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
st.set_page_config(page_title="Norm.AI - Topografía 2.5", layout="wide")
st.title("📐 Extractor de Poligonales (Gemini 2.5 Stable)")

# USAMOS EL MODELO QUE APARECE EN TU LISTA
MODELO_DISPONIBLE = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_DISPONIBLE)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. LÓGICA DE DIBUJO ---
def generar_dxf(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for t in tramos:
        try:
            dist = float(t.get('distancia', 0))
            # Convertimos el ángulo que nos da la IA
            ang = math.radians(float(t.get('angulo_deg', 0)))
            np = puntos[-1] + Vec2(math.cos(ang) * dist, math.sin(ang) * dist)
            
            if t.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        except: continue
        
    # Crear Cuadro de Datos a un lado
    x_tab = max([p.x for p in puntos]) + 10 if puntos else 20
    msp.add_text("CUADRO TÉCNICO NORM.AI", dxfattribs={'height': 0.8}).set_placement((x_tab, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_tab, -(i * 0.7)))

    path = os.path.join(tempfile.gettempdir(), f"poligonal_2.5_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 3. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura (9 páginas)", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Procesar Poligonal Completa"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Preparando {num_pags} páginas para Gemini 2.5...")

            imagenes_para_ia = []
            
            # 1. CONVERTIR CADA PÁGINA EN IMAGEN
            with st.spinner("Leyendo páginas..."):
                for i in range(num_pags):
                    page = doc_pdf.load_page(i)
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    img_path = os.path.join(tempfile.gettempdir(), f"p_{i}.jpg")
                    
                    # Guardar como JPG optimizado
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img.thumbnail((1200, 1200))
                    img.save(img_path, "JPEG", quality=80)
                    
                    # Subir a Google
                    g_file = genai.upload_file(path=img_path)
                    imagenes_para_ia.append(g_file)
                    os.remove(img_path)

            # 2. ESPERAR PROCESAMIENTO
            while any(f.state.name == "PROCESSING" for f in imagenes_para_ia):
                time.sleep(1)
                imagenes_para_ia = [genai.get_file(f.name) for f in imagenes_para_ia]

            # 3. PROMPT DE INGENIERÍA
            prompt = """
            Eres un experto en topografía salvadoreña. Se adjuntan varias páginas de una escritura.
            1. Busca la descripción técnica de rumbos y distancias. 
            2. Conecta los datos de todas las páginas para formar una sola poligonal continua.
            3. Devuelve estrictamente un JSON unificado con TODOS los tramos encontrados:
            {"tramos": [{"rumbo": "N 10° 15' 20\" E", "distancia": 25.40, "tipo": "linea", "angulo_deg": 45.0}]}
            """

            with st.spinner("La IA está uniendo los rumbos..."):
                # Enviamos el prompt y la lista completa de imágenes
                response = model.generate_content([prompt] + imagenes_para_ia)
                
                match = re.search(r'\{.*\}', response.text, re.DOTALL)
                if match:
                    datos = json.loads(match.group())
                    if datos.get('tramos'):
                        ruta = generar_dxf(datos['tramos'])
                        st.success(f"✅ Se generaron {len(datos['tramos'])} tramos.")
                        with open(ruta, "rb") as f:
                            st.download_button("💾 Descargar DXF Final", f, file_name="poligonal_completa.dxf")
                        st.json(datos)
                    else:
                        st.warning("No se detectaron tramos técnicos en las páginas.")
                else:
                    st.error("La IA no pudo estructurar los datos. Verifica que el PDF sea legible.")

            # Limpiar archivos de Google
            for f in imagenes_para_ia:
                genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Error detectado: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
