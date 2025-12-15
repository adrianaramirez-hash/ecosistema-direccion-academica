import streamlit as st
import observacion_clases
import encuesta_calidad
import procesar_encuestas_calidad as proc  # Procesa ORIGINAL → PROCESADO

# ============================================================
# Configuración básica de la página (debe ir antes de cualquier st.*)
# ============================================================
st.set_page_config(page_title="Dirección Académica", layout="wide")

# ============================================================
# Header (logo + título)
# ============================================================
logo_url = "udl_logo.png"

col1, col2 = st.columns([1, 4])
with col1:
    st.image(logo_url, use_container_width=True)

with col2:
    st.title("Dirección Académica")
    st.write("Seguimiento del Plan Anual.")

st.divider()

# ============================================================
# Inicialización / Procesamiento (ORIGINAL → PROCESADO)
# ============================================================
with st.expander("Inicialización de encuestas (solo administración)", expanded=False):
    st.caption(
        "Usa este botón para convertir respuestas de texto a números y llenar el archivo PROCESADO. "
        "Solo se requiere cuando haya nuevas respuestas."
    )

    if st.button("🔄 Procesar encuestas (ORIGINAL → PROCESADO)"):
        try:
            with st.spinner("Procesando encuestas, espera por favor..."):
                # Ajusta esta llave a la que estés usando en Secrets.
                # Si tu secreto se llama distinto, cambia la clave.
                resultado = proc.main(st.secrets["gcp_service_account_json"])
            st.success("Proceso terminado correctamente")
            st.json(resultado)
        except Exception as e:
            st.error("Falló el procesamiento. Copia el error completo para revisarlo.")
            st.exception(e)

st.divider()

# ============================================================
# Selectores globales (vista, carrera, sección)
# ============================================================
vista = st.selectbox(
    "Selecciona la vista:",
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
    carrera = st.selectbox(
        "Selecciona la carrera:",
        CARRERAS,
        key="carrera_selector",
    )

st.divider()

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

# Persistencia de sección (evita reinicios inesperados)
if "seccion_selector" not in st.session_state:
    st.session_state["seccion_selector"] = "Encuesta de calidad"

seccion = st.selectbox(
    "Selecciona el apartado del plan anual que deseas revisar:",
    SECCIONES,
    key="seccion_selector",
)

st.divider()

# ============================================================
# Enrutamiento por sección (módulos)
# ============================================================
if seccion == "Observación de clases":
    observacion_clases.render_observacion_clases(vista, carrera)

elif seccion == "Encuesta de calidad":
    encuesta_calidad.render_encuesta_calidad(vista, carrera)

else:
    # Panel inicial solo cuando NO estás en un módulo implementado
    st.subheader("Panel inicial")
    st.write(f"Vista actual: **{vista}**")

    if carrera:
        st.write(f"Carrera seleccionada: **{carrera}**")
    else:
        st.write("Carrera seleccionada: *no aplica para esta vista*")

    st.write(f"Apartado seleccionado: **{seccion}**")
    st.markdown("---")
    st.info("Este apartado aún está en construcción dentro del ecosistema.")
