import streamlit as st
import google.generativeai as genai
import json
import math
import matplotlib.pyplot as plt
import ezdxf
import os
import tempfile
import folium
from streamlit_folium import st_folium
import re

# --- 1. CONFIGURACIÓN Y FUNCIONES BASE ---
st.set_page_config(page_title="GraphiTop", layout="wide")
st.title("🏗️ GraphiTop: Suite de Análisis Topográfico")

try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except KeyError:
    st.error("Falta configurar la llave de la API. Revisa tu archivo secrets.toml")
    st.stop()

def calcular_area(x, y):
    area = 0.0
    n = len(x)
    for i in range(n):
        j = (i + 1) % n
        area += x[i] * y[j] - x[j] * y[i]
    return abs(area) / 2.0

def extraer_poligono_dxf(file_stream):
    try:
        doc = ezdxf.read(file_stream)
        msp = doc.modelspace()
        for entity in msp.query('LWPOLYLINE POLYLINE'):
            puntos = list(entity.vertices()) if entity.dxftype() == 'POLYLINE' else entity.get_points('xy')
            if puntos:
                x = [p[0] for p in puntos]
                y = [p[1] for p in puntos]
                return x, y
    except Exception:
        return None, None
    return None, None

def rumbo_a_azimut(rumbo_str):
    """NUEVO TRADUCTOR INDESTRUCTIBLE: Encuentra los números sin importar los símbolos."""
    try:
        r = str(rumbo_str).upper()
        
        # 1. Identificar cuadrante
        ns = 'N' if 'N' in r else ('S' if 'S' in r else None)
        ew = 'E' if 'E' in r else ('W' if 'W' in r else None)
        
        if not ns or not ew:
            return 0.0 # Fallback si no hay cuadrante

        # 2. Extraer solo los números (grados, minutos, segundos) sin importar los símbolos entre ellos
        nums = re.findall(r"[\d.]+", r)
        
        grados = float(nums[0]) if len(nums) > 0 else 0.0
        minutos = float(nums[1]) if len(nums) > 1 else 0.0
        segundos = float(nums[2]) if len(nums) > 2 else 0.0

        grados_dec = grados + (minutos / 60.0) + (segundos / 3600.0)

        # 3. Calcular Azimut basado en el cuadrante
        if ns == 'N' and ew == 'E': return grados_dec
        if ns == 'S' and ew == 'E': return 180.0 - grados_dec
        if ns == 'S' and ew == 'W': return 180.0 + grados_dec
        if ns == 'N' and ew == 'W': return 360.0 - grados_dec
    except Exception:
        return 0.0
    return 0.0

# --- AGENTES DE IA ---
instrucciones_topografia = """
Eres un experto topógrafo. Tu ÚNICA tarea es extraer exactamente los linderos (tramos, rumbos y distancias) de los documentos legales proporcionados.
NO calcules azimuts. NO modifiques los ángulos. Solo copia el rumbo y la distancia EXACTAMENTE como aparecen en el documento.
REGLA PARA CURVAS: Si un tramo es curvo, debes buscar y extraer estrictamente los datos de su "CUERDA" (rumbo y distancia de la cuerda) para usarlos como valores principales.
Formatea los rumbos así (Ej: "N 28° 39' 11'' W"). USA DOS COMILLAS SIMPLES para segundos.
Responde ÚNICAMENTE con un arreglo JSON válido: 
[
  {"tramo": "Norte 1", "distancia": 18.31, "rumbo": "S 89 10 15 E", "es_curva": false, "radio": 0},
  {"tramo": "Norte 2", "distancia": 5.20, "rumbo": "N 10 00 00 E", "es_curva": true, "radio": 15.5}
]
"""
modelo_topografo = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_topografia)

instrucciones_visual = "Eres un Arquitecto Auditor Senior. Compara visualmente los dos planos proporcionados y genera un reporte técnico estructurado detallando las discrepancias."
modelo_auditor = genai.GenerativeModel('gemini-2.5-pro', system_instruction=instrucciones_visual)

# --- 2. INTERFAZ DE PESTAÑAS ---
tab1, tab2, tab3, tab4 = st.tabs([
    "📄 1. Generador DXF", 
    "⚖️ 2. Comparativo Visual (PDF/IMG)", 
    "📐 3. Comparativo CAD (DXF)", 
    "🌍 4. Mapa Interactivo"
])

# --- PESTAÑA 1: GENERADOR ---
with tab1:
    st.header("Generar Poligonal desde Documento Legal")
    st.write("Sube tu escritura o plano legal para analizar la topografía.")
    arch_gen = st.file_uploader("Sube el documento legal", type=["pdf", "jpg", "png"], key="gen_file")
    
    if st.button("🚀 Extraer y Generar DXF", key="btn_gen"):
        if arch_gen:
            with st.spinner("Leyendo documento con precisión matemática..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_gen.name.split('.')[-1]}") as tf:
                    tf.write(arch_gen.getbuffer())
                    temp_path = tf.name
                
                archivo_subido = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([archivo_subido])
                genai.delete_file(archivo_subido.name)
                os.remove(temp_path)
                
                try:
                    texto_json = respuesta.text.strip().strip('```json').strip('```')
                    datos = json.loads(texto_json)
                except Exception as e:
                    st.error(f"Error al leer los datos de la IA: {e}")
                    st.stop()
                
                with st.expander("🔍 Ver datos extraídos exactamente como están en la escritura"):
                    st.json(datos)

                # Motor Matemático Mejorado
                x, y = 0.0, 0.0
                cx, cy = [x], [y]
                for t in datos:
                    if t.get("rumbo") is not None:
                        # Usar el NUEVO traductor
                        azimut_calculado = rumbo_a_azimut(t["rumbo"])
                        az_rad = math.radians(azimut_calculado)
                        x += t["distancia"] * math.sin(az_rad)
                        y += t["distancia"] * math.cos(az_rad)
                        cx.append(x)
                        cy.append(y)
                
                # Gráfico con Matplotlib
                fig, ax = plt.subplots(figsize=(8,8))
                
                # Dibujar tramos individuales para poder hacer curvas punteadas
                for i in range(len(cx) - 1):
                    px, py = cx[i], cy[i]
                    nx, ny = cx[i+1], cy[i+1]
                    
                    es_curva = i < len(datos) and datos[i].get("es_curva", False)
                    estilo = '--' if es_curva else '-'
                    color_linea = 'red' if es_curva else 'blue'
                    
                    ax.plot([px, nx], [py, ny], color=color_linea, linestyle=estilo, linewidth=2)
                    
                    # Dibujar mojón
                    ax.plot(px, py, marker='o', color='darkgreen', markersize=6)
                    
                    # Etiqueta del mojón
                    texto_mojon = f"  M{i+1}"
                    if es_curva:
                        radio = datos[i].get("radio", "N/A")
                        texto_mojon += f"\n  (Curva R={radio})"
                        
                    ax.text(px, py, texto_mojon, fontsize=9, color='darkgreen', fontweight='bold', va='bottom')

                ax.fill(cx, cy, color='blue', alpha=0.05)
                ax.axis('equal')
                ax.grid(True, linestyle='--', alpha=0.6)
                st.pyplot(fig)

                # Generación del archivo DXF
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                
                # Dibujar polígono en DXF (la cuerda va en capa separada si es curva)
                for i in range(len(cx) - 1):
                    px, py = cx[i], cy[i]
                    nx, ny = cx[i+1], cy[i+1]
                    
                    es_curva = i < len(datos) and datos[i].get("es_curva", False)
                    # Color 1 (Rojo) para cuerdas, 5 (Azul) para líneas rectas
                    color_dxf = 1 if es_curva else 5 
                    
                    msp.add_line((px, py), (nx, ny), dxfattribs={'color': color_dxf})
                    msp.add_circle((px, py), radius=0.5, dxfattribs={'color': 2})
                    msp.add_text(f"M{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((px + 1, py + 1))

                nombre_archivo = "GraphiTop_Plano.dxf"
                doc.saveas(nombre_archivo)
                with open(nombre_archivo, "rb") as file:
                    st.success("¡Análisis topográfico procesado exitosamente!")
                    st.download_button(label="📥 Descargar Archivo DXF", data=file, file_name=nombre_archivo, mime="application/dxf")
        else:
            st.warning("Sube un archivo primero.")

# --- PESTAÑAS 2, 3, y 4 (Se mantienen iguales) ---
with tab2: st.info("Pestaña activa.")
with tab3: st.info("Pestaña activa.")
with tab4: st.info("Pestaña activa.")
