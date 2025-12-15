import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import gspread
import json
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIG (PROCESADO)
# ============================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# PROCESADO (el que me compartiste)
SPREADSHEET_URL_PROCESADO = (
    "https://docs.google.com/spreadsheets/d/"
    "1zwa-cG8Bwn6IA0VBrW_gsIb-bB92nTpa2H5sS4LVvak/edit"
)

HOJAS_NUM = {
    "Virtual": "Virtual_num",
    "Escolar": "Escolar_num",
    "Prepa": "Prepa_num",
}
HOJA_COMENTARIOS = "Comentarios"
HOJA_LOG = "Log_conversion"

# Encabezados base (según lo que me compartiste)
CARRERA_COL_BY_HOJA = {
    "Virtual_num": "Selecciona el programa académico que estudias",
    "Escolar_num": "Carrera de procedencia",
    "Prepa_num": None,  # Prepa no tiene carrera
}
TIMESTAMP_COL = "Marca temporal"  # aparece en las 3

# ============================================================
# DICCIONARIO DE SECCIONES (RANGOS EXCEL) OBLIGATORIO
# ============================================================
SECCIONES_POR_HOJA = {
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
def excel_col_to_index(col: str) -> int:
    col = str(col).strip().upper()
    n = 0
    for ch in col:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1

def columnas_por_rango(df: pd.DataFrame, start_col: str, end_col: str) -> list[str]:
    i = excel_col_to_index(start_col)
    j = excel_col_to_index(end_col)
    if i > j:
        i, j = j, i
    cols = df.columns.tolist()
    if not cols:
        return []
    i = max(0, i)
    j = min(len(cols) - 1, j)
    return cols[i : j + 1]

def numeric_series(s: pd.Series) -> pd.Series:
    # PROCESADO: sin conversiones semánticas; lo no numérico -> NaN
    return pd.to_numeric(s, errors="coerce")

def mean_ponderado_por_respuestas(df: pd.DataFrame, item_cols: list[str]) -> tuple[float, int]:
    """
    Promedio ponderado por respuestas válidas a nivel reactivo:
    apila todos los valores numéricos de los reactivos y promedia.
    """
    if not item_cols:
        return (np.nan, 0)
    arr = df[item_cols].apply(numeric_series).to_numpy().ravel()
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return (np.nan, 0)
    return (float(valid.mean()), int(valid.size))

def promedios_por_seccion(df: pd.DataFrame, hoja: str) -> pd.DataFrame:
    rows = []
    for seccion, (a, b) in SECCIONES_POR_HOJA[hoja].items():
        cols = columnas_por_rango(df, a, b)
        prom, n_valid = mean_ponderado_por_respuestas(df, cols)
        rows.append({"Sección": seccion, "Promedio": prom, "Respuestas válidas": n_valid})
    return pd.DataFrame(rows)

def detalle_por_reactivo(df: pd.DataFrame, hoja: str, seccion: str) -> pd.DataFrame:
    a, b = SECCIONES_POR_HOJA[hoja][seccion]
    cols = columnas_por_rango(df, a, b)

    data = []
    for col in cols:
        ser = numeric_series(df[col])
        valid = ser.dropna()
        data.append({
            "Reactivo": str(col),  # encabezado completo
            "Promedio": float(valid.mean()) if len(valid) else np.nan,
            "Respuestas válidas": int(valid.shape[0]),
        })
    df_det = pd.DataFrame(data)

    # OCULTAR columnas sin datos (lo pediste)
    df_det = df_det[df_det["Respuestas válidas"] > 0].copy()

    return df_det

def chart_barras_seccion(df_sec: pd.DataFrame, title: str):
    df_plot = df_sec.dropna(subset=["Promedio"]).copy()
    if df_plot.empty:
        st.info("No hay promedios válidos por sección para graficar.")
        return
    c = (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X("Sección:N", sort=None, axis=alt.Axis(labelAngle=-35, labelLimit=0)),
            y=alt.Y("Promedio:Q", scale=alt.Scale(domain=[0, 5])),
            tooltip=["Sección:N", "Promedio:Q", "Respuestas válidas:Q"],
        )
        .properties(height=320, title=title)
    )
    st.altair_chart(c, use_container_width=True)

def chart_barras_reactivos(df_det: pd.DataFrame, title: str):
    if df_det.empty:
        st.info("No hay reactivos con respuestas válidas para graficar.")
        return
    df_plot = df_det.dropna(subset=["Promedio"]).copy()
    if df_plot.empty:
        st.info("No hay promedios válidos por reactivo para graficar.")
        return
    c = (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X("Promedio:Q", scale=alt.Scale(domain=[0, 5])),
            y=alt.Y("Reactivo:N", sort="-x", axis=alt.Axis(labelLimit=0)),
            tooltip=["Reactivo:N", "Promedio:Q", "Respuestas válidas:Q"],
        )
        .properties(height=min(900, 28 * max(6, len(df_plot))), title=title)
    )
    st.altair_chart(c, use_container_width=True)

# ============================================================
# CARGA SHEETS (PROCESADO)
# ============================================================
def _buscar_hoja(sh, nombre: str):
    objetivo = str(nombre).strip().lower()
    for ws in sh.worksheets():
        if ws.title.strip().lower() == objetivo:
            return ws
    for ws in sh.worksheets():
        if objetivo in ws.title.strip().lower():
            return ws
    return None

def leer_hoja_df(sh, nombre_hoja: str) -> pd.DataFrame:
    ws = None
    try:
        ws = sh.worksheet(nombre_hoja)
    except Exception:
        ws = _buscar_hoja(sh, nombre_hoja)

    if ws is None:
        return pd.DataFrame()

    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame()

    header = values[0]
    rows = values[1:]

    # encabezados únicos
    counts = {}
    header_unique = []
    for h in header:
        base = (h.strip() if isinstance(h, str) else str(h)) or "columna_sin_nombre"
        if base not in counts:
            counts[base] = 1
            header_unique.append(base)
        else:
            counts[base] += 1
            header_unique.append(f"{base}_{counts[base]}")

    df = pd.DataFrame(rows, columns=header_unique)
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    return df

def ensure_numeric_processed(df: pd.DataFrame, hoja: str) -> pd.DataFrame:
    """
    PROCESADO: no conversiones de texto->número en Streamlit.
    Solo coerción a numérico para columnas no-base.
    """
    if df.empty:
        return df

    carrera_col = CARRERA_COL_BY_HOJA.get(hoja)
    keep_text = set(["Modalidad"])

    if TIMESTAMP_COL in df.columns:
        keep_text.add(TIMESTAMP_COL)
        df[TIMESTAMP_COL] = pd.to_datetime(df[TIMESTAMP_COL], dayfirst=True, errors="coerce")

    if carrera_col and carrera_col in df.columns:
        keep_text.add(carrera_col)

    for col in df.columns:
        if col in keep_text:
            continue
        df[col] = numeric_series(df[col])

    return df

@st.cache_data(ttl=120, show_spinner=False)
def cargar_datos_procesados():
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_url(SPREADSHEET_URL_PROCESADO)

    data = {}
    for _, hoja in HOJAS_NUM.items():
        df = leer_hoja_df(sh, hoja)
        data[hoja] = ensure_numeric_processed(df, hoja)

    df_com = leer_hoja_df(sh, HOJA_COMENTARIOS)
    df_log = leer_hoja_df(sh, HOJA_LOG)

    return data, df_com, df_log

# ============================================================
# FILTROS
# ============================================================
def filtrar_por_carrera(df: pd.DataFrame, hoja: str, carrera: str | None) -> pd.DataFrame:
    carrera_col = CARRERA_COL_BY_HOJA.get(hoja)
    if df.empty:
        return df
    if (not carrera_col) or (not carrera) or (carrera == "UDL completa"):
        return df
    if carrera_col not in df.columns:
        return df
    return df[df[carrera_col].astype(str).str.strip() == str(carrera).strip()].copy()

def carreras_disponibles(data: dict) -> list[str]:
    carreras = set()
    for hoja, df in data.items():
        col = CARRERA_COL_BY_HOJA.get(hoja)
        if col and (not df.empty) and col in df.columns:
            carreras.update(df[col].dropna().astype(str).str.strip().tolist())
    out = sorted([c for c in carreras if c])
    return out

# ============================================================
# RENDER PRINCIPAL
# ============================================================
def render_encuesta_calidad(vista: str, carrera_seleccionada: str | None):
    st.header("Encuesta de calidad")

    data, df_com, df_log = cargar_datos_procesados()

    # 1) Modalidad -> hoja
    modalidad_ui = st.selectbox("Selecciona modalidad", list(HOJAS_NUM.keys()), index=0)
    hoja = HOJAS_NUM[modalidad_ui]
    df_base = data.get(hoja, pd.DataFrame())

    if df_base.empty:
        st.info(f"No hay datos en la hoja {hoja}.")
        return

    # 2) Alcance (DG/DA) vs Director
    carrera_col = CARRERA_COL_BY_HOJA.get(hoja)
    carreras = carreras_disponibles(data)

    if vista in ("Dirección General", "Dirección Académica"):
        if carrera_col:
            alcance = st.selectbox("Filtro de alcance", ["UDL completa"] + carreras, index=0)
        else:
            st.info("En esta modalidad no existe columna de carrera; el análisis se presenta sin filtro por carrera.")
            alcance = "UDL completa"
        carrera_filtro = None if alcance == "UDL completa" else alcance
    else:
        carrera_filtro = carrera_seleccionada if carrera_col else None

    df = filtrar_por_carrera(df_base, hoja, carrera_filtro if carrera_filtro else "UDL completa")

    # KPIs permitidos
    total_respuestas = int(df.shape[0])

    all_cols = []
    for _, (a, b) in SECCIONES_POR_HOJA[hoja].items():
        all_cols.extend(columnas_por_rango(df, a, b))
    prom_general, _nvalid = mean_ponderado_por_respuestas(df, all_cols)

    c1, c2 = st.columns(2)
    c1.metric("Total de respuestas", total_respuestas)
    c2.metric("Promedio general (0–5)", None if np.isnan(prom_general) else round(prom_general, 3))

    st.divider()

    # 3) Promedio por sección
    st.subheader("Promedio por sección")
    df_sec = promedios_por_seccion(df, hoja)
    st.dataframe(
        df_sec,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sección": st.column_config.TextColumn("Sección"),
            "Promedio": st.column_config.NumberColumn("Promedio (0–5)", format="%.3f"),
            "Respuestas válidas": st.column_config.NumberColumn("Respuestas válidas"),
        },
    )
    chart_barras_seccion(df_sec, "Promedio por sección (0–5)")

    # 4) Drill-down obligatorio
    st.subheader("Selecciona la sección evaluada")

    # Lista solo secciones que tengan al menos 1 reactivo con válidas > 0
    secciones_validas = []
    for sec in SECCIONES_POR_HOJA[hoja].keys():
        tmp = detalle_por_reactivo(df, hoja, sec)
        if not tmp.empty:
            secciones_validas.append(sec)

    if not secciones_validas:
        st.info("No hay secciones con respuestas válidas para el filtro actual.")
        st.divider()
        return

    seccion_sel = st.selectbox("Sección", secciones_validas, index=0)

    df_det = detalle_por_reactivo(df, hoja, seccion_sel)

    if df_det.empty:
        st.info("No hay reactivos con respuestas válidas en esta sección para el filtro actual.")
        st.divider()
        return

    st.dataframe(
        df_det,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Reactivo": st.column_config.TextColumn("Reactivo (texto completo)", width="large"),
            "Promedio": st.column_config.NumberColumn("Promedio (0–5)", format="%.3f"),
            "Respuestas válidas": st.column_config.NumberColumn("Respuestas válidas"),
        },
    )
    chart_barras_reactivos(df_det, f"Promedio por reactivo | {seccion_sel}")

    st.divider()

    # 5) Comentarios y Log (solo DG/DA)
    if vista in ("Dirección General", "Dirección Académica"):
        st.subheader("Comentarios")
        if df_com.empty:
            st.info("No hay datos en la hoja Comentarios.")
        else:
            dfc = df_com.copy()
            if carrera_filtro and carrera_col and carrera_col in dfc.columns:
                dfc = dfc[dfc[carrera_col].astype(str).str.strip() == str(carrera_filtro).strip()].copy()
            st.dataframe(dfc, use_container_width=True, hide_index=True)

        st.subheader("Log de conversión (diagnóstico)")
        if df_log.empty:
            st.info("No hay datos en la hoja Log_conversion.")
        else:
            dfl = df_log.copy()
            if carrera_filtro and carrera_col and carrera_col in dfl.columns:
                dfl = dfl[dfl[carrera_col].astype(str).str.strip() == str(carrera_filtro).strip()].copy()
            st.dataframe(dfl, use_container_width=True, hide_index=True)

    st.caption("Restricciones aplicadas: sin 'mejor/peor', sin rankings valorativos y sin lenguaje valorativo.")
