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
st.set_page_config(page_title="Norm.AI - Topografía Profesional", layout="wide")
st.title("📐 Norm.AI: Análisis de Macro-Escrituras y Cierre")

MODELO_ACTIVO = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel(model_name=MODELO_ACTIVO)
else:
    st.error("⚠️ Configura la API Key.")
    st.stop()

# --- 2. FILTROS MATEMÁTICOS Y CÁLCULO DE ÁREA ---
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
    return float(numeros[0]) if numeros else 0.0

def interpretar_rumbo_o_azimut(texto, ultimo_rad=0.0):
    if not texto: return ultimo_rad
    t = str(texto).upper().strip()
    
    # 1. Intento de Azimut (0-360 grados)
    match_az = re.search(r'(\d+)\s*[°º]\s*(\d+)\s*[\'’]\s*(\d+(?:\.\d+)?)?\s*["”]', t)
    if match_az and not any(x in t for x in ['N', 'S', 'E', 'W', 'O']):
        g, m, s = match_az.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        return math.radians(90 - dec)

    # 2. Intento de Rumbo Tradicional
    t_norm = t.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E')
    t_norm = t_norm.replace('NORTE', 'N').replace('SUR', 'S')
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

# --- 3. GENERADOR DE DXF (COMPLETO) ---
def crear_dxf_integral(datos):
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6 # Metros
    msp = doc.modelspace()

    current_x, current_y = 0.0, 0.0
    puntos_dwg = [(current_x, current_y)]
    ultimo_rad = 0.0

    tramos = datos.get('tramos', [])
    for i, t in enumerate(tramos):
        if not isinstance(t, dict): continue
        dist = limpiar_numero(t.get('distancia'))
        rumbo_txt = str(t.get('rumbo_limpio', ''))
        es_curva = t.get('es_curva', False)
        rad = interpretar_rumbo_o_azimut(rumbo_txt, ultimo_rad)

        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)

            # Etiqueta en medio de la línea
            mid_x = (current_x + next_x) / 2
            mid_y = (current_y + next_y) / 2
            color_txt = 3 if es_curva else 7
            msp.add_text(f"L{i+1}", dxfattribs={'height': 1.5, 'color': color_txt}).set_placement((mid_x + 0.3, mid_y + 0.3))

            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    tiene_error_cierre = False
    if len(puntos_dwg) > 1:
        msp.add_lwpolyline(puntos_dwg, dxfattribs={'color': 7})

        if puntos_dwg[-1] != puntos_dwg[0]:
            dist_cierre = math.sqrt((puntos_dwg[-1][0])**2 + (puntos_dwg[-1][1])**2)
            if dist_cierre > 0.01:
                msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1})
                tiene_error_cierre = True

    # --- FICHA TÉCNICA (DATOS RESTAURADOS) ---
    max_x = max([p[0] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    max_y = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    x_side = max_x + 30
    y_ref = max_y if max_y > 50 else 50

    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 2.0, 'color': 2}).set_placement((x_side, y_ref))
    y_ref -= 5

    msp.add_text("DATOS GENERALES:", dxfattribs={'height': 1.5, 'color': 1}).set_placement((x_side, y_ref))
    y_ref -= 3.0
    propietario = str(datos.get('propietario', 'No detectado'))
    msp.add_text(f"PROPIETARIO ACTUAL: {sanitizar_texto(propietario)}", dxfattribs={'height': 1.0}).set_placement((x_side + 2, y_ref))

    y_ref -= 4.0
    area_calc = calcular_area(puntos_dwg)
    msp.add_text(f"AREA CALCULADA CAD: {area_calc:,.2f} m2", dxfattribs={'height': 1.2, 'color': 4}).set_placement((x_side + 2, y_ref))

    y_ref -= 6
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.5, 'color': 1}).set_placement((x_side, y_ref))
    colindantes = datos.get('colindantes', [])
    for col in colindantes:
        y_ref -= 2.0
        msp.add_text(f"- {sanitizar_texto(col)}", dxfattribs={'height': 0.8}).set_placement((x_side + 2, y_ref))

    y_ref -= 6
    msp.add_text("NOTAS Y RESTRICCIONES:", dxfattribs={'height': 1.5, 'color': 3}).set_placement((x_side, y_ref))
    y_ref -= 3.0
    serv = str(datos.get('servidumbres', 'Ninguna mencionada'))
    msp.add_text(f"SERVIDUMBRES: {sanitizar_texto(serv)}", dxfattribs={'height': 0.8}).set_placement((x_side + 2, y_ref))
    y_ref -= 2.0
    queb = str(datos.get('quebradas', 'No menciona'))
    msp.add_text(f"CUERPOS DE AGUA: {sanitizar_texto(queb)}", dxfattribs={'height': 0.8}).set_placement((x_side + 2, y_ref))

    # CUADRO DE RUMBOS EXPANDIBLE (Para 70+ líneas)
    y_ref -= 8
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 1.5, 'color': 4}).set_placement((x_side, y_ref))
    y_ref -= 3.0

    # Cabeceras de tabla
    col_x_start = x_side
    msp.add_text("Est", dxfattribs={'height': 0.8, 'color': 7}).set_placement((col_x_start + 2, y_ref))
    msp.add_text("Rumbo/Azimut", dxfattribs={'height': 0.8, 'color': 7}).set_placement((col_x_start + 12, y_ref))
    msp.add_text("Distancia", dxfattribs={'height': 0.8, 'color': 7}).set_placement((col_x_start + 45, y_ref))
    y_ref -= 2.0

    tiene_alguna_curva = False
    for i, t in enumerate(tramos):
        d_val = limpiar_numero(t.get('distancia'))
        r_val = sanitizar_texto(t.get('rumbo_limpio', ''))
        est_val = sanitizar_texto(t.get('estacion', f"{i+1}"))
        es_curva = t.get('es_curva', False)
        
        col_fila = 3 if es_curva else 7
        if es_curva: tiene_alguna_curva = True
            
        if len(r_val) > 25: r_val = r_val[:22] + "..."
            
        msp.add_text(f"{est_val}", dxfattribs={'height': 0.8, 'color': col_fila}).set_placement((col_x_start + 2, y_ref))
        msp.add_text(r_val, dxfattribs={'height': 0.8, 'color': col_fila}).set_placement((col_x_start + 12, y_ref))
        msp.add_text(f"{d_val:.2f} m", dxfattribs={'height': 0.8, 'color': col_fila}).set_placement((col_x_start + 45, y_ref))
        
        y_ref -= 1.8
        
        # Lógica para no salirnos de la pantalla si hay demasiados tramos (columnas múltiples)
        if y_ref < (max_y - 300):
            col_x_start += 70
            y_ref = max_y - 50

    if tiene_alguna_curva:
        y_ref -= 6
        msp.add_text("AVISO GEOMETRIA (Verde): Los tramos curvos se dibujan rectos.", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_side, y_ref))

    if tiene_error_cierre:
        y_ref -= 4
        msp.add_text("AVISO DE CIERRE (Rojo): Discrepancia detectada en la escritura.", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_side, y_ref))

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_Macro_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube la Macro-Escritura (PDF)", type=["pdf"])

if archivo:
    if st.button("🚀 Extraer y Trazar Plano Completo"):
        try:
            status = st.status("Analizando múltiples folios y secuencia técnica...", expanded=True)
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            google_files = []

            for i in range(len(doc_pdf)):
                page = doc_pdf.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_path = os.path.join(tempfile.gettempdir(), f"folio_{i}.jpg")
                Image.frombytes("RGB", [pix.width, pix.height], pix.samples).save(img_path, "JPEG", quality=80)
                google_files.append(genai.upload_file(path=img_path))
                os.remove(img_path)

            while any(f.state.name == "PROCESSING" for f in google_files):
                time.sleep(1); google_files = [genai.get_file(f.name) for f in google_files]

            prompt = """
            Eres un experto legal y topógrafo salvadoreño. Analiza esta escritura masiva (remedición):
            1. 'propietario': Dueño actual.
            2. 'colindantes': Lista de vecinos.
            3. 'servidumbres' y 'quebradas': Si las hay.
            4. 'tramos': Extrae LA LISTA COMPLETA en ESTRICTO ORDEN SECUENCIAL. NO TE SALTES NINGUNA ESTACIÓN.
            
            Para cada tramo:
            - 'estacion': Identificador del tramo (ej. '1 al 2', 'E2-E3').
            - 'rumbo_limpio': El rumbo (N 10° E) o el Azimut (120° 30' 00").
            - 'distancia': Solo número.
            - 'es_curva': Obligatorio (true/false).
            
            Responde ÚNICAMENTE con el bloque JSON purificado.
            Formato:
            {
              "propietario": "...",
              "colindantes": ["Norte: ..."],
              "servidumbres": "...",
              "quebradas": "...",
              "tramos": [
                {"estacion": "1 al 2", "rumbo_limpio": "N 10° E", "distancia": 15.50, "es_curva": false},
                {"estacion": "2 al 3", "rumbo_limpio": "150° 20' 00\"", "distancia": 25.00, "es_curva": true}
              ]
            }
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
                st.error("⚠️ La IA generó un formato revuelto al intentar leer tantos datos. Reintenta.")
                st.stop()

            ruta_dxf = crear_dxf_integral(datos)

            for f in google_files: 
                try: genai.delete_file(f.name)
                except Exception: pass

            status.update(label="✅ Macro-Expediente Generado Correctamente", state="complete")
            with open(ruta_dxf, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="Plano_NormAI_Macro.dxf")

        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption(f"Norm.AI | Arquitectura & Tecnología | Miguel Guidos")
