import streamlit as st

def render_encuesta_calidad(vista: str, carrera: str | None) -> None:
    st.subheader("Encuesta de calidad")
    st.info("Módulo en construcción. La app ya está operativa y este apartado será el siguiente en desarrollarse.")
    st.write("Vista:", vista)
    if carrera:
        st.write("Carrera:", carrera)
