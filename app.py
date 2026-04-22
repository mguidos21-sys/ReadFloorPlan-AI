import streamlit as st
import google.generativeai as genai
import google.api_core.exceptions
import ezdxf
from ezdxf.math import Vec2
from PyPDF2 import PdfReader, PdfWriter
import json
import re
import math
import os
import tempfile
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Extractor de Poligonales", layout="wide")
st.title("📐 Generador de Poligonales desde PDF")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Flash-Lite es el mejor para no agotar la cuota de tokens
    model = genai.GenerativeModel('models/gemini-2.0-flash-lite')
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- LÓGICA DE DIBUJO ---
def generar_dxf(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    for t in tramos:
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
    
    path = os.path.join(tempfile.gettempdir(), f"poligonal_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- INTERFAZ ---
archivo = st.file_uploader("Sube el PDF de la escritura/memoria", type=["pdf"])

if archivo:
    # Leer el PDF para saber cuántas páginas tiene
    reader = PdfReader(archivo)
    num_paginas = len(reader.pages)
    
    st.info(f"El documento tiene {num_paginas} páginas.")
    
    # Selector de página para ahorrar CUOTA
    pag_seleccionada = st.number_input("¿En qué página están los rumbos y distancias?", 
                                       min_value=1, max_value=num_paginas, value=1)

    if st.button("🚀 Generar Poligonal de esta página"):
        try:
            # 1. Extraer solo la página seleccionada para NO saturar la cuota
            writer = PdfWriter()
            writer.add_page(reader.pages[pag_seleccionada - 1])
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                writer.write(tmp)
                tmp_path = tmp.name

            # 2. Subir a Google
            g_file = genai.upload_file(path=tmp_path)
            while g_file.state.name == "PROCESSING":
                time.sleep(2)
                g_file = genai.get_file(g_file.name)

            prompt = "Analiza los rumbos y distancias de esta página. Genera JSON: {'tramos': [{'rumbo': 'N 10E', 'distancia': 20.0, 'tipo': 'linea', 'angulo_deg': 45}]}"

            with st.spinner("Analizando datos..."):
                response = model.generate_content([prompt, g_file])
                match = re.search(r'\{.*\}', response.text, re.DOTALL)
                
                if match:
                    datos = json.loads(match.group())
                    dxf_path = generar_dxf(datos)
                    st.success("✅ Poligonal extraída.")
                    with open(dxf_path, "rb") as f:
                        st.download_button("💾 Descargar DXF", f, file_name="poligonal.dxf")
                    st.json(datos)
                else:
                    st.error("No se encontró formato de rumbos en esta página.")

            genai.delete_file(g_file.name)
            os.remove(tmp_path)

        except google.api_core.exceptions.ResourceExhausted:
            st.error("🛑 Cuota llena. El documento sigue siendo muy pesado. Intenta subir una foto de la página.")
        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
