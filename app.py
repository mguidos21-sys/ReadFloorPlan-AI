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
st.set_page_config(page_title="Norm.AI - Arquitectura & Catastro", layout="wide")
st.title("📐 Norm.AI: Extractor de Información Legal y Técnica")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key en los Secrets.")
    st.stop()

# --- 2. MATEMÁTICA DE RUMBOS ---
def parsear_rumbo_sv(rumbo_str):
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

# --- 3. GENERADOR DE DXF ENRIQUECIDO ---
def crear_dxf_completo(datos):
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    # --- CAPA 1: GEOMETRÍA UNIDA ---
    puntos = [Vec2(0, 0)]
    tramos = datos.get('tramos', [])
    for t in tramos:
        try:
            dist = float(t.get('distancia', 0))
            rad = parsear_rumbo_sv(t.get('rumbo', ''))
            if rad is not None and dist > 0:
                p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                puntos.append(p_final)
        except: continue
    
    if len(puntos) > 1:
        # Esto crea una polilínea UNIDA en AutoCAD
        msp.add_lwpolyline(puntos, dxfattribs={'color': 7, 'layer': 'POLIGONAL'})

    # --- CAPA 2: INFORMACIÓN LEGAL ---
    x_info = 40 # Posición a la derecha del dibujo
    y_start = 20
    
    # Estilo de encabezado
    msp.add_text("DATOS DEL PROYECTO (NORM.AI)", dxfattribs={'height': 1.2, 'color': 2}).set_placement((x_info, y_start))
    
    # Propietario
    y_start -= 3
    msp.add_text(f"PROPIETARIO: {datos.get('propietario', 'No detectado')}", 
                 dxfattribs={'height': 0.7}).set_placement((x_info, y_start))
    
    # Colindantes
    y_start -= 4
    msp.add_text("COLINDANTES:", dxfattribs={'height': 0.8, 'color': 1}).set_placement((x_info, y_start))
    for col in datos.get('colindantes', []):
        y_start -= 1.5
        msp.add_text(f"- {col}", dxfattribs={'height': 0.5}).set_placement((x_info + 2, y_start))
    
    # Restricciones (Servidumbres y Quebradas)
    y_start -= 4
    msp.add_text("RESTRICCIONES Y NOTAS:", dxfattribs={'height': 0.8, 'color': 1}).set_placement((x_info, y_start))
    
    y_start -= 1.5
    msp.add_text(f"SERVIDUMBRES: {datos.get('servidumbres', 'Ninguna mencionada')}", 
                 dxfattribs={'height': 0.5}).set_placement((x_info + 2, y_start))
    
    y_start -= 1.5
    quebradas = datos.get('quebradas', 'No menciona')
    msp.add_text(f"QUEBRADAS/CUERPOS AGUA: {quebradas}", 
                 dxfattribs={'height': 0.5}).set_placement((x_info + 2, y_start))

    # Cuadro Técnico de Rumbos (al final)
    y_start -= 5
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 0.8, 'color': 3}).set_placement((x_info, y_start))
    for i, t in enumerate(tramos):
        y_start -= 1.2
        txt = f"L{i+1}: {t.get('rumbo')} | Dist: {t.get('distancia')} m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((x_info + 2, y_start))

    temp_path = os.path.join(tempfile.gettempdir(), f"normai_full_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. PROCESAMIENTO ---
archivo = st.file_uploader("Sube el PDF de la escritura (Análisis Integral)", type=["pdf"])

if archivo:
    if st.button("🚀 Iniciar Extracción Multinivel"):
        try:
            status = st.status("Analizando expediente...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            # Paso 1: Subida de páginas
            status.write("📄 Escaneando páginas del documento...")
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
                img_path = os.path.join(tempfile.gettempdir(), f"page_{i}.jpg")
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img.save(img_path, "JPEG", quality=80)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1)
                google_files = [genai.get_file(f.name) for f in google_files]

            # Paso 2: El Prompt Maestro
            status.write("🧠 Extrayendo Propietario, Colindantes y Geometría...")
            prompt = """
            Analiza integralmente este documento de propiedad (escritura).
            Extrae la siguiente información en formato JSON:
            1. 'propietario': Nombre completo de la persona o sociedad dueña.
            2. 'colindantes': Lista de nombres de vecinos mencionados (ej: 'Norte: Juan Perez').
            3. 'servidumbres': Describe si hay servidumbres de paso, acueducto o eléctricas.
            4. 'quebradas': Indica si el texto menciona quebradas, ríos o zonas de protección hídrica.
            5. 'tramos': Lista de rumbos y distancias (N 10°E, 15.0m).
            
            Formato de salida esperado (JSON puro):
            {
              "propietario": "...",
              "colindantes": ["...", "..."],
              "servidumbres": "...",
              "quebradas": "...",
              "tramos": [{"rumbo": "...", "distancia": 0.0, "tipo": "linea"}]
            }
            """
            
            response = model.generate_content([prompt] + google_files)
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            
            if match:
                datos = json.loads(match.group())
                ruta_dxf = crear_dxf_completo(datos)
                
                status.update(label="✅ Expediente Procesado con Éxito", state="complete")
                st.success(f"Se detectó a: {datos.get('propietario', 'N/A')}")
                
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 DESCARGAR DXF INTEGRAL", f, file_name="NormAI_Proyecto.dxf")
                
                # Vista previa de datos extraídos
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Datos Legales")
                    st.write(f"**Propietario:** {datos.get('propietario')}")
                    st.write(f"**Servidumbres:** {datos.get('servidumbres')}")
                    st.write(f"**Quebradas:** {datos.get('quebradas')}")
                with col2:
                    st.subheader("Colindantes")
                    for c in datos.get('colindantes', []):
                        st.write(f"📍 {c}")
            
            # Limpieza
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Error en Norm.AI: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
