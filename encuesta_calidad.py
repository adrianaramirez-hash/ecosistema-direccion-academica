import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"

HOJA_VIRTUAL = "servicios virtual y mixto virtual"
HOJA_ESCOLAR = "servicios escolarizados y licenciaturas ejecutivas"
HOJA_PREPA = "Preparatoria"
HOJA_APLICACIONES = "Aplicaciones"

COLUMNA_CARRERA = "Carrera de procedencia"


# ============================================================
# CARGA DE DATOS DESDE GOOGLE SHEETS
# ============================================================

@st.cache_data(ttl=60)
def cargar_datos_calidad():
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_URL)

    def cargar_hoja(nombre):
        ws = sh.worksheet(nombre)
        return pd.DataFrame(ws.get_all_records())

    df_virtual = cargar_hoja(HOJA_VIRTUAL)
    df_esco = cargar_hoja(HOJA_ESCOLAR)
    df_prepa = cargar_hoja(HOJA_PREPA)
    df_aplic = cargar_hoja(HOJA_APLICACIONES)

    return df_virtual, df_esco, df_prepa, df_aplic


# ============================================================
# DEFINICIÓN DE SECCIONES POR MODALIDAD
# ============================================================

SECCIONES = {
    "virtual": {
        "Director / Coordinador": ("C", "G"),
        "Aprendizaje": ("H", "P"),
        "Materiales en plataforma": ("Q", "U"),
        "Evaluación del conocimiento": ("V", "Y"),
        "Acceso soporte académico": ("Z", "AD"),
        "Acceso soporte administrativo": ("AE", "AI"),
        "Comunicación con compañeros": ("AJ", "AQ"),
        "Recomendación": ("AR", "AU"),
        "Plataforma SEAC": ("AV", "AZ"),
        "Comunicación con la universidad": ("BA", "BE"),
    },
    "escolar": {
        "Servicios administrativos / apoyo": ("I", "V"),
        "Servicios académicos": ("W", "AH"),
        "Director / Coordinador": ("AI", "AM"),
        "Instalaciones y equipo": ("AN", "AX"),
        "Ambiente escolar": ("AY", "BE"),
    },
    "prepa": {
        "Servicios administrativos / apoyo": ("H", "Q"),
        "Servicios académicos": ("R", "AC"),
        "Directores y coordinadores": ("AD", "BB"),
        "Instalaciones y equipo tecnológico": ("BC", "BN"),
        "Ambiente escolar": ("BO", "BU"),
    },
}


# ============================================================
# FUNCIÓN PARA OBTENER PROMEDIOS POR SECCIÓN
# ============================================================

def columnas_por_rango(df, col_ini, col_fin):
    """Obtiene columnas usando letra A–Z independientemente del nombre."""
    cols = list(df.columns)
    try:
        i = cols.index(col_ini)
        j = cols.index(col_fin)
        return cols[i : j + 1]
    except:
        return []


def promedio_seccion(df, rango):
    col_ini, col_fin = rango
    cols = columnas_por_rango(df, col_ini, col_fin)
    if not cols:
        return None
    df_num = df[cols].apply(pd.to_numeric, errors="coerce")
    return df_num.mean().mean()


# ============================================================
# FUNCIÓN PRINCIPAL DEL MÓDULO
# ============================================================

def render_encuesta_calidad(vista, carrera_seleccionada):
    st.header("📊 Encuesta de Calidad – Resultados")

    try:
        df_virtual, df_esco, df_prepa, df_aplic = cargar_datos_calidad()
    except Exception as e:
        st.error("❌ No se pudieron cargar los datos de la Encuesta de Calidad.")
        st.exception(e)
        return

    # ────────────────────────────────────────────────
    # SELECTOR DE APLICACIÓN
    # ────────────────────────────────────────────────
    if "descripcion" in df_aplic.columns:
        aplicaciones = df_aplic["descripcion"].unique()
    else:
        aplicaciones = ["Aplicación 1"]

    aplic_sel = st.selectbox("Seleccione aplicación:", aplicaciones)
    st.divider()

    # ────────────────────────────────────────────────
    # PREPARAR MODALIDADES
    # ────────────────────────────────────────────────
    modalidades = {
        "Servicios virtuales y mixto virtual": (df_virtual, "virtual"),
        "Servicios escolarizados / ejecutivas": (df_esco, "escolar"),
        "Preparatoria": (df_prepa, "prepa"),
    }

    # ============================================================
    # VISTA DE DIRECCIÓN GENERAL y DIRECCIÓN ACADÉMICA
    # ============================================================
    if vista in ["Dirección General", "Dirección Académica"]:
        for nombre, (df, tipo) in modalidades.items():
            if df.empty:
                continue

            st.subheader(f"🔹 {nombre}")

            for seccion, rango in SECCIONES[tipo].items():
                prom = promedio_seccion(df, rango)
                if prom is not None:
                    st.write(f"**{seccion}:** {prom:.2f}")

            st.markdown("---")

    # ============================================================
    # VISTA DE DIRECTOR DE CARRERA
    # ============================================================
    if vista == "Director de carrera" and carrera_seleccionada:
        st.subheader(f"Resultados para: **{carrera_seleccionada}**")

        for nombre, (df, tipo) in modalidades.items():

            if df.empty or COLUMNA_CARRERA not in df.columns:
                continue

            df_filtrado = df[df[COLUMNA_CARRERA] == carrera_seleccionada]

            if df_filtrado.empty:
                continue

            st.markdown(f"### {nombre}")

            for seccion, rango in SECCIONES[tipo].items():
                prom = promedio_seccion(df_filtrado, rango)
                if prom is not None:
                    st.write(f"- **{seccion}:** {prom:.2f}")

            st.markdown("---")

