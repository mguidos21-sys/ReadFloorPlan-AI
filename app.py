import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Lector de Planos IA", layout="centered")

st.title("🏗️ Lector de Planos Pro")
st.write("Análisis técnico de imágenes y PDFs.")

# --- CONFIGURACIÓN DE LA API ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Configura tu 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

genai.configure(api_key=api_key)

# --- CARGA DE ARCHIVOS ---
uploaded_file = st.file_uploader("Sube un plano (Imagen o PDF)", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    # Mostrar vista previa si es imagen
    if uploaded_file.type != "application/pdf":
        img = Image.open(uploaded_file)
        st.image(img, caption='Vista previa del plano', use_container_width=True)
    else:
        st.info("📄 Documento PDF detectado.")

    if st.button("Analizar con IA"):
        try:
            with st.spinner("Procesando archivo..."):
                # 1. Creamos un archivo temporal para que la API de Google lo pueda leer
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name

                # 2. Subimos el archivo a la infraestructura de Google (File API)
                # Esto es MUCHO más estable para PDFs
                google_file = genai.upload_file(path=tmp_path)
                
                # 3. Inicializamos el modelo (usamos el nombre completo para evitar el 404)
                model = genai.GenerativeModel(model_name="gemini-1.5-flash")

                # 4. Generamos el contenido
                prompt = "Analiza este plano arquitectónico. Identifica ejes, dimensiones, nombres de cuartos y notas técnicas."
                response = model.generate_content([prompt, google_file])

                # 5. Limpieza: Borramos el archivo de Google y el temporal local
                genai.delete_file(google_file.name)
                os.remove(tmp_path)

                st.success("¡Análisis listo!")
                st.markdown(response.text)

        except Exception as e:
            if "404" in str(e):
                st.error("❌ Error 404: El modelo no fue encontrado. Intenta actualizar la librería en requirements.txt.")
            elif "ResourceExhausted" in str(e) or "429" in str(e):
                st.error("🛑 Cuota agotada. Espera 1 minuto.")
            else:
                st.error(f"Error crítico: {e}")

# --- PIE DE PÁGINA ---
st.divider()
st.caption("Optimizado para análisis de normativa y planos técnicos.")
