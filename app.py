import streamlit as st
import observacion_clases
import encuesta_calidad
import procesar_encuestas_calidad as proc

st.set_page_config(page_title="Dirección Académica", layout="wide")

# =========================
# Header
# =========================
logo_url = "udl_logo.png"

col1, col2 = st.columns([1, 4], vertical_alignment="center")
with col1:
    try:
        st.image(logo_url, use_container_width=True)
    except Exception:
        st.caption("Logo no disponible")
with col2:
    st.title("Dirección Académica")
    st.write("Seguimiento del Plan Anual.")

st.markdown("---")

# =========================
# Sidebar - Selectores
# =========================
st.sidebar.header("Navegación")

vista = st.sidebar.selectbox(
    "Vista",
    ["Dirección General", "Dirección Académica", "Director de carrera"],
    key="vista_selector",
)

CARRERAS = [
    "Actuación",
    "Administración de Empresas",
    "Cine y TV Digital",
    "Comunicación Multimedia",
    "Contaduría",
    "Creación y Gestión de Empresas Turísticas",
    "Derecho",
    "Diseño de Modas",
    "Diseño Gráfico",
    "Finanzas",
    "Gastronomía",
    "Mercadotecnia",
    "Nutrición",
    "Pedagogía",
    "Psicología",
    "Tecnologías de la Información",
    "Lic. Ejecutiva: Administración de Empresas",
    "Lic. Ejecutiva: Contaduría",
    "Lic. Ejecutiva: Derecho",
    "Lic. Ejecutiva: Informática",
    "Lic. Ejecutiva: Mercadotecnia",
    "Lic. Ejecutiva: Pedagogía",
    "Maestría en Administración de Negocios (MBA)",
    "Maestría en Derecho Corporativo",
    "Maestría en Desarrollo del Potencial Humano y Organizacional",
    "Maestría en Odontología Legal y Forense",
    "Maestría en Psicoterapia Familiar",
    "Maestría en Psicoterapia Psicoanalítica",
    "Maestría en Administración de Recursos Humanos",
    "Maestría en Finanzas",
    "Maestría en Educación Especial",
    "Preparatoria",
]

carrera = None
if vista == "Director de carrera":
    carrera = st.sidebar.selectbox("Carrera", CARRERAS, key="carrera_selector")

SECCIONES = [
    "Observación de clases",
    "Encuesta de calidad",
    "Evaluación docente",
    "Capacitaciones",
    "Índice de reprobación",
    "Titulación",
    "Ceneval",
    "Exámenes departamentales",
    "Aulas virtuales",
]

if "seccion_selector" not in st.session_state:
    st.session_state["seccion_selector"] = "Observación de clases"

seccion = st.sidebar.selectbox(
    "Apartado del plan anual",
    SECCIONES,
    key="seccion_selector",
)

# =========================
# Admin (opcional) - Procesar encuestas
# =========================
with st.sidebar.expander("Administración", expanded=False):
    st.caption("Procesa encuestas (stub por ahora).")
    if st.button("Procesar encuestas (ORIGINAL → PROCESADO)"):
        try:
            resultado = proc.main(st.secrets.get("gcp_service_account_json", {}))
            st.success("Listo.")
            st.json(resultado)
        except Exception as e:
            st.error("Error al procesar.")
            st.exception(e)

# =========================
# Primera plana (contenido)
# =========================
st.subheader("Panel principal")
st.write(f"**Vista:** {vista}")
st.write(f"**Carrera:** {carrera if carrera else 'No aplica'}")
st.write(f"**Apartado:** {seccion}")
st.markdown("---")

# =========================
# Enrutamiento
# =========================
if seccion == "Observación de clases":
    observacion_clases.render_observacion_clases(vista, carrera)

elif seccion == "Encuesta de calidad":
    encuesta_calidad.render_encuesta_calidad(vista, carrera)

else:
    st.info("Este apartado aún está en construcción dentro del ecosistema.")
