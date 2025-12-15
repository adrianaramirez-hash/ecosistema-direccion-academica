import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials
import altair as alt

# ============================================================
# CONFIG
# ============================================================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# >>> PROCESADO (destino) <<<
SPREADSHEET_PROCESADO_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1zwa-cG8Bwn6IA0VBrW_gsIb-bB92nTpa2H5sS4LVvak/edit"
)

# Hojas en PROCESADO
SHEET_VIRTUAL = "Virtual_num"
SHEET_ESCOLAR = "Escolar_num"
SHEET_PREPA = "Prepa_num"
SHEET_RES_FORM = "Resumen_formularios"
SHEET_RES_SEC = "Resumen_secciones"
SHEET_COMENT = "Comentarios"
SHEET_LOG = "Log_conversion"

COLUMNA_TIMESTAMP = "Marca temporal"
COLUMNA_CARRERA = "Carrera de procedencia"

# ============================================================
# SECCIONES (rangos Excel, tal como los definiste)
# ============================================================
SECCIONES_POR_MODALIDAD = {
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
        "Instalaciones / equipo tecnológico": ("AN", "AX"),
        "Ambiente escolar": ("AY", "BE"),
    },
    "prepa": {
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
def _norm(x) -> str:
    return "" if x is None else str(x).strip().lower()

def excel_col_to_index(col: str) -> int:
    col = col.strip().upper()
    n = 0
    for ch in col:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1

def cols_por_rango(df: pd.DataFrame, a: str, b: str) -> list[str]:
    i = excel_col_to_index(a)
    j = excel_col_to_index(b)
    if i > j:
        i, j = j, i
    cols = list(df.columns)
    i = max(i, 0)
    j = min(j, len(cols) - 1)
    return cols[i : j + 1]

def leer_hoja_a_dataframe(sh, nombre_hoja: str) -> pd.DataFrame:
    """
    Lee una hoja con get_all_values y vuelve headers únicos.
    """
    try:
        ws = sh.worksheet(nombre_hoja)
    except Exception:
        return pd.DataFrame()

    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame()

    header = values[0]
    data = values[1:]

    counts = {}
    header_unique = []
    for h in header:
        base = h if h != "" else "columna_sin_nombre"
        if base not in counts:
            counts[base] = 1
            header_unique.append(base)
        else:
            counts[base] += 1
            header_unique.append(f"{base}_{counts[base]}")

    df = pd.DataFrame(data, columns=[c.strip() for c in header_unique])
    return df

def asegurar_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """
    En PROCESADO, 'Marca temporal' se guardó como string.
    Lo convertimos a datetime para filtros.
    """
    if df.empty:
        return df
    if COLUMNA_TIMESTAMP in df.columns:
        df[COLUMNA_TIMESTAMP] = pd.to_datetime(df[COLUMNA_TIMESTAMP], errors="coerce")
    return df

def detectar_modalidad_por_tab(tab_name: str) -> str:
    t = _norm(tab_name)
    if "virtual" in t:
        return "virtual"
    if "escolar" in t:
        return "escolar"
    if "prepa" in t:
        return "prepa"
    return "desconocida"

def columnas_numericas_en_secciones(df: pd.DataFrame, modalidad: str) -> list[str]:
    """
    Devuelve columnas numéricas dentro de los rangos definidos por sección.
    """
    if df.empty:
        return []
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    num_cols = []
    for _, (a, b) in secciones.items():
        cols = cols_por_rango(df, a, b)
        for c in cols:
            if c in df.columns:
                # intentamos a numeric (muchas columnas vienen como str desde Sheets)
                s = pd.to_numeric(df[c], errors="coerce")
                if s.notna().sum() > 0:
                    num_cols.append(c)
    return list(dict.fromkeys(num_cols))

def promedio_global(df: pd.DataFrame, modalidad: str) -> float | None:
    if df.empty:
        return None
    num_cols = columnas_numericas_en_secciones(df, modalidad)
    if not num_cols:
        return None
    tmp = df.copy()
    for c in num_cols:
        tmp[c] = pd.to_numeric(tmp[c], errors="coerce")
    return float(tmp[num_cols].mean(axis=1).mean())

def promedios_por_seccion(df: pd.DataFrame, modalidad: str) -> pd.DataFrame:
    """
    Calcula promedio por sección usando los rangos definidos.
    Robusto: si una sección no tiene columnas numéricas válidas -> Promedio = NaN.
    """
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    rows = []
    if df.empty:
        return pd.DataFrame(columns=["Sección", "Promedio", "Reactivos_usados"])

    for sec, (a, b) in secciones.items():
        cols = cols_por_rango(df, a, b)
        cols_ok = []
        tmp = df.copy()
        for c in cols:
            if c in tmp.columns:
                tmp[c] = pd.to_numeric(tmp[c], errors="coerce")
                if tmp[c].notna().sum() > 0:
                    cols_ok.append(c)

        if cols_ok:
            val = float(tmp[cols_ok].mean(axis=1).mean())
        else:
            val = None

        rows.append({"Sección": sec, "Promedio": val, "Reactivos_usados": len(cols_ok)})

    out = pd.DataFrame(rows)
    return out

def grafica_barras_secciones(df_sec: pd.DataFrame, titulo: str):
    df_plot = df_sec.dropna(subset=["Promedio"]).copy()
    if df_plot.empty:
        st.info("No hay promedios numéricos suficientes para graficar secciones.")
        return

    chart = (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X("Sección:N", sort="-y", title="Sección"),
            y=alt.Y("Promedio:Q", title="Promedio"),
            tooltip=["Sección", "Promedio", "Reactivos_usados"],
        )
        .properties(height=320, title=titulo)
    )
    st.altair_chart(chart, use_container_width=True)

def grafica_distribucion_carrera(df: pd.DataFrame, titulo: str):
    if df.empty or COLUMNA_CARRERA not in df.columns:
        return

    serie = df[COLUMNA_CARRERA].fillna("Sin carrera").astype(str)
    df_c = serie.value_counts().reset_index()
    df_c.columns = ["Carrera", "Respuestas"]

    if df_c.empty:
        return

    chart = (
        alt.Chart(df_c)
        .mark_bar()
        .encode(
            x=alt.X("Carrera:N", sort="-y", title="Carrera"),
            y=alt.Y("Respuestas:Q", title="Respuestas"),
            tooltip=["Carrera", "Respuestas"],
        )
        .properties(height=320, title=titulo)
    )
    st.altair_chart(chart, use_container_width=True)
    st.dataframe(df_c, use_container_width=True)

# ============================================================
# CARGA DE DATOS (PROCESADO)
# ============================================================
@st.cache_data(ttl=120)
def cargar_procesado():
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_PROCESADO_URL)

    df_v = leer_hoja_a_dataframe(sh, SHEET_VIRTUAL)
    df_e = leer_hoja_a_dataframe(sh, SHEET_ESCOLAR)
    df_p = leer_hoja_a_dataframe(sh, SHEET_PREPA)

    df_rf = leer_hoja_a_dataframe(sh, SHEET_RES_FORM)
    df_rs = leer_hoja_a_dataframe(sh, SHEET_RES_SEC)

    df_com = leer_hoja_a_dataframe(sh, SHEET_COMENT)
    df_log = leer_hoja_a_dataframe(sh, SHEET_LOG)

    # normalizar fechas
    df_v = asegurar_datetime(df_v)
    df_e = asegurar_datetime(df_e)
    df_p = asegurar_datetime(df_p)

    return df_v, df_e, df_p, df_rf, df_rs, df_com, df_log

# ============================================================
# UI: TAB POR MODALIDAD
# ============================================================
def render_tab_modalidad(vista: str, carrera: str | None, modalidad: str, df: pd.DataFrame):
    st.subheader(f"Resultados – {modalidad.capitalize()}")

    if df.empty:
        st.warning("No hay datos en el PROCESADO para esta modalidad.")
        return

    # Filtro por carrera para Directores
    df_fil = df.copy()
    if vista == "Director de carrera" and carrera and COLUMNA_CARRERA in df_fil.columns:
        df_fil = df_fil[df_fil[COLUMNA_CARRERA].astype(str) == str(carrera)]

    # KPI
    total = len(df_fil)
    prom = promedio_global(df_fil, modalidad)

    c1, c2 = st.columns(2)
    c1.metric("Respuestas", total)
    c2.metric("Promedio general (0–5)", f"{prom:.2f}" if prom is not None else "N/D")

    if total == 0:
        st.warning("No hay respuestas para el filtro actual.")
        return

    st.markdown("---")

    # Promedios por sección
    df_sec = promedios_por_seccion(df_fil, modalidad)
    st.subheader("Promedio por sección")
    st.dataframe(df_sec, use_container_width=True)
    grafica_barras_secciones(df_sec, f"Promedio por sección – {modalidad.capitalize()}")

    st.markdown("---")

    # Distribución por carrera (solo DG/DA; a directores no les aporta)
    if vista in ("Dirección General", "Dirección Académica"):
        st.subheader("Distribución de respuestas por carrera")
        grafica_distribucion_carrera(df_fil, f"Distribución por carrera – {modalidad.capitalize()}")

    # Comentarios (si existen en df)
    # En tu PROCESADO, los comentarios se guardan en la hoja Comentarios, no aquí.
    st.caption("Nota: Los comentarios cualitativos se consultan en la pestaña 'Comentarios' del archivo PROCESADO.")

# ============================================================
# UI: TAB INSTITUCIONAL
# ============================================================
def render_tab_institucional(vista: str, carrera: str | None, df_v, df_e, df_p, df_rf, df_rs, df_com):
    st.subheader("Institucional UDL (todas las modalidades)")

    # Unir para visión global
    df_all = pd.concat([df_v, df_e, df_p], ignore_index=True)

    # Para directores, filtramos por carrera si existe la columna
    if vista == "Director de carrera" and carrera and COLUMNA_CARRERA in df_all.columns:
        df_all = df_all[df_all[COLUMNA_CARRERA].astype(str) == str(carrera)]

    total = len(df_all)

    # Promedio institucional: promedio de promedios ponderado por filas de cada modalidad filtrada
    prom_v = promedio_global(df_v if vista != "Director de carrera" else df_v[df_v.get(COLUMNA_CARRERA, "").astype(str) == str(carrera)] if (carrera and COLUMNA_CARRERA in df_v.columns) else df_v, "virtual")
    prom_e = promedio_global(df_e if vista != "Director de carrera" else df_e[df_e.get(COLUMNA_CARRERA, "").astype(str) == str(carrera)] if (carrera and COLUMNA_CARRERA in df_e.columns) else df_e, "escolar")
    prom_p = promedio_global(df_p if vista != "Director de carrera" else df_p[df_p.get(COLUMNA_CARRERA, "").astype(str) == str(carrera)] if (carrera and COLUMNA_CARRERA in df_p.columns) else df_p, "prepa")

    # Ponderación por número de filas con el filtro aplicado
    n_v = len(df_v if vista != "Director de carrera" else df_all[df_all.get("Modalidad", "").astype(str) == "virtual"])
    n_e = len(df_e if vista != "Director de carrera" else df_all[df_all.get("Modalidad", "").astype(str) == "escolar"])
    n_p = len(df_p if vista != "Director de carrera" else df_all[df_all.get("Modalidad", "").astype(str) == "prepa"])

    numer = 0.0
    denom = 0
    for p, n in [(prom_v, n_v), (prom_e, n_e), (prom_p, n_p)]:
        if p is not None and n > 0:
            numer += p * n
            denom += n
    prom_inst = (numer / denom) if denom > 0 else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Respuestas totales", total)
    c2.metric("Promedio institucional (0–5)", f"{prom_inst:.2f}" if prom_inst is not None else "N/D")
    c3.metric("Modalidades incluidas", "Virtual + Escolar + Prepa")

    st.markdown("---")

    # Resumen por formularios (si existe tabla precomputada)
    st.subheader("Resumen por modalidad")
    if not df_rf.empty and all(c in df_rf.columns for c in ["Formulario", "Respuestas", "Promedio"]):
        st.dataframe(df_rf, use_container_width=True)
    else:
        st.info("No se encontró 'Resumen_formularios' con columnas esperadas (Formulario/Respuestas/Promedio).")

    st.markdown("---")

    # Promedio institucional por sección (usamos Resumen_secciones como base)
    st.subheader("Promedio UDL por sección (por modalidad)")
    if not df_rs.empty and all(c in df_rs.columns for c in ["Modalidad", "Sección", "Promedio"]):
        # Asegurar num
        df_rs2 = df_rs.copy()
        df_rs2["Promedio"] = pd.to_numeric(df_rs2["Promedio"], errors="coerce")

        st.dataframe(df_rs2, use_container_width=True)

        # Gráfica comparativa por modalidad
        df_plot = df_rs2.dropna(subset=["Promedio"]).copy()
        if not df_plot.empty:
            chart = (
                alt.Chart(df_plot)
                .mark_bar()
                .encode(
                    x=alt.X("Sección:N", sort="-y"),
                    y=alt.Y("Promedio:Q"),
                    color="Modalidad:N",
                    tooltip=["Modalidad", "Sección", "Promedio"],
                )
                .properties(height=360, title="Promedio por sección y modalidad")
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No hay promedios por sección suficientes para graficar.")
    else:
        st.info("No se encontró 'Resumen_secciones' con columnas esperadas (Modalidad/Sección/Promedio).")

    st.markdown("---")

    # Distribución por carrera (DG/DA)
    if vista in ("Dirección General", "Dirección Académica"):
        st.subheader("Distribución total por carrera (todas las modalidades)")
        grafica_distribucion_carrera(df_all, "Distribución por carrera – Institucional")

    # Comentarios
    st.markdown("---")
    st.subheader("Comentarios cualitativos (muestra)")
    if df_com.empty:
        st.info("No hay comentarios en la hoja Comentarios.")
    else:
        st.dataframe(df_com.head(200), use_container_width=True)
        st.caption("Mostrando los primeros 200 registros. El total está en el archivo PROCESADO.")

# ============================================================
# ENTRADA PRINCIPAL
# ============================================================
def render_encuesta_calidad(vista: str, carrera_seleccionada: str | None):
    st.header("Encuesta de calidad – Resultados (desde PROCESADO)")

    df_v, df_e, df_p, df_rf, df_rs, df_com, df_log = cargar_procesado()

    # Tabs
    tabs = st.tabs(["Institucional UDL", "Virtual", "Escolar", "Prepa", "Log (diagnóstico)"])

    with tabs[0]:
        render_tab_institucional(vista, carrera_seleccionada, df_v, df_e, df_p, df_rf, df_rs, df_com)

    with tabs[1]:
        render_tab_modalidad(vista, carrera_seleccionada, "virtual", df_v)

    with tabs[2]:
        render_tab_modalidad(vista, carrera_seleccionada, "escolar", df_e)

    with tabs[3]:
        render_tab_modalidad(vista, carrera_seleccionada, "prepa", df_p)

    with tabs[4]:
        st.subheader("Log de conversión (textos no reconocidos)")
        st.caption(
            "Esta pestaña sirve para afinar el diccionario de conversión texto→número. "
            "Si ves muchos valores aquí, significa que las opciones del formulario vienen con textos distintos."
        )
        if df_log.empty:
            st.success("Sin registros en Log_conversion.")
        else:
            st.dataframe(df_log, use_container_width=True)
