import streamlit as st
import google.generativeai as genai
import json
import math
import matplotlib.pyplot as plt
import ezdxf
import os
import tempfile

# --- FUNCIONES MATEMÁTICAS ---
def calcular_area(x, y):
    """Calcula el área de un polígono usando la fórmula de Gauss (Shoelace)."""
    area = 0.0
    n = len(x)
    for i in range(n):
        j = (i + 1) % n
        area += x[i] * y[j] - x[j] * y[i]
    return abs(area) / 2.0

def extraer_poligono_dxf(file_stream):
    """Extrae las coordenadas X, Y de la primera polilínea encontrada en un archivo DXF."""
    try:
        doc = ezdxf.read(file_stream)
        msp = doc.modelspace()
        for entity in msp.query('LWPOLYLINE POLYLINE'):
            puntos = list(entity.vertices()) if entity.dxftype() == 'POLYLINE' else entity.get_points('xy')
            if puntos:
                x = [p[0] for p in puntos]
                y = [p[1] for p in puntos]
                return x, y
    except Exception as e:
        return None, None
    return None, None

# --- 1. CONFIGURACIÓN DE LA APP ---
st.set_page_config(page_title="Inspec.AI - Comparativo", layout="wide")
st.title("🏗️ Inspec.AI: Generador y Comparador de Poligonales")
st.write("Genera poligonales limpias con identificación de mojones y compáralas con los planos CAD de tus contratistas.")

# --- 2. CONEXIÓN API ---
try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except KeyError:
    st.error("Falta configurar la llave de la API.")
    st.stop()

instrucciones_agente = """
Eres Inspec.AI, un experto revisor de proyectos arquitectónicos. 
Tu tarea es analizar documentos o descripciones técnicas y extraer CADA tramo de los linderos, su distancia en metros y el rumbo.
Debes calcular el azimut en grados decimales.
Formatea el rumbo a GMS (Ejemplo: "N 28° 39' 11\" W").
Responde ÚNICAMENTE con un arreglo en formato JSON válido, sin texto adicional.
"""
modelo_inspec = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_agente)

# --- 3. INTERFAZ DE CARGA ---
col1, col2 = st.columns(2)
with col1:
    st.subheader("1. Datos Legales (Inspec.AI)")
    archivo_pdf = st.file_uploader("📂 Sube la escritura (PDF)", type=["pdf"], key="pdf_legal")
    texto_escritura = st.text_area("📄 O pega el texto manualmente:", height=100)

with col2:
    st.subheader("2. Comparativo (Opcional)")
    archivo_dxf_prof = st.file_uploader("📂 Sube el plano del topógrafo (.dxf) para cotejar", type=["dxf"], key="dxf_prof")
    st.info("Pídele al dibujante que guarde su DWG de AutoCAD usando 'Guardar como -> DXF' antes de subirlo.")

if st.button("🚀 Procesar y Comparar Proyecto", use_container_width=True):
    if archivo_pdf is None and not texto_escritura.strip():
        st.warning("Por favor, sube la escritura o ingresa el texto primero en la columna izquierda.")
    else:
        with st.spinner('Procesando documentos legales y analizando geometría...'):
            try:
                # --- A. PROCESAMIENTO IA ---
                contenido_a_enviar = []
                if texto_escritura.strip():
                    contenido_a_enviar.append(texto_escritura)
                
                pdf_subido, temp_pdf_path = None, None
                if archivo_pdf is not None:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                        temp_file.write(archivo_pdf.getbuffer())
                        temp_pdf_path = temp_file.name
                    pdf_subido = genai.upload_file(temp_pdf_path, mime_type="application/pdf")
                    contenido_a_enviar.append(pdf_subido)

                respuesta = modelo_inspec.generate_content(contenido_a_enviar)
                
                if pdf_subido:
                    genai.delete_file(pdf_subido.name)
                    os.remove(temp_pdf_path)

                texto_json = respuesta.text.strip().strip('```json').strip('```')
                datos_terreno = json.loads(texto_json)
                
                # --- B. MOTOR MATEMÁTICO IA ---
                x, y = 0.0, 0.0
                coord_x_ia, coord_y_ia = [x], [y]

                for tramo in datos_terreno:
                    if tramo.get("azimut") is not None:
                        azimut_rad = math.radians(tramo["azimut"])
                        x += tramo["distancia"] * math.sin(azimut_rad)
                        y += tramo["distancia"] * math.cos(azimut_rad)
                        coord_x_ia.append(x)
                        coord_y_ia.append(y)

                # Cerrar polígono IA para cálculo de área
                coord_x_ia_cerrado = coord_x_ia + [coord_x_ia[0]]
                coord_y_ia_cerrado = coord_y_ia + [coord_y_ia[0]]
                area_ia = calcular_area(coord_x_ia_cerrado, coord_y_ia_cerrado)

                # --- C. EXTRACCIÓN DXF PROFESIONAL (COMPARATIVO) ---
                coord_x_prof, coord_y_prof = None, None
                area_prof = 0.0
                if archivo_dxf_prof is not None:
                    coord_x_prof_raw, coord_y_prof_raw = extraer_poligono_dxf(archivo_dxf_prof)
                    if coord_x_prof_raw and len(coord_x_prof_raw) > 2:
                        area_prof = calcular_area(coord_x_prof_raw, coord_y_prof_raw)
                        offset_x = coord_x_prof_raw[0]
                        offset_y = coord_y_prof_raw[0]
                        coord_x_prof = [px - offset_x for px in coord_x_prof_raw]
                        coord_y_prof = [py - offset_y for py in coord_y_prof_raw]

                # --- D. VISUALIZACIÓN Y RESULTADOS ---
                st.success("¡Análisis completado exitosamente!")
                
                st.markdown("### 📊 Comparativo de Superficies")
                met1, met2, met3 = st.columns(3)
                met1.metric(label="Área Legal (Según Escritura/IA)", value=f"{area_ia:,.2f} m²")
                
                if coord_x_prof:
                    diferencia = area_prof - area_ia
                    met2.metric(label="Área Dibujada (Topógrafo)", value=f"{area_prof:,.2f} m²", delta=f"{diferencia:,.2f} m²", delta_color="inverse")
                    if abs(diferencia) > 1.0:
                        met3.error("⚠️ Discrepancia detectada. Revisa los vértices.")
                    else:
                        met3.success("✅ Las áreas coinciden dentro del margen de tolerancia.")
                else:
                    met2.metric(label="Área Dibujada (Topógrafo)", value="No se subió archivo")

                st.markdown("### 🗺️ Superposición de Planos")
                fig, ax = plt.subplots(figsize=(10, 10))
                
                # Dibujar IA
                ax.plot(coord_x_ia, coord_y_ia, color='blue', linestyle='-', linewidth=2, label='Legal (IA)')
                ax.fill(coord_x_ia, coord_y_ia, color='blue', alpha=0.1)
                
                # Marcar e identificar Mojones en el gráfico web
                for i in range(len(coord_x_ia) - 1): # -1 para no duplicar la etiqueta en el punto de cierre
                    px, py = coord_x_ia[i], coord_y_ia[i]
                    ax.plot(px, py, marker='o', color='darkgreen', markersize=6)
                    ax.text(px, py, f"  M{i+1}", fontsize=10, color='darkgreen', fontweight='bold', va='bottom')

                # Dibujar Profesional si existe
                if coord_x_prof:
                    ax.plot(coord_x_prof, coord_y_prof, marker='x', color='red', linestyle='--', linewidth=2, label='Topógrafo (DXF)')
                    ax.fill(coord_x_prof, coord_y_prof, color='red', alpha=0.1)

                ax.grid(True, linestyle='--', alpha=0.6)
                ax.axis('equal')
                ax.legend(loc="upper right")
                st.pyplot(fig)

                # --- E. GENERAR DXF PARA DESCARGA (SOLO IA) ---
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                
                # Dibujar líneas del polígono
                msp.add_lwpolyline(list(zip(coord_x_ia, coord_y_ia)), dxfattribs={'color': 5}) # Azul
                
                # Insertar los Mojones en el DXF
                for i in range(len(coord_x_ia) - 1):
                    px, py = coord_x_ia[i], coord_y_ia[i]
                    # Círculo para representar el mojón
                    msp.add_circle((px, py), radius=0.5, dxfattribs={'color': 2}) # Amarillo
                    # Etiqueta de texto (M1, M2...)
                    msp.add_text(f"M{i+1}", dxfattribs={'height': 1.5, 'color': 3}).set_placement((px + 1, py + 1))

                # Cuadro de Construcción
                max_x, max_y = max(coord_x_ia), max(coord_y_ia)
                cuadro_x, cuadro_y = max_x + 15, max_y
                
                msp.add_text("CUADRO DE CONSTRUCCION", dxfattribs={'height': 2, 'color': 3}).set_placement((cuadro_x, cuadro_y))
                cuadro_y -= 4 
                msp.add_text("TRAMO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x, cuadro_y))
                msp.add_text("RUMBO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 15, cuadro_y))
                msp.add_text("DISTANCIA", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 45, cuadro_y))
                cuadro_y -= 2.5
                
                for i, tramo in enumerate(datos_terreno):
                    # Calcular el nombre del tramo basado en los mojones
                    mojon_inicio = i + 1
                    mojon_fin = i + 2 if i < len(datos_terreno) - 1 else 1
                    texto_tramo = f"M{mojon_inicio} a M{mojon_fin}"
                    
                    msp.add_text(texto_tramo, dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x, cuadro_y))
                    msp.add_text(str(tramo.get('rumbo_formateado', 'FALTA')), dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 15, cuadro_y))
                    msp.add_text(f"{tramo.get('distancia', 'FALTA')} m", dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 45, cuadro_y))
                    cuadro_y -= 2 

                nombre_archivo = "Poligonal_Legal_InspecAI.dxf"
                doc.saveas(nombre_archivo)
                with open(nombre_archivo, "rb") as file:
                    st.download_button(label="📥 Descargar Archivo DXF (Plano Legal IA)", data=file, file_name=nombre_archivo, mime="application/dxf")

            except Exception as e:
                st.error(f"Hubo un error al procesar el documento. Detalle: {e}")
