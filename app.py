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

# --- 1. CONFIGURACIÓN DEL MODELO ---
st.set_page_config(page_title="Norm.AI - Topografía Profesional", layout="wide")
st.title("📐 Extractor de Poligonales ")

# Usamos el modelo que confirmamos que tienes activo
MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. MATEMÁTICA DE RUMBOS ---
def parsear_rumbo_final(rumbo_str):
    if not rumbo_str or rumbo_str.lower() == 'none': return None
    r = rumbo_str.upper().replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E')
    r = r.replace('NORTE', 'N').replace('SUR', 'S')
    match = re.search(r'([NS])\s*(\d+)[°°º]?\s*(\d+)\'?\s*(?:(\d+(?:\.\d+)?)\s*")?\s*([EW])', r)
    if match:
        ns, g, m, s, ew = match.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return None

# --- 3. GENERADOR DE DXF MEJORADO ---
def crear_dxf_compatible(tramos):
    # Usamos R2018 para máxima compatibilidad actual
    doc = ezdxf.new('R2018')
    # Configurar unidades a Metros (6 = Meters)
    doc.header['$INSUNITS'] = 6
    msp = doc.modelspace()
    
    puntos = [Vec2(0, 0)]
    tramos_dibujados = 0
    
    for i, t in enumerate(tramos):
        try:
            dist = float(t.get('distancia', 0))
            if dist <= 0: continue # Evitar errores de geometría
            
            rad = parsear_rumbo_final(t.get('rumbo', ''))
            
            if rad is not None:
                p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(ang_rad := rad) * dist)
                
                # Dibujar
                if t.get('tipo') == 'curva':
                    msp.add_lwpolyline([puntos[-1], p_final], dxfattribs={'bulge': 0.4, 'color': 3})
                else:
                    msp.add_line(puntos[-1], p_final, dxfattribs={'color': 7})
                
                puntos.append(p_final)
                tramos_dibujados += 1
        except:
            continue

    # Si hay puntos, agregar cuadro técnico simple
    if tramos_dibujados > 0:
        x_text = 30
        msp.add_text("CUADRO TÉCNICO", dxfattribs={'height': 1.0}).set_placement((x_text, 10))
        for i, t in enumerate(tramos):
            txt = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
            msp.add_text(txt, dxfattribs={'height': 0.5}).set_placement((x_text, 10 - (i+1)*1.5))

    temp_file = os.path.join(tempfile.gettempdir(), f"normai_{int(time.time())}.dxf")
    doc.saveas(temp_file)
    return temp_file, tramos_dibujados

# --- 4. PROCESAMIENTO ---
archivo = st.file_uploader("Sube el PDF técnico", type=["pdf"])

if archivo:
    if st.button("🚀 Generar Archivo CAD"):
        try:
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            
            # Unificar páginas
            with st.spinner("Procesando documento..."):
                paginas = []
                for i in range(num_pags):
                    p = doc_pdf.load_page(i)
                    pix = p.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    paginas.append(img)
                
                w = max(p.size[0] for p in paginas)
                h = sum(p.size[1] for p in paginas)
                final_img = Image.new("RGB", (w, h))
                y = 0
                for p in paginas:
                    final_img.paste(p, (0, y))
                    y += p.size[1]
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    final_img.save(tmp.name, "JPEG", quality=80)
                    path_tmp = tmp.name

            # Enviar a Gemini
            g_file = genai.upload_file(path=path_tmp)
            while g_file.state.name == "PROCESSING": time.sleep(1); g_file = genai.get_file(g_file.name)

            prompt = "Extract survey bearings/distances. Return JSON: {'tramos': [{'rumbo': 'N 10°E', 'distancia': 15.0, 'tipo': 'linea'}]}"
            response = model.generate_content([prompt, g_file])
            
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                datos = json.loads(match.group())
                ruta_dxf, cuenta = crear_dxf_compatible(datos['tramos'])
                
                if cuenta > 0:
                    st.success(f"✅ Archivo CAD generado con {cuenta} tramos.")
                    with open(ruta_dxf, "rb") as f:
                        st.download_button("💾 Descargar DXF para AutoCAD", f, file_name="plano_normai.dxf")
                    st.json(datos)
                else:
                    st.error("El archivo se generó vacío. Revisa que los rumbos en el PDF sean legibles.")
            
            genai.delete_file(g_file.name)
            os.remove(path_tmp)

        except Exception as e:
            st.error(f"Error técnico: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
