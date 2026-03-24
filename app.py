import streamlit as st
import google.generativeai as genai
import json
import math
import matplotlib.pyplot as plt
import ezdxf
import os
import tempfile
import re

# Intentamos importar la librería de mapas (Si falla, la app no se cae)
try:
    from pyproj import Transformer
    PYPROJ_INSTALLED = True
except ImportError:
    PYPROJ_INSTALLED = False

# --- 1. CONFIGURACIÓN Y MEMORIA ---
st.set_page_config(page_title="GraphiTop", layout="wide")
st.title("🏗️ GraphiTop: Suite de Análisis Topográfico")

if "datos_p1" not in st.session_state: st.session_state.datos_p1 = None

try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except KeyError:
    st.error("Falta configurar la llave de la API en secrets.toml")
    st.stop()

# --- FUNCIONES MATEMÁTICAS ---
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
    """Traductor de emergencia si falla la IA."""
    try:
        r = str(rumbo_str).upper()
        r = r.replace('NORTE', 'N').replace('SUR', 'S').replace('ESTE', 'E').replace('ORIENTE', 'E').replace('OESTE', 'W').replace('PONIENTE', 'W')
        ns = 'N' if 'N' in r else ('S' if 'S' in r else None)
        ew = 'E' if 'E' in r else ('W' if 'W' in r else None)
        nums = re.findall(r"[\d.]+", r.replace(',', '.'))
        grados = float(nums[0]) if len(nums) > 0 else 0.0
        minutos = float(nums[1]) if len(nums) > 1 else 0.0
        segundos = float(nums[2]) if len(nums) > 2 else 0.0
        grados_dec = grados + (minutos / 60.0) + (segundos / 3600.0)
        
        if not ns and not ew: return grados_dec
        if ns == 'N' and ew == 'E': return grados_dec
        if ns == 'N' and ew == 'W': return 360.0 - grados_dec
        if ns == 'S' and ew == 'E': return 180.0 - grados_dec
        if ns == 'S' and ew == 'W': return 180.0 + grados_dec
    except Exception: return 0.0
    return 0.0

def extraer_json_seguro(texto_ia):
    try:
        match = re.search(r'\[.*\]', texto_ia, re.DOTALL)
        if match: return json.loads(match.group(0))
        return []
    except Exception: return []

# --- AGENTES DE IA ---
instrucciones_topografia = """
Eres un Perito Topógrafo en El Salvador. Extrae los linderos del documento.
REGLA DE ORO: Debes calcular el AZIMUT en grados decimales para cada tramo y colocarlo en el campo "azimut".
Asegúrate de que 'distancia' y 'azimut' sean NÚMEROS.
Formato JSON estricto: [{"tramo": "L1", "distancia": 15.5, "rumbo": "N 20 15 00 W", "azimut": 339.75, "es_curva": false, "radio": 0}]
"""

modelo_topografo = genai.GenerativeModel('gemini-2.5-pro', system_instruction=instrucciones_topografia)
modelo_auditor = genai.GenerativeModel('gemini-2.5-pro', system_instruction="Eres un Arquitecto Auditor Senior. Compara visualmente los dos planos y detalla discrepancias.")

# --- INTERFAZ DE PESTAÑAS ---
tab1, tab2, tab3, tab4 = st.tabs([
    "📄 1. Generador DXF", 
    "⚖️ 2. Comparativo Visual", 
    "📐 3. Comparativo CAD", 
    "🔄 4. Convertidor Topográfico"
])

# --- PESTAÑA 1: GENERADOR DXF ---
with tab1:
    st.header("Generar Poligonal desde Documento Legal")
    arch_gen = st.file_uploader("Sube la escritura o plano", type=["pdf", "jpg", "png"], key="gen_file")
    
    if st.button("🚀 Extraer Linderos y Dibujar", key="btn_gen"):
        if arch_gen:
            with st.spinner("Leyendo documento y calculando azimuts (Esto evita que se dibuje recto)..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{arch_gen.name.split('.')[-1]}") as tf:
                    tf.write(arch_gen.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)
                
                texto_limpio = respuesta.text.replace('```json', '').replace('```', '').strip()
                try:
                    st.session_state.datos_p1 = json.loads(texto_limpio)
                except Exception:
                    st.session_state.datos_p1 = extraer_json_seguro(respuesta.text)
                
                if not st.session_state.datos_p1:
                    st.error("Error al leer la escritura. Intenta de nuevo.")
        else:
            st.warning("Sube un archivo primero.")

    if st.session_state.datos_p1:
        datos = st.session_state.datos_p1
        st.markdown("### 📋 Cuadro de Datos Extraídos")
        st.dataframe(datos, use_container_width=True)

        x, y = 0.0, 0.0
        cx, cy = [x], [y]
        
        for t in datos:
            t_lower = {k.lower(): v for k, v in t.items()}
            dist_cruda = str(t_lower.get("distancia", "0")).replace(',', '.').replace('m', '')
            try: dist = float(dist_cruda)
            except ValueError: dist = 0.0
            
            # Usamos el Azimut de la IA primero para obligar al polígono a formarse
            az_ia = t_lower.get("azimut", 0)
            if az_ia and float(az_ia) > 0:
                azimut_calculado = float(az_ia)
            else:
                rumbo_texto = str(t_lower.get('rumbo', ''))
                azimut_calculado = rumbo_a_azimut(rumbo_texto)
                
            az_rad = math.radians(azimut_calculado)
            x += dist * math.sin(az_rad)
            y += dist * math.cos(az_rad)
            cx.append(x)
            cy.append(y)
        
        if len(cx) >= 2:
            st.markdown("### 📐 Poligonal Dibujada")
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
                ax.text(px, py, texto_mojon, fontsize=9, color='darkgreen', fontweight='bold')

            ax.fill(cx, cy, color='blue', alpha=0.05)
            ax.axis('equal')
            ax.grid(True, linestyle=':', alpha=0.6)
            st.pyplot(fig)

            # Generador DXF
            doc = ezdxf.new('R2010')
            msp = doc.modelspace()
            
            for i in range(len(cx) - 1):
                px, py = cx[i], cy[i]
                nx, ny = cx[i+1], cy[i+1]
                es_curva = i < len(datos) and datos[i].get("es_curva", False)
                msp.add_line((px, py), (nx, ny), dxfattribs={'color': 1 if es_curva else 5})
                msp.add_circle((px, py), radius=0.5, dxfattribs={'color': 2})
                msp.add_text(f"M{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((px + 1, py + 1))

            max_x, max_y = max(cx), max(cy)
            cuadro_x, cuadro_y = max_x + 15, max_y
            
            msp.add_text("CUADRO DE CONSTRUCCION", dxfattribs={'height': 2.5, 'color': 3}).set_placement((cuadro_x, cuadro_y))
            cuadro_y -= 4 
            
            msp.add_text("EST", dxfattribs={'height': 1.5, 'color': 2}).set_placement((cuadro_x, cuadro_y))
            msp.add_text("PV", dxfattribs={'height': 1.5, 'color': 2}).set_placement((cuadro_x + 8, cuadro_y))
            msp.add_text("RUMBO", dxfattribs={'height': 1.5, 'color': 2}).set_placement((cuadro_x + 18, cuadro_y))
            msp.add_text("DISTANCIA", dxfattribs={'height': 1.5, 'color': 2}).set_placement((cuadro_x + 45, cuadro_y))
            msp.add_text("COORD X", dxfattribs={'height': 1.5, 'color': 2}).set_placement((cuadro_x + 65, cuadro_y))
            msp.add_text("COORD Y", dxfattribs={'height': 1.5, 'color': 2}).set_placement((cuadro_x + 85, cuadro_y))
            cuadro_y -= 3
            
            for i, t in enumerate(datos):
                t_lower = {k.lower(): v for k, v in t.items()}
                est = f"M{i+1}"
                pv = f"M{i+2}" if i < len(datos) else "M1"
                rumbo_texto = str(t_lower.get('rumbo', 'FALTA'))
                dist_texto = f"{t_lower.get('distancia', '0')} m"
                coord_x_texto = f"{cx[i]:.3f}"
                coord_y_texto = f"{cy[i]:.3f}"
                
                msp.add_text(est, dxfattribs={'height': 1.2, 'color': 7}).set_placement((cuadro_x, cuadro_y))
                msp.add_text(pv, dxfattribs={'height': 1.2, 'color': 7}).set_placement((cuadro_x + 8, cuadro_y))
                msp.add_text(rumbo_texto, dxfattribs={'height': 1.2, 'color': 7}).set_placement((cuadro_x + 18, cuadro_y))
                msp.add_text(dist_texto, dxfattribs={'height': 1.2, 'color': 7}).set_placement((cuadro_x + 45, cuadro_y))
                msp.add_text(coord_x_texto, dxfattribs={'height': 1.2, 'color': 7}).set_placement((cuadro_x + 65, cuadro_y))
                msp.add_text(coord_y_texto, dxfattribs={'height': 1.2, 'color': 7}).set_placement((cuadro_x + 85, cuadro_y))
                cuadro_y -= 2.5 

            with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_dxf:
                doc.saveas(tmp_dxf.name)
                with open(tmp_dxf.name, "rb") as f:
                    dxf_data = f.read()
            
            st.download_button("📥 Descargar Archivo DXF", data=dxf_data, file_name="GraphiTop_Plano.dxf", mime="application/dxf")

# --- PESTAÑA 2: COMPARATIVO VISUAL ---
with tab2:
    st.header("Auditoría Visual de Planos")
    colA, colB = st.columns(2)
    with colA: arch_A = st.file_uploader("Plano A (Referencia)", type=["pdf", "jpg", "png"], key="vis_a")
    with colB: arch_B = st.file_uploader("Plano B (A Evaluar)", type=["pdf", "jpg", "png"], key="vis_b")
    
    if st.button("👁️ Comparar Visualmente", key="btn_vis"):
        if arch_A and arch_B:
            with st.spinner("Analizando ambos planos..."):
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
                    
                st.markdown("### 📋 Reporte de Auditoría Visual")
                st.write(res_visual.text)
        else:
            st.warning("Sube ambos planos.")

# --- PESTAÑA 3: COMPARATIVO CAD ---
with tab3:
    st.header("Superposición Matemática")
    col_izq, col_der = st.columns(2)
    with col_izq: arch_legal = st.file_uploader("1. Escritura (PDF)", type=["pdf", "jpg", "png"], key="cad_leg")
    with col_der: arch_dxf = st.file_uploader("2. Topográfico (DXF)", type=["dxf"], key="cad_dxf")
    
    if st.button("⚖️ Ejecutar Superposición", key="btn_cad"):
        if arch_legal and arch_dxf:
            with st.spinner("Extrayendo polígonos..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tf:
                    tf.write(arch_legal.getbuffer())
                    temp_path = tf.name
                
                upload = genai.upload_file(temp_path)
                respuesta = modelo_topografo.generate_content([upload])
                genai.delete_file(upload.name)
                os.remove(temp_path)
                
                texto_limpio = respuesta.text.replace('```json', '').replace('```', '').strip()
                try: datos = json.loads(texto_limpio)
                except: datos = extraer_json_seguro(respuesta.text)
                
                if datos:
                    x, y = 0.0, 0.0
                    cx, cy = [x], [y]
                    for t in datos:
                        dist = float(str(t.get("distancia", "0")).replace(',', '.').replace('m', ''))
                        az_ia = t.get("azimut", 0)
                        azimut_calculado = float(az_ia) if az_ia else rumbo_a_azimut(str(t.get('rumbo', '')))
                        az_rad = math.radians(azimut_calculado)
                        x += dist * math.sin(az_rad)
                        y += dist * math.cos(az_rad)
                        cx.append(x)
                        cy.append(y)
                    area_ia = calcular_area(cx, cy)

                    coord_x_prof_raw, coord_y_prof_raw = extraer_poligono_dxf(arch_dxf)
                    if coord_x_prof_raw and len(coord_x_prof_raw) > 2:
                        area_prof = calcular_area(coord_x_prof_raw, coord_y_prof_raw)
                        offset_x, offset_y = coord_x_prof_raw[0], coord_y_prof_raw[0]
                        coord_x_prof = [px - offset_x for px in coord_x_prof_raw]
                        coord_y_prof = [py - offset_y for py in coord_y_prof_raw]
                        
                        st.markdown("### 📊 Comparativo de Superficies")
                        met1, met2, met3 = st.columns(3)
                        met1.metric(label="Área Legal", value=f"{area_ia:,.2f} m²")
                        diferencia = area_prof - area_ia
                        met2.metric(label="Área Topógrafo", value=f"{area_prof:,.2f} m²", delta=f"{diferencia:,.2f} m²", delta_color="inverse")
                        
                        fig, ax = plt.subplots(figsize=(10, 10))
                        ax.plot(cx, cy, color='blue', linestyle='-', linewidth=2, label='Legal')
                        ax.plot(coord_x_prof, coord_y_prof, marker='x', color='red', linestyle='--', linewidth=2, label='DXF')
                        ax.legend()
                        ax.axis('equal')
                        ax.grid(True, linestyle='--', alpha=0.6)
                        st.pyplot(fig)
                    else: st.error("No se detectó polilínea cerrada en el DXF.")
                else: st.error("Fallo al leer la escritura.")
        else: st.warning("Sube ambos archivos.")

# --- PESTAÑA 4: CONVERTIDOR TOPOGRÁFICO ---
with tab4:
    st.header("🔄 Convertidor Topográfico")
    st.write("Herramientas oficiales para cálculos de OPAMSS y CNR El Salvador.")
    
    # 1. Herramientas Rápidas
    col_area, col_azi = st.columns(2)
    with col_area:
        st.subheader("📏 Conversión de Áreas")
        area_input = st.number_input("Valor a convertir:", value=1.0, min_value=0.0)
        tipo_area = st.selectbox("Conversión:", 
                                ["v² a m² (Varas a Metros)", 
                                 "m² a v² (Metros a Varas)",
                                 "Manzanas a v²",
                                 "Manzanas a m²"])
        
        res_area = 0.0
        if "v² a m²" in tipo_area: res_area = area_input * 0.698896
        elif "m² a v²" in tipo_area: res_area = area_input / 0.698896
        elif "Manzanas a v²" in tipo_area: res_area = area_input * 10000.0
        elif "Manzanas a m²" in tipo_area: res_area = area_input * 6988.96
        
        st.success(f"**Resultado:** {res_area:,.4f}")

    with col_azi:
        st.subheader("📍 Grados a Azimut Decimal")
        cuadrante = st.selectbox("Cuadrante (Rumbo):", ["Norte-Este (NE)", "Norte-Oeste (NW)", "Sur-Este (SE)", "Sur-Oeste (SW)"])
        cg, cm, cs = st.columns(3)
        with cg: grad = cg.number_input("Grados (°)", value=0, min_value=0, max_value=90)
        with cm: min_val = cm.number_input("Minutos (')", value=0, min_value=0, max_value=59)
        with cs: sec_val = cs.number_input("Segundos ('')", value=0.0, min_value=0.0, max_value=59.9)
        
        dec_val = grad + (min_val / 60.0) + (sec_val / 3600.0)
        azimut_final = 0.0
        if "NE" in cuadrante: azimut_final = dec_val
        elif "NW" in cuadrante: azimut_final = 360.0 - dec_val
        elif "SE" in cuadrante: azimut_final = 180.0 - dec_val
        elif "SW" in cuadrante: azimut_final = 180.0 + dec_val
        st.info(f"**Azimut Decimal:** {azimut_final:.4f}°")

    st.markdown("---")
    
    # 2. Convertidor Especializado WGS84 a Cónica
    st.subheader("🌐 WGS84 ⇄ Proyección Cónica (LCC El Salvador EPSG:5367)")
    
    if not PYPROJ_INSTALLED:
        st.error("⚠️ Falta la librería matemática de mapas. Ve a tu archivo `requirements.txt` en GitHub, agrega la palabra `pyproj` en una línea nueva, guarda y reinicia la app para activar esta función.")
    else:
        modo_conversion = st.radio("Dirección de la conversión:", 
                                   ["WGS84 ➔ Proyección Cónica", "Proyección Cónica ➔ WGS84"], 
                                   horizontal=True)
                                   
        if modo_conversion == "WGS84 ➔ Proyección Cónica":
            col_wgs, col_con = st.columns(2)
            with col_wgs:
                st.markdown("**1. Latitud (Norte)**")
                cg1, cm1, cs1 = st.columns(3)
                with cg1: lat_g = st.number_input("Grados (N)", value=13, min_value=0, max_value=90)
                with cm1: lat_m = st.number_input("Minutos (N)", value=0, min_value=0, max_value=59)
                with cs1: lat_s = st.number_input("Segundos (N)", value=0.0, format="%.5f")
                
                st.markdown("**2. Longitud (Oeste)**")
                cg2, cm2, cs2 = st.columns(3)
                with cg2: lon_g = st.number_input("Grados (W)", value=89, min_value=0, max_value=180)
                with cm2: lon_m = st.number_input("Minutos (W)", value=0, min_value=0, max_value=59)
                with cs2: lon_s = st.number_input("Segundos (W)", value=0.0, format="%.5f")
                
            with col_con:
                st.markdown("**Resultados Cónica**")
                if st.button("🔄 Calcular Coordenadas Planas (X, Y)"):
                    lat_dec = lat_g + (lat_m / 60.0) + (lat_s / 3600.0)
                    lon_dec = -(lon_g + (lon_m / 60.0) + (lon_s / 3600.0)) # W es negativo
                    
                    # Transformación matemática oficial El Salvador
                    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5367", always_xy=True)
                    x_con, y_con = transformer.transform(lon_dec, lat_dec)
                    
                    st.success(f"**E (X):** {x_con:,.4f} m\n\n**N (Y):** {y_con:,.4f} m")
        
        else:
            col_con, col_wgs = st.columns(2)
            with col_con:
                st.markdown("**1. Proyección Cónica**")
                x_in = st.number_input("Coordenada E (X)", value=500000.0, format="%.4f")
                y_in = st.number_input("Coordenada N (Y)", value=295000.0, format="%.4f")
            
            with col_wgs:
                st.markdown("**Resultados WGS84**")
                if st.button("🔄 Calcular Latitud y Longitud"):
                    transformer = Transformer.from_crs("EPSG:5367", "EPSG:4326", always_xy=True)
                    lon_dec, lat_dec = transformer.transform(x_in, y_in)
                    
                    # Convertir Lat a DMS
                    lat_g_out = int(abs(lat_dec))
                    lat_m_out = int((abs(lat_dec) - lat_g_out) * 60)
                    lat_s_out = ((abs(lat_dec) - lat_g_out) - (lat_m_out/60.0)) * 3600
                    
                    # Convertir Lon a DMS
                    lon_dec_abs = abs(lon_dec)
                    lon_g_out = int(lon_dec_abs)
                    lon_m_out = int((lon_dec_abs - lon_g_out) * 60)
                    lon_s_out = ((lon_dec_abs - lon_g_out) - (lon_m_out/60.0)) * 3600
                    
                    st.success(f"**Latitud (N):** {lat_g_out}° {lat_m_out}' {lat_s_out:.4f}''\n\n**Longitud (W):** {lon_g_out}° {lon_m_out}' {lon_s_out:.4f}''")
