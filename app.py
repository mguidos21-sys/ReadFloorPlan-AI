import streamlit as st
import google.generativeai as genai
from PIL import Image
import tempfile
import os

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Lector de Planos IA", layout="centered")
st.title("🏗️ Lector de Planos Pro")
st.write("Sube un plano (Imagen o PDF) para analizarlo con IA.")

# --- 2. CONFIGURACIÓN DE LA API (Secrets) ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Por favor, agrega tu 'GOOGLE_API_KEY' en los Secrets de Streamlit.")
    st.stop()

genai.configure(api_key=api_key)

# --- DIAGNÓSTICO DE MODELOS ---
try:
    # Intentamos listar los modelos para ver cuáles están disponibles para tu cuenta
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    st.write(f"Modelos disponibles en tu cuenta: {available_models}")
    
    # Intentamos elegir Flash si está en la lista, si no, el primero que encuentre
    if 'models/gemini-1.5-flash' in available_models:
        model_name = 'models/gemini-1.5-flash'
    elif 'models/gemini-pro' in available_models:
        model_name = 'models/gemini-pro'
    else:
        model_name = available_models[0]
        
    model = genai.GenerativeModel(model_name=model_name)
    st.success(f"Usando el modelo: {model_name}")

except Exception as e:
    st.error(f"Error al listar modelos: {e}")
    # Fallback manual si el listado falla
    model = genai.GenerativeModel(model_name='gemini-pro')

# --- 4. CARGA DE ARCHIVOS ---
uploaded_file = st.file_uploader("Sube un plano (JPG, PNG o PDF)", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    # Vista previa sencilla
    if uploaded_file.type != "application/pdf":
        img = Image.open(uploaded_file)
        st.image(img, caption='Vista previa del plano', use_container_width=True)
    else:
        st.info("📄 Documento PDF listo para análisis.")

    # --- 5. BOTÓN DE ACCIÓN ---
    if st.button("Analizar con IA"):
        try:
            with st.spinner("Procesando archivo... esto puede tardar unos segundos"):
                
                # Crear un archivo temporal para que Google lo procese
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name

                # Subir archivo a la API de Google
                google_file = genai.upload_file(path=tmp_path)
                
                # Definir el prompt para el arquitecto
                prompt = (
                    "Eres un asistente experto en arquitectura y normativas. "
                    "Analiza este plano y extrae: áreas principales, dimensiones detectadas, "
                    "y notas técnicas importantes."
                )

                # Generar respuesta
                response = model.generate_content([prompt, google_file])

                # Limpieza (Borrar archivos temporales)
                genai.delete_file(google_file.name)
                os.remove(tmp_path)

                # Mostrar resultado
                st.success("¡Análisis completado!")
                st.markdown("### Resultados del análisis:")
                st.write(response.text)

        except Exception as e:
            error_str = str(e)
            if "404" in error_str:
                st.error("❌ Error 404: El modelo no se encontró. Verifica que la librería esté actualizada en requirements.txt.")
            elif "ResourceExhausted" in error_str or "429" in error_str:
                st.error("🛑 Cuota agotada: La versión gratuita de Google tiene límites. Espera 1 minuto e intenta de nuevo.")
            else:
                st.error(f"Ocurrió un error: {e}")

# --- PIE DE PÁGINA ---
st.divider()
st.caption("Herramienta de apoyo para revisión de planos.")
