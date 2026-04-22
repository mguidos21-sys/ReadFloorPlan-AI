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

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Topografía y Curvas", layout="wide")
st.title("📐 Extractor de Poligonales con Soporte de Curvas")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key en Secrets.")
    st.stop()

# --- 2. MATEMÁTICA DE RUMBOS Y CURVAS ---
def parsear_rumbo(rumbo_str):
    if not rumbo_str or rumbo_str.lower() == 'none': return None
    match = re.search(r'([NS])\s*(\d+)[°°º]\s*(\d+)\'\s*(\d+(?:\.\d+)?)"\s*([EW])', rumbo_str, re.IGNORECASE)
    if match:
        ns, g, m, s, ew = match.groups()
        dec = float(g) + float(m)/60 + float(s)/3600
        ns, ew = ns.upper(), ew.upper()
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return None

def calcular_bulge(radio, longitud_arco):
    """Calcula el factor de curvatura para ezdxf basado en el arco y radio"""
    if radio == 0 or longitud_arco == 0: return 0
    # Ángulo central (theta) en radianes
    theta = longitud_arco / radio
    # El bulge es tan(theta/4)
    return math.tan(theta / 4)

# --- 3. LÓGICA DE DIBUJO ---
def generar_dxf_profesional(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for t in tramos:
        dist = float(t.get('distancia', 0))
        ang_rad = parsear_rumbo(t.get('rumbo'))
        
        if ang_rad is not None:
            # Calcular punto final del tramo (como si fuera recto)
            nuevo_punto = puntos[-1] + Vec2(math.cos(ang_rad) * dist, math.sin(ang_rad) * dist)
            
            if t.get('tipo') == 'curva' and t.get('radio'):
                try:
                    r = float(t.get('radio'))
                    l_arco = float(t.get('distancia')) # En curvas, la distancia suele ser la longitud de arco
                    bulge = calcular_bulge(r, l_arco)
                    
                    # Agregar polilínea con curvatura
                    msp.add_lwpolyline([puntos[-1], nuevo_punto], dxfattribs={'bulge': bulge})
                except:
                    msp.add_line(puntos[-1], nuevo_punto)
            else:
                msp.add_line(puntos[-1], nuevo_punto)
            
            puntos.append(nuevo_point if 'nuevo_point' in locals() else nuevo_punto)

    # Cuadro Técnico
    x_off = 25
    msp.add_text("CUADRO TÉCNICO (INCLUYE CURVAS)", dxfattribs={'height': 0.8}).set_placement((x_off, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        if t.get('radio'): txt += f" (R={t.get('radio')}m)"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_off, -(i * 0.8)))

    path = os.path.join(tempfile.gettempdir(), f"poligonal_curva_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 4. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Generar Poligonal con Curvas"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            
            with st.spinner("Analizando y uniendo páginas..."):
                all_pages_img = []
                for i in range(num_pags):
                    page = doc_pdf.load_page(i)
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    all_pages_img.append(img)
                
                # Unir imágenes
                w = max(i.size[0] for i in all_pages_img)
                h = sum(i.size[1] for i in all_pages_img)
                combined = Image.new("RGB", (w, h))
                y = 0
                for img in all_pages_img:
                    combined.paste(img, (0, y)); y += img.size[1]
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    combined.save(tmp.name, "JPEG", quality=75)
                    tmp_path = tmp.name

            st.info("Buscando Radio y Longitud de Arco...")
            g_file = genai.upload_file(path=tmp_path)
            while g_file.state.name == "PROCESSING": time.sleep(1); g_file = genai.get_file(g_file.name)

            prompt = """
            Extract survey data. Look closely for 'Radio' or 'Arco' in curved segments.
            Example input: 'Norte 87° 40' Oeste, tramo curvo con radio de 10.0m y arco de 6.0m'.
            JSON format: {"tramos": [{"rumbo": "N 87° 40' 00\" W", "distancia": 6.0, "tipo": "curva", "radio": 10.0}]}
            Return ONLY JSON.
            """

            response = model.generate_content([prompt, g_file])
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            
            if match:
                datos = json.loads(match.group())
                ruta = generar_dxf_profesional(datos['tramos'])
                st.success("✅ ¡Poligonal con curvas generada!")
                with open(ruta, "rb") as f:
                    st.download_button("💾 Descargar DXF", f, file_name="poligonal_curvas.dxf")
                st.json(datos)
            
            genai.delete_file(g_file.name)
            os.remove(tmp_path)

        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
