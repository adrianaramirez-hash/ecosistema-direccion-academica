import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials

# ------------------------------------------------------
# CONFIGURACION
# ------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"

HOJA_VIRTUAL = "servicios virtual y mixto virtual"
HOJA_ESCOLAR = "servicios escolarizados y licenciaturas ejecutivas"
HOJA_PREPA = "Preparatoria"
HOJA_APLICACIONES = "Aplicaciones"

COLUMNA_SERVICIO = "Carrera de procedencia"

# ------------------------------------------------------
# LEER DATOS
# ------------------------------------------------------

@st.cache_data(ttl=60)
def cargar_datos_calidad():
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_URL)

    ws_virtual = sh.worksheet(HOJA_VIRTUAL)
    df_virtual = pd.DataFrame(ws_virtual.get_all_records())

    ws_esco = sh.worksheet(HOJA_ESCOLAR)
    df_esco = pd.DataFrame(ws_esco.get_all_records())

    ws_prepa = sh.worksheet(HOJA_PREPA)
    df_prepa = pd.DataFrame(ws_prepa.get_all_records())

    ws_aplic = sh.worksheet(HOJA_APLICACIONES)
    df_aplic = pd.DataFrame(ws_aplic.get_all_records())

    return df_virtual, df_esco, df_prepa, df_aplic


# ------------------------------------------------------
# MAPEO DE SECCIONES POR MODALIDAD
# ------------------------------------------------------

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

# ------------------------------------------------------
# OBTENER PROMEDIOS POR SECCION
# ------------------------------------------------------

def extraer_seccion(df, rango):
    col_ini, col_fin = rango
    cols = df.loc[:, col_ini:col_fin]
    cols = cols.apply(pd.to_numeric, errors="coerce")
    return cols.mean(axis=1), cols.mean().mean()


# ------------------------------------------------------
# UI PRINCIPAL
# ------------------------------------------------------

def render_encuesta_calidad(vista, carrera_seleccionada):
    st.header("📊 Encuesta de Calidad – Resultados")

    try:
        df_virtual, df_esco, df_prepa, df_aplic = cargar_datos_calidad()
    except Exception as e:
        st.error("No se pudieron cargar los datos de la Encuesta de calidad.")
        st.exception(e)
        return

    # -------------------------------
    # SELECTOR DE APLICACIÓN
    # -------------------------------

    if "descripcion" in df_aplic.columns:
        aplicaciones = df_aplic["descripcion"].unique()
    else:
        aplicaciones = ["Aplicación 1"]

    aplic_sel = st.selectbox("Seleccione aplicación:", aplicaciones)

    st.markdown("---")

    # -------------------------------
    # PREPARAR DATOS POR MODALIDAD
    # -------------------------------

    modalidades = {
        "Servicios virtuales": (df_virtual, "virtual"),
        "Servicios escolarizados / ejecutivas": (df_esco, "escolar"),
        "Preparatoria": (df_prepa, "prepa"),
    }

    # Vista global
    if vista in ["Dirección General", "Dirección Académica"]:
        st.subheader("Resultados generales por modalidad")

        for nombre, (df, tipo) in modalidades.items():
            if df.empty:
                continue

            st.markdown(f"### {nombre}")

            if COLUMNA_SERVICIO in df.columns:
                df_mod = df.copy()
            else:
                st.warning(f"No existe columna '{COLUM
