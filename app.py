import streamlit as st
import google.generativeai as genai
import json
import math
import matplotlib.pyplot as plt
import ezdxf
import PyPDF2

# 1. Configuración de la App
st.set_page_config(page_title="Inspec.AI - Poligonales", layout="wide")
st.title("🏗️ Inspec.AI: Generador Automático de Poligonales")
st.write("Sube tu documento en PDF o pega la descripción técnica del terreno para generar el archivo CAD.")

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
Tu tarea es leer descripciones técnicas y extraer cada tramo, su distancia en metros, el texto exacto del rumbo y calcular su equivalente en azimut en grados decimales.
Responde ÚNICAMENTE con un arreglo en formato JSON válido, sin texto adicional.
Estructura esperada:
[
  {"tramo": "Norte 1", "distancia": 18.31, "rumbo": "Sur 89° 10' 15\" Este", "azimut": 90.829}
]
"""
modelo_inspec = genai.GenerativeModel('gemini-2.5-flash', system_instruction=instrucciones_agente)

# 4. Interfaz de Usuario: Carga de PDF y Texto
texto_preliminar = ""

# Widget para subir PDF
archivo_pdf = st.file_uploader("📂 Sube la escritura en formato PDF (Opcional)", type=["pdf"])

if archivo_pdf is not None:
    try:
        lector_pdf = PyPDF2.PdfReader(archivo_pdf)
        for pagina in lector_pdf.pages:
            texto_extraido = pagina.extract_text()
            if texto_extraido:
                texto_preliminar += texto_extraido + "\n"
        st.success("✅ PDF leído correctamente. Revisa el texto extraído abajo.")
    except Exception as e:
        st.error(f"Hubo un error al leer el PDF: {e}")

# Cuadro de texto (se llena automáticamente si se sube un PDF)
texto_escritura = st.text_area("📄 Texto de la Escritura (Edita o pega texto manualmente):", value=texto_preliminar, height=250)

if st.button("🚀 Procesar y Generar DXF"):
    if not texto_escritura.strip():
        st.warning("Por favor, sube un PDF o ingresa el texto del documento primero.")
    else:
        with st.spinner('Analizando texto y calculando geometría...'):
            try:
                # Análisis de la IA
                respuesta = modelo_inspec.generate_content(texto_escritura)
                texto_json = respuesta.text.strip().strip('```json').strip('```')
                datos_terreno = json.loads(texto_json)
                
                # Motor Matemático
                x, y = 0.0, 0.0
                coordenadas_x, coordenadas_y = [x], [y]

                for tramo in datos_terreno:
                    if tramo.get("azimut") is not None:
                        azimut_rad = math.radians(tramo["azimut"])
                        x += tramo["distancia"] * math.sin(azimut_rad)
                        y += tramo["distancia"] * math.cos(azimut_rad)
                        coordenadas_x.append(x)
                        coordenadas_y.append(y)

                # Exportación a DXF con Cuadro
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
                
                # Mostrar éxito y botón de descarga
                st.success("¡Análisis completado exitosamente!")
                
                with open(nombre_archivo, "rb") as file:
                    st.download_button(
                        label="📥 Descargar Archivo DXF para AutoCAD",
                        data=file,
                        file_name=nombre_archivo,
                        mime="application/dxf"
                    )
                
                # Visualización en pantalla
                st.subheader("Vista Previa")
                fig, ax = plt.subplots(figsize=(6, 6))
                ax.plot(coordenadas_x, coordenadas_y, marker='o', color='b', linestyle='-')
                ax.fill(coordenadas_x, coordenadas_y, color='cyan', alpha=0.2)
                ax.grid(True)
                ax.axis('equal')
                st.pyplot(fig)

            except Exception as e:
                st.error(f"Hubo un error al interpretar el texto. Revisa que el formato sea correcto. Detalle: {e}")
