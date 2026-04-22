import streamlit as st
import google.generativeai as genai
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

# --- 1. CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Norm.AI - Topografía Definitiva", layout="wide")
st.title("📐 Extractor de Poligonales (Resolución Geométrica)")

# MODELO SELECCIONADO (De tu lista confirmada)
MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Falta API Key en Secrets.")
    st.stop()

# --- 2. FUNCIÓN MAESTRA DE CONVERSIÓN DE RUMBOS (El Arreglo) ---
def parsear_rumbo_salvadoreno(rumbo_str):
    """
    Convierte 'N 02° 35' 01" E' a ángulo cartesiano en radianes (N=90, E=0, S=270, W=180).
    Soporta formato decimal si la IA falla.
    """
    if not rumbo_str or rumbo_str.lower() == 'none':
        return None, "Error: Rumbo incompleto"

    # Regex para el formato estándar de escritura (N 02° 35' 01" E)
    match = re.match(r'([NS])\s*(\d+)[°°º]\s*(\d+)\'\s*(\d+(?:\.\d+)?)"\s*([EW])', rumbo_str, re.IGNORECASE)
    
    if match:
        cuadrante_ns = match.group(1).upper()
        grados = float(match.group(2))
        minutos = float(match.group(3))
        segundos = float(match.group(4))
        cuadrante_ew = match.group(5).upper()
        
        # Convertir DMS a decimal
        angulo_decimal = grados + (minutos / 60) + (segundos / 3600)
    else:
        # Intento de parseo de formato decimal si la IA lo da
        decimal_match = re.match(r'([NS])\s*(\d+(?:\.\d+)?)\s*([EW])', rumbo_str, re.IGNORECASE)
        if decimal_match:
            cuadrante_ns = decimal_match.group(1).upper()
            angulo_decimal = float(decimal_match.group(2))
            cuadrante_ew = decimal_match.group(3).upper()
        else:
            return None, f"Error formato: {rumbo_str}"

    # Lógica Topográfica a Cartesiana
    # Partimos de Norte = 90 grados cartesianos
    if cuadrante_ns == 'N' and cuadrante_ew == 'E':
        angulo_cartesiano = 90 - angulo_decimal
    elif cuadrante_ns == 'N' and cuadrante_ew == 'W':
        angulo_cartesiano = 90 + angulo_decimal
    elif cuadrante_ns == 'S' and cuadrante_ew == 'E':
        angulo_cartesiano = 270 + angulo_decimal
    elif cuadrante_ns == 'S' and cuadrante_ew == 'W':
        angulo_cartesiano = 270 - angulo_decimal
    else:
        return None, "Error Cuadrante"

    return math.radians(angulo_cartesiano), angulo_decimal

# --- 3. LÓGICA DE DIBUJO ---
def generar_dxf_geometria_real(tramos):
    doc = ezdxf.new('R2010')
    doc.layers.add("NOTAS", color=1) # Layer para errores
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    # Dibujar geometría
    for i, t in enumerate(tramos):
        dist_raw = t.get('distancia', 0)
        try:
            dist = float(dist_raw)
        except:
            msp.add_text(f"E{i+1}: Distancia invalida ({dist_raw})", dxfattribs={'layer': 'NOTAS', 'height': 0.5}).set_placement((0, -(i+1)))
            continue

        rumbo_str = t.get('rumbo')
        angulo_rad, decimal_grados = parsear_rumbo_salvadoreno(rumbo_str)
        
        if angulo_rad is not None:
            # Cálculo Cartesiano Real: Delta X = Dist * cos(ang), Delta Y = Dist * sin(ang)
            np = puntos[-1] + Vec2(math.cos(angulo_rad) * dist, math.sin(angulo_rad) * dist)
            
            if t.get('tipo') == 'curva':
                msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
            else:
                msp.add_line(puntos[-1], np)
            puntos.append(np)
        else:
            msp.add_text(f"E{i+1}: {decimal_grados}", dxfattribs={'layer': 'NOTAS', 'height': 0.5}).set_placement((0, -(i+1)))

    # Cuadro Técnico a la derecha (este ya funcionaba)
    x_off = 20
    msp.add_text("CUADRO TÉCNICO NORM.AI", dxfattribs={'height': 0.8}).set_placement((x_off, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_off, -(i * 0.7)))

    path = os.path.join(tempfile.gettempdir(), f"poligonal_real_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 4. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura (9 páginas)", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Generar Poligonal Geométrica"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            st.info(f"Cosiendo {num_pags} páginas...")

            # RASTERIZADO UNIFICADO: Creamos una tira gigante (Zoom 0.9 para balance cuota/legibilidad)
            with st.spinner("Creando imagen global..."):
                all_pages = []
                for i in range(num_pags):
                    page = doc_pdf.load_page(i)
                    pix = page.get_pixmap(matrix=fitz.Matrix(0.9, 0.9))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    all_pages.append(img)
                
                w = max(i.size[0] for i in all_pages)
                h = sum(i.size[1] for i in all_pages)
                combined_img = Image.new("RGB", (w, h))
                y_off = 0
                for img in all_pages:
                    combined_img.paste(img, (0, y_off))
                    y_off += img.size[1]
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    combined_img.save(tmp.name, "JPEG", quality=75)
                    tmp_path = tmp.name

            # SUBIR A GOOGLE
            st.info("Subiendo documento...")
            g_file = genai.upload_file(path=tmp_path)
            while g_file.state.name == "PROCESSING":
                time.sleep(1)
                g_file = genai.get_file(g_file.name)

            # PROMPT DE INGENIERÍA
            prompt = """
            Extract survey bearings and distances from ALL 9 PAGES shown.
            They are continuous technical memory data.
            Extract strictly structured JSON. Ensure no 'None' values in bearings.
            Output JSON: {"tramos": [{"rumbo": "N 02° 35' 01\" E", "distancia": 15.0, "tipo": "linea"}]}
            """

            with st.spinner("La IA está uniendo la poligonal..."):
                response = model.generate_content([prompt, g_file])
                match = re.search(r'\{.*\}', response.text, re.DOTALL)
                
                if match:
                    datos = json.loads(match.group())
                    if datos.get('tramos'):
                        ruta = generar_dxf_geometria_real(datos['tramos'])
                        st.success(f"✅ Poligonal de {len(datos['tramos'])} tramos generada.")
                        with open(ruta, "rb") as f:
                            st.download_button("💾 Descargar DXF Geométrico Real", f, file_name="poligonal.dxf")
                        st.json(datos)
                    else: st.warning("No se detectaron tramos.")
                else: st.error("No se pudo estructurar los datos de rumbos.")

            genai.delete_file(g_file.name)
            os.remove(tmp_path)

        except Exception as e:
            st.error(f"Error crítico: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
