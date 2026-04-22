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
st.title("📐 Extractor de Poligonales (Versión Pro-Curvas)")

# MODELO CONFIRMADO EN TU LISTA
MODELO_ACTIVO = 'gemini-2.0-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Falta API Key en Secrets.")
    st.stop()

# --- 2. MATEMÁTICA TOPOGRÁFICA ROBUSTA ---
def parsear_rumbo_sv(rumbo_str):
    if not rumbo_str or rumbo_str.lower() == 'none': return None
    
    # Reemplazos para términos salvadoreños comunes
    r = rumbo_str.upper().replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E')
    r = r.replace('NORTE', 'N').replace('SUR', 'S')
    
    # Regex flexible: Grados y minutos obligatorios, segundos opcionales
    match = re.search(r'([NS])\s*(\d+)[°°º]?\s*(\d+)\'?\s*(?:(\d+(?:\.\d+)?)\s*")?\s*([EW])', r)
    
    if match:
        ns, g, m, s, ew = match.groups()
        segundos = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + segundos/3600
        
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return None

# --- 3. LÓGICA DE DIBUJO ---
def generar_dxf_final(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for i, t in enumerate(tramos):
        try:
            dist = float(t.get('distancia', 0))
            ang_rad = parsear_rumbo_sv(t.get('rumbo', ''))
            
            if ang_rad is not None:
                # Calculamos el siguiente vértice
                np = puntos[-1] + Vec2(math.cos(ang_rad) * dist, math.sin(ang_rad) * dist)
                
                # Manejo de Curvas
                if t.get('tipo') == 'curva':
                    # Si no hay radio, usamos un radio genérico (distancia * 1.5) para que se vea la curva
                    radio = float(t.get('radio')) if t.get('radio') else dist * 1.2
                    # El bulge define la panza de la curva (0.4 es una curva suave estándar)
                    msp.add_lwpolyline([puntos[-1], np], dxfattribs={'bulge': 0.4, 'color': 3})
                else:
                    msp.add_line(puntos[-1], np)
                
                puntos.append(np)
            else:
                st.warning(f"No se pudo entender el rumbo del tramo {i+1}: {t.get('rumbo')}")
        except Exception as e:
            continue

    # Cierre automático visual (Línea punteada al punto de origen)
    if len(puntos) > 2:
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'linetype': 'DASHED', 'color': 1})

    # Cuadro de Datos
    x_c = 30
    msp.add_text("CUADRO TÉCNICO NORM.AI", dxfattribs={'height': 0.8}).set_placement((x_c, 5))
    for i, t in enumerate(tramos):
        txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_c, -(i * 0.8)))

    path = os.path.join(tempfile.gettempdir(), f"poligonal_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# --- 4. INTERFAZ Y PROCESAMIENTO ---
archivo_pdf = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo_pdf:
    if st.button("🚀 Generar Plano Técnico Completo"):
        try:
            doc_pdf = fitz.open(stream=archivo_pdf.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            
            with st.spinner("Uniendo y analizando páginas..."):
                all_imgs = []
                for i in range(num_pags):
                    page = doc_pdf.load_page(i)
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    all_imgs.append(img)
                
                # Unión vertical de las 9 páginas
                w = max(i.size[0] for i in all_imgs)
                h = sum(i.size[1] for i in all_imgs)
                combined = Image.new("RGB", (w, h))
                curr_y = 0
                for img in all_imgs:
                    combined.paste(img, (0, curr_y))
                    curr_y += img.size[1]
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    combined.save(tmp.name, "JPEG", quality=80)
                    tmp_path = tmp.name

            # Procesamiento con Gemini
            g_file = genai.upload_file(path=tmp_path)
            while g_file.state.name == "PROCESSING": time.sleep(1); g_file = genai.get_file(g_file.name)

            prompt = """
            Eres un experto en topografía de El Salvador. 
            Analiza el documento y busca el Cuadro de Rumbos o la Memoria Descriptiva.
            1. Los rumbos pueden decir 'Norte', 'Sur', 'Poniente' u 'Oriente'.
            2. Identifica si un tramo es curvo. Busca la palabra 'Radio' o 'Arco' en el texto.
            3. Devuelve estrictamente un JSON con todos los linderos en orden:
            {"tramos": [{"rumbo": "N 87° 40' W", "distancia": 6.0, "tipo": "curva", "radio": 10.0}]}
            """

            response = model.generate_content([prompt, g_file])
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            
            if match:
                datos = json.loads(match.group())
                ruta_dxf = generar_dxf_final(datos['tramos'])
                st.success("✅ Poligonal generada con éxito.")
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 Descargar DXF para AutoCAD", f, file_name="poligonal.dxf")
                st.json(datos)
            else:
                st.error("La IA no pudo estructurar los rumbos. Intenta con una imagen más clara.")
            
            genai.delete_file(g_file.name)
            os.remove(tmp_path)

        except Exception as e:
            st.error(f"Error crítico en el motor: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
