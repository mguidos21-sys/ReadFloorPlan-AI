import streamlit as st
import google.generativeai as genai
import json
import math
import matplotlib.pyplot as plt
import ezdxf
from ezdxf.enums import TextEntityAlignment
import os
import tempfile

# 1. Configuración de la App
st.set_page_config(page_title="Inspec.AI - Poligonales", layout="wide")
st.title("🏗️ Inspec.AI: Generador Automático de Poligonales")
st.write("Sube tu escritura en PDF o pega la descripción técnica para generar el archivo CAD con rumbos y distancias en las líneas.")

# 2. Conectar la API
try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except KeyError:
    st.error("Falta configurar la llave de la API en los secretos del servidor.")
    st.stop()

# 3. Instrucciones del Agente (Actualizado para GMS)
instrucciones_agente = """
Eres Inspec.AI, un experto revisor de proyectos arquitectónicos. 
Tu tarea es analizar documentos o descripciones técnicas y extraer CADA tramo de los linderos, su distancia en metros y el rumbo.
Debes calcular el azimut en grados decimales.
ADEMÁS, debes formatear el rumbo en su versión corta tradicional con grados, minutos y segundos (Ejemplo: "N 28° 39' 11\" W" o "S 89° 10' 15\" E").
Responde ÚNICAMENTE con un arreglo en formato JSON válido, sin texto adicional.
Estructura esperada:
[
  {"tramo": "Norte 1", "distancia": 18.31, "rumbo_formateado": "S 89° 10' 15\" E", "azimut": 90.829}
]
"""
modelo_inspec = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_agente)

# 4. Interfaz de Usuario
archivo_pdf = st.file_uploader("📂 Sube la escritura en formato PDF", type=["pdf"])
texto_escritura = st.text_area("📄 O pega el texto manualmente aquí:", height=150)

if st.button("🚀 Procesar y Generar DXF"):
    if archivo_pdf is None and not texto_escritura.strip():
        st.warning("Por favor, sube un archivo PDF o ingresa el texto primero.")
    else:
        with st.spinner('Inspec.AI está analizando el documento y calculando la topografía...'):
            try:
                # 5. Preparar contenido para la IA
                contenido_a_enviar = []
                if texto_escritura.strip():
                    contenido_a_enviar.append(texto_escritura)
                
                pdf_subido = None
                temp_pdf_path = None
                if archivo_pdf is not None:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                        temp_file.write(archivo_pdf.getbuffer())
                        temp_pdf_path = temp_file.name
                    pdf_subido = genai.upload_file(temp_pdf_path, mime_type="application/pdf")
                    contenido_a_enviar.append(pdf_subido)

                respuesta = modelo_inspec.generate_content(contenido_a_enviar)
                
                if pdf_subido is not None:
                    genai.delete_file(pdf_subido.name)
                    os.remove(temp_pdf_path)

                # 6. Procesamiento Matemático
                texto_json = respuesta.text.strip().strip('```json').strip('```')
                datos_terreno = json.loads(texto_json)
                
                if not datos_terreno:
                    st.error("La IA no pudo encontrar rumbos ni distancias.")
                    st.stop()
                
                x, y = 0.0, 0.0
                coordenadas_x, coordenadas_y = [x], [y]
                segmentos = [] # Guardaremos las líneas para ponerles texto

                for tramo in datos_terreno:
                    if tramo.get("azimut") is not None:
                        azimut_rad = math.radians(tramo["azimut"])
                        x_prev, y_prev = x, y # Guardamos el punto anterior
                        
                        x += tramo["distancia"] * math.sin(azimut_rad)
                        y += tramo["distancia"] * math.cos(azimut_rad)
                        
                        coordenadas_x.append(x)
                        coordenadas_y.append(y)
                        
                        # Guardamos la info del segmento para las etiquetas
                        segmentos.append({
                            'x1': x_prev, 'y1': y_prev,
                            'x2': x, 'y2': y,
                            'distancia': tramo.get('distancia', 0),
                            'rumbo': tramo.get('rumbo_formateado', 'Falta')
                        })

                # 7. Generación del DXF
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                msp.add_lwpolyline(list(zip(coordenadas_x, coordenadas_y)), dxfattribs={'color': 1})
                
                # --- DIBUJAR TEXTOS SOBRE LAS LÍNEAS EN EL DXF ---
                for seg in segmentos:
                    dx = seg['x2'] - seg['x1']
                    dy = seg['y2'] - seg['y1']
                    mid_x = seg['x1'] + dx / 2
                    mid_y = seg['y1'] + dy / 2
                    
                    # Calcular el ángulo de la línea
                    angle = math.degrees(math.atan2(dy, dx))
                    
                    # Evitar que el texto quede de cabeza
                    if angle > 90: angle -= 180
                    elif angle < -90: angle += 180
                        
                    # Insertar Distancia (Arriba de la línea)
                    msp.add_text(f"{seg['distancia']}m", dxfattribs={'height': 1.2, 'rotation': angle, 'color': 3}).set_placement((mid_x, mid_y), align=TextEntityAlignment.BOTTOM_CENTER)
                    # Insertar Rumbo (Abajo de la línea)
                    msp.add_text(f"{seg['rumbo']}", dxfattribs={'height': 1.0, 'rotation': angle, 'color': 2}).set_placement((mid_x, mid_y), align=TextEntityAlignment.TOP_CENTER)

                # --- CUADRO DE CONSTRUCCIÓN ---
                max_x, max_y = max(coordenadas_x), max(coordenadas_y)
                cuadro_x, cuadro_y = max_x + 15, max_y
                
                msp.add_text("CUADRO DE CONSTRUCCION", dxfattribs={'height': 2, 'color': 3}).set_placement((cuadro_x, cuadro_y))
                cuadro_y -= 4 
                msp.add_text("TRAMO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x, cuadro_y))
                msp.add_text("RUMBO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 15, cuadro_y))
                msp.add_text("DISTANCIA", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 45, cuadro_y))
                cuadro_y -= 2.5
                
                for tramo in datos_terreno:
                    msp.add_text(str(tramo.get('tramo', '')), dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x, cuadro_y))
                    msp.add_text(str(tramo.get('rumbo_formateado', 'FALTA')), dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 15, cuadro_y))
                    msp.add_text(f"{tramo.get('distancia', 'FALTA')} m", dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 45, cuadro_y))
                    cuadro_y -= 2 

                nombre_archivo = "Poligonal_InspecAI.dxf"
                doc.saveas(nombre_archivo)
                
                st.success("¡Planos generados exitosamente!")
                with open(nombre_archivo, "rb") as file:
                    st.download_button(label="📥 Descargar Archivo DXF para AutoCAD", data=file, file_name=nombre_archivo, mime="application/dxf")
                
                # 8. Visualización en Pantalla (También con textos rotados)
                st.subheader("Vista Previa")
                fig, ax = plt.subplots(figsize=(10, 10))
                ax.plot(coordenadas_x, coordenadas_y, marker='o', color='b', linestyle='-', linewidth=1.5)
                ax.fill(coordenadas_x, coordenadas_y, color='cyan', alpha=0.1)
                
                for seg in segmentos:
                    dx = seg['x2'] - seg['x1']
                    dy = seg['y2'] - seg['y1']
                    mid_x = seg['x1'] + dx / 2
                    mid_y = seg['y1'] + dy / 2
                    angle = math.degrees(math.atan2(dy, dx))
                    
                    if angle > 90: angle -= 180
                    elif angle < -90: angle += 180
                        
                    texto_etiqueta = f"{seg['distancia']}m\n{seg['rumbo']}"
                    # Dibujamos el texto rotado en el gráfico web
                    ax.text(mid_x, mid_y, texto_etiqueta, rotation=angle, ha='center', va='center', fontsize=7, color='darkred', bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1))

                ax.grid(True, linestyle='--', alpha=0.6)
                ax.axis('equal')
                st.pyplot(fig)

            except Exception as e:
                st.error(f"Hubo un error al procesar el documento. Detalle: {e}")

