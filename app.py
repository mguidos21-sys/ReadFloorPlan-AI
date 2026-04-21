import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Lector de Planos IA", layout="centered")
st.title("🏗️ Lector de Planos Pro (v2026)")

# --- CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Falta la API Key en los Secrets.")
    st.stop()

# --- CONFIGURACIÓN DEL MODELO ---
# Usamos uno de los modelos que confirmamos que tienes disponibles
MODEL_NAME = 'models/gemini-2.5-flash' 
model = genai.GenerativeModel(model_name=MODEL_NAME)

# --- CARGA DE ARCHIVOS ---
uploaded_file = st.file_uploader("Sube un plano (Imagen o PDF)", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    if uploaded_file.type != "application/pdf":
        st.image(Image.open(uploaded_file), caption='Vista previa', use_container_width=True)
    else:
        st.info("📄 PDF detectado. Listo para análisis técnico.")

    if st.button("Analizar con Gemini 2.5"):
        try:
            with st.spinner("Analizando plano con IA de última generación..."):
                # 1. Crear archivo temporal
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name

                # 2. Subir a Google File API (vital para PDFs)
                google_file = genai.upload_file(path=tmp_path)
                
                # 3. Prompt enfocado en arquitectura
                prompt = (
                    "Eres un experto en revisión de planos y normativa urbana. "
                    "Analiza este archivo y extrae las medidas principales, nombres de ambientes, "
                    "y cualquier nota técnica relevante para trámites de construcción."
                )

                # 4. Generar contenido
                response = model.generate_content([prompt, google_file])

                # 5. Limpieza
                genai.delete_file(google_file.name)
                os.remove(tmp_path)

                st.success("¡Análisis completo!")
                st.markdown(response.text)

        except Exception as e:
            st.error(f"Hubo un problema: {e}")

st.divider()
st.caption(f"Utilizando tecnología: {MODEL_NAME}")
