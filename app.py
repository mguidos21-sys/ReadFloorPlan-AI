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

# --- 1. CONFIGURACIÓN Y FUNCIONES BASE ---
st.set_page_config(page_title="Comparativo AI", layout="wide")
st.title("🏗️ Comparativo: Suite de Análisis Topográfico")

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

# --- AGENTES DE IA (AQUÍ ESTÁ LA NUEVA REGLA DE CURVAS) ---
instrucciones_topografia = """
Eres un experto revisor de proyectos arquitectónicos. Extrae CADA tramo, distancia en metros y el rumbo de los documentos o imágenes.
REGLA PARA CURVAS: Si un tramo es curvo, debes buscar y extraer estrictamente los datos de su "CUERDA" (rumbo y distancia de la cuerda) para usarlos como valores principales.
Calcula el azimut en grados decimales. Formatea el rumbo a GMS (Ej: "N 28° 39' 11'' W"). USA DOS COMILLAS SIMPLES para segundos.
Responde ÚNICAMENTE con un arreglo en formato JSON válido: 
[
  {"tramo": "Norte 1", "distancia": 18.31, "rumbo_formateado": "S 89° 10' 15'' E", "azimut": 90.829, "es_curva": false, "radio": 0},
  {"tramo": "Norte 2", "distancia": 5.20, "rumbo_formateado": "N 10° 00' 00'' E", "azimut": 10.0, "es_curva": true, "radio": 15.5}
]
"""
modelo_topografo = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_topografia)

instrucciones_visual = """
Eres un Arquitecto Auditor Senior. Compara visualmente los dos planos proporcionados (Plano A y Plano B).
Identifica discrepancias en cotas, huellas, rumbos o elementos arquitectónicos.
Genera un reporte técnico estructurado detallando las diferencias encontradas o confirmando si son idénticos.
"""
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
    st.write("Sube tu escritura (PDF) o una imagen (JPG/PNG) del cuadro de rumbos y distancias.")
    arch_gen = st.file_uploader("Sube el documento legal", type=["pdf", "jpg", "png"], key="gen_file")
    
    if st.button("🚀 Extraer y Generar DXF", key="btn_gen"):
        if arch_gen:
            with st.spinner("Procesando documento y detectando curvas..."):
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
                
                with st.expander("🔍 Ver datos extraídos (Auditoría)"):
                    st.json(datos)

                # Motor Matemático
                x, y = 0.0, 0.0
                cx, cy = [x], [y]
                for t in datos:
                    if t.get("azimut") is not None:
                        az_rad = math.radians(t["azimut"])
                        x += t["distancia"] * math.sin(az_rad)
                        y += t["distancia"] * math.cos(az_rad)
                        cx.append(x)
                        cy.append(y)
                
                # Gráfico con Matplotlib
                fig, ax = plt.subplots(figsize=(8,8))
                ax.plot(cx, cy, color='blue', linestyle='-', linewidth=2, label='Poligonal Generada')
                ax.fill(cx, cy, color='blue', alpha=0.1)
                
                for i in range(len(cx) - 1):
                    px, py = cx[i], cy[i]
                    ax.plot(px, py, marker='o', color='darkgreen', markersize=6)
                    texto_mojon = f"  M{i+1}"
                    
                    # Identificador visual de curvas
                    if i < len(datos) and datos[i].get("es_curva", False):
                        radio = datos[i].get("radio", "N/A")
                        texto_mojon += f"\n  (Curva R={radio})"
                        
                    ax.text(px, py, texto_mojon, fontsize=9, color='darkgreen', fontweight='bold', va='bottom')

                ax.axis('equal')
                ax.grid(True, linestyle='--', alpha=0.6)
                st.pyplot(fig)

                # --- Generación del archivo DXF ---
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                msp.add_lwpolyline(list(zip(cx, cy)), dxfattribs={'color': 5})
                
                for i in range(len(cx) - 1):
                    px, py = cx[i], cy[i]
                    msp.add_circle((px, py), radius=0.5, dxfattribs={'color': 2})
                    msp.add_text(f"M{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((px + 1, py + 1))

                max_x, max_y = max(cx), max(cy)
                cuadro_x, cuadro_y = max_x + 15, max_y
                
                msp.add_text("CUADRO DE CONSTRUCCION", dxfattribs={'height': 2, 'color': 3}).set_placement((cuadro_x, cuadro_y))
                cuadro_y -= 4 
                msp.add_text("TRAMO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x, cuadro_y))
                msp.add_text("RUMBO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 15, cuadro_y))
                msp.add_text("DISTANCIA", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 45, cuadro_y))
                cuadro_y -= 2.5
                
                for i, tramo in enumerate(datos):
                    mojon_inicio = i + 1
                    mojon_fin = i + 2 if i < len(datos) - 1 else 1
                    
                    # Si es curva, lo indicamos en el DXF
                    nota_curva = " (Cuerda)" if tramo.get("es_curva", False) else ""
                    texto_tramo = f"M{mojon_inicio} a M{mojon_fin}{nota_curva}"
                    
                    msp.add_text(texto_tramo, dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x, cuadro_y))
                    msp.add_text(str(tramo.get('rumbo_formateado', 'FALTA')), dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 15, cuadro_y))
                    msp.add_text(f"{tramo.get('distancia', 'FALTA')} m", dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 45, cuadro_y))
                    cuadro_y -= 2 

                nombre_archivo = "Poligonal_Legal_InspecAI.dxf"
                doc.saveas(nombre_archivo)
                with open(nombre_archivo, "rb") as file:
                    st.success("¡Análisis y geometría procesados correctamente!")
                    st.download_button(label="📥 Descargar Archivo DXF", data=file, file_name=nombre_archivo, mime="application/dxf")
        else:
            st.warning("Sube un archivo primero.")

# --- PESTAÑA 2: COMPARATIVO VISUAL ---
with tab2:
    st.header("Auditoría Visual de Planos")
    colA, colB = st.columns(2)
    with colA: arch_A = st.file_uploader("Plano A (Referencia)", type=["pdf", "jpg", "png"])
    with colB: arch_B = st.file_uploader("Plano B (A Evaluar)", type=["pdf", "jpg", "png"])
    
    if st.button("👁️ Comparar Planos", key="btn_vis"):
        if arch_A and arch_B:
            with st.spinner("La IA está analizando visualmente ambos planos..."):
                files_to_delete = []
                docs_to_send = []
                for f in [arch_A, arch_B]:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{f.name.split('.')[-1]}") as tf:
                        tf.write(f.getbuffer())
                    upload = genai.upload_file(tf.name)
                    docs_to_send.append(upload)
                    files_to_delete.append((upload, tf.name))
                
                res_visual = modelo_auditor.generate_content(docs_to_send)
                
                for upload, tmp_path in files_to_delete:
                    genai.delete_file(upload.name)
                    os.remove(tmp_path)
                    
                st.markdown("### 📋 Reporte de Auditoría")
                st.write(res_visual.text)
        else:
            st.warning("Sube ambos planos para comparar.")

# --- PESTAÑA 3: COMPARATIVO CAD ---
with tab3:
    st.header("Superposición Matemática (IA vs Topógrafo)")
    st.info("Sube la escritura y el DXF del topógrafo para verificar las diferencias de área y geometría.")
    col_izq, col_der = st.columns(2)
    with col_izq:
        arch_legal_cad = st.file_uploader("Sube la escritura", type=["pdf", "jpg", "png"], key="legal_cad")
    with col_der:
        arch_dxf_prof = st.file_uploader("Sube el DXF del topógrafo", type=["dxf"], key="dxf_prof")
    
    if st.button("⚖️ Ejecutar Comparativo", key="btn_comp_cad"):
        if arch_legal_cad and arch_dxf_prof:
            st.info("Función de superposición lista para integrarse.")
            # Aquí irá la lógica de superposición que ya programamos antes.
        else:
            st.warning("Sube ambos archivos para realizar la comparación matemática.")

# --- PESTAÑA 4: MAPA INTERACTIVO ---
with tab4:
    st.header("Geolocalización del Proyecto")
    st.write("Ingresa las coordenadas de amarre (Punto de inicio M1) para proyectar el terreno en el mapa.")
    
    col_lat, col_lon = st.columns(2)
    with col_lat: lat_inicio = st.number_input("Latitud Inicial (Ej. 13.698)", value=13.698000, format="%.6f")
    with col_lon: lon_inicio = st.number_input("Longitud Inicial (Ej. -89.145)", value=-89.
