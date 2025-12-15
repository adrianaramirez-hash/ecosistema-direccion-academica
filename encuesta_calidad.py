import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import gspread
from google.oauth2.service_account import Credentials
from collections.abc import Mapping
import json

# ============================================================
# CONFIGURACIÓN
# ============================================================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_KEY_PROCESADO = "1zwa-cG8Bwn6IA0VBrW_gsIb-bB92nTpa2H5sS4LVvak"

HOJAS = {
    "Virtual": "Virtual_num",
    "Escolar": "Escolar_num",
    "Prepa": "Prepa_num",
}

HOJA_COMENTARIOS = "Comentarios"
HOJA_LOG = "Log_conversion"

TIMESTAMP_COL = "Marca temporal"

CARRERA_COL = {
    "Virtual_num": "Selecciona el programa académico que estudias",
    "Escolar_num": "Carrera de procedencia",
    "Prepa_num": None,
}

# ============================================================
# DICCIONARIO DE SECCIONES (OBLIGATORIO)
# ============================================================
SECCIONES = {
    "Virtual_num": {
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
    "Escolar_num": {
        "Servicios administrativos / apoyo": ("I", "V"),
        "Servicios académicos": ("W", "AH"),
        "Director / Coordinador": ("AI", "AM"),
        "Instalaciones / equipo tecnológico": ("AN", "AX"),
        "Ambiente escolar": ("AY", "BE"),
    },
    "Prepa_num": {
        "Servicios administrativos / apoyo": ("H", "Q"),
        "Servicios académicos": ("R", "AC"),
        "Directores y coordinadores": ("AD", "BB"),
        "Instalaciones / equipo tecnológico": ("BC", "BN"),
        "Ambiente escolar": ("BO", "BU"),
    },
}

# ============================================================
# UTILIDADES
# ============================================================
def excel_col_to_index(col):
    n = 0
    for c in col.upper():
        if "A" <= c <= "Z":
            n = n * 26 + (ord(c) - ord("A") + 1)
    return n - 1

def columnas_rango(df, a, b):
    i, j = excel_col_to_index(a), excel_col_to_index(b)
    return df.columns[i:j+1]

def get_service_account():
    if "gcp_service_account_json" in st.secrets:
        v = st.secrets["gcp_service_account_json"]
        if isinstance(v, str):
            return json.loads(v)
        if isinstance(v, Mapping):
            return dict(v)
    raise RuntimeError("No se encontró gcp_service_account_json en secrets")

# ============================================================
# CARGA DE DATOS
# ============================================================
@st.cache_data(ttl=120)
def cargar_datos():
    creds = Credentials.from_service_account_info(
        get_service_account(),
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_KEY_PROCESADO)

    data = {}
    for hoja in HOJAS.values():
        ws = sh.worksheet(hoja)
        df = pd.DataFrame(ws.get_all_records())
        data[hoja] = df

    df_com = pd.DataFrame(sh.worksheet(HOJA_COMENTARIOS).get_all_records())
    df_log = pd.DataFrame(sh.worksheet(HOJA_LOG).get_all_records())

    return data, df_com, df_log

# ============================================================
# MÉTRICAS
# ============================================================
def promedio_general(df, hoja):
    cols = []
    for a, b in SECCIONES[hoja].values():
        cols.extend(columnas_rango(df, a, b))
    vals = pd.to_numeric(df[cols].stack(), errors="coerce").dropna()
    return vals.mean() if not vals.empty else np.nan

def promedio_por_seccion(df, hoja):
    rows = []
    for sec, (a, b) in SECCIONES[hoja].items():
        cols = columnas_rango(df, a, b)
        vals = pd.to_numeric(df[cols].stack(), errors="coerce").dropna()
        rows.append({
            "Sección": sec,
            "Promedio": vals.mean() if not vals.empty else np.nan,
            "Respuestas válidas": len(vals),
        })
    return pd.DataFrame(rows)

def detalle_reactivos(df, hoja, seccion):
    a, b = SECCIONES[hoja][seccion]
    rows = []
    for col in columnas_rango(df, a, b):
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(vals) > 0:
            rows.append({
                "Reactivo": col,
                "Promedio": vals.mean(),
                "Respuestas válidas": len(vals),
            })
    return pd.DataFrame(rows)

# ============================================================
# RENDER
# ============================================================
def render_encuesta_calidad(vista, carrera):
    st.header("Encuesta de calidad")

    data, df_com, df_log = cargar_datos()

    modalidad = st.selectbox("Selecciona modalidad", list(HOJAS.keys()))
    hoja = HOJAS[modalidad]
    df = data[hoja]

    carrera_col = CARRERA_COL[hoja]

    if vista in ("Dirección General", "Dirección Académica") and carrera_col:
        carreras = sorted(df[carrera_col].dropna().unique())
        sel = st.selectbox("Filtro de alcance", ["UDL completa"] + carreras)
        if sel != "UDL completa":
            df = df[df[carrera_col] == sel]
    elif vista == "Director de carrera" and carrera_col:
        df = df[df[carrera_col] == carrera]

    st.metric("Total de respuestas", len(df))
    prom = promedio_general(df, hoja)
    st.metric("Promedio general (0–5)", round(prom, 3) if not np.isnan(prom) else "N/D")

    st.divider()

    st.subheader("Promedio por sección")
    df_sec = promedio_por_seccion(df, hoja)
    st.dataframe(df_sec, use_container_width=True, hide_index=True)

    st.altair_chart(
        alt.Chart(df_sec.dropna())
        .mark_bar()
        .encode(
            x="Sección:N",
            y=alt.Y("Promedio:Q", scale=alt.Scale(domain=[0, 5])),
            tooltip=["Sección", "Promedio", "Respuestas válidas"],
        ),
        use_container_width=True,
    )

    st.subheader("Selecciona la sección evaluada")
    secciones_validas = df_sec[df_sec["Respuestas válidas"] > 0]["Sección"].tolist()

    if not secciones_validas:
        st.info("No hay secciones con respuestas válidas.")
        return

    sec_sel = st.selectbox("Sección", secciones_validas)
    df_det = detalle_reactivos(df, hoja, sec_sel)

    st.dataframe(df_det, use_container_width=True, hide_index=True)

    st.altair_chart(
        alt.Chart(df_det)
        .mark_bar()
        .encode(
            y=alt.Y("Reactivo:N", sort="-x"),
            x=alt.X("Promedio:Q", scale=alt.Scale(domain=[0, 5])),
            tooltip=["Reactivo", "Promedio", "Respuestas válidas"],
        ),
        use_container_width=True,
    )

    if vista in ("Dirección General", "Dirección Académica"):
        st.subheader("Comentarios")
        st.dataframe(df_com, use_container_width=True, hide_index=True)

        st.subheader("Log de conversión")
        st.dataframe(df_log, use_container_width=True, hide_index=True)
