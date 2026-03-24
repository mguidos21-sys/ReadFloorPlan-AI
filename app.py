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
    """Traductor indestructible: Encuentra los números sin importar los símbolos."""
    try:
        r = str(rumbo_str).upper()
        # Identificar cuadrante
        ns = 'N' if 'N' in r else ('S' if 'S' in r else None)
        ew = 'E' if 'E' in r else ('W' if 'W' in r else None)
        if not ns or not ew: return 0.0

        # Extraer solo los números (grados, minutos, segundos)
        nums = re.findall(r"[\d.]+", r)
        grados = float(nums[0]) if len(nums) > 0 else 0.0
        minutos = float(nums[1]) if len(nums) > 1 else 0.0
        segundos = float(nums[2]) if len(nums) > 2 else 0.0

        grados_dec = grados + (minutos / 60.0) + (segundos / 3600.0)

        if ns == 'N' and ew == 'E': return grados_dec
        if ns == 'S' and ew == 'E': return 180.0 - grados_dec
        if ns == 'S' and ew == 'W': return 180.0 + grados_dec
        if ns == 'N' and ew == 'W': return 360.0 - grados_dec
    except Exception:
        return 0.0
    return 0.0

# --- AGENTES DE IA ---
instrucciones_topografia = """
Eres un experto topógrafo. Tu ÚNICA tarea es extraer los linderos de la escritura o plano.
NO calcules nada. Solo copia el rumbo y la distancia EXACTAMENTE como aparecen.
REGLA CURVAS: Si el tramo es curvo, extrae rumbo y distancia de su CUERDA, y anota el RADIO.
Responde ÚNICAMENTE con JSON:
[
  {"tramo": "Norte 1", "distancia": 18.31, "rumbo": "S 89 10 15 E", "es_curva": false, "radio": 0}
]
"""
modelo_topografo = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_topografia)

instrucciones_visual = "Eres un Arquitecto Auditor Senior. Compara visualmente los dos planos y reporta discrepancias estructurales o de linderos."
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
            with st.spinner("Procesando linderos..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_gen.name.split('.')[-1]}") as tf:
                    tf.write(arch_gen.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)
                
                try:
                    datos = json.loads(respuesta.text.replace('```json', '').replace('```', '').strip())
                except:
                    st.error("Error al leer el documento.")
                    st.stop()
                
                with st.expander("🔍 Ver datos extraídos"):
                    st.json(datos)

                x, y = 0.0, 0.0
                cx, cy = [x], [y]
                for t in datos:
                    azimut_calculado = rumbo_a_azimut(t["rumbo"])
                    az_rad = math.radians(azimut_calculado)
                    x += t["distancia"] * math.sin(az_rad)
                    y += t["distancia"] * math.cos(az_rad)
                    cx.append(x)
                    cy.append(y)
                
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

                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                for i in range(len(cx) - 1):
                    px, py = cx[i], cy[i]
                    nx, ny = cx[i+1], cy[i+1]
                    es_curva = i < len(datos) and datos[i].get("es_curva", False)
                    msp.add_line((px, py), (nx, ny), dxfattribs={'color': 1 if es_curva else 5})
                    msp.add_circle((px, py), radius=0.5, dxfattribs={'color': 2})
                    msp.add_text(f"M{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((px + 1, py + 1))

                nombre_archivo = "GraphiTop_Plano.dxf"
                doc.saveas(nombre_archivo)
                with open(nombre_archivo, "rb") as file:
                    st.download_button("📥 Descargar Archivo DXF", data=file, file_name=nombre_archivo, mime="application/dxf")
        else:
            st.warning("Sube un archivo.")

# --- PESTAÑA 2: COMPARATIVO VISUAL ---
with tab2:
    st.header("Auditoría Visual de Planos")
    colA, colB = st.columns(2)
    with colA: arch_A = st.file_uploader("Plano A (Referencia)", type=["pdf", "jpg", "png"])
    with colB: arch_B = st.file_uploader("Plano B (A Evaluar)", type=["pdf", "jpg", "png"])
    
    if st.button("👁️ Comparar Planos", key="btn_vis"):
        if arch_A and arch_B:
            with st.spinner("Analizando visualmente ambos planos..."):
                files_del = []
                docs_send = []
                for f in [arch_A, arch_B]:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{f.name.split('.')[-1]}") as tf:
                        tf.write(f.getbuffer())
                    upload = genai.upload_file(tf.name)
                    docs_send.append(upload)
                    files_del.append((upload, tf.name))
                
                res_visual = modelo_auditor.generate_content(docs_send)
                for upload, tmp_path in files_del:
                    genai.delete_file(upload.name)
                    os.remove(tmp_path)
                    
                st.markdown("### 📋 Reporte de Auditoría")
                st.write(res_visual.text)
        else:
            st.warning("Sube ambos planos para comparar.")

# --- PESTAÑA 3: COMPARATIVO CAD ---
with tab3:
    st.header("Superposición Matemática (IA vs Topógrafo)")
    col_izq, col_der = st.columns(2)
    with col_izq: arch_legal = st.file_uploader("1. Sube la escritura", type=["pdf", "jpg", "png"], key="legal_cad")
    with col_der: arch_dxf = st.file_uploader("2. Sube el DXF del topógrafo", type=["dxf"], key="dxf_prof")
    
    if st.button("⚖️ Ejecutar Comparativo", key="btn_comp_cad"):
        if arch_legal and arch_dxf:
            with st.spinner("Procesando y superponiendo geometrías..."):
                # 1. Extraer IA
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tf:
                    tf.write(arch_legal.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)
                
                datos = json.loads(respuesta.text.replace('```json', '').replace('```', '').strip())
                x, y = 0.0, 0.0
                cx, cy = [x], [y]
                for t in datos:
                    azimut_calculado = rumbo_a_azimut(t["rumbo"])
                    az_rad = math.radians(azimut_calculado)
                    x += t["distancia"] * math.sin(az_rad)
                    y += t["distancia"] * math.cos(az_rad)
                    cx.append(x)
                    cy.append(y)
                area_ia = calcular_area(cx, cy)

                # 2. Extraer Topógrafo
                coord_x_prof_raw, coord_y_prof_raw = extraer_poligono_dxf(arch_dxf)
                if coord_x_prof_raw and len(coord_x_prof_raw) > 2:
                    area_prof = calcular_area(coord_x_prof_raw, coord_y_prof_raw)
                    offset_x = coord_x_prof_raw[0]
                    offset_y = coord_y_prof_raw[0]
                    coord_x_prof = [px - offset_x for px in coord_x_prof_raw]
                    coord_y_prof = [py - offset_y for py in coord_y_prof_raw]
                    
                    # 3. Mostrar Resultados
                    st.markdown("### 📊 Comparativo de Superficies")
                    met1, met2, met3 = st.columns(3)
                    met1.metric(label="Área Legal (IA)", value=f"{area_ia:,.2f} m²")
                    diferencia = area_prof - area_ia
                    met2.metric(label="Área Dibujada (Topógrafo)", value=f"{area_prof:,.2f} m²", delta=f"{diferencia:,.2f} m²", delta_color="inverse")
                    if abs(diferencia) > 1.0: met3.error("⚠️ Discrepancia detectada.")
                    else: met3.success("✅ Las áreas coinciden.")

                    fig, ax = plt.subplots(figsize=(10, 10))
                    ax.plot(cx, cy, color='blue', linestyle='-', linewidth=2, label='Legal (IA)')
                    ax.plot(coord_x_prof, coord_y_prof, marker='x', color='red', linestyle='--', linewidth=2, label='Topógrafo (DXF)')
                    ax.legend()
                    ax.axis('equal')
                    ax.grid(True, linestyle='--', alpha=0.6)
                    st.pyplot(fig)
                else:
                    st.error("No se detectó una polilínea cerrada en el DXF.")
        else:
            st.warning("Sube ambos archivos.")

# --- PESTAÑA 4: MAPA INTERACTIVO ---
with tab4:
    st.header("Geolocalización del Proyecto")
    col_lat, col_lon = st.columns(2)
    with col_lat: lat_inicio = st.number_input("Latitud Inicial (Ej. 13.698)", value=13.698000, format="%.6f")
    with col_lon: lon_inicio = st.number_input("Longitud Inicial (Ej. -89.145)", value=-89.145000, format="%.6f")
    
    arch_mapa = st.file_uploader("Sube la escritura para trazar el mapa", type=["pdf", "jpg", "png"], key="map_file")
    
    if st.button("🌍 Proyectar en Mapa", key="btn_mapa"):
        if arch_mapa:
            with st.spinner("Calculando trigonometría esférica..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_mapa.name.split('.')[-1]}") as tf:
                    tf.write(arch_mapa.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)
                
                try:
                    datos = json.loads(respuesta.text.replace('```json', '').replace('```', '').strip())
                except:
                    st.error("Error al extraer los datos.")
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
                
                m = folium.Map(location=[lat_inicio, lon_inicio], zoom_start=18, tiles="Esri.WorldImagery")
                folium.Polygon(locations=puntos_gps, color="cyan", weight=3, fill=True, fill_color="blue", fill_opacity=0.3).add_to(m)
                folium.Marker([lat_inicio, lon_inicio], tooltip="M1 (Punto de Inicio)", icon=folium.Icon(color="red")).add_to(m)
                
                st.success("¡Terreno proyectado exitosamente!")
                st_data = st_folium(m, width=800, height=500)
        else:
            st.warning("Sube un archivo primero.")
