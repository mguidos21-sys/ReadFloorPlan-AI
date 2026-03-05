import streamlit as st
import google.generativeai as genai
import json
import math
import matplotlib.pyplot as plt
import ezdxf
import os
import tempfile

# 1. Configuración de la App
st.set_page_config(page_title="Inspec.AI - Poligonales", layout="wide")
st.title("🏗️ Inspec.AI: Generador Automático de Poligonales")
st.write("Sube tu escritura en PDF (incluso documentos escaneados) o pega la descripción técnica para generar el archivo CAD.")

# 2. Conectar la API
try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except KeyError:
    st.error("Falta configurar la llave de la API en los secretos del servidor.")
    st.stop()

# 3. Instrucciones del Agente
instrucciones_agente = """
Eres Inspec.AI, un experto revisor de proyectos arquitectónicos. 
Tu tarea es analizar documentos o descripciones técnicas y extraer CADA tramo de los linderos, su distancia en metros, el texto exacto del rumbo y calcular su equivalente en azimut en grados decimales.
Si recibes un documento escaneado, lee cuidadosamente el texto de la imagen para extraer esta información topográfica.
Responde ÚNICAMENTE con un arreglo en formato JSON válido, sin texto adicional.
Estructura esperada:
[
  {"tramo": "Norte 1", "distancia": 18.31, "rumbo": "Sur 89° 10' 15\" Este", "azimut": 90.829}
]
"""
modelo_inspec = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_agente)

# 4. Interfaz de Usuario
archivo_pdf = st.file_uploader("📂 Sube la escritura en formato PDF", type=["pdf"])
texto_escritura = st.text_area("📄 O pega el texto manualmente aquí (si no tienes el PDF):", height=150)

if st.button("🚀 Procesar y Generar DXF"):
    if archivo_pdf is None and not texto_escritura.strip():
        st.warning("Por favor, sube un archivo PDF o ingresa el texto primero.")
    else:
        with st.spinner('La IA está leyendo el documento y calculando la geometría. Esto puede tomar unos segundos...'):
            try:
                # 5. Preparar lo que le enviaremos a la IA
                contenido_a_enviar = []
                
                # Si escribió texto manual, lo agregamos
                if texto_escritura.strip():
                    contenido_a_enviar.append(texto_escritura)
                
                # Si subió un PDF, lo procesamos con la API de Archivos de Gemini
                pdf_subido = None
                temp_pdf_path = None
                if archivo_pdf is not None:
                    # Guardamos el archivo temporalmente en el servidor
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                        temp_file.write(archivo_pdf.getbuffer())
                        temp_pdf_path = temp_file.name
                    
                    # Subimos el PDF a los servidores de Gemini para que lo pueda "ver"
                    pdf_subido = genai.upload_file(temp_pdf_path, mime_type="application/pdf")
                    contenido_a_enviar.append(pdf_subido)

                # 6. Enviamos el paquete a Inspec.AI
                respuesta = modelo_inspec.generate_content(contenido_a_enviar)
                
                # Limpieza de archivos temporales por seguridad
                if pdf_subido is not None:
                    genai.delete_file(pdf_subido.name)
                    os.remove(temp_pdf_path)

                # 7. Procesamiento Matemático
                texto_json = respuesta.text.strip().strip('```json').strip('```')
                datos_terreno = json.loads(texto_json)
                
                if not datos_terreno:
                    st.error("La IA no pudo encontrar rumbos ni distancias en este documento.")
                    st.stop()
                
                x, y = 0.0, 0.0
                coordenadas_x, coordenadas_y = [x], [y]

                for tramo in datos_terreno:
                    if tramo.get("azimut") is not None:
                        azimut_rad = math.radians(tramo["azimut"])
                        x += tramo["distancia"] * math.sin(azimut_rad)
                        y += tramo["distancia"] * math.cos(azimut_rad)
                        coordenadas_x.append(x)
                        coordenadas_y.append(y)

                # 8. Generación del DXF y el Cuadro
                doc = ezdxf.new('R2010')
                msp = doc.modelspace()
                msp.add_lwpolyline(list(zip(coordenadas_x, coordenadas_y)), dxfattribs={'color': 1})
                
                max_x, max_y = max(coordenadas_x), max(coordenadas_y)
                cuadro_x, cuadro_y = max_x + 15, max_y
                
                msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 2, 'color': 3}).set_placement((cuadro_x, cuadro_y))
                cuadro_y -= 4 
                
                msp.add_text("TRAMO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x, cuadro_y))
                msp.add_text("RUMBO", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 15, cuadro_y))
                msp.add_text("AZIMUT", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 65, cuadro_y))
                msp.add_text("DISTANCIA", dxfattribs={'height': 1.2, 'color': 2}).set_placement((cuadro_x + 85, cuadro_y))
                cuadro_y -= 2.5
                
                for tramo in datos_terreno:
                    msp.add_text(str(tramo.get('tramo', '')), dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x, cuadro_y))
                    msp.add_text(str(tramo.get('rumbo', 'FALTA')), dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 15, cuadro_y))
                    msp.add_text(f"{tramo.get('azimut', 'FALTA')}°", dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 65, cuadro_y))
                    msp.add_text(f"{tramo.get('distancia', 'FALTA')} m", dxfattribs={'height': 1, 'color': 7}).set_placement((cuadro_x + 85, cuadro_y))
                    cuadro_y -= 2 

                nombre_archivo = "Poligonal_InspecAI.dxf"
                doc.saveas(nombre_archivo)
                
                st.success("¡Análisis completado exitosamente!")
                
                with open(nombre_archivo, "rb") as file:
                    st.download_button(
                        label="📥 Descargar Archivo DXF para AutoCAD",
                        data=file,
                        file_name=nombre_archivo,
                        mime="application/dxf"
                    )
                
                st.subheader("Vista Previa")
                fig, ax = plt.subplots(figsize=(6, 6))
                ax.plot(coordenadas_x, coordenadas_y, marker='o', color='b', linestyle='-')
                ax.fill(coordenadas_x, coordenadas_y, color='cyan', alpha=0.2)
                ax.grid(True)
                ax.axis('equal')
                st.pyplot(fig)

            except Exception as e:
                st.error(f"Hubo un error al procesar el documento. Detalle: {e}")

