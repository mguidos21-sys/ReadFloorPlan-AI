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
st.set_page_config(page_title="Norm.AI - Arquitectura El Salvador", layout="wide")
st.title("📐 Norm.AI: Expediente Técnico y Poligonal")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. FILTROS DE LIMPIEZA ---
def sanitizar_texto(texto):
    if not texto: return "N/A"
    t = str(texto).replace('\n', ' ').strip()
    t = re.sub(r'[^\x20-\x7E\xA0-\xFF]', '', t) 
    return t

def limpiar_numero(valor):
    if valor is None: return 0.0
    numeros = re.findall(r"[-+]?\d*\.\d+|\d+", str(valor).replace(',', '.'))
    return float(numeros[0]) if numeros else 0.0

def interpretar_rumbo_sv(rumbo_str, ultimo_rad=0.0):
    if not rumbo_str or not isinstance(rumbo_str, str): return ultimo_rad
    r = rumbo_str.upper().strip()
    
    # EL ARREGLO: Soporte nativo para puntos cardinales puros (Sin grados)
    if r in ['NORTE', 'N']: return math.pi / 2          # 90 grados hacia arriba
    if r in ['SUR', 'S']: return 3 * math.pi / 2        # 270 grados hacia abajo
    if r in ['ESTE', 'ORIENTE', 'E']: return 0.0        # 0 grados hacia la derecha
    if r in ['OESTE', 'PONIENTE', 'W']: return math.pi  # 180 grados hacia la izquierda

    # Si trae grados, aplicamos la fórmula normal
    r = r.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E')
    match = re.search(r'([NS])\s*(\d+)[°\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\s]*([EW])', r)
    if match:
        ns, g, m, s, ew = match.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return ultimo_rad

# --- 3. GENERADOR DE DXF ---
def crear_dxf_integral(datos):
    doc = ezdxf.new('R2010') 
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()
    
    # --- DIBUJO DE GEOMETRÍA ---
    current_x, current_y = 0.0, 0.0
    puntos_dwg = [(current_x, current_y)]
    ultimo_rad = 0.0
    
    tramos = datos.get('tramos', [])
    for t in tramos:
        if not isinstance(t, dict): continue
        dist = limpiar_numero(t.get('distancia'))
        rumbo_txt = str(t.get('rumbo', ''))
        rad = interpretar_rumbo_sv(rumbo_txt, ultimo_rad)
        
        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)
            color_linea = 3 if "ARCO" in rumbo_txt.upper() else 7
            msp.add_line((current_x, current_y), (next_x, next_y), dxfattribs={'color': color_linea})
            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    if len(puntos_dwg) > 2:
        msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1})

    # --- FICHA TÉCNICA (SIDEBAR) ---
    max_x = max([p[0] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    max_y = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    x_side = max_x + 15
    y_ref = max_y if max_y > 30 else 30
    
    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_side, y_ref))
    y_ref -= 5
    
    msp.add_text("DATOS GENERALES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_side, y_ref))
    y_ref -= 2.5
    propietario = str(datos.get('propietario', 'No detectado'))
    msp.add_text(f"PROPIETARIO: {sanitizar_texto(propietario)}", dxfattribs={'height': 0.7}).set_placement((x_side + 2, y_ref))
    
    y_ref -= 5
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_side, y_ref))
    colindantes = datos.get('colindantes', [])
    for col in colindantes:
        y_ref -= 1.8
        msp.add_text(f"- {sanitizar_texto(col)}", dxfattribs={'height': 0.6}).set_placement((x_side + 2, y_ref))
    
    y_ref -= 6
    msp.add_text("NOTAS Y RESTRICCIONES:", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_side, y_ref))
    y_ref -= 2.5
    serv = str(datos.get('servidumbres', 'Ninguna mencionada'))
    msp.add_text(f"SERVIDUMBRES: {sanitizar_texto(serv)}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))
    y_ref -= 1.5
    queb = str(datos.get('quebradas', 'No menciona'))
    msp.add_text(f"CUERPOS DE AGUA: {sanitizar_texto(queb)}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))

    # EL ARREGLO DE LA TABLA: Columnas alineadas mediante coordenadas fijas
    y_ref -= 8
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 1.0, 'color': 4}).set_placement((x_side, y_ref))
    y_ref -= 2.0
    
    # Encabezados en columnas
    msp.add_text("Linea", dxfattribs={'height': 0.6, 'color': 7}).set_placement((x_side + 2, y_ref))
    msp.add_text("Rumbo", dxfattribs={'height': 0.6, 'color': 7}).set_placement((x_side + 10, y_ref))
    msp.add_text("Distancia", dxfattribs={'height': 0.6, 'color': 7}).set_placement((x_side + 35, y_ref))
    y_ref -= 1.5

    for i, t in enumerate(tramos):
        if not isinstance(t, dict): continue
        d_val = limpiar_numero(t.get('distancia'))
        r_val = sanitizar_texto(t.get('rumbo', ''))
        
        # Datos en columnas
        msp.add_text(f"L{i+1}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))
        msp.add_text(r_val, dxfattribs={'height': 0.5}).set_placement((x_side + 10, y_ref))
        msp.add_text(f"{d_val:.2f} m", dxfattribs={'height': 0.5}).set_placement((x_side + 35, y_ref))
        y_ref -= 1.3

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_Final_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube la Escritura (PDF)", type=["pdf"])

if archivo:
    if st.button("🚀 Generar Plano Correcto"):
        try:
            status = st.status("Analizando expediente técnico...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.1, 1.1))
                img_path = os.path.join(tempfile.gettempdir(), f"folio_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=75)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)
            
            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1); google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Analiza esta escritura y extrae la información en ESPAÑOL:
            1. 'propietario': Nombre completo del titular.
            2. 'colindantes': Lista de vecinos por punto cardinal.
            3. 'servidumbres' y 'quebradas'.
            4. 'tramos': Lista OBLIGATORIA con 'rumbo' (texto literal de la escritura) y 'distancia' (solo número).
            
            Formato JSON ESTRICTO:
            {
              "propietario": "...",
              "colindantes": ["Norte: ...", "Sur: ..."],
              "servidumbres": "...",
              "quebradas": "...",
              "tramos": [{"rumbo": "Norte", "distancia": 15.50}]
            }
            """
            
            response = model.generate_content([prompt] + google_files)
            text = response.text
            clean_json = text[text.find('{'):text.rfind('}')+1]
            datos = json.loads(clean_json)
            
            ruta_dxf = crear_dxf_integral(datos)
            
            status.update(label="✅ Plano Generado Exitosamente", state="complete")
            with open(ruta_dxf, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="Plano_NormAI_Final.dxf")
            
            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Error en el motor: {e}")
            
st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
