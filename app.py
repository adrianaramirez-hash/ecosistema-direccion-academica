import streamlit as st
from modules.home import render as render_home

# ============================================================
# Configuración básica (antes de cualquier st.*)
# ============================================================
st.set_page_config(page_title="Dirección Académica", layout="wide")

# ============================================================
# Estado inicial
# ============================================================
if "rol" not in st.session_state:
    st.session_state.rol = "Usuario"

# ============================================================
# Sidebar: navegación
# ============================================================
st.sidebar.title("Navegación")

st.session_state.rol = st.sidebar.selectbox(
    "Rol / Vista",
    options=["Usuario", "Director"],
    index=0 if st.session_state.rol == "Usuario" else 1
)

menu = ["Primera plana"]

# Placeholder: si es Director, mostramos “Servicios” (sin conectar módulos aún)
if st.session_state.rol == "Director":
    st.sidebar.subheader("Servicios")
    _servicios = st.sidebar.multiselect(
        "Selecciona servicios a habilitar",
        options=[
            "Observación de clases",
            "Encuesta de calidad",
            "CENEVAL",
            "Evaluación docente",
            "Titulación"
        ],
        default=[]
    )
    menu.extend(_servicios)

st.sidebar.divider()
seleccion = st.sidebar.radio("Ir a:", options=menu, index=0)

# ============================================================
# Header (logo en raíz)
# ============================================================
col1, col2 = st.columns([1, 5], vertical_alignment="center")
with col1:
    try:
        st.image("udl_logo.png", use_container_width=True)
    except Exception:
        st.caption("Logo no encontrado (udl_logo.png)")

with col2:
    st.title("Dirección Académica")
    st.write("Seguimiento del plan anual, visualización y toma de decisiones.")

st.divider()

# ============================================================
# Router simple
# ============================================================
if seleccion == "Primera plana":
    render_home(rol=st.session_state.rol)
else:
    st.subheader(seleccion)
    st.info("Este módulo aún no está construido. Lo conectaremos en el siguiente paso.")
