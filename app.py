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
st.set_page_config(page_title="Norm.AI - Topografía El Salvador", layout="wide")
st.title("📐 Norm.AI: Expediente Técnico y Poligonal")

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
    return float(numeros[0]) if numeros else 0.0

def interpretar_rumbo_sv(rumbo_str, ultimo_rad=0.0):
    if not rumbo_str or not isinstance(rumbo_str, str): return ultimo_rad
    r = rumbo_str.upper().strip()

    if r in ['N', 'NORTE']: return math.pi / 2
    if r in ['S', 'SUR']: return 3 * math.pi / 2
    if r in ['E', 'ESTE', 'ORIENTE']: return 0.0
    if r in ['W', 'OESTE', 'PONIENTE']: return math.pi

    r_norm = r.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E')
    r_norm = r_norm.replace('NORTE', 'N').replace('SUR', 'S')
    match = re.search(r'([NS])\s*(\d+)[°\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\s]*([EW])', r_norm)
    if match:
        ns, g, m, s, ew = match.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)

    if 'NORTE' in r: return math.pi / 2
    if 'SUR' in r: return 3 * math.pi / 2
    if 'ESTE' in r or 'ORIENTE' in r: return 0.0
    if 'OESTE' in r or 'PONIENTE' in r: return math.pi

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
        if not isinstance(t, dict): continue
        dist = limpiar_numero(t.get('distancia'))
        rumbo_txt = str(t.get('rumbo_limpio', t.get('rumbo_texto', '')))
        rad = interpretar_rumbo_sv(rumbo_txt, ultimo_rad)

        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)

            # ETIQUETAS L1, L2 EN EL PUNTO MEDIO DE LA LÍNEA
            mid_x = (current_x + next_x) / 2
            mid_y = (current_y + next_y) / 2
            msp.add_text(f"L{i+1}", dxfattribs={'height': 0.8, 'color': 3}).set_placement((mid_x + 0.3, mid_y + 0.3))

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

    max_x = max([p[0] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    max_y = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    x_side = max_x + 15
    y_ref = max_y if max_y > 30 else 30

    msp.add_text("FICHA TECNICA - NORM.AI", dxfattribs={'height': 1.5, 'color': 2}).set_placement((x_side, y_ref))
    y_ref -= 5

    msp.add_text("DATOS GENERALES:", dxfattribs={'height': 1.0, 'color': 1}).set_placement((x_side, y_ref))
    y_ref -= 2.5
    propietario = str(datos.get('propietario', 'No detectado'))
    msp.add_text(f"PROPIETARIO ACTUAL: {sanitizar_texto(propietario)}", dxfattribs={'height': 0.7}).set_placement((x_side + 2, y_ref))

    y_ref -= 3.5
    area_calc = calcular_area(puntos_dwg)
    msp.add_text(f"AREA CALCULADA CAD: {area_calc:,.2f} m2", dxfattribs={'height': 0.8, 'color': 4}).set_placement((x_side + 2, y_ref))

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

    y_ref -= 8
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 1.0, 'color': 4}).set_placement((x_side, y_ref))
    y_ref -= 2.0

    msp.add_text("Linea", dxfattribs={'height': 0.6, 'color': 7}).set_placement((x_side + 2, y_ref))
    msp.add_text("Rumbo", dxfattribs={'height': 0.6, 'color': 7}).set_placement((x_side + 10, y_ref))
    msp.add_text("Distancia", dxfattribs={'height': 0.6, 'color': 7}).set_placement((x_side + 25, y_ref))
    y_ref -= 1.5

    for i, t in enumerate(tramos):
        if not isinstance(t, dict): continue
        d_val = limpiar_numero(t.get('distancia'))
        r_val = sanitizar_texto(t.get('rumbo_limpio', t.get('rumbo_texto', '')))
        if len(r_val) > 22: r_val = r_val[:19] + "..."

        msp.add_text(f"L{i+1}", dxfattribs={'height': 0.5}).set_placement((x_side + 2, y_ref))
        msp.add_text(r_val, dxfattribs={'height': 0.5}).set_placement((x_side + 10, y_ref))
        msp.add_text(f"{d_val:.2f} m", dxfattribs={'height': 0.5}).set_placement((x_side + 25, y_ref))
        y_ref -= 1.3

    if tiene_error_cierre:
        y_ref -= 4
        msp.add_text("NOTA DE CIERRE TOPOGRAFICO:", dxfattribs={'height': 0.8, 'color': 1}).set_placement((x_side, y_ref))
        y_ref -= 1.5
        msp.add_text("La linea roja indica el error de cierre del poligono.", dxfattribs={'height': 0.5, 'color': 7}).set_placement((x_side + 2, y_ref))
        y_ref -= 1.0
        msp.add_text("Esta discrepancia proviene de los datos de la escritura,", dxfattribs={'height': 0.5, 'color': 7}).set_placement((x_side + 2, y_ref))
        y_ref -= 1.0
        msp.add_text("no es un error de calculo del sistema Norm.AI.", dxfattribs={'height': 0.5, 'color': 7}).set_placement((x_side + 2, y_ref))

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_Poligono_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
archivo = st.file_uploader("Sube la Escritura (PDF)", type=["pdf"])

if archivo:
    if st.button("🚀 Extraer y Trazar Plano"):
        try:
            status = st.status("Analizando expediente legal...", expanded=True)
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

            # EL PROMPT RESTAURADO PARA QUE LEA TODO EL TERRENO
            prompt = """
            Eres un experto legal y catastral salvadoreño. Analiza esta escritura:
            1. 'propietario': Lee TODO el historial y extrae al DUEÑO ACTUAL Y DEFINITIVO.
            2. 'colindantes': Lista de vecinos.
            3. 'servidumbres' y 'quebradas'.
            4. 'tramos': Extrae TODOS LOS TRAMOS SIN SALTARTE NINGUNO para cerrar el polígono completo.
            - 'rumbo_texto': Frase original.
            - 'rumbo_limpio': UNA SOLA PALABRA (NORTE, SUR, ESTE, OESTE) o el grado (N 10° E).
            - 'distancia': Solo número.

            Formato JSON ESTRICTO:
            {
              "propietario": "Nombre de la dueña actual",
              "colindantes": ["Norte: ...", "Sur: ..."],
              "servidumbres": "...",
              "quebradas": "...",
              "tramos": [
                {"rumbo_texto": "Al Norte...", "rumbo_limpio": "NORTE", "distancia": 15.50},
                {"rumbo_texto": "Al Oriente...", "rumbo_limpio": "ESTE", "distancia": 10.00},
                {"rumbo_texto": "Al Sur...", "rumbo_limpio": "SUR", "distancia": 15.50},
                {"rumbo_texto": "Al Poniente...", "rumbo_limpio": "OESTE", "distancia": 10.00}
              ]
            }
            """

            response = model.generate_content([prompt] + google_files)
            text = response.text
            clean_json = text[text.find('{'):text.rfind('}')+1]
            datos = json.loads(clean_json)

            ruta_dxf = crear_dxf_integral(datos)

            status.update(label="✅ Expediente Técnico Listo", state="complete")
            with open(ruta_dxf, "rb") as f:
                st.download_button("💾 DESCARGAR DXF", f, file_name="Plano_NormAI_Final.dxf")

            for f in google_files: genai.delete_file(f.name)

        except Exception as e:
            st.error(f"Error en el motor: {e}")


st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
