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

# --- 1. CONFIGURACIÓN Y MEMORIA ---
st.set_page_config(page_title="GraphiTop", layout="wide")
st.title("🏗️ GraphiTop: Suite de Análisis Topográfico")

if "datos_p1" not in st.session_state: st.session_state.datos_p1 = None
if "datos_p4" not in st.session_state: st.session_state.datos_p4 = None

try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except KeyError:
    st.error("Falta configurar la llave de la API en secrets.toml")
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
    except Exception: return None, None
    return None, None

def rumbo_a_azimut(rumbo_str):
    try:
        r = str(rumbo_str).upper()
        ns = 'N' if 'N' in r else ('S' if 'S' in r else None)
        ew = 'E' if 'E' in r else ('W' if 'W' in r else None)
        if not ns or not ew: return 0.0

        nums = re.findall(r"[\d.]+", r.replace(',', '.'))
        grados = float(nums[0]) if len(nums) > 0 else 0.0
        minutos = float(nums[1]) if len(nums) > 1 else 0.0
        segundos = float(nums[2]) if len(nums) > 2 else 0.0
        grados_dec = grados + (minutos / 60.0) + (segundos / 3600.0)

        if ns == 'N' and ew == 'E': return grados_dec
        if ns == 'S' and ew == 'E': return 180.0 - grados_dec
        if ns == 'S' and ew == 'W': return 180.0 + grados_dec
        if ns == 'N' and ew == 'W': return 360.0 - grados_dec
    except Exception: return 0.0
    return 0.0

def extraer_json_seguro(texto_ia):
    try:
        match = re.search(r'\[.*\]', texto_ia, re.DOTALL)
        if match: return json.loads(match.group(0))
        return []
    except Exception: return []

instrucciones_topografia = """
Extrae los linderos de la escritura. Si hay curva, extrae los datos de la CUERDA.
Asegúrate de que 'distancia' sea un NÚMERO (no texto).
El formato debe ser un arreglo estricto: [{"tramo": "L1", "distancia": 15.5, "rumbo": "N 20 15 00 W", "es_curva": false, "radio": 0}]
"""

modelo_topografo = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_topografia)
modelo_auditor = genai.GenerativeModel('gemini-2.5-pro', system_instruction="Eres un Arquitecto Auditor Senior. Compara visualmente los dos planos.")

tab1, tab2, tab3, tab4 = st.tabs(["📄 1. Generador DXF", "⚖️ 2. Comparativo Visual", "📐 3. Comparativo CAD", "🌍 4. Mapa Interactivo"])

# --- PESTAÑA 1: GENERADOR ---
with tab1:
    st.header("Generar Poligonal desde Documento Legal")
    arch_gen = st.file_uploader("Sube el documento legal", type=["pdf", "jpg", "png"], key="gen_file")
    
    if st.button("🚀 Extraer Linderos", key="btn_gen"):
        if arch_gen:
            with st.spinner("Procesando documento..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_gen.name.split('.')[-1]}") as tf:
                    tf.write(arch_gen.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)
                
                # Filtro de limpieza indestructible
                texto_limpio = respuesta.text.replace('```json', '').replace('```', '').strip()
                try:
                    st.session_state.datos_p1 = json.loads(texto_limpio)
                except Exception:
                    st.session_state.datos_p1 = extraer_json_seguro(respuesta.text)
                
                if not st.session_state.datos_p1:
                    st.error("Error al leer la escritura. La IA no generó datos válidos.")
        else:
            st.warning("Sube un archivo primero.")

    if st.session_state.datos_p1:
        datos = st.session_state.datos_p1
        
        st.markdown("### 📋 Cuadro de Construcción Extraído")
        st.dataframe(datos, use_container_width=True)

        x, y = 0.0, 0.0
        cx, cy = [x], [y]
        for t in datos:
            dist_cruda = str(t.get("distancia", "0")).replace(',', '.').replace('m', '').replace(' ', '')
            try: dist = float(dist_cruda)
            except ValueError: dist = 0.0
                
            azimut_calculado = rumbo_a_azimut(t.get("rumbo", ""))
            az_rad = math.radians(azimut_calculado)
            x += dist * math.sin(az_rad)
            y += dist * math.cos(az_rad)
            cx.append(x)
            cy.append(y)
        
        if len(cx) >= 2:
            st.markdown("### 📐 Poligonal Generada")
            fig, ax = plt.subplots(figsize=(8,8))
            for i in range(len(cx) - 1):
                px, py = cx[i], cy[i]
                nx, ny = cx[i+1], cy[i+1]
                es_curva = i < len(datos) and datos[i].get("es_curva", False)
                estilo = '--' if es_curva else '-'
                color_linea = 'red' if es_curva else 'blue'
                
                ax.plot([px, nx], [py, ny], color=color_linea, linestyle=estilo, linewidth=2)
                ax.plot(px, py, marker='o', color='darkgreen', markersize=6)
                texto_mojon = f" M{i+1}"
                if es_curva: texto_mojon += f"\n (R={datos[i].get('radio', 'N/A')})"
                ax.text(px, py, texto_mojon, fontsize=9, color='darkgreen', fontweight='bold')

            ax.fill(cx, cy, color='blue', alpha=0.05)
            ax.axis('equal')
            ax.grid(True, linestyle=':', alpha=0.6)
            st.pyplot(fig)

            # --- GENERADOR DXF CON CUADRO DE CONSTRUCCIÓN ---
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            
            # 1. Dibujar el polígono
            for i in range(len(cx) - 1):
                px, py = cx[i], cy[i]
                nx, ny = cx[i+1], cy[i+1]
                es_curva = i < len(datos) and datos[i].get("es_curva", False)
                msp.add_line((px, py), (nx, ny), dxfattribs={'color': 1 if es_curva else 5})
                msp.add_circle((px, py), radius=0.5, dxfattribs={'color': 2})
                msp.add_text(f"M{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((px + 1, py + 1))

            # 2. Dibujar la tabla de datos a la derecha del dibujo
            max_x, max_y = max(cx), max(cy)
            cuadro_x, cuadro_y = max_x + 15, max_y
            
            msp.add_text("CUADRO DE CONSTRUCCION", dxfattribs={'height': 2, 'color': 3}).set_placement((cuadro_x, cuadro_y))
            cuadro_y -= 4 
            msp.add_text("TRAMO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x, cuadro_y))
            msp.add_text("RUMBO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 15, cuadro_y))
            msp.add_text("DISTANCIA", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 45, cuadro_y))
            cuadro_y -= 2.5
            
            for i, t in enumerate(datos):
                mojon_inicio = i + 1
                mojon_fin = i + 2 if i < len(datos) else 1
                nota_curva = " (Cuerda)" if t.get("es_curva", False) else ""
                texto_tramo = f"M{mojon_inicio} a M{mojon_fin}{nota_curva}"
                
                msp.add_text(texto_tramo, dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x, cuadro_y))
                msp.add_text(str(t.get('rumbo', 'FALTA')), dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 15, cuadro_y))
                msp.add_text(f"{t.get('distancia', '0')} m", dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 45, cuadro_y))
                cuadro_y -= 2 

            # Preparar archivo para descarga
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_dxf:
                doc.saveas(tmp_dxf.name)
                with open(tmp_dxf.name, "rb") as f:
                    dxf_data = f.read()
            
            st.download_button("📥 Descargar Archivo DXF", data=dxf_data, file_name="GraphiTop_Plano.dxf", mime="application/dxf")

# --- PESTAÑA 2 y 3 ---
with tab2:
    st.header("Auditoría Visual de Planos")
    colA, colB = st.columns(2)
    with colA: arch_A = st.file_uploader("Plano A", type=["pdf", "jpg", "png"])
    with colB: arch_B = st.file_uploader("Plano B", type=["pdf", "jpg", "png"])
    if st.button("👁️ Comparar"):
        if arch_A and arch_B: st.success("Función activa")

with tab3:
    st.header("Superposición Matemática (IA vs Topógrafo)")
    col_izq, col_der = st.columns(2)
    with col_izq: arch_legal = st.file_uploader("1. Sube la escritura", type=["pdf", "jpg", "png"])
    with col_der: arch_dxf = st.file_uploader("2. Sube el DXF del topógrafo", type=["dxf"])
    if st.button("⚖️ Ejecutar Comparativo"):
        if arch_legal and arch_dxf: st.success("Función activa")

# --- PESTAÑA 4: MAPA INTERACTIVO ---
with tab4:
    st.header("Geolocalización del Proyecto")
    st.info("Pista: Ve a Google Maps, copia las coordenadas de la esquina inicial de tu terreno y pégalas aquí.")
    col_lat, col_lon = st.columns(2)
    with col_lat: lat_inicio = st.number_input("Latitud Inicial (M1)", value=13.698000, format="%.6f")
    with col_lon: lon_inicio = st.number_input("Longitud Inicial (M1)", value=-89.145000, format="%.6f")
    
    arch_mapa = st.file_uploader("Sube la escritura para trazar el mapa", type=["pdf", "jpg", "png"], key="map_file")
    
    if st.button("🌍 Leer Datos del Mapa", key="btn_mapa"):
        if arch_mapa:
            with st.spinner("Procesando linderos..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_mapa.name.split('.')[-1]}") as tf:
                    tf.write(arch_mapa.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)

                texto_limpio = respuesta.text.replace('```json', '').replace('```', '').strip()
                try:
                    st.session_state.datos_p4 = json.loads(texto_limpio)
                except Exception:
                    st.session_state.datos_p4 = extraer_json_seguro(respuesta.text)
                
                if not st.session_state.datos_p4:
                    st.error("Error extrayendo los datos.")
        else:
            st.warning("Sube un archivo primero.")

    if st.session_state.datos_p4:
        datos = st.session_state.datos_p4
        
        st.markdown("### 📋 Datos en uso para el mapa")
        st.dataframe(datos, use_container_width=True)

        puntos_gps = [(lat_inicio, lon_inicio)]
        lat_actual, lon_actual = lat_inicio, lon_inicio
        R_TIERRA = 111320.0 
        
        for t in datos:
            dist_cruda = str(t.get("distancia", "0")).replace(',', '.').replace('m', '')
            try: dist = float(dist_cruda)
            except: dist = 0.0
            
            azimut_calculado = rumbo_a_azimut(t.get("rumbo", ""))
            az_rad = math.radians(azimut_calculado)
            
            delta_y = dist * math.cos(az_rad)
            delta_x = dist * math.sin(az_rad)
            delta_lat = delta_y / R_TIERRA
            delta_lon = delta_x / (R_TIERRA * math.cos(math.radians(lat_actual)))
            
            lat_actual += delta_lat
            lon_actual += delta_lon
            puntos_gps.append((lat_actual, lon_actual))
        
        if len(puntos_gps) >= 2:
            m = folium.Map(location=[lat_inicio, lon_inicio], zoom_start=18, tiles="Esri.WorldImagery")
            folium.Polygon(locations=puntos_gps, color="cyan", weight=3, fill=True, fill_color="blue", fill_opacity=0.3).add_to(m)
            folium.Marker([lat_inicio, lon_inicio], tooltip="M1 (Punto de Inicio)", icon=folium.Icon(color="red")).add_to(m)
            m.fit_bounds(puntos_gps)
            
            st.success("¡Terreno proyectado exitosamente!")
            st_data = st_folium(m, width=800, height=500)
