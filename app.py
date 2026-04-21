import streamlit as st
import google.generativeai as genai
from PIL import Image
import os

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Lector de Planos IA", layout="centered")

st.title("🏗️ Lector de Planos con IA")
st.write("Sube una imagen de tu plano para analizarla.")

# --- CONFIGURACIÓN DE LA API ---
# Intenta obtener la API Key desde los Secrets de Streamlit
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Falta la API Key en los Secrets de Streamlit.")
    st.stop()

genai.configure(api_key=api_key)

# --- CONFIGURACIÓN DEL MODELO ---
# Usamos 'gemini-1.5-flash' para evitar el error de ResourceExhausted (Cuota)
# ya que es más liviano y tiene límites más amplios que el 'pro'.
model = genai.GenerativeModel('gemini-1.5-flash')

# --- INTERFAZ DE CARGA ---
uploaded_file = st.file_uploader("Elige una imagen del plano...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Mostrar la imagen cargada
    image = Image.open(uploaded_file)
    st.image(image, caption='Plano cargado correctamente', use_container_width=True)
    
    # Botón para activar el análisis
    if st.button("Analizar Plano"):
        try:
            with st.spinner("La IA está analizando los detalles del plano..."):
                # Preparamos el prompt técnico
                prompt = (
                    "Actúa como un experto topógrafo y arquitecto. "
                    "Analiza detalladamente este plano. Identifica medidas, "
                    "estructuras, nombres de áreas y cualquier detalle técnico relevante."
                )
                
                # LLAMADA A LA API (Aquí es donde ocurría el error)
                response = model.generate_content([prompt, image])
                
                # Mostrar resultado
                st.success("¡Análisis completado!")
                st.markdown("### Resumen del análisis:")
                st.write(response.text)

        except Exception as e:
            # Captura específica del error de cuota (ResourceExhausted)
            error_msg = str(e)
            if "429" in error_msg or "ResourceExhausted" in error_msg:
                st.error("🛑 **Error de Cuota:** Has superado el límite de solicitudes gratuitas de Google.")
                st.info("Espera 60 segundos antes de intentar de nuevo o reduce el tamaño de la imagen.")
            else:
                st.error(f"Ocurrió un error inesperado: {e}")

# --- PIE DE PÁGINA ---
st.divider()
st.caption("Desarrollado con Streamlit y Google Gemini 1.5 Flash")
