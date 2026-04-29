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
st.set_page_config(page_title="Norm.AI - Heavy Duty Edition", layout="wide")
st.title("📐 Norm.AI: Procesamiento de Macro-Escrituras y Cierre Catastral")

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

def limpiar_numero_distancia(valor):
    """Extrae el número, asumiendo que debe ser una distancia válida."""
    if valor is None: return 0.0
    # Busca números racionales, ignorando si están extremadamente cerca de cero (ruido OCR)
    numeros = re.findall(r"[-+]?\d*\.\d+|\d+", str(valor).replace(',', '.'))
    if not numeros: return 0.0
    dist = float(numeros[0])
    # Heurística para Altos de Metrópoli: distancias < 0.05m en macro-terrenos suelen ser ruido.
    return dist if dist >= 0.05 else 0.0

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

# --- 3. GENERADOR DE DXF (PROFESIONAL Y ROBUSTO) ---
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
        dist = limpiar_numero_distancia(t.get('distancia'))
        rumbo_txt = str(t.get('rumbo_limpio', ''))
        es_curva = t.get('es_curva', False)
        rad = interpretar_rumbo_o_azimut(rumbo_txt, ultimo_rad)

        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)

            mid_x = (current_x + next_x) / 2
            mid_y = (current_y + next_y) / 2
            
            color_txt = 3 if es_curva else 7 
            # Etiquetamos el número de lindero de la tabla (L1, L2...)
            label = sanitizar_texto(t.get('etiqueta_tabla', f"L{i+1}"))
            msp.add_text(label, dxfattribs={'height': 1.0, 'color': color_txt}).set_placement((mid_x + 0.3, mid_y + 0.3))

            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    tiene_error_cierre = False
    if len(puntos_dwg) > 1:
        msp.add_lwpolyline(puntos_dwg, dxfattribs={'color': 7}) # color 7 = blanco/negro

        if puntos_dwg[-1] != puntos_dwg[0]:
            dist_cierre = math.sqrt((puntos_dwg[-1][0])**2 + (puntos_dwg[-1][1])**2)
            if dist_cierre > 0.1: # Tolerancia de cierre para macro-terrenos
                msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1}) # color 1 = rojo
                tiene_error_cierre = True

    # --- FICHA TÉCNICA (DATOS RESTAURADOS) ---
    max_x = max([p[0] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    max_y = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    x_side = max_x + 40
    y_ref = max_y if max_y > 50 else 50

    # SECCIÓN 1: DATOS GENERALES (Restaurada)
    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 2.5, 'color': 2}).set_placement((x_side, y_ref))
    y_ref -= 8
    
    msp.add_text("DATOS GENERALES:", dxfattribs={'height': 1.8, 'color': 1}).set_placement((x_side, y_ref))
    y_ref -= 5.0
    
    prop_txt = sanitizar_texto(datos.get('propietario', 'N/A'))
    msp.add_text(f"PROPIETARIO ACTUAL: {prop_txt}", dxfattribs={'height': 1.0, 'color': 5}).set_placement((x_side + 2, y_ref))
    
    y_ref -= 4.0
    area_calc = calcular_area(puntos_dwg)
    msp.add_text(f"AREA CALCULADA CAD: {area_calc:,.2f} m2", dxfattribs={'height': 1.2, 'color': 6}).set_placement((x_side + 2, y_ref))

    y_ref -= 6
    msp.add_text("COLINDANTES:", dxfattribs={'height': 1.8, 'color': 1}).set_placement((x_side, y_ref))
    colindantes = datos.get('colindantes', [])
    for col in colindantes:
        y_ref -= 2.5
        msp.add_text(f"- {sanitizar_texto(col)}", dxfattribs={'height': 0.8, 'color': 1}).set_placement((x_side + 2, y_ref))
    
    y_ref -= 8
    msp.add_text("NOTAS Y RESTRICCIONES:", dxfattribs={'height': 1.8, 'color': 3}).set_placement((x_side, y_ref))
    y_ref -= 4.0
    serv = str(datos.get('servidumbres', 'Ninguna mencionada'))
    msp.add_text(f"SERVIDUMBRES: {sanitizar_texto(serv)}", dxfattribs={'height': 0.8, 'color': 4}).set_placement((x_side + 2, y_ref))
    y_ref -= 2.5
    queb = str(datos.get('quebradas', 'No menciona'))
    msp.add_text(f"CUERPOS DE AGUA: {sanitizar_texto(queb)}", dxfattribs={'height': 0.8, 'color': 8}).set_placement((x_side + 2, y_ref))

    # SECCIÓN 2: CUADRO TÉCNICO ORGANIZADO (Columnas múltiples)
    y_ref -= 15
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS (76 ESTACIONES)", dxfattribs={'height': 2.0, 'color': 4}).set_placement((x_side, y_ref))
    y_ref -= 5.0
    
    # Cabeceras
    header_height = 0.8
    msp.add_text("Lin", dxfattribs={'height': header_height, 'color': 7}).set_placement((x_side + 2, y_ref))
    msp.add_text("Rumbo/Azimut", dxfattribs={'height': header_height, 'color': 7}).set_placement((x_side + 10, y_ref))
    msp.add_text("Dist (m)", dxfattribs={'height': header_height, 'color': 7}).set_placement((x_side + 40, y_ref))
    y_ref -= 3.0

    # Lógica para manejar las 76 estaciones en columnas legibles
    tiene_alguna_curva = False
    data_height = 0.6
    column_width = 50
    current_col_x = x_side

    for i, t in enumerate(tramos):
        dist = limpiar_numero_distancia(t.get('distancia'))
        r_val = sanitizar_texto(t.get('rumbo_limpio', ''))
        label = sanitizar_texto(t.get('etiqueta_tabla', f"L{i+1}"))
        es_curva = t.get('es_curva', False)
        
        col_fila = 3 if es_curva else 7 # Verde si es curva, blanco si no
        if es_curva: tiene_alguna_curva = True
            
        if len(r_val) > 28: r_val = r_val[:25] + "..."
            
        msp.add_text(f"{label}", dxfattribs={'height': data_height, 'color': col_fila}).set_placement((current_col_x + 2, y_ref))
        msp.add_text(r_val, dxfattribs={'height': data_height, 'color': col_fila}).set_placement((current_col_x + 10, y_ref))
        msp.add_text(f"{dist:.2f}", dxfattribs={'height': data_height, 'color': col_fila}).set_placement((current_col_x + 40, y_ref))
        
        y_ref -= 1.2
        
        # Si la lista es muy larga (nos acercamos al borde inferior virtual), saltamos a otra columna
        if y_ref < (max_y - 250):
            y_ref = max_y - 30 # Reseteamos altura (bajo los generales)
            current_col_x += column_width # Desplazamos a la derecha

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_MacroExpediente_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube la Escritura de Altos de Metrópoli (PDF)", type=["pdf"])

if archivo:
    if st.button("🚀 Extraer 76 Estaciones y Trazar Expediente Completo"):
        try:
            status = st.status("Analizando múltiples folios y validando 76 estaciones técnicas...", expanded=True)
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

            # PROMPT REDISEÑADO PARA MACRO-ESCRITURAS Y NOISE REDUCTION
            prompt = """
            Eres un experto en ingeniería legal y catastral salvadoreña. Analiza la REMEDICIÓN de 'Altos de Metrópoli'.
            IMPORTANTE: El documento contiene exactamente 76 TRAMOS para el perímetro principal.
            TU OBJETIVO: No omitas ninguno. Divide tu búsqueda secuencialmente: Lindero Norte (28), Oriente (21), Sur (17), Poniente (10).
            
            Para cada tramo técnico:
            - 'etiqueta_tabla': Nombre secuencial (ej. 'L1', 'TRAMO 1-2').
            - 'rumbo_limpio': UNA SOLA CADENA. Sea Rumbo (N 10° E) o Azimut (120° 30' 00").
            - 'distancia': Solo número. Ignora cualquier número extremadamente pequeño (ej. 0.01m) que parezca un punto de OCR o marca visual. Busca el número que esté *después* de la palabra 'metros' o 'mts'.
            - 'es_curva': Obligatorio (true/false).
            
            No olvides extraer los datos generales.
            Responde ÚNICAMENTE con el bloque JSON purificado.
            Formato:
            {
              "propietario": "...",
              "colindantes": ["Norte: ..."],
              "servidumbres": "...",
              "quebradas": "...",
              "tramos": [
                {"etiqueta_tabla": "L1", "rumbo_limpio": "N 10° E", "distancia": 45.0, "es_curva": false},
                ... (así hasta completar los 76)
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
                st.error("⚠️ La IA generó un formato revuelto al intentar leer tantos datos secuenciales. Reintenta.")
                st.stop()

            ruta_dxf = crear_dxf_integral(datos)

            for f in google_files: 
                try: genai.delete_file(f.name)
                except Exception: pass

            status.update(label="✅ Expediente Catastral de Gran Escala Generado", state="complete")
            with open(ruta_dxf, "rb") as f:
                st.download_button("💾 DESCARGAR DXF PROFESIONAL", f, file_name="NormAI_AltosMetropoli_76.dxf")

        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption(f"Norm.AI | Arquitectura & Tecnología | Miguel Guidos")
