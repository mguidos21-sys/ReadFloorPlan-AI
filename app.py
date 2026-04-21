import streamlit as st
import google.generativeai as genai
import google.api_core.exceptions
import ezdxf
from ezdxf.math import Vec2
import json
import re
import math
import os
import tempfile
import time

# --- 1. CONFIGURACIÓN Y VERSIÓN ---
st.set_page_config(page_title="Norm.AI - Topografía Pro", layout="centered")
st.title("📐 Extractor de Poligonales y Cuadros Técnicos")

# --- 2. CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    # Usamos el modelo que confirmamos que tienes disponible
    model = genai.GenerativeModel('models/gemini-2.5-flash')
else:
    st.error("⚠️ Configura tu 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

# --- 3. LÓGICA DE DIBUJO CAD ---
def generar_dxf_profesional(datos):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    puntos = [Vec2(0, 0)]
    
    # Dibujar la geometría
    for tramo in datos.get('tramos', []):
        dist = float(tramo.get('distancia', 0))
        # Simplificación de ángulo (en producción usarías rumbos reales)
        angulo = math.radians(float(tramo.get('angulo_deg', 0)))
        
        nuevo_punto = puntos[-1] + Vec2(math.cos(angulo)*dist, math.sin(angulo)*dist)
        
        if tramo.get('tipo') == 'curva':
            msp.add_lwpolyline([puntos[-1], nuevo_punto], dxfattribs={'bulge': 0.4})
        else:
            msp.add_line(puntos[-1], nuevo_punto)
        puntos.append(nuevo_punto)

    # Crear Cuadro de Rumbos (Texto en el CAD)
    y_offset = 0
    msp.add_text("CUADRO DE DATOS TÉCNICOS", dxfattribs={'height': 0.7}).set_placement((20, 5))
    for i, t in enumerate(datos.get('tramos', [])):
        txt = f"Lado {i+1}: {t.get('rumbo')} - {t.get('distancia')}m"
        msp.add_text(txt, dxfattribs={'height': 0.4}).set_placement((20, y_offset))
        y_offset -= 1

    path = "poligonal_norm_ai.dxf"
    doc.saveas(path)
    return path

# --- 4. INTERFAZ DE USUARIO ---
archivo = st.file_uploader("Sube tu plano o memoria descriptiva (PDF/JPG/PNG)", type=["pdf", "jpg", "png"])

if archivo:
    # EL BOTÓN TIENE UN 'KEY' ÚNICO PARA EVITAR EL ERROR DE DUPLICADO
    if st.button("🚀 Iniciar Procesamiento Técnico", key="btn_principal_analisis"):
        
        intentos_maximos = 3
        exito = False
        
        # 1. Preparar el archivo para Google
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{archivo.name.split('.')[-1]}") as tmp:
            tmp.write(archivo.getvalue())
            tmp_path = tmp.name
        
        try:
            google_file = genai.upload_file(path=tmp_path)
            
            # 2. Bucle de reintentos para evitar ResourceExhausted
            for i in range(intentos_maximos):
                try:
                    with st.spinner(f"Analizando con Gemini 2.5 (Intento {i+1})..."):
                        prompt = """
                        Analiza la poligonal. Extrae rumbos, distancias y curvas.
                        Devuelve un JSON con este formato:
                        {"tramos": [{"rumbo": "N 10E", "distancia": 20.5, "tipo": "linea", "angulo_deg": 45}]}
                        """
                        response = model.generate_content([prompt, google_file])
                        
                        # Intentar procesar el JSON
                        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if json_match:
                            datos_ia = json.loads(json_match.group())
                            
                            # 3. Generar el archivo CAD
                            ruta_dxf = generar_dxf_profesional(datos_ia)
                            
                            st.success("¡Geometría procesada exitosamente!")
                            
                            with open(ruta
