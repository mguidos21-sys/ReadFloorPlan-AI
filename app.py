import streamlit as st
import google.generativeai as genai
import ezdxf
import json
import re
import math
import os
import tempfile
import time

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Procesamiento de escritura a poligonal", layout="wide")
st.title("📐 Procesamiento de escritura a poligonal")

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
    if valor is None: return 0.0
    numeros = re.findall(r"[-+]?\d*\.\d+|\d+", str(valor).replace(',', '.'))
    if not numeros: return 0.0
    n = float(numeros[0])
    return n if n >= 0.05 else 0.0

def interpretar_rumbo_o_azimut(texto, ultimo_rad=0.0):
    if not texto: return ultimo_rad
    t = str(texto).upper().strip()
    
    match_az = re.search(r'(\d+)\s*[°º]\s*(\d+)\s*[\'’]\s*(\d+(?:\.\d+)?)?\s*["”\'\s]*', t)
    if match_az and not any(x in t for x in ['N', 'S', 'E', 'W', 'O']):
        g, m, s = match_az.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        return math.radians(90 - dec)

    t_norm = t.replace('OESTE', 'W').replace('PONIENTE', 'W').replace('ORIENTE', 'E').replace('ESTE', 'E').replace('NORTE', 'N').replace('SUR', 'S')
    
    match_r = re.search(r'([NS])\s*(\d+)[°\s]*(\d+)[\'\s]*(\d+(?:\.\d+)?)?[\"”\'\s]*([EW])', t_norm)
    if match_r:
        ns, g, m, s, ew = match_r.groups()
        seg = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + seg/3600
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
        
    letras = [c for c in t_norm if c in ['N', 'S', 'E', 'W']]
    if letras:
        if all(c == 'N' for c in letras): return math.radians(90)
        if all(c == 'S' for c in letras): return math.radians(270)
        if all(c == 'E' for c in letras): return math.radians(0)
        if all(c == 'W' for c in letras): return math.radians(180)
        if set(letras) == {'N', 'E'}: return math.radians(45)
        if set(letras) == {'N', 'W'}: return math.radians(135)
        if set(letras) == {'S', 'E'}: return math.radians(315)
        if set(letras) == {'S', 'W'}: return math.radians(225)

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
        dist = limpiar_numero_distancia(t.get('distancia'))
        r_txt = str(t.get('rumbo_limpio', ''))
        es_curva = t.get('es_curva', False)
        rad = interpretar_rumbo_o_azimut(r_txt, ultimo_rad)

        if dist > 0:
            next_x = round(current_x + math.cos(rad) * dist, 4)
            next_y = round(current_y + math.sin(rad) * dist, 4)

            mid_x = (current_x + next_x) / 2
            mid_y = (current_y + next_y) / 2
            
            color_txt = 3 if es_curva else 7 
            label = sanitizar_texto(t.get('etiqueta', f"E{i+1}"))
            msp.add_text(label, dxfattribs={'height': 1.0, 'color': color_txt}).set_placement((mid_x + 0.3, mid_y + 0.3))

            current_x, current_y = next_x, next_y
            puntos_dwg.append((current_x, current_y))
            ultimo_rad = rad

    if len(puntos_dwg) > 1:
        msp.add_lwpolyline(puntos_dwg, dxfattribs={'color': 7})
        if puntos_dwg[-1] != puntos_dwg[0]:
            dist_cierre = math.sqrt((puntos_dwg[-1][0])**2 + (puntos_dwg[-1][1])**2)
            if dist_cierre > 0.1: 
                msp.add_line(puntos_dwg[-1], puntos_dwg[0], dxfattribs={'color': 1})

    max_x = max([p[0] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    max_y = max([p[1] for p in puntos_dwg]) if len(puntos_dwg) > 1 else 0
    x_side = max_x + 40
    y_ref = max_y if max_y > 50 else 50

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

    y_ref -= 15
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 2.0, 'color': 4}).set_placement((x_side, y_ref))
    y_ref -= 5.0
    
    header_height = 0.8
    msp.add_text("Est", dxfattribs={'height': header_height, 'color': 7}).set_placement((x_side + 2, y_ref))
    msp.add_text("Rumbo/Azimut", dxfattribs={'height': header_height, 'color': 7}).set_placement((x_side + 10, y_ref))
    msp.add_text("Dist (m)", dxfattribs={'height': header_height, 'color': 7}).set_placement((x_side + 40, y_ref))
    y_ref -= 3.0

    tiene_alguna_curva = False
    data_height = 0.6
    column_width = 50
    current_col_x = x_side

    for i, t in enumerate(tramos):
        dist = limpiar_numero_distancia(t.get('distancia'))
        r_val = sanitizar_texto(t.get('rumbo_limpio', ''))
        label = sanitizar_texto(t.get('etiqueta', f"E{i+1}"))
        es_curva = t.get('es_curva', False)
        
        col_fila = 3 if es_curva else 7
        if es_curva: tiene_alguna_curva = True
            
        if len(r_val) > 28: r_val = r_val[:25] + "..."
            
        msp.add_text(f"{label}", dxfattribs={'height': data_height, 'color': col_fila}).set_placement((current_col_x + 2, y_ref))
        msp.add_text(r_val, dxfattribs={'height': data_height, 'color': col_fila}).set_placement((current_col_x + 10, y_ref))
        msp.add_text(f"{dist:.2f}", dxfattribs={'height': data_height, 'color': col_fila}).set_placement((current_col_x + 40, y_ref))
        
        y_ref -= 1.2
        
        if y_ref < (max_y - 250):
            y_ref = max_y - 30 
            current_col_x += column_width 
            
            msp.add_text("Est", dxfattribs={'height': header_height, 'color': 7}).set_placement((current_col_x + 2, y_ref))
            msp.add_text("Rumbo/Azimut", dxfattribs={'height': header_height, 'color': 7}).set_placement((current_col_x + 10, y_ref))
            msp.add_text("Dist (m)", dxfattribs={'height': header_height, 'color': 7}).set_placement((current_col_x + 40, y_ref))
            y_ref -= 3.0

    if tiene_alguna_curva:
        y_ref -= 6
        msp.add_text("AVISO GEOMETRIA (Verde): Tramos curvos dibujados rectos.", dxfattribs={'height': 1.0, 'color': 3}).set_placement((x_side, y_ref))

    temp_path = os.path.join(tempfile.gettempdir(), f"NormAI_Expediente_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. INTERFAZ ---
st.info("💡 **Sistema Anti-Fatiga Activado:** Extracción exhaustiva garantizada para escrituras de cualquier longitud.")

archivo = st.file_uploader("Sube el PDF de la Escritura", type=["pdf"])

if archivo:
    if st.button("🚀 Extraer Datos y Trazar Poligonal"):
        try:
            status = st.status("Analizando documento nativo con precisión milimétrica...", expanded=True)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                temp_pdf.write(archivo.read())
                temp_pdf_path = temp_pdf.name

            gemini_file = genai.upload_file(temp_pdf_path)

            while gemini_file.state.name == "PROCESSING":
                time.sleep(1)
                gemini_file = genai.get_file(gemini_file.name)

            prompt = """
            Eres un ingeniero topógrafo experto analizando un documento legal.
            
            INSTRUCCIONES ESTRICTAS Y OBLIGATORIAS:
            1. Extrae propietario, colindantes, servidumbres y quebradas.
            2. AISLAMIENTO: Si el documento describe varios lotes (ej. Lote 1, Lote 2), extrae ÚNICAMENTE la descripción técnica del PRIMER LOTE.
            3. MANDATO DE EXHAUSTIVIDAD ABSOLUTA: TIENES ESTRICTAMENTE PROHIBIDO RESUMIR LA LISTA DE TRAMOS.
               - Inicia en el primer tramo del perímetro.
               - Extrae cada tramo secuencialmente.
               - Tu condición de parada NO es una cantidad de tramos, sino encontrar en el texto la frase que indica el cierre del polígono (ej. "y así se llega al vértice inicial", "llegando al punto de partida", etc.).
               - Así sean 10, 50 o 150 tramos, tu obligación es procesar el texto hasta la frase de cierre.
            4. ESCRITURAS ANTIGUAS: Si solo hay puntos cardinales (ej. "Al Norte linda..."), úsalos como rumbo (ej. {"rumbo_limpio": "NORTE"}).
            5. FORMATO: NUNCA uses comillas dobles (") para los segundos en los rumbos. Usa dos comillas simples ('').
            
            Responde ÚNICAMENTE con este JSON:
            {
              "propietario": "Nombre completo",
              "colindantes": ["Norte: ...", "Sur: ..."],
              "servidumbres": "Describir si hay",
              "quebradas": "Describir si hay",
              "tramos": [
                {"etiqueta": "E1", "rumbo_limpio": "N 10° 15' 20'' E", "distancia": 45.00, "es_curva": false}
              ]
            }
            """
            
            # 🔥 INYECCIÓN DE PARÁMETROS PARA EVITAR PEREZA ARTIFICIAL 🔥
            response = model.generate_content(
                [prompt, gemini_file],
                generation_config={"temperature": 0.0, "max_output_tokens": 8192}
            )
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
                st.error("⚠️ Error de lectura de datos. El documento es demasiado complejo o la IA abortó la escritura.")
                st.stop()
            
            ruta = crear_dxf_integral(datos)
            status.update(label=f"✅ Datos recuperados íntegramente. {len(datos.get('tramos', []))} tramos extraídos.", state="complete")
            
            with open(ruta, "rb") as f:
                st.download_button("💾 DESCARGAR DXF PROFESIONAL", f, file_name="Plano_Generado_NormAI.dxf")
            
            try:
                genai.delete_file(gemini_file.name)
                os.remove(temp_pdf_path)
            except: pass
                
        except Exception as e:
            st.error(f"Error: {e}")

st.divider()
st.caption("Norm.AI | Tecnología de Precisión | Arq. Miguel Guidos")
