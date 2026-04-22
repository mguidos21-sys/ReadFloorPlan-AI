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
st.set_page_config(page_title="Norm.AI - Topografía Real", layout="wide")
st.title("📐 Norm.AI: Generador de Poligonales y Expedientes")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. MOTOR GEOMÉTRICO (VERSIÓN 2026) ---
def parsear_rumbo_indestructible(rumbo_str):
    if not rumbo_str or not isinstance(rumbo_str, str): return None
    
    # Limpieza total de caracteres
    r = rumbo_str.upper()
    r = r.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ESTE', 'E').replace('ORIENTE', 'E')
    r = r.replace('NORTE', 'N').replace('SUR', 'S')
    
    # Regex súper permisiva para cualquier tipo de grado, minuto o segundo
    # Acepta: N 01°39'24" W, N 01 39 24 W, N 01-39-24 W, etc.
    match = re.search(r'([NS])\s*(\d+)[\s°°º\-]*(\d+)[\s\'’\-]*(\d+(?:\.\d+)?)[\s"”\-]*([EW])', r)
    
    if match:
        ns, g, m, s, ew = match.groups()
        dec = float(g) + float(m)/60 + float(s)/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return None

# --- 3. GENERADOR DE DXF ---
def crear_dxf_final(datos):
    doc = ezdxf.new('R2018')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    puntos = [Vec2(0, 0)]
    log_dibujo = []
    
    tramos = datos.get('tramos', [])
    for i, t in enumerate(tramos):
        try:
            dist = float(t.get('distancia', 0))
            rumbo_txt = str(t.get('rumbo', ''))
            
            rad = parsear_rumbo_indestructible(rumbo_txt)
            
            # Si es un arco sin rumbo, intentamos mantener la dirección previa o una estimación
            if rad is None and "ARCO" in rumbo_txt.upper():
                # Para no romper la poligonal, usamos el rumbo del tramo anterior 
                # o una línea recta si es el primero
                rad = parsear_rumbo_indestructible(tramos[i-1].get('rumbo')) if i > 0 else 0
            
            if rad is not None and dist > 0:
                p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                
                # Dibujamos directamente en capa 0 para evitar errores de visualización
                if "ARCO" in rumbo_txt.upper():
                    msp.add_lwpolyline([puntos[-1], p_final], dxfattribs={'bulge': 0.3, 'color': 3})
                else:
                    msp.add_line(puntos[-1], p_final, dxfattribs={'color': 7})
                
                puntos.append(p_final)
                log_dibujo.append(f"Tramo {i+1}: Dibujado OK")
            else:
                log_dibujo.append(f"Tramo {i+1}: Error en rumbo ({rumbo_txt})")
        except:
            log_dibujo.append(f"Tramo {i+1}: Error crítico")

    # Cierre de seguridad
    if len(puntos) > 2:
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'color': 1, 'linetype': 'DASHED'})

    # Ficha Técnica a la derecha
    x_off = max([p.x for p in puntos]) + 15 if len(puntos) > 1 else 30
    y_off = 30
    
    msp.add_text("FICHA TÉCNICA - NORM.AI", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_off, y_off))
    y_off -= 5
    msp.add_text(f"PROPIETARIO: {str(datos.get('propietario', 'No detectado'))}", dxfattribs={'height': 0.8}).set_placement((x_off, y_off))
    
    y_off -= 8
    msp.add_text("NOTAS TÉCNICAS:", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_off, y_off))
    y_off -= 3
    msp.add_text(f"SERVIDUMBRES: {str(datos.get('servidumbres', 'Ninguna'))}", dxfattribs={'height': 0.5}).set_placement((x_off + 2, y_off))
    y_off -= 2
    msp.add_text(f"ZONAS HÍDRICAS: {str(datos.get('quebradas', 'N/A'))}", dxfattribs={'height': 0.5}).set_placement((x_off + 2, y_off))

    temp_path = os.path.join(tempfile.gettempdir(), f"plano_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path, log_dibujo

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube la Escritura", type=["pdf"])

if archivo:
    if st.button("🚀 Generar Poligonal y Ficha"):
        try:
            status = st.status("Analizando expediente...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"f_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=75)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1)
                google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Extract from this deed:
            1. 'propietario': Name.
            2. 'colindantes': List.
            3. 'servidumbres' & 'quebradas': Details.
            4. 'tramos': Array with 'rumbo' and 'distancia'.
            
            Return ONLY JSON. No text before or after.
            """
            
            response = model.generate_content([prompt] + google_files)
            
            # Limpieza robusta de JSON (Extra data fix)
            text = response.text
            clean_json = text[text.find('{'):text.rfind('}')+1]
            datos = json.loads(clean_json)
            
            ruta_dxf, log = crear_dxf_final(datos)
            
            status.update(label="✅ Proceso finalizado", state="complete")
            
            st.subheader("Estado del Dibujo")
            for l in log: st.write(f"- {l}")
            
            with open(ruta_dxf, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="Plano_Final_NormAI.dxf")
            
            st.json(datos)
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Fallo: {e}")
st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
