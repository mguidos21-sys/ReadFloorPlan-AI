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
st.set_page_config(page_title="Norm.AI - Topografía Integral", layout="wide")
st.title("📐 Extractor de Poligonales Completas (9 Páginas)")
st.markdown("Este módulo une todo el documento para generar la poligonal cerrada.")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos Gemini 1.5 Flash: es el mejor equilibrando cuota y capacidad multi-página
    model = genai.GenerativeModel('models/gemini-1.5-flash')
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. LÓGICA DE DIBUJO ---
def generar_dxf(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    # Dibujar geometría
    for t in tramos:
        try:
            d = float(t.get('distancia', 0))
            a = math.radians(float(t.get('angulo_deg', 0)))
            np = puntos[-1] + Vec2(math.cos(a) * d, math.sin(a) * d)
            
            if t.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        except: continue
        
    # Dibujar línea de cierre si no cerró automáticamente
    if len(puntos) > 2 and puntos[0].distance(puntos[-1]) > 0.01:
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'layer': 'CIERRE_NORM'})

    # Cuadro Técnico a la derecha
    x_tab = 20
    msp.add_text("CUADRO DE RUMBOS (UNIFICADO)", dxfattribs={'height': 0.8}).set_placement((x_tab, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_tab, -(i * 0.7)))

    path = os.path.join(tempfile.gettempdir(), f"poligonal_completa.dxf")
    doc.saveas(path)
    return path

# --- 3. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF completo de la escritura", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Generar Poligonal Cerrada"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Cosiendo {num_pags} páginas para análisis global...")

            # 1. RASTERIZADO UNIFICADO: Creamos una "tira" gigante de páginas
            with st.spinner("Creando imagen de ultra-baja resolución para la IA..."):
                all_pages = []
                # Zoom bajo (0.8) para que quepan muchas páginas sin agotar tokens
                matrix = fitz.Matrix(0.8, 0.8) 
                
                for i in range(num_pags):
                    page = doc_pdf.load_page(i)
                    pix = page.get_pixmap(matrix=matrix)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    all_pages.append(img)
                
                # Unir verticalmente las páginas en una sola imagen
                w = max(i.size[0] for i in all_pages)
                h = sum(i.size[1] for i in all_pages)
                combined_img = Image.new("RGB", (w, h))
                
                y_offset = 0
                for img in all_pages:
                    combined_img.paste(img, (0, y_offset))
                    y_offset += img.size[1]
                
                # Guardar imagen temporal
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    combined_img.save(tmp.name, "JPEG", quality=70) # Compresión extra
                    tmp_path = tmp.name

            # 2. SUBIR A GOOGLE (UN SOLO ARCHIVO)
            st.info("Subiendo documento consolidado...")
            g_file = genai.upload_file(path=tmp_path)
            while g_file.state.name == "PROCESSING":
                time.sleep(1)
                g_file = genai.get_file(g_file.name)

            # 3. PROMPT DE ANÁLISIS GLOBAL
            prompt = """
            Actúa como experto topógrafo. Se adjunta un documento de 9 páginas unido en una sola imagen.
            Contiene la descripción técnica de un terreno grande.
            1. Busca la sección de rumbos y distancias que comienza en una página y continúa en las siguientes.
            2. Extrae la secuencia completa y secuencial de tramos.
            3. Devuelve estrictamente un JSON unificado:
            {"tramos": [{"rumbo": "N 10°E", "distancia": 25.0, "tipo": "linea", "angulo_deg": 45}]}
            """

            with st.spinner("La IA está leyendo y uniendo todo el polígono..."):
                response = model.generate_content([prompt, g_file])
                
                match = re.search(r'\{.*\}', response.text, re.DOTALL)
                if match:
                    datos = json.loads(match.group())
                    ruta = generar_dxf(datos)
                    
                    st.success(f"✅ Poligonal de {len(datos['tramos'])} tramos generada.")
                    with open(ruta, "rb") as f:
                        st.download_button("💾 Descargar DXF Unificado", f, file_name="poligonal.dxf")
                    st.json(datos)
                else:
                    st.error("No se pudo extraer una estructura de rumbos válida de todo el documento.")

            # Limpieza
            genai.delete_file(g_file.name)
            os.remove(tmp_path)

        except Exception as e:
            st.error(f"Error crítico: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
