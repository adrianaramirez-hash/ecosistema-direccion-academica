import streamlit as st
import observacion_clases
import encuesta_calidad
import procesar_encuestas_calidad as proc  # <-- NUEVO

# Configuración básica de la página (debe ir antes de cualquier st.*)
st.set_page_config(page_title="Dirección Académica", layout="wide")

# Escudo de la UDL desde el repositorio
logo_url = "udl_logo.png"

# Encabezado con escudo + texto
col1, col2 = st.columns([1, 4])

with col1:
    st.image(logo_url, use_container_width=True)

with col2:
    st.title("Dirección Académica")
    st.write("Seguimiento del Plan Anual.")

st.divider()

# ============================================================
# BOTÓN PARA PROCESAR ENCUESTAS (ORIGINAL → PROCESADO)
# ============================================================
with st.expander("Inicialización de encuestas (solo administración)", expanded=False):
    st.caption(
        "Usa este botón para convertir respuestas de texto a números y llenar el archivo PROCESADO. "
        "Solo se requiere cuando haya nuevas respuestas."
    )

    if st.button("🔄 Procesar encuestas (ORIGINAL → PROCESADO)"):
        try:
            with st.spinner("Procesando encuestas, espera por favor..."):
                resultado = proc.main(st.secrets["gcp_service_account_json"])
            st.success("Proceso terminado correctamente")
            st.json(resultado)
        except Exception as e:
            st.error("Falló el procesamiento. Copia el error completo para revisarlo.")
            st.exception(e)

st.divider()

# Selector de vista
vista = st.selectbox(
    "Selecciona la vista:",
    ["Dirección General", "Dirección Académica", "Director de carrera"],
)

carrera = None
if vista == "Director de carrera":
    carrera = st.selectbox(
        "Selecciona la carrera:",
        [
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
        ],
    )

st.divider()

# Menú desplegable de secciones
seccion = st.selectbox(
    "Selecciona el apartado del plan anual que deseas revisar:",
    [
        "Observación de clases",
        "Encuesta de calidad",
        "Evaluación docente",
        "Capacitaciones",
        "Índice de reprobación",
        "Titulación",
        "Ceneval",
        "Exámenes departamentales",
        "Aulas virtuales",
    ],
)

st.divider()

st.subheader("Panel inicial")

st.write(f"Vista actual: **{vista}**")

if carrera:
    st.write(f"Carrera seleccionada: **{carrera}**")
else:
    st.write("Carrera seleccionada: *no aplica para esta vista*")

st.write(f"Apartado seleccionado: **{seccion}**")

st.markdown("---")

# Enrutamiento por sección
if seccion == "Observación de clases":
    observacion_clases.render_observacion_clases(vista, carrera)

elif seccion == "Encuesta de calidad":
    encuesta_calidad.render_encuesta_calidad(vista, carrera)

else:
    st.info("Este apartado aún está en construcción dentro del ecosistema.")
