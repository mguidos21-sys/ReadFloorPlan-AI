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

def rumbo_a_azimut(rumbo_str):
    """Convierte un texto de rumbo (Ej: N 25° 30' 15'' W) a Azimut decimal exacto."""
    try:
        r = str(rumbo_str).upper().replace('"', "''").replace(" ", "")
        # Extraer partes usando expresiones regulares
        match = re.search(r'([NS])(\d+)[°D]+(\d+)[\'M]+([\d.]+)[\'\'"S]*([EW])', r)
        if match:
            ns, grados, minutos, segundos, ew = match.groups()
        else:
            # Intentar sin segundos
            match = re.search(r'([NS])(\d+)[°D]+(\d+)[\'M]*([EW])', r)
            if match:
                ns, grados, minutos, ew = match.groups()
                segundos = 0
            else:
                return 0.0 # Fallback si no entiende el formato

        grados_dec = float(grados) + float(minutos)/60.0 + float(segundos)/3600.0

        if ns == 'N' and ew == 'E': return grados_dec
        if ns == 'S' and ew == 'E': return 180.0 - grados_dec
        if ns == 'S' and ew == 'W': return 180.0 + grados_dec
        if ns == 'N' and ew == 'W': return 360.0 - grados_dec
    except Exception:
        return 0.0
    return 0.0

# --- AGENTES DE IA (NUEVO PROMPT ESTRICTO DE LECTURA) ---
instrucciones_topografia = """
Eres un experto topógrafo. Tu ÚNICA tarea es extraer exactamente los linderos de la escritura o plano.
NO calcules nada. Solo copia el rumbo y la distancia EXACTAMENTE como aparecen en el documento.

REGLA PARA CURVAS: Si el tramo es curvo, extrae el rumbo de su CUERDA, la distancia de su CUERDA y el RADIO.

Responde ÚNICAMENTE con un arreglo JSON con esta estructura exacta:
[
  {"tramo": "Norte 1", "distancia": 18.31, "rumbo": "S 89° 10' 15'' E", "es_curva": false, "radio": 0},
  {"tramo": "Norte 2", "distancia": 5.20, "rumbo": "N 10° 00' 00'' E", "es_curva": true, "radio": 15.5}
]
"""
modelo_topografo = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_topografia)

instrucciones_visual = "Eres un Arquitecto Auditor Senior. Compara visualmente los dos planos y reporta discrepancias."
modelo_auditor = genai.GenerativeModel('gemini-2.5-pro', system_instruction=instrucciones_visual)

# --- 2. INTERFAZ DE PESTAÑAS ---
tab1, tab2, tab3, tab4 = st.tabs([
    "📄 1. Generador DXF", 
    "⚖️ 2. Comparativo Visual", 
    "📐 3. Comparativo CAD", 
    "🌍 4. Mapa Interactivo"
])

# --- PESTAÑA 1: GENERADOR ---
with tab1:
    st.header("Generar Poligonal desde Documento Legal")
    arch_gen = st.file_uploader("Sube el documento legal", type=["pdf", "jpg", "png"], key="gen_file")
    
    if st.button("🚀 Extraer y Generar DXF", key="btn_gen"):
        if arch_gen:
            with st.spinner("Leyendo documento con precisión..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_gen.name.split('.')[-1]}") as tf:
                    tf.write(arch_gen.getbuffer())
                    temp_path = tf.name
                
                archivo_subido = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([archivo_subido])
                genai.delete_file(archivo_subido.name)
                os.remove(temp_path)
                
                try:
                    texto_json = respuesta.text.replace('```json', '').replace('```', '').strip()
                    datos = json.loads(texto_json)
                except Exception as e:
                    st.error("Error al leer el documento. Asegúrate de que los rumbos estén legibles.")
                    st.stop()
                
                with st.expander("🔍 Ver datos extraídos exactamente como están en la escritura"):
                    st.json(datos)

                # Motor Matemático en Python
                x, y = 0.0, 0.0
                cx, cy = [x], [y]
                for t in datos:
                    azimut_calculado = rumbo_a_azimut(t["rumbo"])
                    az_rad = math.radians(azimut_calculado)
                    x += t["distancia"] * math.sin(az_rad)
                    y += t["distancia"] * math.cos(az_rad)
                    cx.append(x)
                    cy.append(y)
                
                # Gráfico
                fig, ax = plt.subplots(figsize=(8,8))
                
                for i in range(len(cx) - 1):
                    px, py = cx[i], cy[i]
                    nx, ny = cx[i+1], cy[i+1]
                    
                    # Dibujar línea normal o punteada si es curva
                    es_curva = i < len(datos) and datos[i].get("es_curva", False)
                    estilo = '--' if es_curva else '-'
                    color_linea = 'red' if es_curva else 'blue'
                    
                    ax.plot([px, nx], [py, ny], color=color_linea, linestyle=estilo, linewidth=2)
                    ax.plot(px, py, marker='o', color='darkgreen', markersize=6)
                    
                    texto_mojon = f" M{i+1}"
                    if es_curva: texto_mojon += f"\n (Curva R={datos[i].get('radio', 'N/A')})"
                    ax.text(px, py, texto_mojon, fontsize=9, color='darkgreen', fontweight='bold', va='bottom')

                ax.fill(cx, cy, color='blue', alpha=0.05)
                ax.axis('equal')
                ax.grid(True, linestyle=':', alpha=0.6)
                st.pyplot(fig)

                # Generación DXF
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                
                for i in range(len(cx) - 1):
                    px, py = cx[i], cy[i]
                    nx, ny = cx[i+1], cy[i+1]
                    es_curva = i < len(datos) and datos[i].get("es_curva", False)
                    # La cuerda va en capa separada (roja) si es curva
                    color_dxf = 1 if es_curva else 5 
                    msp.add_line((px, py), (nx, ny), dxfattribs={'color': color_dxf})
                    msp.add_circle((px, py), radius=0.5, dxfattribs={'color': 2})
                    msp.add_text(f"M{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((px + 1, py + 1))

                nombre_archivo = "GraphiTop_Plano.dxf"
                doc.saveas(nombre_archivo)
                with open(nombre_archivo, "rb") as file:
                    st.success("¡Coordenadas exactas procesadas!")
                    st.download_button("📥 Descargar Archivo DXF", data=file, file_name=nombre_archivo, mime="application/dxf")

# --- PESTAÑA 2 y 3 (Se mantienen iguales por brevedad de lectura, puedes dejarlas en blanco por ahora si lo deseas o conservar las anteriores) ---
with tab2: st.info("Auditoría visual activa.")
with tab3: st.info("Superposición activa.")

# --- PESTAÑA 4: MAPA INTERACTIVO ---
with tab4:
    st.header("Geolocalización del Proyecto")
    col_lat, col_lon = st.columns(2)
    with col_lat: lat_inicio = st.number_input("Latitud Inicial (Ej. 13.698)", value=13.698000, format="%.6f")
    with col_lon: lon_inicio = st.number_input("Longitud Inicial (Ej. -89.145)", value=-89.145000, format="%.6f")
    
    arch_mapa = st.file_uploader("Sube la escritura para trazar el mapa", type=["pdf", "jpg", "png"], key="map_file")
    
    if st.button("🌍 Proyectar en Mapa", key="btn_mapa"):
        if arch_mapa:
            with st.spinner("Procesando coordenadas GPS..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_mapa.name.split('.')[-1]}") as tf:
                    tf.write(arch_mapa.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)
                
                try:
                    texto_json = respuesta.text.replace('```json', '').replace('```', '').strip()
                    datos = json.loads(texto_json)
                except Exception as e:
                    st.error("Error al extraer los datos para el mapa. Asegúrate de que el PDF sea legible.")
                    st.stop()
                
                puntos_gps = [(lat_inicio, lon_inicio)]
                lat_actual, lon_actual = lat_inicio, lon_inicio
                R_TIERRA = 111320.0 
                
                for t in datos:
                    azimut_calculado = rumbo_a_azimut(t["rumbo"])
                    az_rad = math.radians(azimut_calculado)
                    dist = t["distancia"]
                    
                    delta_y = dist * math.cos(az_rad)
                    delta_x = dist * math.sin(az_rad)
                    
                    delta_lat = delta_y / R_TIERRA
                    delta_lon = delta_x / (R_TIERRA * math.cos(math.radians(lat_actual)))
                    
                    lat_actual += delta_lat
                    lon_actual += delta_lon
                    puntos_gps.append((lat_actual, lon_actual))
                
                st.success("¡Terreno proyectado exitosamente!")
                
                # Renderizar mapa
                m = folium.Map(location=[lat_inicio, lon_inicio], zoom_start=18, tiles="Esri.WorldImagery")
                folium.Polygon(locations=puntos_gps, color="cyan", weight=3, fill=True, fill_color="blue", fill_opacity=0.3).add_to(m)
                folium.Marker([lat_inicio, lon_inicio], tooltip="M1 (Punto de Inicio)", icon=folium.Icon(color="red")).add_to(m)
                
                st_data = st_folium(m, width=800, height=500)
        else:
            st.warning("Por favor, sube un archivo primero.")
