import streamlit as st
import google.generativeai as genai
import ezdxf
from ezdxf.math import Vec2
import json
import re
import math
import os
import tempfile

# --- LÓGICA DE CÁLCULO TOPOGRÁFICO ---
def rumbo_a_radianes(rumbo):
    # Ejemplo: "N 45 00 00 E"
    partes = re.findall(r"([NSEW])|(\d+\.?\d*)", rumbo)
    # Lógica simplificada para convertir rumbos a ángulos polares
    # (En un entorno real, aquí se procesan grados, minutos y segundos)
    return math.radians(45) # Placeholder para la lógica de conversión

def generar_poligonal_avanzada(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    # Dibujar Poligonal y procesar Curvas
    for i, tramo in enumerate(datos['tramos']):
        dist = float(tramo['distancia'])
        # Aquí se aplicaría la conversión de rumbo a ángulo real
        angulo = math.radians(float(tramo.get('angulo_deg', 0))) 
        
        nuevo_punto = puntos[-1] + Vec2(math.cos(angulo)*dist, math.sin(angulo)*dist)
        
        if tramo.get('tipo') == 'curva':
            # Agregar arco usando bulge (simplificado)
            msp.add_lwpolyline([puntos[-1], nuevo_punto], dxfattribs={'bulge': 0.5})
        else:
            msp.add_line(puntos[-1], nuevo_punto)
        
        puntos.append(nuevo_punto)

    # --- GENERAR CUADRO DE RUMBOS Y DISTANCIAS ---
    # Dibujamos una tabla simple con líneas y texto en el CAD
    x_tabla, y_tabla = 20, 0 # Posición a la par del dibujo
    msp.add_text("CUADRO DE RUMBOS Y DISTANCIAS", dxfattribs={'height': 0.5}).set_placement((x_tabla, y_tabla + 2))
    
    header = "EST | RUMBO | DISTANCIA | VÉRTICE"
    msp.add_text(header, dxfattribs={'height': 0.3}).set_placement((x_tabla, y_tabla + 1))
    
    for i, tramo in enumerate(datos['tramos']):
        linea = f"{i+1}-{i+2} | {tramo['rumbo']} | {tramo['distancia']}m"
        msp.add_text(linea, dxfattribs={'height(0.25)'}).set_placement((x_tabla, y_tabla - (i * 0.5)))

    path = "poligonal_tecnica.dxf"
    doc.saveas(path)
    return path

# --- INTERFAZ DE STREAMLIT ---
st.set_page_config(page_title="Norm.AI - Topografía Pro")
st.title("📐 Extractor de Poligonales y Cuadros Técnicos")

if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("Configura tu API Key")
    st.stop()

archivo = st.file_uploader("Sube plano o memoria descriptiva", type=["pdf", "jpg", "png"])

if archivo and st.button("Procesar Memoria Técnica"):
    with st.spinner("Interpretando datos topográficos..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(archivo.getvalue())
            google_file = genai.upload_file(path=tmp.name)

        # Prompt ultra-específico
        prompt = """
        Analiza el documento y extrae la poligonal.
        Busca rumbos, distancias y datos de curvas (radio, delta).
        Devuelve un JSON estrictamente así:
        {
          "tramos": [
            {"rumbo": "N 10°20' E", "distancia": 15.50, "tipo": "linea", "angulo_deg": 80},
            {"rumbo": "S 80°00' E", "distancia": 5.00, "tipo": "curva", "radio": 10.0, "angulo_deg": -10}
          ]
        }
        """
        
        res = model.generate_content([prompt, google_file])
        try:
            # Extraer y limpiar JSON
            json_data = json.loads(re.search(r'\{.*\}', res.text, re.DOTALL).group())
            archivo_dxf = generar_poligonal_avanzada(json_data)
            
            st.success("✅ Geometría y Cuadro de Rumbos generados.")
            
            with open(archivo_dxf, "rb") as f:
                st.download_button("📥 Descargar DXF para AutoCAD", f, file_name="poligonal_final.dxf")
                
            st.json(json_data) # Mostrar los datos extraídos para verificación
        except Exception as e:
            st.error(f"Error al procesar: {e}")
