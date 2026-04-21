import streamlit as st
import google.generativeai as genai
from PIL import Image
import os

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Lector de Planos IA", layout="centered")

st.title("🏗️ Lector de Planos e Información Técnica")
st.write("Sube tu plano en formato **Imagen (JPG/PNG)** o **PDF**.")

# --- CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Falta la API Key en los Secrets de Streamlit.")
    st.stop()

genai.configure(api_key=api_key)

# Usamos Flash por su mayor velocidad y límites de cuota más amplios
model = genai.GenerativeModel('gemini-1.5-flash')

# --- INTERFAZ DE CARGA ---
# Añadimos 'pdf' a los tipos permitidos
uploaded_file = st.file_uploader("Sube tu archivo (Imagen o PDF)", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    # 1. Determinar el tipo de archivo y preparar el contenido
    file_type = uploaded_file.type
    
    if file_type == "application/pdf":
        # Preparar el PDF para la IA
        documento_para_ia = {
            "mime_type": "application/pdf",
            "data": uploaded_file.getvalue()
        }
        st.info("📄 Archivo PDF cargado correctamente.")
    else:
        # Preparar la Imagen para la IA
        img = Image.open(uploaded_file)
        documento_para_ia = img
        st.image(img, caption='Imagen cargada', use_container_width=True)
    
    # --- BOTÓN DE ANÁLISIS ---
    if st.button("Analizar Documento"):
        try:
            with st.spinner("La IA está procesando el archivo..."):
                prompt = (
                    "Actúa como un experto en ingeniería y arquitectura. "
                    "Analiza este archivo (plano o documento técnico). "
                    "Extrae medidas, leyendas, nombres de ambientes y detalles técnicos. "
                    "Presenta la información de forma estructurada."
                )
                
                # Enviamos el contenido (sea PDF o Imagen)
                response = model.generate_content([prompt, documento_para_ia])
                
                st.success("¡Análisis completado!")
                st.markdown("### Detalles detectados:")
                st.write(response.text)

        except Exception as e:
            error_msg = str(e)
            if "ResourceExhausted" in error_msg or "429" in error_msg:
                st.error("🛑 Cuota agotada. Por favor, espera un minuto antes de reintentar.")
            else:
                st.error(f"Error al procesar: {e}")

# --- PIE DE PÁGINA ---
st.divider()
st.caption("Compatible con Planos en PDF, JPG y PNG")
