import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials
import altair as alt

# -------------------------------------------------------------------
# CONFIGURACIÓN BÁSICA
# -------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Tu archivo maestro de calidad
SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)

# -------------------------------------------------------------------
# UTILIDADES
# -------------------------------------------------------------------


def _normalizar_texto(txt: str) -> str:
    if txt is None:
        return ""
    return str(txt).strip().lower().replace("_", " ")


def detectar_modalidad(formulario: str) -> str:
    """
    A partir del texto del campo 'formulario' de la hoja Aplicaciones,
    devolvemos la modalidad: 'virtual', 'escolar' o 'prepa'.
    """
    t = _normalizar_texto(formulario)

    if "virtual" in t and "mixto" in t:
        return "virtual"
    if "escolarizados" in t or "licenciaturas ejecutivas" in t:
        return "escolar"
    if "preparatoria" in t or "prepa" in t:
        return "prepa"

    return "desconocida"


def obtener_nombre_hoja(formulario: str) -> str:
    """
    Mapeo flexible de 'formulario' (Aplicaciones) al nombre de la hoja
    de respuestas correspondiente.
    """
    t = _normalizar_texto(formulario)

    # intentamos detectar por palabras clave
    if "virtual" in t and "mixto" in t:
        # nombres posibles
        return "servicios virtual y mixto virtual"
    if "escolarizados" in t or "licenciaturas ejecutivas" in t:
        return "servicios escolarizados y licenciaturas ejecutivas"
    if "preparatoria" in t or "prepa" in t:
        return "Preparatoria"

    # por si decides usar exactamente los mismos nombres de formulario
    return formulario


# -------------------------------------------------------------------
# CARGA DE DATOS
# -------------------------------------------------------------------


@st.cache_data(ttl=60)
def cargar_datos_calidad():
    # Credenciales desde secrets (Streamlit Cloud)
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_URL)

    # Hojas de respuestas
    def leer_hoja(nombre_hoja):
        try:
            ws = sh.worksheet(nombre_hoja)
        except Exception:
            return pd.DataFrame()
        datos = ws.get_all_records()
        df = pd.DataFrame(datos)
        return df

    df_virtual = leer_hoja("servicios virtual y mixto virtual")
    df_esco = leer_hoja("servicios escolarizados y licenciaturas ejecutivas")
    df_prepa = leer_hoja("Preparatoria")

    # Hoja de aplicaciones
    try:
        ws_aplic = sh.worksheet("Aplicaciones")
    except Exception as e:
        st.error("No se encontró la hoja 'Aplicaciones' en el archivo de calidad.")
        st.exception(e)
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        )

    datos_aplic = ws_aplic.get_all_records()
    df_aplic = pd.DataFrame(datos_aplic)

    # Limpieza de fechas en aplicaciones
    for col in ["fecha_inicio", "fecha_fin"]:
        if col in df_aplic.columns:
            df_aplic[col] = pd.to_datetime(
                df_aplic[col], dayfirst=True, errors="coerce"
            )

    # Normalizamos texto de formulario
    if "formulario" in df_aplic.columns:
        df_aplic["formulario"] = df_aplic["formulario"].astype(str).str.strip()
    else:
        df_aplic["formulario"] = ""

    # Aseguramos Marca temporal como datetime en cada df de respuestas
    def normalizar_fechas_respuestas(df):
        if df.empty:
            return df
        if "Marca temporal" in df.columns:
            df["Marca temporal"] = pd.to_datetime(
                df["Marca temporal"], dayfirst=True, errors="coerce"
            )
        return df

    df_virtual = normalizar_fechas_respuestas(df_virtual)
    df_esco = normalizar_fechas_respuestas(df_esco)
    df_prepa = normalizar_fechas_respuestas(df_prepa)

    return df_virtual, df_esco, df_prepa, df_aplic


# -------------------------------------------------------------------
# INTERFAZ PRINCIPAL
# -------------------------------------------------------------------


def render_encuesta_calidad(vista: str, carrera_seleccionada: str | None):
    st.header("📊 Encuesta de calidad – Resultados")

    (
        df_virtual,
        df_esco,
        df_prepa,
        df_aplic,
    ) = cargar_datos_calidad()

    if df_aplic.empty:
        st.warning("No se pudieron cargar las aplicaciones de la encuesta.")
        return

    # ------------------------------------------------------------------
    # SELECTOR DE APLICACIÓN
    # ------------------------------------------------------------------
    # Etiqueta para el selectbox
    df_aplic = df_aplic.copy()
    if "descripcion" not in df_aplic.columns:
        df_aplic["descripcion"] = df_aplic["aplicacion_id"].astype(str)

    df_aplic["label"] = df_aplic["descripcion"]

    opciones = df_aplic["label"].tolist()
    if not opciones:
        st.warning("No hay aplicaciones registradas en la hoja 'Aplicaciones'.")
        return

    label_sel = st.selectbox(
        "Selecciona la aplicación de la encuesta:",
        opciones,
    )

    fila_aplic = df_aplic[df_aplic["label"] == label_sel].iloc[0]

    formulario = fila_aplic.get("formulario", "")
    aplic_id = fila_aplic.get("aplicacion_id", "")
    f_ini = fila_aplic.get("fecha_inicio", pd.NaT)
    f_fin = fila_aplic.get("fecha_fin", pd.NaT)

    modalidad = detectar_modalidad(formulario)
    nombre_hoja = obtener_nombre_hoja(formulario)

    st.write(
        f"Aplicación seleccionada: **{fila_aplic['descripcion']}**  "
        f"(ID: `{aplic_id}`)"
    )
    st.write(f"Modalidad detectada: **{modalidad}**")
    st.write(
        "Rango de fechas considerado: "
        f"{f_ini.date() if pd.notna(f_ini) else '—'} a "
        f"{f_fin.date() if pd.notna(f_fin) else '—'}"
    )

    # ------------------------------------------------------------------
    # SELECCIÓN DEL DATAFRAME BASE SEGÚN MODALIDAD
    # ------------------------------------------------------------------
    if modalidad == "virtual":
        df_base = df_virtual.copy()
    elif modalidad == "escolar":
        df_base = df_esco.copy()
    elif modalidad == "prepa":
        df_base = df_prepa.copy()
    else:
        # Intento de rescate: usamos el nombre de hoja derivado
        st.warning(
            "No se pudo detectar claramente la modalidad a partir del formulario. "
            "Se intentará usar el nombre de hoja derivado."
        )
        # usamos el cliente para leer esa hoja directamente
        try:
            (
                df_v,
                df_e,
                df_p,
                _,
            ) = cargar_datos_calidad()
        except Exception:
            df_base = pd.DataFrame()
        else:
            # no hay forma clara de escoger, así que leemos en frío
            df_base = pd.DataFrame()

    if df_base.empty:
        st.warning(
            "La hoja de respuestas correspondiente a esta modalidad está vacía "
            "o no se pudo leer. "
            "Verifica el nombre de las hojas en el archivo de Google Sheets."
        )
        return

    # ------------------------------------------------------------------
    # FILTRO POR FECHAS (APLICACIÓN)
    # ------------------------------------------------------------------
    df_filtrado = df_base.copy()

    if pd.notna(f_ini) and pd.notna(f_fin):
        # nos aseguramos que fecha_inicio <= fecha_fin
        if f_ini > f_fin:
            f_ini, f_fin = f_fin, f_ini

        if "Marca temporal" in df_filtrado.columns:
            mask = (df_filtrado["Marca temporal"] >= f_ini) & (
                df_filtrado["Marca temporal"] <= f_fin
            )
            df_filtrado = df_filtrado.loc[mask]

    # ------------------------------------------------------------------
    # FILTRO POR CARRERA (SOLO DIRECTOR DE CARRERA)
    # ------------------------------------------------------------------
    if (
        vista == "Director de carrera"
        and carrera_seleccionada
        and "Carrera de procedencia " in df_filtrado.columns
    ):
        df_filtrado = df_filtrado[
            df_filtrado["Carrera de procedencia "] == carrera_seleccionada
        ]

    # ------------------------------------------------------------------
    # REVISIÓN DE DATOS FILTRADOS
    # ------------------------------------------------------------------
    st.caption(
        f"Respuestas totales en la modalidad seleccionada: "
        f"**{len(df_base)}** · "
        f"Respuestas dentro del rango de la aplicación (y filtros): "
        f"**{len(df_filtrado)}**"
    )

    if df_filtrado.empty:
        st.warning("No hay respuestas en el rango de fechas para esta aplicación.")
        return

    # ------------------------------------------------------------------
    # KPI SENCILLO: CONTEO Y PROMEDIO GLOBAL DE ESCALA
    # ------------------------------------------------------------------
    # Para no depender de nombres específicos de columnas de escala,
    # tomamos todas las columnas numéricas y calculamos un promedio general.
    df_numeric = df_filtrado.select_dtypes(include=["number"])

    total_resp = len(df_filtrado)
    if not df_numeric.empty:
        promedio_global = df_numeric.mean(axis=1).mean()
    else:
        promedio_global = None

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Respuestas en esta aplicación (después de filtros)", total_resp)
    with col2:
        if promedio_global is not None:
            st.metric("Promedio global (todas las preguntas numéricas)", f"{promedio_global:.2f}")
        else:
            st.metric("Promedio global", "N/D")

    st.markdown("---")

    # ------------------------------------------------------------------
    # DISTRIBUCIÓN POR CARRERA (VISIÓN DIRECCIÓN)
    # ------------------------------------------------------------------
    if "Carrera de procedencia " in df_filtrado.columns:
        st.subheader("Distribución de respuestas por carrera")

        df_carr = (
            df_filtrado["Carrera de procedencia "]
            .value_counts()
            .reset_index()
            .rename(
                columns={
                    "index": "Carrera",
                    "Carrera de procedencia ": "Respuestas",
                }
            )
        )

        chart = (
            alt.Chart(df_carr)
            .mark_bar()
            .encode(
                x=alt.X("Carrera:N", sort="-y"),
                y=alt.Y("Respuestas:Q"),
                tooltip=["Carrera", "Respuestas"],
            )
            .properties(height=320)
        )
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(df_carr, use_container_width=True)

    # ------------------------------------------------------------------
    # TABLA DETALLE (MUESTRA LAS RESPUESTAS FILTRADAS)
    # ------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Detalle de respuestas (muestra filtrada)")

    st.dataframe(df_filtrado, use_container_width=True)


# -------------------------------------------------------------------
# Si quieres probar este módulo de forma independiente en Streamlit
# (ejecutando `streamlit run encuesta_calidad.py`), descomenta:
# -------------------------------------------------------------------
# if __name__ == "__main__":
#     st.set_page_config(page_title="Encuesta de calidad", layout="wide")
#     render_encuesta_calidad("Dirección General", None)
