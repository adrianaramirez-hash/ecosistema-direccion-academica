# modules/home.py
import streamlit as st

def render(rol: str = "Usuario"):
    st.subheader("Primera plana")

    if rol == "Director":
        st.success("Vista Director activa. Aquí agregaremos accesos y resúmenes ejecutivos.")
    else:
        st.caption("Vista Usuario activa. Aquí mostraremos seguimiento general.")

    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Plan anual", "—")
    with c2:
        st.metric("Observación de clases", "—")
    with c3:
        st.metric("Encuesta de calidad", "—")
    with c4:
        st.metric("CENEVAL", "—")

    st.divider()
    st.write("Siguientes pasos:")
    st.markdown(
        """
        1. Conectar Observación de clases.
        2. Conectar Encuesta de calidad.
        3. Llevar indicadores a esta primera plana.
        """
    )
