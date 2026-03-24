import streamlit as st
import google.generativeai as genai
import json
import math
import matplotlib.pyplot as plt
import ezdxf
import os
import tempfile
import re

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
    """Traductor de emergencia por si la IA olvida calcular el azimut."""
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
            with st.spinner("Leyendo documento y calculando azimuts..."):
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
            
            # MAGIA AQUÍ: Usamos el Azimut directo de la IA para evitar la línea recta
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
            
            st.download_button("📥 Descargar Archivo DXF Completo", data=dxf_data, file_name="GraphiTop_Plano.dxf", mime="application/dxf")

# --- PESTAÑA 2: COMPARATIVO VISUAL (RESTAURADA) ---
with tab2:
    st.header("Auditoría Visual de Planos")
    st.write("Sube dos planos para que la IA busque diferencias estructurales o de sellos.")
    colA, colB = st.columns(2)
    with colA: arch_A = st.file_uploader("Plano A (Referencia)", type=["pdf", "jpg", "png"], key="vis_a")
    with colB: arch_B = st.file_uploader("Plano B (A Evaluar)", type=["pdf", "jpg", "png"], key="vis_b")
    
    if st.button("👁️ Comparar Visualmente", key="btn_vis"):
        if arch_A and arch_B:
            with st.spinner("Analizando ambos planos con IA Visual..."):
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
            st.warning("Sube ambos planos para comparar.")

# --- PESTAÑA 3: COMPARATIVO CAD (RESTAURADA) ---
with tab3:
    st.header("Superposición Matemática (Escritura vs DXF)")
    st.write("Verifica si el archivo de AutoCAD coincide con los linderos de la escritura.")
    col_izq, col_der = st.columns(2)
    with col_izq: arch_legal = st.file_uploader("1. Sube la escritura (PDF)", type=["pdf", "jpg", "png"], key="cad_leg")
    with col_der: arch_dxf = st.file_uploader("2. Sube el plano topográfico (DXF)", type=["dxf"], key="cad_dxf")
    
    if st.button("⚖️ Ejecutar Superposición", key="btn_cad"):
        if arch_legal and arch_dxf:
            with st.spinner("Extrayendo y superponiendo polígonos..."):
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
                        # Alinear el DXF al origen (0,0) para poder superponerlos
                        offset_x, offset_y = coord_x_prof_raw[0], coord_y_prof_raw[0]
                        coord_x_prof = [px - offset_x for px in coord_x_prof_raw]
                        coord_y_prof = [py - offset_y for py in coord_y_prof_raw]
                        
                        st.markdown("### 📊 Comparativo de Superficies")
                        met1, met2, met3 = st.columns(3)
                        met1.metric(label="Área Legal (Escritura)", value=f"{area_ia:,.2f} m²")
                        diferencia = area_prof - area_ia
                        met2.metric(label="Área Dibujada (AutoCAD)", value=f"{area_prof:,.2f} m²", delta=f"{diferencia:,.2f} m²", delta_color="inverse")
                        if abs(diferencia) > 1.0: met3.error("⚠️ Discrepancia detectada.")
                        else: met3.success("✅ Las áreas coinciden.")

                        fig, ax = plt.subplots(figsize=(10, 10))
                        ax.plot(cx, cy, color='blue', linestyle='-', linewidth=2, label='Legal (Escritura)')
                        ax.plot(coord_x_prof, coord_y_prof, marker='x', color='red', linestyle='--', linewidth=2, label='Topógrafo (AutoCAD)')
                        ax.legend()
                        ax.axis('equal')
                        ax.grid(True, linestyle='--', alpha=0.6)
                        st.pyplot(fig)
                    else:
                        st.error("No se detectó una polilínea cerrada en el DXF.")
                else:
                    st.error("Fallo al leer la escritura.")
        else:
            st.warning("Sube ambos archivos.")

# --- PESTAÑA 4: CONVERTIDOR TOPOGRÁFICO (NUEVA) ---
with tab4:
    st.header("🔄 Convertidor Topográfico (El Salvador)")
    st.write("Herramientas rápidas para cálculos de OPAMSS y CNR.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📏 Conversión de Áreas")
        area_input = st.number_input("Ingresa el valor del Área:", value=1.0, min_value=0.0)
        tipo_area = st.selectbox("De qué unidad a qué unidad:", 
                                ["Varas Cuadradas (v²) a Metros Cuadrados (m²)", 
                                 "Metros Cuadrados (m²) a Varas Cuadradas (v²)",
                                 "Manzanas a Varas Cuadradas (v²)",
                                 "Manzanas a Metros Cuadrados (m²)"])
        
        # Factor CNR El Salvador: 1 v² = 0.698896 m² / 1 Manzana = 10,000 v²
        res_area = 0.0
        if "v² a m²" in tipo_area: res_area = area_input * 0.698896
        elif "m² a v²" in tipo_area: res_area = area_input / 0.698896
        elif "Manzanas a v²" in tipo_area: res_area = area_input * 10000.0
        elif "Manzanas a m²" in tipo_area: res_area = area_input * 6988.96
        
        st.success(f"**Resultado:** {res_area:,.4f}")

    with col2:
        st.subheader("📍 Grados a Azimut Decimal")
        st.write("Convierte rumbos escritos a grados decimales para AutoCAD.")
        cuadrante = st.selectbox("Cuadrante:", ["Norte-Este (NE)", "Norte-Oeste (NW)", "Sur-Este (SE)", "Sur-Oeste (SW)"])
        col_g, col_m, col_s = st.columns(3)
        with col_g: grad = col_g.number_input("Grados (°)", value=0, min_value=0, max_value=90)
        with col_m: min_val = col_m.number_input("Minutos (')", value=0, min_value=0, max_value=59)
        with col_s: sec_val = col_s.number_input("Segundos ('')", value=0.0, min_value=0.0, max_value=59.9)
        
        dec_val = grad + (min_val / 60.0) + (sec_val / 3600.0)
        azimut_final = 0.0
        if "NE" in cuadrante: azimut_final = dec_val
        elif "NW" in cuadrante: azimut_final = 360.0 - dec_val
        elif "SE" in cuadrante: azimut_final = 180.0 - dec_val
        elif "SW" in cuadrante: azimut_final = 180.0 + dec_val
        
        st.info(f"**Azimut Decimal:** {azimut_final:.4f}°")
