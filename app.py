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
st.set_page_config(page_title="Norm.AI - Topografía 2.5", layout="wide")
st.title("📐 Extractor de Poligonales (Versión Estabilidad 2026)")

# MODELO ACTUALIZADO SEGÚN TU LISTA DE DISPONIBLES
MODELO_PRINCIPAL = 'gemini-2.5-flash'

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Intentamos conectar con el modelo 2.5
    try:
        model = genai.GenerativeModel(model_name=MODELO_PRINCIPAL)
    except:
        st.error("Error al inicializar el modelo. Verifica tu API Key.")
        st.stop()
else:
    st.error("⚠️ Configura la API Key en los Secrets de Streamlit.")
    st.stop()

# --- 2. MATEMÁTICA TOPOGRÁFICA (N, S, Poniente, Oriente) ---
def convertir_rumbo_a_radianes(rumbo_str):
    if not rumbo_str or rumbo_str.lower() == 'none': return None
    
    # Limpieza de términos salvadoreños
    r = rumbo_str.upper().replace('OESTE', 'W').replace('PONIENTE', 'W')
    r = r.replace('ESTE', 'E').replace('ORIENTE', 'E')
    r = r.replace('NORTE', 'N').replace('SUR', 'S')
    
    # Regex flexible: Grados y minutos obligatorios, segundos opcionales
    match = re.search(r'([NS])\s*(\d+)[°°º]?\s*(\d+)\'?\s*(?:(\d+(?:\.\d+)?)\s*")?\s*([EW])', r)
    
    if match:
        ns, g, m, s, ew = match.groups()
        segundos = float(s) if s else 0.0
        dec = float(g) + float(m)/60 + segundos/3600
        
        # Conversión a sistema cartesiano (N=90°, E=0°, S=270°, W=180°)
        if ns == 'N' and ew == 'E': ang = 90 - dec
        elif ns == 'N' and ew == 'W': ang = 90 + dec
        elif ns == 'S' and ew == 'E': ang = 270 + dec
        elif ns == 'S' and ew == 'W': ang = 270 - dec
        return math.radians(ang)
    return None

# --- 3. LÓGICA DE DIBUJO CAD ---
def crear_archivo_dxf(tramos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    for i, t in enumerate(tramos):
        try:
            dist = float(t.get('distancia', 0))
            rad = convertir_rumbo_a_radianes(t.get('rumbo', ''))
            
            if rad is not None:
                # Calcular siguiente vértice
                p_final = puntos[-1] + Vec2(math.cos(rad) * dist, math.sin(rad) * dist)
                
                # Dibujar Curva o Línea
                if t.get('tipo') == 'curva':
                    # Bulge de 0.4 para representar curvatura visual si no hay radio exacto
                    msp.add_lwpolyline([puntos[-1], p_final], dxfattribs={'bulge': 0.4, 'color': 3})
                else:
                    msp.add_line(puntos[-1], p_final)
                
                puntos.append(p_final)
            else:
                st.warning(f"Salto en tramo {i+1}: Formato de rumbo no reconocido.")
        except Exception:
            continue

    # Línea de cierre (opcional, en color rojo para verificar error de cierre)
    if len(puntos) > 2:
        msp.add_line(puntos[-1], puntos[0], dxfattribs={'linetype': 'DASHED', 'color': 1})

    # Cuadro de datos técnico
    x_offset = 35
    msp.add_text("CUADRO TÉCNICO NORM.AI", dxfattribs={'height': 0.8}).set_placement((x_offset, 10))
    for i, t in enumerate(tramos):
        info = f"L{i+1}: {t.get('rumbo')} | {t.get('distancia')}m"
        msp.add_text(info, dxfattribs={'height': 0.5}).set_placement((x_offset, 10 - (i+1)*1.2))

    temp_path = os.path.join(tempfile.gettempdir(), f"topografia_{int(time.time())}.dxf")
    doc.saveas(temp_path)
    return temp_path

# --- 4. PROCESAMIENTO ---
archivo = st.file_uploader("Sube el PDF de la escritura (9 páginas)", type=["pdf"])

if archivo:
    if st.button("🚀 Procesar Poligonal con Gemini 2.5"):
        try:
            doc_pdf = fitz.open(stream=archivo.read(), filetype="pdf")
            num_pags = len(doc_pdf)
            
            with st.spinner("Unificando páginas de la escritura..."):
                paginas_img = []
                for i in range(num_pags):
                    p = doc_pdf.load_page(i)
                    pix = p.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    paginas_img.append(img)
                
                # Unir verticalmente
                ancho = max(p.size[0] for p in paginas_img)
                alto = sum(p.size[1] for p in paginas_img)
                img_final = Image.new("RGB", (ancho, alto))
                y_coord = 0
                for p in paginas_img:
                    img_final.paste(p, (0, y_coord))
                    y_coord += p.size[1]
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img_final.save(tmp.name, "JPEG", quality=75)
                    ruta_tmp = tmp.name

            # Subida a Google Cloud
            st.info(f"Analizando con motor {MODELO_PRINCIPAL}...")
            g_file = genai.upload_file(path=ruta_tmp)
            while g_file.state.name == "PROCESSING":
                time.sleep(1)
                g_file = genai.get_file(g_file.name)

            prompt = """
            Eres un experto en catastro de El Salvador. 
            Analiza el documento y extrae la descripción técnica de rumbos y distancias.
            1. Conecta los datos de todas las páginas.
            2. Identifica tramos rectos y curvos (busca palabras como 'Radio' o 'Arco').
            3. Devuelve estrictamente un JSON:
            {"tramos": [{"rumbo": "N 87° 40' W", "distancia": 6.0, "tipo": "curva", "radio": 10.0}]}
            """

            response = model.generate_content([prompt, g_file])
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            
            if match:
                datos_json = json.loads(match.group())
                ruta_dxf = crear_archivo_dxf(datos_json['tramos'])
                st.success("✅ ¡Geometría generada!")
                with open(ruta_dxf, "rb") as f:
                    st.download_button("💾 Descargar DXF para AutoCAD", f, file_name="poligonal_2.5.dxf")
                st.json(datos_json)
            else:
                st.error("No se pudo extraer la estructura de datos. Verifica la legibilidad del PDF.")

            genai.delete_file(g_file.name)
            os.remove(ruta_tmp)

        except Exception as e:
            st.error(f"Error en el motor: {e}")

st.divider()
st.caption(f"Norm.AI | Miguel Guidos - Arquitectura & Tecnología | 2026")
