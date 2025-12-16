import streamlit as st

import observacion_clases
import encuesta_calidad
import procesar_encuestas_calidad as proc  # ORIGINAL → PROCESADO


# =========================
# Constantes
# =========================
APP_TITLE = "Dirección Académica"
APP_SUBTITLE = "Seguimiento del Plan Anual."
LOGO_PATH = "udl_logo.png"

VISTAS = ["Dirección General", "Dirección Académica", "Director de carrera"]

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

DEFAULT_SECCION = "Encuesta de calidad"


# =========================
# Helpers UI
# =========================
def render_header() -> None:
    col1, col2 = st.columns([1, 4], vertical_alignment="center")
    with col1:
        try:
            st.image(LOGO_PATH, use_container_width=True)
        except Exception:
            st.caption("Logo no disponible")
    with col2:
        st.title(APP_TITLE)
        st.write(APP_SUBTITLE)


def render_admin_processing() -> None:
    with st.expander("Inicialización de encuestas (solo administración)", expanded=False):
        st.caption(
            "Convierte respuestas de texto a valores numéricos y llena el archivo PROCESADO. "
            "Úsalo únicamente cuando haya nuevas respuestas."
        )

        if st.button("Procesar encuestas (ORIGINAL → PROCESADO)"):
            try:
                with st.spinner("Procesando encuestas..."):
                    resultado = proc.main(st.secrets["gcp_service_account_json"])
                st.success("Proceso terminado correctamente.")
                # Si quieres debug, deja esto; si no, puedes quitarlo.
                st.json(resultado)
            except KeyError:
                st.error(
                    "No encontré el secreto `gcp_service_account_json` en `st.secrets`."
                )
            except Exception as e:
                st.error("Falló el procesamiento. Copia el error completo para revisarlo.")
                st.exception(e)


def render_sidebar_selectors():
    st.sidebar.header("Navegación")

    vista = st.sidebar.selectbox("Vista", VISTAS, key="vista_selector")

    carrera = None
    if vista == "Director de carrera":
        carrera = st.sidebar.selectbox("Carrera", CARRERAS, key="carrera_selector")

    if "seccion_selector" not in st.session_state:
        st.session_state["seccion_selector"] = DEFAULT_SECCION

    seccion = st.sidebar.selectbox(
        "Apartado del plan anual",
        SECCIONES,
        key="seccion_selector",
    )

    return vista, carrera, seccion


def render_placeholder(vista: str, carrera: str | None, seccion: str) -> None:
    st.subheader("Panel inicial")
    st.write(f"Vista actual: **{vista}**")
    st.write(f"Carrera seleccionada: **{carrera}**" if carrera else "Carrera seleccionada: *no aplica*")
    st.write(f"Apartado seleccionado: **{seccion}**")
    st.markdown("---")
    st.info("Este apartado aún está en construcción dentro del ecosistema.")


# =========================
# App
# =========================
st.set_page_config(page_title=APP_TITLE, layout="wide")

render_header()
render_admin_processing()

vista, carrera, seccion = render_sidebar_selectors()
st.markdown("---")

ROUTES = {
    "Observación de clases": lambda: observacion_clases.render_observacion_clases(vista, carrera),
    "Encuesta de calidad": lambda: encuesta_calidad.render_encuesta_calidad(vista, carrera),
}

handler = ROUTES.get(seccion)
if handler:
    handler()
else:
    render_placeholder(vista, carrera, seccion)
