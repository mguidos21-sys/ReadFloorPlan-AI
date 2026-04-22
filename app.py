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
import traceback

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Gestión de Expedientes", layout="wide")
st.title("📐 Norm.AI: Análisis Técnico-Legal de Escrituras")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. LÓGICA DE GEOMETRÍA ---
def convertir_a_radianes(rumbo_str):
    if not rumbo_str or str(rumbo_str).lower() == 'none': return None
    r = rumbo_str.upper().replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E').replace('NORTE', 'N').replace('SUR', 'S')
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

# --- 3. GENERADOR DE PLANO INTEGRAL ---
def crear_dxf_expediente(datos):
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    # POLIGONAL UNIDA
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    for t in tramos:
        try:
            dist = float(t.get('distancia', 0))
            rad = convertir_rumbo_a_radianes_sv(t.get('rumbo')) # Ver función corregida abajo
            if rad is not None and dist > 0:
                p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                puntos.append(p_final)
        except: continue
    
    if len(puntos) > 1:
        msp.add_lwpolyline(puntos, dxfattribs={'color': 7, 'layer': 'POLIGONAL_PROPIEDAD'})

    # BLOQUE DE INFORMACIÓN (A la derecha)
    x_ref, y_ref = 50, 20
    
    # Encabezado y Propietario
    msp.add_text("INFORMACIÓN DEL EXPEDIENTE", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_ref, y_ref))
    msp.add_text(f"PROPIETARIO: {datos.get('propietario', 'No especificado')}", 
                 dxfattribs={'height': 0.8}).set_placement((x_ref, y_ref - 4))
    
    # Colindantes
    y_ref -= 8
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_ref, y_ref))
    colindantes = datos.get('colindantes', [])
    if isinstance(colindantes, list):
        for i, col in enumerate(colindantes):
            msp.add_text(f"- {col}", dxfattribs={'height': 0.6}).set_placement((x_ref + 2, y_ref - 2 - (i*1.5)))
            y_ref -= 1.5
    
    # Notas Especiales (Quebradas y Servidumbres)
    y_ref -= 6
    msp.add_text("NOTAS TÉCNICAS:", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_ref, y_ref))
    msp.add_text(f"SERVIDUMBRES: {datos.get('servidumbres', 'N/A')}", dxfattribs={'height': 0.6}).set_placement((x_ref + 2, y_ref - 3))
    msp.add_text(f"ZONAS HÍDRICAS/QUEBRADAS: {datos.get('quebradas', 'No menciona')}", dxfattribs={'height': 0.6}).set_placement((x_ref + 2, y_ref - 5))

    path = os.path.join(tempfile.gettempdir(), f"expediente_{int(time.time())}.dxf")
    doc.saveas(path)
    return path

# Función auxiliar de rumbos para el DXF
def convertir_rumbo_a_radianes_sv(rumbo_str):
    return convertir_a_radianes(rumbo_str)

# --- 4. INTERFAZ Y PROCESAMIENTO ---
archivo = st.file_uploader("Sube el PDF de la escritura", type=["pdf"])

if archivo:
    if st.button("🚀 Extraer Memoria Descriptiva y Datos Legales"):
        try:
            status = st.status("Analizando 9 páginas...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            # Subida optimizada (Calidad media para ahorrar memoria)
            status.write("📤 Subiendo folios a la nube...")
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
                img_path = os.path.join(tempfile.gettempdir(), f"folio_{i}.jpg")
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img.save(img_path, "JPEG", quality=70)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1)
                google_files = [genai.get_file(f.name) for f in google_files]

            # EL PROMPT DE ANÁLISIS INTEGRAL
            status.write("🧠 Leyendo rumbos, propietarios y restricciones...")
            prompt = """
            Escanea exhaustivamente estas 9 páginas. Necesito un reporte técnico-legal completo.
            Genera un JSON con:
            1. 'propietario': El nombre del dueño actual del inmueble.
            2. 'colindantes': Lista de vecinos por punto cardinal si están presentes.
            3. 'servidumbres': Cualquier mención a paso, acueductos o líneas eléctricas.
            4. 'quebradas': Si menciona cuerpos de agua o zonas de protección.
            5. 'tramos': La tabla de rumbos y distancias (N 10E, 15.0m).
            
            JSON format:
            {"propietario": "...", "colindantes": [], "servidumbres": "...", "quebradas": "...", "tramos": []}
            """
            
            response = model.generate_content([prompt] + google_files)
            
            # Buscador de JSON más agresivo
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                datos = json.loads(match.group())
                ruta_dxf = crear_dxf_expediente(datos)
                
                status.update(label="✅ Análisis Completo", state="complete")
                st.success(f"Propietario detectado: {datos.get('propietario')}")
                
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 DESCARGAR DXF INTEGRAL", f, file_name="NormAI_Plano_Legal.dxf")
                
                st.subheader("Resumen de Información Extraída")
                st.json(datos)
            
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            # ESTO MOSTRARÁ EL ERROR REAL SI HAY OTRO "OH NO"
            st.error("Hubo un fallo en el motor.")
            st.code(traceback.format_exc())

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
