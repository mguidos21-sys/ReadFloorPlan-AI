import streamlit as st
import google.generativeai as genai
import google.api_core.exceptions
import ezdxf
from ezdxf.math import Vec2
import fitz  # PyMuPDF
import json
import re
import math
import os
import tempfile
import time

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Topografía Integral", layout="wide")
st.title("📐 Extractor de Poligonales Multi-página")
st.markdown("Este módulo analiza todo el PDF automáticamente para encontrar la poligonal completa.")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos Flash-Lite por su enorme ventana de contexto y eficiencia de cuota
    model = genai.GenerativeModel('models/gemini-2.0-flash-lite')
else:
    st.error("Falta API Key en Secrets.")
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
            # La IA nos da el ángulo calculado del rumbo
            ang = math.radians(float(tramo.get('angulo_deg', 0)))
            np = puntos[-1] + Vec2(math.cos(ang) * dist, math.sin(ang) * dist)
            
            if tramo.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        except: continue

    # Cuadro Técnico automático
    x_tab = 20
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 0.8}).set_placement((x_tab, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_tab, -(i * 0.7)))

    path = os.path.join(tempfile.gettempdir(), f"poligonal_completa.dxf")
    doc.saveas(path)
    return path

# --- 3. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF completo de la escritura", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Procesar Documento Completo"):
        try:
            # Abrir PDF
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Procesando {num_pags} páginas...")

            google_files = []
            progress_bar = st.progress(0)

            # 1. CONVERTIR CADA PÁGINA A IMAGEN OPTIMIZADA
            # Usamos una resolución menor (1.2) para que quepan muchas páginas en la cuota
            with st.spinner("Preparando páginas para la IA..."):
                for i in range(num_pags):
                    pagina = doc_pdf.load_page(i)
                    pix = pagina.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)) 
                    img_path = os.path.join(tempfile.gettempdir(), f"pag_{i}.jpg")
                    pix.save(img_path)
                    
                    # Subir a Google
                    g_file = genai.upload_file(path=img_path)
                    google_files.append(g_file)
                    
                    # Actualizar progreso
                    progress_bar.progress((i + 1) / num_pags)
                    os.remove(img_path)

            # 2. ESPERAR A QUE TODOS ESTÉN "ACTIVE"
            with st.spinner("Google está indexando las páginas..."):
                for gf in google_files:
                    while gf.state.name == "PROCESSING":
                        time.sleep(1)
                        gf = genai.get_file(gf.name)

            # 3. PROMPT PARA ANÁLISIS GLOBAL
            prompt = """
            Analiza TODAS las páginas proporcionadas. Contienen la descripción técnica de un terreno.
            1. Busca la sección de 'Rumbos y Distancias'. 
            2. Es probable que la lista comience en una página y continúe en las siguientes.
            3. Extrae la secuencia COMPLETA sin saltarte tramos.
            4. Devuelve UN SOLO JSON con todos los tramos combinados:
            {"tramos": [{"rumbo": "N 10°E", "distancia": 25.0, "tipo": "linea", "angulo_deg": 45}]}
            """

            with st.spinner("La IA está leyendo y uniendo la poligonal..."):
                # Enviamos la lista completa de archivos
                response = model.generate_content([prompt] + google_files)
                
                match = re.search(r'\{.*\}', response.text, re.DOTALL)
                if match:
                    datos = json.loads(match.group())
                    dxf_path = generar_dxf(datos)
                    
                    st.success(f"✅ Se detectaron {len(datos['tramos'])} tramos en todo el documento.")
                    with open(dxf_path, "rb") as f:
                        st.download_button("💾 Descargar Poligonal Completa (DXF)", f, 
                                         file_name="poligonal_normai_completa.dxf")
                    st.json(datos)
                else:
                    st.error("No se pudo extraer una estructura de rumbos válida de estas páginas.")

            # Limpieza en la nube
            for gf in google_files:
                genai.delete_file(gf.name)

        except google.api_core.exceptions.ResourceExhausted:
            st.error("🛑 El documento es demasiado extenso para procesarlo en un solo minuto. Prueba separándolo en grupos de 10 páginas.")
        except Exception as e:
            st.error(f"Error crítico: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
