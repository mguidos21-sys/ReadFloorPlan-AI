import streamlit as st
import google.generativeai as genai
import ezdxf
import fitz  # PyMuPDF
from PIL import Image
import json
import re
import math
import os
import tempfile
import time

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Norm.AI - Edición Profesional", layout="wide")
st.title("📐 Norm.AI: Levantamiento de Macro-Terrenos y Auditoría")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. FILTROS MATEMÁTICOS ---
def calcular_area(puntos):
    n = len(puntos)
    if n < 3: return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += puntos[i][0] * puntos[j][1]
        area -= puntos[j][0] * puntos[i][1]
    return abs(area) / 2.0

def sanitizar_texto(texto):
    if not texto: return "N/A"
    t = str(texto).replace('\n', ' ').strip()
    t = re.sub(r'[^\x20-\x7E\xA0-\xFF]', '', t)
    return t

def limpiar_numero(valor):
    if valor is None: return 0.0
    numeros = re.findall(r"[-+]?\d*\.\d+|\d+", str(valor).replace(',', '.'))
    if not numeros: return 0.0
    n = float(numeros[0])
    return n if n > 0.05 else 0.0 # Filtro contra ruido OCR

def interpretar_rumbo_o_azimut(texto, ultimo_rad=0.0):
    if not texto: return ultimo_rad
    t = str(texto).upper().strip()
    
    match_az = re.search(r'(\d+)\s*[°º]\s*(\d+)\s*[\'’]\s*(\d+(?:\.\d+)?)?\s*["”]', t)
    if match_az and not any(x in t for x in ['N', 'S', 'E', 'W', 'O']):
        g, m, s = match_az.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        return math.radians(90 - dec)

    t_norm = t.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E').replace('NORTE', 'N').replace('SUR', 'S')
    match_r = re.search(r'([NS])\s*(\d+)[°\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\s]*([EW])', t_norm)
    if match_r:
        ns, g, m, s, ew = match_r.groups()
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
    doc.header['$INSUNITS'] = 6
    msp = doc.modelspace()

    current_x, current_y = 0.0, 0.0
    puntos_dwg = [(current_x, current_y)]
    ultimo_rad = 0.0

    tramos = datos.get('tramos', [])
    for i, t in enumerate(tramos):
        dist = limpiar_numero(t.get('distancia'))
        r_txt = t.get('rumbo_limpio', '')
        rad = interpretar_rumbo_o_azimut(r_txt, ultimo_rad)

        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)
            
            mid_x, mid_y = (current_x + next_x)/2, (current_y + next_y)/2
            msp.add_text(f"E{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((mid_x + 0.5, mid_y + 0.5))

            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    if len(puntos_dwg) > 1:
        msp.add_lwpolyline(puntos_dwg, dxfattribs={'color': 7})
        if puntos_dwg[-1] != puntos_dwg[0]:
            msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1})

    max_x = max([p[0] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    max_y = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    x_ref, y_ref = max_x + 30, max_y + 15

    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 2.5, 'color': 2}).set_placement((x_ref, y_ref))
    y_ref -= 8
    
    msp.add_text(f"PROPIETARIO: {sanitizar_texto(datos.get('propietario', 'N/A'))}", dxfattribs={'height': 1.2}).set_placement((x_ref, y_ref))
    y_ref -= 5
    
    # DATOS RESTAURADOS
    colindantes = datos.get('colindantes', [])
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.2, 'color': 1}).set_placement((x_ref, y_ref))
    for col in colindantes:
        y_ref -= 2.0
        msp.add_text(f"- {sanitizar_texto(col)}", dxfattribs={'height': 0.8}).set_placement((x_ref + 2, y_ref))
    
    y_ref -= 4
    area_calc = calcular_area(puntos_dwg)
    msp.add_text(f"AREA CALCULADA CAD: {area_calc:,.2f} m2", dxfattribs={'height': 1.5, 'color': 4}).set_placement((x_ref, y_ref))
    y_ref -= 10

    col_x = x_ref
    for i, t in enumerate(tramos):
        linea = f"E{i+1}: {t.get('rumbo_limpio')} | {t.get('distancia')}m"
        msp.add_text(linea, dxfattribs={'height': 0.8}).set_placement((col_x, y_ref))
        y_ref -= 1.8
        if y_ref < (max_y - 350): 
            y_ref = max_y - 50 # Ajuste para no pisar colindantes
            col_x += 65

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_Final_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube el PDF de Altos de Metrópoli", type=["pdf"])

if archivo:
    if st.button("🚀 Forzar Extracción Real (Sin Resúmenes)"):
        try:
            status = st.status("Leyendo 19 páginas. Obligando al sistema a transcribir los 76 tramos reales...")
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []
            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_path = os.path.join(tempfile.gettempdir(), f"p_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=80)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)

            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1); google_files = [genai.get_file(f.name) for f in google_files]

            # EL PROMPT A PRUEBA DE PEREZA
            prompt = """
            Eres un topógrafo experto. Analiza la REMEDICIÓN de 'Altos de Metrópoli' (Porción 2).
            
            MISIÓN CRÍTICA: El perímetro principal tiene EXACTAMENTE 76 TRAMOS. 
            Debes leer todo el documento y extraer la verdad. 
            REGLA DE ORO: NO resumas. NO uses puntos suspensivos. Escribe los 76 tramos reales.

            Extrae y devuelve ESTRICTAMENTE este JSON:
            {
              "propietario": "Dueño actual",
              "colindantes": ["Norte: ...", "Sur: ..."],
              "tramos": [
                {"rumbo_limpio": "Azimut o Rumbo 1", "distancia": 10.50},
                {"rumbo_limpio": "Azimut o Rumbo 2", "distancia": 25.00}
              ]
            }
            Asegúrate de que el arreglo "tramos" tenga 76 elementos reales.
            """
            
            response = model.generate_content([prompt] + google_files)
            text = response.text
            
            try:
                if "```json" in text:
                    clean_json = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    clean_json = text.split("```")[1].split("```")[0].strip()
                else:
                    clean_json = text[text.find('{'):text.rfind('}')+1].strip()
                datos = json.loads(clean_json)
            except json.JSONDecodeError:
                st.error("⚠️ Error de formato. Intenta de nuevo.")
                st.stop()
            
            ruta = crear_dxf_integral(datos)
            status.update(label=f"✅ ¡Completado! {len(datos.get('tramos', []))} tramos leídos.", state="complete")
            
            with open(ruta, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="NormAI_Metropoli_Auditoria.dxf")
            
            for f in google_files: 
                try: genai.delete_file(f.name)
                except: pass
                
        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption("Norm.AI | Miguel Guidos - Tecnología de Precisión")
