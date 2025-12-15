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

SPREADSHEET_PROCESADO_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1zwa-cG8Bwn6IA0VBrW_gsIb-bB92nTpa2H5sS4LVvak/edit"
)

SHEET_VIRTUAL = "Virtual_num"
SHEET_ESCOLAR = "Escolar_num"
SHEET_PREPA = "Prepa_num"
SHEET_COMENT = "Comentarios"
SHEET_LOG = "Log_conversion"

COLUMNA_TIMESTAMP = "Marca temporal"
COLUMNA_CARRERA = "Carrera de procedencia"

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

    return pd.DataFrame(data, columns=[c.strip() for c in header_unique])

def asegurar_datetime(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if COLUMNA_TIMESTAMP in df.columns:
        df[COLUMNA_TIMESTAMP] = pd.to_datetime(df[COLUMNA_TIMESTAMP], errors="coerce")
    return df

def aplicar_filtro_carrera(df: pd.DataFrame, carrera: str | None) -> pd.DataFrame:
    if df.empty or not carrera:
        return df
    if COLUMNA_CARRERA not in df.columns:
        # si no existe columna de carrera, devolvemos vacío para evitar mezclar
        return df.iloc[0:0]
    return df[df[COLUMNA_CARRERA].astype(str) == str(carrera)]

def columnas_numericas_en_secciones(df: pd.DataFrame, modalidad: str) -> list[str]:
    if df.empty:
        return []
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    num_cols = []
    for _, (a, b) in secciones.items():
        for c in cols_por_rango(df, a, b):
            if c in df.columns:
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
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    rows = []
    if df.empty:
        return pd.DataFrame(columns=["Sección", "Respuestas", "Promedio_UDL", "Reactivos_usados"])

    for sec, (a, b) in secciones.items():
        cols = cols_por_rango(df, a, b)
        tmp = df.copy()

        cols_ok = []
        for c in cols:
            if c in tmp.columns:
                tmp[c] = pd.to_numeric(tmp[c], errors="coerce")
                if tmp[c].notna().sum() > 0:
                    cols_ok.append(c)

        prom = float(tmp[cols_ok].mean(axis=1).mean()) if cols_ok else None

        rows.append({
            "Sección": sec,
            "Respuestas": int(len(df)),
            "Promedio_UDL": prom,
            "Reactivos_usados": int(len(cols_ok)),
        })

    return pd.DataFrame(rows)

def grafica_barras_secciones(df_sec: pd.DataFrame, titulo: str):
    df_plot = df_sec.dropna(subset=["Promedio_UDL"]).copy()
    if df_plot.empty:
        st.info("No hay promedios numéricos suficientes para graficar secciones.")
        return

    chart = (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X("Sección:N", sort="-y", title="Sección"),
            y=alt.Y("Promedio_UDL:Q", title="Promedio (0–5)"),
            tooltip=["Sección", "Promedio_UDL", "Reactivos_usados", "Respuestas"],
        )
        .properties(height=340, title=titulo)
    )
    st.altair_chart(chart, use_container_width=True)

def grafica_distribucion_carrera(df: pd.DataFrame, titulo: str):
    if df.empty or COLUMNA_CARRERA not in df.columns:
        return

    serie = df[COLUMNA_CARRERA].fillna("Sin carrera").astype(str)
    df_c = serie.value_counts().reset_index()
    df_c.columns = ["Carrera", "Respuestas"]

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

def promedio_ponderado(pares_prom_n):
    numer, denom = 0.0, 0
    for p, n in pares_prom_n:
        if p is not None and n > 0:
            numer += p * n
            denom += n
    return (numer / denom) if denom > 0 else None

# ============================================================
# CARGA DE DATOS
# ============================================================
@st.cache_data(ttl=120)
def cargar_procesado():
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_PROCESADO_URL)

    df_v = asegurar_datetime(leer_hoja_a_dataframe(sh, SHEET_VIRTUAL))
    df_e = asegurar_datetime(leer_hoja_a_dataframe(sh, SHEET_ESCOLAR))
    df_p = asegurar_datetime(leer_hoja_a_dataframe(sh, SHEET_PREPA))
    df_com = leer_hoja_a_dataframe(sh, SHEET_COMENT)
    df_log = leer_hoja_a_dataframe(sh, SHEET_LOG)

    return df_v, df_e, df_p, df_com, df_log

# ============================================================
# TAB MODALIDAD
# ============================================================
def render_tab_modalidad(modalidad: str, df: pd.DataFrame):
    st.subheader(f"{modalidad.capitalize()}")

    if df.empty:
        st.warning("No hay datos para esta modalidad con el filtro actual.")
        return

    total = int(len(df))
    prom = promedio_global(df, modalidad)

    c1, c2 = st.columns(2)
    c1.metric("Respuestas", total)
    c2.metric("Promedio general (0–5)", f"{prom:.2f}" if prom is not None else "N/D")

    st.markdown("---")
    st.subheader("Promedio por sección")
    df_sec = promedios_por_seccion(df, modalidad)
    st.dataframe(df_sec, use_container_width=True)
    grafica_barras_secciones(df_sec, f"Promedio por sección – {modalidad.capitalize()}")

# ============================================================
# INSTITUCIONAL (DG/DA): por modalidad + (opcional) filtrado por carrera
# ============================================================
def render_institucional_por_modalidad(df_v, df_e, df_p, df_com, mostrar_distribucion: bool):
    st.subheader("Institucional – Comparativo por modalidad")

    n_v, n_e, n_p = int(len(df_v)), int(len(df_e)), int(len(df_p))
    p_v = promedio_global(df_v, "virtual")
    p_e = promedio_global(df_e, "escolar")
    p_p = promedio_global(df_p, "prepa")

    prom_inst = promedio_ponderado([(p_v, n_v), (p_e, n_e), (p_p, n_p)])

    c1, c2 = st.columns(2)
    c1.metric("Respuestas totales", n_v + n_e + n_p)
    c2.metric("Promedio general (0–5)", f"{prom_inst:.2f}" if prom_inst is not None else "N/D")

    st.markdown("---")
    st.subheader("Resumen por modalidad")
    st.dataframe(pd.DataFrame([
        {"Modalidad": "virtual", "Respuestas": n_v, "Promedio_general": p_v},
        {"Modalidad": "escolar", "Respuestas": n_e, "Promedio_general": p_e},
        {"Modalidad": "prepa", "Respuestas": n_p, "Promedio_general": p_p},
    ]), use_container_width=True)

    st.markdown("---")
    st.subheader("Promedio por sección (comparativo por modalidad)")
    sec_v = promedios_por_seccion(df_v, "virtual"); sec_v["Modalidad"] = "virtual"
    sec_e = promedios_por_seccion(df_e, "escolar"); sec_e["Modalidad"] = "escolar"
    sec_p = promedios_por_seccion(df_p, "prepa");   sec_p["Modalidad"] = "prepa"

    df_sec_all = pd.concat([sec_v, sec_e, sec_p], ignore_index=True)
    df_sec_all["Promedio_UDL"] = pd.to_numeric(df_sec_all["Promedio_UDL"], errors="coerce")
    st.dataframe(df_sec_all, use_container_width=True)

    df_plot = df_sec_all.dropna(subset=["Promedio_UDL"]).copy()
    if not df_plot.empty:
        chart = (
            alt.Chart(df_plot)
            .mark_bar()
            .encode(
                x=alt.X("Sección:N", sort="-y"),
                y=alt.Y("Promedio_UDL:Q", title="Promedio (0–5)"),
                color="Modalidad:N",
                tooltip=["Modalidad", "Sección", "Promedio_UDL", "Reactivos_usados", "Respuestas"],
            )
            .properties(height=380, title="Promedio por sección y modalidad")
        )
        st.altair_chart(chart, use_container_width=True)

    if mostrar_distribucion:
        st.markdown("---")
        st.subheader("Distribución de respuestas por carrera (solo UDL completo)")
        # Solo tiene sentido cuando NO se filtró por una sola carrera
        df_all = pd.concat([df_v, df_e, df_p], ignore_index=True)
        grafica_distribucion_carrera(df_all, "Distribución por carrera – Todas las modalidades")

    st.markdown("---")
    st.subheader("Comentarios (muestra)")
    if df_com.empty:
        st.info("No hay comentarios para el filtro actual.")
    else:
        st.dataframe(df_com.head(200), use_container_width=True)

# ============================================================
# RESUMEN DIRECTOR (solo su carrera)
# ============================================================
def render_resumen_director(carrera: str, df_v, df_e, df_p):
    st.subheader(f"Resumen – {carrera}")

    fv = aplicar_filtro_carrera(df_v, carrera)
    fe = aplicar_filtro_carrera(df_e, carrera)
    fp = aplicar_filtro_carrera(df_p, carrera)

    n_v, n_e, n_p = len(fv), len(fe), len(fp)
    p_v = promedio_global(fv, "virtual")
    p_e = promedio_global(fe, "escolar")
    p_p = promedio_global(fp, "prepa")

    prom_total = promedio_ponderado([(p_v, n_v), (p_e, n_e), (p_p, n_p)])

    c1, c2 = st.columns(2)
    c1.metric("Respuestas totales (tu carrera)", n_v + n_e + n_p)
    c2.metric("Promedio general (0–5)", f"{prom_total:.2f}" if prom_total is not None else "N/D")

    st.markdown("---")
    st.subheader("Desglose por modalidad")
    st.dataframe(pd.DataFrame([
        {"Modalidad": "virtual", "Respuestas": n_v, "Promedio_general": p_v},
        {"Modalidad": "escolar", "Respuestas": n_e, "Promedio_general": p_e},
        {"Modalidad": "prepa", "Respuestas": n_p, "Promedio_general": p_p},
    ]), use_container_width=True)

# ============================================================
# ENTRADA PRINCIPAL
# ============================================================
def render_encuesta_calidad(vista: str, carrera_seleccionada: str | None):
    st.header("Encuesta de calidad – Resultados")

    df_v, df_e, df_p, df_com, df_log = cargar_procesado()

    # =========================
    # DIRECTOR
    # =========================
    if vista == "Director de carrera":
        if not carrera_seleccionada:
            st.warning("Selecciona una carrera para ver tus resultados.")
            return

        fv = aplicar_filtro_carrera(df_v, carrera_seleccionada)
        fe = aplicar_filtro_carrera(df_e, carrera_seleccionada)
        fp = aplicar_filtro_carrera(df_p, carrera_seleccionada)

        tabs = st.tabs(["Resumen (tu carrera)", "Virtual", "Escolar", "Prepa"])

        with tabs[0]:
            render_resumen_director(carrera_seleccionada, df_v, df_e, df_p)

        with tabs[1]:
            render_tab_modalidad("virtual", fv)

        with tabs[2]:
            render_tab_modalidad("escolar", fe)

        with tabs[3]:
            render_tab_modalidad("prepa", fp)

        return

    # =========================
    # DG / DA
    # =========================
    st.subheader("Filtros (DG/DA)")

    # catálogo de carreras basado en datos reales (si existe columna)
    df_all = pd.concat([df_v, df_e, df_p], ignore_index=True)
    carreras_data = []
    if COLUMNA_CARRERA in df_all.columns:
        carreras_data = sorted([c for c in df_all[COLUMNA_CARRERA].dropna().astype(str).unique().tolist() if c.strip()])

    alcance = st.radio(
        "Alcance de análisis:",
        ["UDL (todas las carreras)", "Una carrera específica"],
        horizontal=True,
    )

    carrera_filtro = None
    if alcance == "Una carrera específica":
        if not carreras_data:
            st.warning("No se encontró columna de carrera en los datos para filtrar.")
        else:
            carrera_filtro = st.selectbox("Selecciona la carrera a analizar:", carreras_data)

    # aplicar filtro (si procede) a DFs
    df_v2 = aplicar_filtro_carrera(df_v, carrera_filtro) if carrera_filtro else df_v
    df_e2 = aplicar_filtro_carrera(df_e, carrera_filtro) if carrera_filtro else df_e
    df_p2 = aplicar_filtro_carrera(df_p, carrera_filtro) if carrera_filtro else df_p

    # comentarios también deben filtrarse si estamos en carrera específica
    df_com2 = df_com
    if carrera_filtro and (COLUMNA_CARRERA in df_com2.columns):
        df_com2 = df_com2[df_com2[COLUMNA_CARRERA].astype(str) == str(carrera_filtro)]

    st.markdown("---")

    tabs = st.tabs([
        "Institucional (por modalidad)",
        "Virtual",
        "Escolar",
        "Prepa",
        "Log (diagnóstico)"
    ])

    with tabs[0]:
        # Distribución por carrera solo cuando estamos en UDL completo
        mostrar_distribucion = (alcance == "UDL (todas las carreras)")
        render_institucional_por_modalidad(df_v2, df_e2, df_p2, df_com2, mostrar_distribucion)

    with tabs[1]:
        render_tab_modalidad("virtual", df_v2)

    with tabs[2]:
        render_tab_modalidad("escolar", df_e2)

    with tabs[3]:
        render_tab_modalidad("prepa", df_p2)

    with tabs[4]:
        st.subheader("Log de conversión (textos no reconocidos)")
        if df_log.empty:
            st.success("Sin registros en Log_conversion.")
        else:
            st.dataframe(df_log, use_container_width=True)
