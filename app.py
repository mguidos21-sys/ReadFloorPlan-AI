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
st.set_page_config(page_title="Norm.AI - Topografía El Salvador", layout="wide")
st.title("📐 Extractor de Poligonales (Versión Multi-Formato)")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Falta API Key en Secrets.")
    st.stop()

# --- 2. MATEMÁTICA CORREGIDA (Soporta grados y minutos sin segundos) ---
def parsear_rumbo_flexible(rumbo_str):
    if not rumbo_str or rumbo_str.lower() == 'none': return None
    
    # Regex mejorada: Grados y minutos obligatorios, segundos OPCIONALES
    # Soporta: N 87° 40' W  O  N 87° 40' 15" W
    match = re.search(r'([NSns])\s*(\d+)[°°º]?\s*(\d+)\'?\s*(?:(\d+(?:\.\d+)?)\s*")?\s*([OEWew])', rumbo_str, re.IGNORECASE)
    
    if match:
        ns, g, m, s, ew = match.groups()
        segundos = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + segundos/3600
        
        ns, ew = ns.upper(), ew.upper()
        # En El Salvador 'O' es Oeste (West)
        if ew == 'O': ew = 'W'
        
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return None

# --- 3. LÓGICA DE DIBUJO ---
def generar_dxf_robusto(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for i, t in enumerate(tramos):
        try:
            dist = float(t.get('distancia', 0))
            rumbo_txt = t.get('rumbo', '')
            ang_rad = parsear_rumbo_flexible(rumbo_txt)
            
            if ang_rad is not None:
                np = puntos[-1] + Vec2(math.cos(ang_rad) * dist, math.sin(ang_rad) * dist)
                
                # Si es curva y tenemos radio, dibujamos arco. Si no, línea recta.
                if t.get('tipo') == 'curva' and t.get('radio'):
                    r = float(t.get('radio'))
                    # Bulge simple para representación visual
                    msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4})
                else:
                    msp.add_line(puntos[-1], np)
                
                puntos.append(np)
            else:
                # Si falla el rumbo, dejamos una marca de error en el CAD
                msp.add_text(f"ERROR L{i+1}", dxfattribs={'height': 0.5}).set_placement(puntos[-1])
        except Exception as e:
            continue

    # Cuadro de datos
    x_f = 25
    msp.add_text("CUADRO DE DATOS NORM.AI", dxfattribs={'height': 0.8}).set_placement((x_f, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_f, -(i * 0.8)))

    path = os.path.join(tempfile.gettempdir(), f"pol_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 4. INTERFAZ ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Generar Poligonal"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            
            with st.spinner("Uniendo páginas para análisis..."):
                all_img = []
                for i in range(num_pags):
                    page = doc_pdf.load_page(i)
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    all_img.append(img)
                
                w = max(i.size[0] for i in all_img)
                h = sum(i.size[1] for i in all_img)
                combined = Image.new("RGB", (w, h))
                y = 0
                for img in all_img:
                    combined.paste(img, (0, y)); y += img.size[1]
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    combined.save(tmp.name, "JPEG", quality=80)
                    tmp_path = tmp.name

            g_file = genai.upload_file(path=tmp_path)
            while g_file.state.name == "PROCESSING": time.sleep(1); g_file = genai.get_file(g_file.name)

            prompt = """
            Eres un experto en catastro. Analiza las imágenes y busca el cuadro de rumbos.
            Extrae los linderos. Los segundos en los rumbos son opcionales.
            Si dice 'tramo curvo', pon tipo:'curva'. Si encuentras un Radio (R=), inclúyelo.
            JSON: {"tramos": [{"rumbo": "N 87° 40' W", "distancia": 6.0, "tipo": "curva"}]}
            """

            response = model.generate_content([prompt, g_file])
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            
            if match:
                datos = json.loads(match.group())
                ruta = generar_dxf_robusto(datos['tramos'])
                st.success("✅ Poligonal generada correctamente.")
                with open(ruta, "rb") as f:
                    st.download_button("💾 Descargar DXF", f, file_name="poligonal_normai.dxf")
                st.json(datos)
            
            genai.delete_file(g_file.name)
            os.remove(tmp_path)

        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
