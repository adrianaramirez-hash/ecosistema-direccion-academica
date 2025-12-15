import streamlit as st
import pandas as pd
import gspread
import json
import re
from google.oauth2.service_account import Credentials
import altair as alt

# ============================================================
# CONFIG
# ============================================================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)

# Nombres “esperados” (la búsqueda flexible ya los resuelve aunque cambien mayúsculas)
HOJA_VIRTUAL = "servicios virtual y mixto virtual"
HOJA_ESCOLAR = "servicios escolarizados y licenciaturas ejecutivas"
HOJA_PREPA = "Preparatoria"
HOJA_APLIC = "Aplicaciones"

COLUMNA_CARRERA = "Carrera de procedencia"
COLUMNA_TIMESTAMP = "Marca temporal"

# ============================================================
# DICCIONARIOS DE SECCIONES (RANGOS EXCEL)
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
# UTILIDADES: NORMALIZACIÓN / HOJAS FLEXIBLES
# ============================================================
def _norm(txt: str) -> str:
    if txt is None:
        return ""
    return str(txt).strip().lower()

def _limpiar_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    return df

def _buscar_hoja_flexible(sh, nombre_hoja: str):
    objetivo = _norm(nombre_hoja)
    hojas = sh.worksheets()

    # exacta normalizada
    for ws in hojas:
        if _norm(ws.title) == objetivo:
            return ws

    # contiene
    for ws in hojas:
        if objetivo in _norm(ws.title):
            return ws

    return None

def leer_hoja_a_dataframe(sh, nombre_hoja: str) -> pd.DataFrame:
    try:
        ws = sh.worksheet(nombre_hoja)
    except Exception:
        ws = _buscar_hoja_flexible(sh, nombre_hoja)
        if ws is None:
            st.error(f"No se encontró la hoja '{nombre_hoja}' (ni coincidencia aproximada).")
            try:
                st.info("Hojas disponibles: " + ", ".join([w.title for w in sh.worksheets()]))
            except Exception:
                pass
            return pd.DataFrame()

    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame()

    header = values[0]
    data = values[1:]

    # encabezados únicos
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

    df = pd.DataFrame(data, columns=header_unique)
    df = _limpiar_cols(df)
    return df

# ============================================================
# UTILIDADES: EXCEL COL -> ÍNDICE
# ============================================================
def excel_col_to_index(col: str) -> int:
    """
    A -> 0, B -> 1, ..., Z -> 25, AA -> 26, AB -> 27, ...
    """
    col = col.strip().upper()
    n = 0
    for ch in col:
        if not ("A" <= ch <= "Z"):
            continue
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1

def indices_para_rango_excel(start_col: str, end_col: str) -> tuple[int, int]:
    i = excel_col_to_index(start_col)
    j = excel_col_to_index(end_col)
    if i > j:
        i, j = j, i
    return i, j

# ============================================================
# CONVERSIÓN TEXTO -> NÚMERO (0–5 o 1–5)
# ============================================================
COMENTARIOS_HINTS = [
    "¿por qué", "por qué", "porque", "por que",
    "coment", "suger", "observ", "explica", "describe", "motivo",
]

MAPA_TEXTO_A_NUM = {
    # 0–5 (desempeño)
    "no lo utilizo": 0,
    "no lo uso": 0,
    "n/a": None,
    "na": None,
    "no aplica": None,

    "muy malo": 1,
    "malo": 2,
    "regular": 3,
    "bueno": 4,
    "excelente": 5,

    # variantes comunes de satisfacción
    "muy insatisfecho": 1,
    "insatisfecho": 2,
    "neutral": 3,
    "satisfecho": 4,
    "muy satisfecho": 5,

    # si en recomendación usan sí/no
    "sí": 5,
    "si": 5,
    "no": 1,
}

DIGIT_RE = re.compile(r"^\s*([0-5])\s*$")
LEADING_DIGIT_RE = re.compile(r"^\s*([0-5])\s*[-–—\.]\s*.*$")  # "5 - Excelente"

def es_columna_comentario(nombre_col: str) -> bool:
    t = _norm(nombre_col)
    return any(h in t for h in COMENTARIOS_HINTS)

def convertir_serie_a_numerica(s: pd.Series) -> pd.Series:
    """
    Convierte respuestas tipo:
    - "Excelente", "Bueno", "Regular", ...
    - "5", "4", ...
    - "5 - Excelente"
    - "No aplica" -> NaN
    """
    s2 = s.astype(str).str.strip()
    out = []

    for v in s2.tolist():
        t = _norm(v)

        if t in ("", "nan", "none"):
            out.append(None)
            continue

        # número directo 0–5
        m = DIGIT_RE.match(t)
        if m:
            out.append(float(m.group(1)))
            continue

        # "5 - Excelente"
        m2 = LEADING_DIGIT_RE.match(t)
        if m2:
            out.append(float(m2.group(1)))
            continue

        # diccionario literal
        if t in MAPA_TEXTO_A_NUM:
            out.append(MAPA_TEXTO_A_NUM[t])
            continue

        # si no lo reconozco, lo dejo como None (para no contaminar promedio)
        out.append(None)

    return pd.to_numeric(pd.Series(out), errors="coerce")

def normalizar_df_respuestas(df: pd.DataFrame, modalidad: str) -> pd.DataFrame:
    if df.empty:
        return df

    # timestamp
    if COLUMNA_TIMESTAMP in df.columns:
        df[COLUMNA_TIMESTAMP] = pd.to_datetime(df[COLUMNA_TIMESTAMP], dayfirst=True, errors="coerce")

    # agrega modalidad
    df["Modalidad"] = modalidad

    # intenta convertir a numérico todas las columnas que NO sean claramente comentarios/metadatos
    for col in df.columns:
        if col in ("Modalidad",):
            continue
        if col == COLUMNA_TIMESTAMP:
            continue

        # no convertir columna de carrera/edad/turno/grado, etc. (las dejamos como texto)
        # pero sí convertir reactivos dentro de secciones luego. Aun así, hacemos conversión "segura":
        if es_columna_comentario(col):
            continue

        # conversión “blanda”: si la conversión da pocos valores, no forzarla
        conv = convertir_serie_a_numerica(df[col])
        if conv.notna().sum() > 0:
            # si al menos hay algunos números, guardamos conversión
            df[col] = conv

    return df

# ============================================================
# SECCIONES / MÉTRICAS
# ============================================================
def columnas_por_rango(df: pd.DataFrame, start_col: str, end_col: str) -> list[str]:
    i, j = indices_para_rango_excel(start_col, end_col)
    cols = list(df.columns)
    i = max(i, 0)
    j = min(j, len(cols) - 1)
    return cols[i : j + 1]

def columnas_calificables(df: pd.DataFrame, cols: list[str]) -> list[str]:
    """
    Se queda solo con columnas que:
    - no sean comentarios por encabezado
    - tengan al menos 1 valor numérico (tras conversión)
    """
    out = []
    for c in cols:
        if es_columna_comentario(c):
            continue
        if pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().sum() > 0:
            out.append(c)
    return out

def promedio_global(df: pd.DataFrame, modalidad: str) -> float | None:
    if df.empty:
        return None
    # promedio del promedio por fila, usando SOLO columnas dentro de secciones
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    numeric_cols = []
    for _, (a, b) in secciones.items():
        cols = columnas_por_rango(df, a, b)
        numeric_cols.extend(columnas_calificables(df, cols))
    numeric_cols = list(dict.fromkeys(numeric_cols))  # unique preserving order
    if not numeric_cols:
        return None
    return float(df[numeric_cols].mean(axis=1).mean())

def promedio_por_seccion(df: pd.DataFrame, modalidad: str) -> pd.DataFrame:
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    rows = []
    for sec, (a, b) in secciones.items():
        cols = columnas_por_rango(df, a, b)
        cols = columnas_calificables(df, cols)
        if cols:
            val = float(df[cols].mean(axis=1).mean())
            ncols = len(cols)
        else:
            val = float("nan")
            ncols = 0
        rows.append({"Sección": sec, "Promedio": val, "Reactivos usados": ncols})
    out = pd.DataFrame(rows)
    out = out.sort_values("Promedio", ascending=False, na_position="last")
    return out

def promedio_por_reactivo(df: pd.DataFrame, modalidad: str) -> pd.DataFrame:
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    numeric_cols = []
    for _, (a, b) in secciones.items():
        cols = columnas_por_rango(df, a, b)
        numeric_cols.extend(columnas_calificables(df, cols))
    numeric_cols = list(dict.fromkeys(numeric_cols))
    if not numeric_cols:
        return pd.DataFrame(columns=["Reactivo", "Promedio"])
    return (
        df[numeric_cols]
        .mean()
        .reset_index()
        .rename(columns={"index": "Reactivo", 0: "Promedio"})
        .sort_values("Promedio", ascending=False)
    )

def comentarios_por_formulario(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in df.columns if es_columna_comentario(c)]
    base = [c for c in [COLUMNA_TIMESTAMP, COLUMNA_CARRERA, "Carrera de procedencia", "Carrera de procedencia "] if c in df.columns]
    keep = list(dict.fromkeys(base + cols))
    if not keep:
        return pd.DataFrame()
    return df[keep].copy()

# ============================================================
# APLICACIONES / CORTES
# ============================================================
def normalizar_aplicaciones(df_aplic: pd.DataFrame) -> pd.DataFrame:
    if df_aplic.empty:
        return df_aplic

    for col in ["fecha_inicio", "fecha_fin"]:
        if col in df_aplic.columns:
            df_aplic[col] = pd.to_datetime(df_aplic[col], dayfirst=True, errors="coerce")

    if "descripcion" not in df_aplic.columns:
        if "aplicacion_id" in df_aplic.columns:
            df_aplic["descripcion"] = df_aplic["aplicacion_id"].astype(str)
        else:
            df_aplic["descripcion"] = "Aplicación"

    df_aplic["label"] = df_aplic["descripcion"].astype(str)
    return df_aplic

def aplicar_corte_por_fechas(df: pd.DataFrame, f_ini, f_fin) -> pd.DataFrame:
    if df.empty:
        return df
    if pd.isna(f_ini) or pd.isna(f_fin):
        return df
    if COLUMNA_TIMESTAMP not in df.columns:
        return df

    if f_ini > f_fin:
        f_ini, f_fin = f_fin, f_ini

    f_fin_exclusivo = f_fin + pd.Timedelta(days=1)
    mask = (df[COLUMNA_TIMESTAMP] >= f_ini) & (df[COLUMNA_TIMESTAMP] < f_fin_exclusivo)
    return df.loc[mask].copy()

# ============================================================
# CARGA
# ============================================================
@st.cache_data(ttl=60)
def cargar_datos_calidad():
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_URL)

    df_virtual = leer_hoja_a_dataframe(sh, HOJA_VIRTUAL)
    df_esco = leer_hoja_a_dataframe(sh, HOJA_ESCOLAR)
    df_prepa = leer_hoja_a_dataframe(sh, HOJA_PREPA)
    df_aplic = leer_hoja_a_dataframe(sh, HOJA_APLIC)

    df_aplic = normalizar_aplicaciones(df_aplic)

    df_virtual = normalizar_df_respuestas(df_virtual, "virtual")
    df_esco = normalizar_df_respuestas(df_esco, "escolar")
    df_prepa = normalizar_df_respuestas(df_prepa, "prepa")

    return df_virtual, df_esco, df_prepa, df_aplic

# ============================================================
# RENDER: GRÁFICAS
# ============================================================
def chart_barras_seccion(df_sec: pd.DataFrame, title: str):
    if df_sec.empty:
        st.info("No hay datos por sección para graficar.")
        return
    try:
        c = (
            alt.Chart(df_sec.dropna(subset=["Promedio"]))
            .mark_bar()
            .encode(
                x=alt.X("Sección:N", sort="-y"),
                y=alt.Y("Promedio:Q"),
                tooltip=["Sección", "Promedio", "Reactivos usados"],
            )
            .properties(height=320, title=title)
        )
        st.altair_chart(c, use_container_width=True)
    except Exception as e:
        st.error("No se pudo graficar barras por sección.")
        st.exception(e)

def chart_radar_seccion(df_sec: pd.DataFrame, title: str):
    """
    Radar simple en Altair usando coordenadas polares.
    """
    if df_sec.empty:
        st.info("No hay datos por sección para radar.")
        return
    df_plot = df_sec.dropna(subset=["Promedio"]).copy()
    if df_plot.empty:
        st.info("No hay promedios válidos para radar.")
        return

    try:
        # normaliza en 0–5 para radar
        df_plot["Promedio"] = df_plot["Promedio"].astype(float)

        c = (
            alt.Chart(df_plot)
            .mark_line(point=True)
            .encode(
                theta=alt.Theta("Sección:N", sort=None),
                radius=alt.Radius("Promedio:Q", scale=alt.Scale(zero=True)),
                tooltip=["Sección", "Promedio", "Reactivos usados"],
            )
            .properties(height=380, title=title)
        )
        st.altair_chart(c, use_container_width=True)
    except Exception as e:
        st.error("No se pudo generar radar por sección.")
        st.exception(e)

def chart_reactivos(df_react: pd.DataFrame, title: str):
    if df_react.empty:
        st.info("No hay reactivos numéricos para graficar.")
        return
    try:
        df_plot = df_react.copy()
        c = (
            alt.Chart(df_plot)
            .mark_bar()
            .encode(
                x=alt.X("Reactivo:N", sort="-y"),
                y=alt.Y("Promedio:Q"),
                tooltip=["Reactivo", "Promedio"],
            )
            .properties(height=320, title=title)
        )
        st.altair_chart(c, use_container_width=True)
    except Exception as e:
        st.error("No se pudo graficar por reactivo.")
        st.exception(e)

# ============================================================
# RENDER: BLOQUE POR FORMULARIO (TAB)
# ============================================================
def render_formulario_tab(
    titulo: str,
    modalidad: str,
    df_base: pd.DataFrame,
    vista: str,
    carrera_seleccionada: str | None,
    usar_corte: bool,
    f_ini,
    f_fin,
):
    st.subheader(titulo)

    df = df_base.copy()

    # corte por fechas (si aplica)
    if usar_corte:
        df = aplicar_corte_por_fechas(df, f_ini, f_fin)

    # filtro director por carrera
    if vista == "Director de carrera" and carrera_seleccionada:
        if COLUMNA_CARRERA in df.columns:
            df = df[df[COLUMNA_CARRERA].astype(str).str.strip() == str(carrera_seleccionada).strip()]
        else:
            st.warning("Este formulario no contiene 'Carrera de procedencia'. No se puede filtrar por carrera aquí.")

    n = len(df)

    prom = promedio_global(df, modalidad)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Respuestas", n)
    col2.metric("Promedio general", f"{prom:.2f}" if prom is not None else "N/D")

    # por sección
    df_sec = promedio_por_seccion(df, modalidad)
    if not df_sec.empty and df_sec["Promedio"].notna().any():
        mejor = df_sec.dropna(subset=["Promedio"]).iloc[0]
        peor = df_sec.dropna(subset=["Promedio"]).iloc[-1]
        col3.metric("Mejor sección", f"{mejor['Sección']} ({mejor['Promedio']:.2f})")
        col4.metric("Peor sección", f"{peor['Sección']} ({peor['Promedio']:.2f})")
    else:
        col3.metric("Mejor sección", "N/D")
        col4.metric("Peor sección", "N/D")

    st.divider()

    # Sub-vistas dentro del tab
    sub = st.radio(
        "Vista",
        ["KPIs", "Por sección", "Por reactivo", "Comentarios", "Exportables"],
        horizontal=True,
        key=f"sub_{modalidad}_{vista}",
    )

    if sub == "KPIs":
        st.write("Resumen de la aplicación con métricas básicas y distribución general.")
        # distribución simple por carrera si existe
        if COLUMNA_CARRERA in df.columns:
            serie = df[COLUMNA_CARRERA].fillna("Sin carrera").astype(str)
            df_c = serie.value_counts().reset_index()
            df_c.columns = ["Carrera", "Respuestas"]
            st.dataframe(df_c, use_container_width=True)
            try:
                c = (
                    alt.Chart(df_c)
                    .mark_bar()
                    .encode(x=alt.X("Carrera:N", sort="-y"), y="Respuestas:Q", tooltip=["Carrera", "Respuestas"])
                    .properties(height=320, title="Distribución de respuestas por carrera")
                )
                st.altair_chart(c, use_container_width=True)
            except Exception as e:
                st.error("No se pudo graficar distribución por carrera.")
                st.exception(e)

    elif sub == "Por sección":
        st.dataframe(df_sec, use_container_width=True)
        chart_barras_seccion(df_sec, f"{titulo} – Promedio por sección")
        chart_radar_seccion(df_sec, f"{titulo} – Radar por sección")

    elif sub == "Por reactivo":
        df_r = promedio_por_reactivo(df, modalidad)
        st.dataframe(df_r, use_container_width=True)
        chart_reactivos(df_r, f"{titulo} – Promedio por reactivo")

    elif sub == "Comentarios":
        df_com = comentarios_por_formulario(df)
        if df_com.empty:
            st.info("No se detectaron columnas de comentarios para este formulario.")
        else:
            st.dataframe(df_com, use_container_width=True)

    elif sub == "Exportables":
        st.write("Exporta datos filtrados para análisis externo.")
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Descargar respuestas filtradas (CSV)",
            data=csv,
            file_name=f"encuesta_{modalidad}_filtrada.csv",
            mime="text/csv",
            key=f"dl_{modalidad}_{vista}",
        )
        # export por sección
        csv2 = df_sec.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Descargar promedios por sección (CSV)",
            data=csv2,
            file_name=f"encuesta_{modalidad}_promedios_seccion.csv",
            mime="text/csv",
            key=f"dl_sec_{modalidad}_{vista}",
        )

# ============================================================
# RENDER: INSTITUCIONAL UDL
# ============================================================
def render_institucional_udl(df_virtual, df_esco, df_prepa, vista: str, usar_corte: bool, f_ini, f_fin):
    st.subheader("Institucional UDL")

    # aplica corte (si corresponde) por fechas a cada formulario
    v = aplicar_corte_por_fechas(df_virtual, f_ini, f_fin) if usar_corte else df_virtual.copy()
    e = aplicar_corte_por_fechas(df_esco, f_ini, f_fin) if usar_corte else df_esco.copy()
    p = aplicar_corte_por_fechas(df_prepa, f_ini, f_fin) if usar_corte else df_prepa.copy()

    # total y promedio global institucional: promedio del promedio por respuesta, por modalidad y luego ponderado por respuestas
    def prom_y_n(df, mod):
        return (len(df), promedio_global(df, mod))

    nv, pv = prom_y_n(v, "virtual")
    ne, pe = prom_y_n(e, "escolar")
    np_, pp = prom_y_n(p, "prepa")

    total = nv + ne + np_

    # promedio institucional ponderado
    partes = []
    if pv is not None and nv > 0:
        partes.append((nv, pv))
    if pe is not None and ne > 0:
        partes.append((ne, pe))
    if pp is not None and np_ > 0:
        partes.append((np_, pp))

    if partes:
        prom_inst = sum(n * prom for n, prom in partes) / sum(n for n, _ in partes)
    else:
        prom_inst = None

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Respuestas totales UDL", total)
    col2.metric("Promedio general UDL", f"{prom_inst:.2f}" if prom_inst is not None else "N/D")
    col3.metric("Respuestas Virtual/Mixto", nv)
    col4.metric("Respuestas Escolar/Exec + Prepa", ne + np_)

    st.divider()

    sub = st.radio(
        "Vista",
        ["Resumen por formulario", "UDL por sección", "Comparativos", "Exportables"],
        horizontal=True,
        key=f"sub_udl_{vista}",
    )

    if sub == "Resumen por formulario":
        df_res = pd.DataFrame(
            [
                {"Formulario": "Virtual y Mixto Virtual", "Respuestas": nv, "Promedio": pv},
                {"Formulario": "Escolarizados y Lic. Ejecutivas", "Respuestas": ne, "Promedio": pe},
                {"Formulario": "Preparatoria", "Respuestas": np_, "Promedio": pp},
            ]
        )
        st.dataframe(df_res, use_container_width=True)
        try:
            c = (
                alt.Chart(df_res.dropna(subset=["Promedio"]))
                .mark_bar()
                .encode(
                    x=alt.X("Formulario:N", sort=None),
                    y="Promedio:Q",
                    tooltip=["Formulario", "Respuestas", "Promedio"],
                )
                .properties(height=320, title="Promedio general por formulario")
            )
            st.altair_chart(c, use_container_width=True)
        except Exception as e:
            st.error("No se pudo graficar promedio por formulario.")
            st.exception(e)

    elif sub == "UDL por sección":
        # Promedios por sección (ponderados por respuestas) unificando por nombre de sección (si coinciden)
        rows = []
        for mod, df_mod in [("virtual", v), ("escolar", e), ("prepa", p)]:
            df_sec = promedio_por_seccion(df_mod, mod)
            df_sec["Modalidad"] = mod
            df_sec["Respuestas"] = len(df_mod)
            rows.append(df_sec)

        df_all = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
        if df_all.empty:
            st.info("No hay datos por sección para mostrar.")
            return

        st.dataframe(df_all, use_container_width=True)

        # Agregado institucional por nombre de sección (ponderado por respuestas de la modalidad)
        df_valid = df_all.dropna(subset=["Promedio"]).copy()
        if df_valid.empty:
            st.info("No hay promedios válidos para agregar.")
            return

        df_valid["peso"] = df_valid["Respuestas"].clip(lower=1)
        df_valid["prom_peso"] = df_valid["Promedio"] * df_valid["peso"]

        inst = (
            df_valid.groupby("Sección", as_index=False)
            .agg(Respuestas=("peso", "sum"), Promedio_UDL=("prom_peso", "sum"))
        )
        inst["Promedio_UDL"] = inst["Promedio_UDL"] / inst["Respuestas"]

        st.subheader("Promedio UDL por sección (agregado)")
        st.dataframe(inst.sort_values("Promedio_UDL", ascending=False), use_container_width=True)

        try:
            c = (
                alt.Chart(inst)
                .mark_bar()
                .encode(
                    x=alt.X("Sección:N", sort="-y"),
                    y=alt.Y("Promedio_UDL:Q"),
                    tooltip=["Sección", "Respuestas", "Promedio_UDL"],
                )
                .properties(height=320, title="Promedio UDL por sección")
            )
            st.altair_chart(c, use_container_width=True)
        except Exception as e:
            st.error("No se pudo graficar promedio UDL por sección.")
            st.exception(e)

    elif sub == "Comparativos":
        st.write("Comparativos rápidos entre modalidades (promedios por sección dentro de cada modalidad).")
        for mod, df_mod, label in [
            ("virtual", v, "Virtual y Mixto Virtual"),
            ("escolar", e, "Escolarizados y Lic. Ejecutivas"),
            ("prepa", p, "Preparatoria"),
        ]:
            st.markdown(f"### {label}")
            df_sec = promedio_por_seccion(df_mod, mod)
            st.dataframe(df_sec, use_container_width=True)
            chart_barras_seccion(df_sec, f"{label} – Promedio por sección")

    elif sub == "Exportables":
        df_res = pd.DataFrame(
            [
                {"Formulario": "Virtual y Mixto Virtual", "Respuestas": nv, "Promedio": pv},
                {"Formulario": "Escolarizados y Lic. Ejecutivas", "Respuestas": ne, "Promedio": pe},
                {"Formulario": "Preparatoria", "Respuestas": np_, "Promedio": pp},
            ]
        )
        csv = df_res.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Descargar resumen institucional (CSV)",
            data=csv,
            file_name="udl_resumen_formularios.csv",
            mime="text/csv",
            key=f"dl_udl_{vista}",
        )

# ============================================================
# ENTRADA PRINCIPAL
# ============================================================
def render_encuesta_calidad(vista: str, carrera_seleccionada: str | None):
    st.header("Encuesta de calidad – Dashboard")

    df_virtual, df_esco, df_prepa, df_aplic = cargar_datos_calidad()

    # ---- Selector de corte (Aplicaciones) ----
    st.caption("Filtros superiores")

    # Para DG/Acad: pueden elegir “Todas” o un corte. Para Directores: por defecto corte, pero pueden ver todas si quieres.
    cortes = ["Todas"]
    if not df_aplic.empty and "label" in df_aplic.columns:
        cortes.extend(df_aplic["label"].dropna().astype(str).tolist())

    colA, colB = st.columns([2, 1])
    with colA:
        corte_sel = st.selectbox("Corte / Aplicación", cortes, index=0)
    with colB:
        usar_corte = (corte_sel != "Todas")

    f_ini, f_fin = (pd.NaT, pd.NaT)
    if usar_corte and not df_aplic.empty:
        fila = df_aplic[df_aplic["label"] == corte_sel]
        if not fila.empty:
            fila = fila.iloc[0]
            f_ini = fila.get("fecha_inicio", pd.NaT)
            f_fin = fila.get("fecha_fin", pd.NaT)

    # ---- Tabs ----
    tab_udl, tab_v, tab_e, tab_p = st.tabs(
        ["Institucional UDL", "Virtual/Mixto", "Escolar/Exec", "Preparatoria"]
    )

    with tab_udl:
        # Directores NO deberían ver vista institucional completa (opcional). Si quieres bloquear, descomenta.
        # if vista == "Director de carrera":
        #     st.warning("La vista institucional UDL no está disponible para directores.")
        # else:
        render_institucional_udl(df_virtual, df_esco, df_prepa, vista, usar_corte, f_ini, f_fin)

    with tab_v:
        render_formulario_tab(
            "Servicios: Virtual y Mixto Virtual",
            "virtual",
            df_virtual,
            vista,
            carrera_seleccionada,
            usar_corte,
            f_ini,
            f_fin,
        )

    with tab_e:
        render_formulario_tab(
            "Servicios: Escolarizados y Licenciaturas Ejecutivas",
            "escolar",
            df_esco,
            vista,
            carrera_seleccionada,
            usar_corte,
            f_ini,
            f_fin,
        )

    with tab_p:
        render_formulario_tab(
            "Preparatoria",
            "prepa",
            df_prepa,
            vista,
            carrera_seleccionada,
            usar_corte,
            f_ini,
            f_fin,
        )
