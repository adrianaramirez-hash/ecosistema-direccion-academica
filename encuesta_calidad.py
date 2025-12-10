import json
from typing import List, Tuple, Optional

import altair as alt
import gspread
import pandas as pd
import streamlit as st
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

# --------------------------------------------------
# CONFIGURACIÓN BÁSICA
# --------------------------------------------------
st.title("📝 Encuesta de calidad – Reportes")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Ajusta esta URL solo si cambiaste el archivo en Drive.
SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)

# Nombre de la columna de carrera en los formularios
COL_CARRERA = "Carrera de procedencia"


# --------------------------------------------------
# AYUDAS PARA CARGA DE DATOS
# --------------------------------------------------
def _abrir_hoja(sh, posibles_nombres: List[str], obligatorio: bool = True):
    """Intenta abrir una hoja con varios posibles nombres."""
    for nombre in posibles_nombres:
        try:
            return sh.worksheet(nombre)
        except WorksheetNotFound:
            continue
    if obligatorio:
        raise WorksheetNotFound(str(posibles_nombres))
    return None


@st.cache_data(ttl=180)
def cargar_datos_calidad():
    """Conecta a Google Sheets y carga:
    - Virtual
    - Escolarizados / Ejecutivas
    - Preparatoria
    - Aplicaciones
    """
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_URL)

    # Hojas de respuestas (ajustamos a tus nombres)
    ws_virtual = _abrir_hoja(
        sh, ["servicios virtual y mixto virtual", "servicios virtual y mixto virtu"]
    )
    ws_esco = _abrir_hoja(
        sh,
        ["servicios escolarizados y licenciaturas ejecutivas"],
    )
    ws_prepa = _abrir_hoja(sh, ["Preparatoria", "preparatoria"])

    df_virtual = pd.DataFrame(ws_virtual.get_all_records()) if ws_virtual else pd.DataFrame()
    df_esco = pd.DataFrame(ws_esco.get_all_records()) if ws_esco else pd.DataFrame()
    df_prepa = pd.DataFrame(ws_prepa.get_all_records()) if ws_prepa else pd.DataFrame()

    # Hoja de aplicaciones
    ws_aplic = _abrir_hoja(sh, ["Aplicaciones"])
    df_aplic = pd.DataFrame(ws_aplic.get_all_records()) if ws_aplic else pd.DataFrame()

    # Normalizamos fechas de Marca temporal
    for df in (df_virtual, df_esco, df_prepa):
        if "Marca temporal" in df.columns:
            df["Marca temporal"] = pd.to_datetime(df["Marca temporal"], errors="coerce")

    # Normalizamos fechas de Aplicaciones
    if not df_aplic.empty:
        for col in ("fecha_inicio", "fecha_fin"):
            if col in df_aplic.columns:
                df_aplic[col] = pd.to_datetime(df_aplic[col], errors="coerce")

    return df_virtual, df_esco, df_prepa, df_aplic


# --------------------------------------------------
# CONFIGURACIÓN DE SECCIONES (DICCIONARIO QUE ME PASASTE)
# --------------------------------------------------
def excel_col_to_index(col: str) -> int:
    """Convierte una columna tipo Excel (A, B, AA, BU, ...) a índice 0-based."""
    col = col.strip().upper()
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


SECCIONES_CONFIG = {
    "virtual": [
        ("Director / Coordinador", "C", "G"),
        ("Aprendizaje", "H", "P"),
        ("Materiales en la plataforma", "Q", "U"),
        ("Evaluación del conocimiento", "V", "Y"),
        ("Acceso a soporte académico", "Z", "AD"),
        ("Acceso a soporte administrativo", "AE", "AI"),
        ("Comunicación con compañeros", "AJ", "AQ"),
        ("Recomendación", "AR", "AU"),
        ("Plataforma SEAC", "AV", "AZ"),
        ("Comunicación con la universidad", "BA", "BE"),
    ],
    "escolar": [
        ("Servicios administrativos / apoyo", "I", "V"),
        ("Servicios académicos", "W", "AH"),
        ("Director / Coordinador", "AI", "AM"),
        ("Instalaciones y equipo tecnológico", "AN", "AX"),
        ("Ambiente escolar", "AY", "BE"),
    ],
    "prepa": [
        ("Servicios administrativos / apoyo", "H", "Q"),
        ("Servicios académicos", "R", "AC"),
        ("Directores y coordinadores", "AD", "BB"),
        ("Instalaciones y equipo tecnológico", "BC", "BN"),
        ("Ambiente escolar", "BO", "BU"),
    ],
}

FORM_TO_KEY = {
    "servicios virtual y mixto virtual": "virtual",
    "servicios virtual y mixto virtu": "virtual",
    "servicios escolarizados y licenciaturas ejecutivas": "escolar",
    "Preparatoria": "prepa",
    "preparatoria": "prepa",
}

MODALIDAD_LABEL = {
    "virtual": "Servicios virtual y mixto virtual",
    "escolar": "Servicios escolarizados y licenciaturas ejecutivas",
    "prepa": "Preparatoria",
}


def clasificar_semaforo(promedio: Optional[float]) -> str:
    if promedio is None or pd.isna(promedio):
        return ""
    if promedio >= 4.5:
        return "🟢 Alto"
    if promedio >= 3.5:
        return "🟡 Medio"
    return "🔴 Bajo"


def obtener_secciones(df: pd.DataFrame, modalidad_key: str) -> pd.DataFrame:
    """Calcula promedio por sección para un DF y una modalidad."""
    if df.empty:
        return pd.DataFrame(
            columns=["Modalidad", "Sección", "Promedio", "Respuestas", "Semáforo"]
        )

    config = SECCIONES_CONFIG.get(modalidad_key, [])
    resultados = []

    for nombre_seccion, col_ini, col_fin in config:
        idx_ini = excel_col_to_index(col_ini)
        idx_fin = excel_col_to_index(col_fin)
        cols = list(df.columns[idx_ini : idx_fin + 1])

        if not cols:
            continue

        datos = df[cols].apply(pd.to_numeric, errors="coerce")

        if datos.notna().sum().sum() == 0:
            promedio = None
            n_resp = len(df)
        else:
            promedio = float(datos.stack().mean())
            n_resp = int(datos.notna().any(axis=1).sum())

        resultados.append(
            {
                "Modalidad": MODALIDAD_LABEL.get(modalidad_key, modalidad_key),
                "Sección": nombre_seccion,
                "Promedio": promedio,
                "Respuestas": n_resp,
                "Semáforo": clasificar_semaforo(promedio),
            }
        )

    return pd.DataFrame(resultados)


# --------------------------------------------------
# FILTRO POR APLICACIONES (USANDO LA HOJA APLICACIONES)
# --------------------------------------------------
def filtrar_por_aplicaciones(
    df: pd.DataFrame,
    df_aplic: pd.DataFrame,
    formulario_objetivo: Optional[str],
) -> pd.DataFrame:
    """Filtra un DF de respuestas por las aplicaciones seleccionadas.

    - df_aplic: subconjunto de la hoja Aplicaciones que ya respeta año y demás filtros.
    - formulario_objetivo: nombre de formulario de esa hoja (para virtual / escolar / prepa).
    """
    if df.empty or "Marca temporal" not in df.columns:
        return df

    if df_aplic.empty:
        # Sin información de aplicaciones → usamos todo el DF
        return df

    subset = df_aplic.copy()

    if formulario_objetivo:
        subset = subset[subset["formulario"] == formulario_objetivo]

    if subset.empty:
        # No hay aplicaciones para este formulario en el filtro actual
        return pd.DataFrame(columns=df.columns)

    masks = []
    for _, fila in subset.iterrows():
        fi = pd.to_datetime(fila.get("fecha_inicio"), errors="coerce")
        ff = pd.to_datetime(fila.get("fecha_fin"), errors="coerce")

        if pd.isna(fi) or pd.isna(ff):
            # Si no hay fechas válidas en esa fila, avisamos y tomamos todo el rango
            masks.append(pd.Series(True, index=df.index))
        else:
            m = (df["Marca temporal"] >= fi) & (df["Marca temporal"] <= ff)
            masks.append(m)

    if not masks:
        return df

    mask_total = masks[0]
    for m in masks[1:]:
        mask_total |= m

    return df.loc[mask_total].copy()


# --------------------------------------------------
# CARGA DE DATOS
# --------------------------------------------------
try:
    df_virtual_orig, df_esco_orig, df_prepa_orig, df_aplic_orig = cargar_datos_calidad()
except Exception as e:
    st.error("No se pudieron cargar los datos de la Encuesta de calidad.")
    st.exception(e)
    st.stop()

if df_aplic_orig.empty:
    st.warning(
        "La hoja **Aplicaciones** está vacía o no se pudo leer. "
        "Por ahora se mostrarán los resultados sin separar por aplicación."
    )

# --------------------------------------------------
# FILTROS: AÑO, ÁREA, APLICACIÓN
# --------------------------------------------------
st.markdown("### 🎛️ Filtros de aplicación")

df_aplic = df_aplic_orig.copy()

# Año (por fecha_inicio)
years = []
if "fecha_inicio" in df_aplic.columns:
    years = (
        df_aplic["fecha_inicio"]
        .dropna()
        .dt.year.astype(int)
        .sort_values()
        .unique()
        .tolist()
    )

col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    if years:
        year_options = ["Todos los años"] + [str(y) for y in years]
        year_selected = st.selectbox("Año de aplicación", year_options)
    else:
        year_selected = "Todos los años"

with col_f2:
    area_opciones = {
        "Todas las áreas": None,
        "Servicios virtual y mixto virtual": "servicios virtual y mixto virtual",
        "Servicios escolarizados y licenciaturas ejecutivas": "servicios escolarizados y licenciaturas ejecutivas",
        "Preparatoria": "Preparatoria",
    }
    area_visible = st.selectbox("Área / modalidad", list(area_opciones.keys()))
    formulario_filtro = area_opciones[area_visible]

# Filtramos hoja Aplicaciones por año y modalidad (si aplica)
df_aplic_filtro = df_aplic.copy()

if year_selected != "Todos los años" and "fecha_inicio" in df_aplic_filtro.columns:
    anio_int = int(year_selected)
    df_aplic_filtro = df_aplic_filtro[
        df_aplic_filtro["fecha_inicio"].dt.year == anio_int
    ]

if formulario_filtro:
    df_aplic_filtro = df_aplic_filtro[
        df_aplic_filtro["formulario"] == formulario_filtro
    ]

with col_f3:
    if df_aplic_filtro.empty:
        aplicacion_selected_label = st.selectbox(
            "Aplicación",
            ["(no hay aplicaciones para el filtro seleccionado)"],
        )
    else:
        opciones_labels = []
        opciones_indices = []

        opciones_labels.append("Todas las aplicaciones del filtro")
        opciones_indices.append(None)

        for idx, fila in df_aplic_filtro.iterrows():
            desc = str(fila.get("descripcion", "")).strip()
            aplic_id = str(fila.get("aplicacion_id", "")).strip()
            form = str(fila.get("formulario", "")).strip()
            label = f"{aplic_id} – {desc} ({form})"
            opciones_labels.append(label)
            opciones_indices.append(idx)

        aplicacion_selected_label = st.selectbox("Aplicación", opciones_labels)

# Determinamos qué filas de Aplicaciones usar
if df_aplic_filtro.empty or aplicacion_selected_label.startswith("(no hay"):
    df_aplic_seleccion = pd.DataFrame(columns=df_aplic.columns)
else:
    if aplicacion_selected_label == "Todas las aplicaciones del filtro":
        df_aplic_seleccion = df_aplic_filtro.copy()
    else:
        # Buscar índice correspondiente
        pos = opciones_labels.index(aplicacion_selected_label)
        idx_real = opciones_indices[pos]
        df_aplic_seleccion = df_aplic_filtro.loc[[idx_real]].copy()

# Mostramos información del periodo seleccionado
if not df_aplic_seleccion.empty:
    fi_min = df_aplic_seleccion["fecha_inicio"].min()
    ff_max = df_aplic_seleccion["fecha_fin"].max()
    st.caption(
        f"Periodo de aplicación considerado: "
        f"**{fi_min.date() if pd.notna(fi_min) else '—'}** a "
        f"**{ff_max.date() if pd.notna(ff_max) else '—'}**."
    )
else:
    st.caption("Periodo de aplicación: **sin filtro de fechas (todas las respuestas)**.")

st.markdown("---")

# --------------------------------------------------
# VISTA: DIRECCIÓN GENERAL / ACADÉMICA / DIRECTOR
# --------------------------------------------------
# Intentamos recuperar de app.py si existen
vista_externa = st.session_state.get("vista")
carrera_externa = st.session_state.get("carrera")

col_v1, col_v2 = st.columns(2)

with col_v1:
    if vista_externa in [
        "Dirección General",
        "Dirección Académica",
        "Director de carrera",
    ]:
        vista = vista_externa
        st.write(f"**Vista:** {vista}")
    else:
        vista = st.selectbox(
            "Selecciona la vista",
            ["Dirección General", "Dirección Académica", "Director de carrera"],
        )

# Primero filtramos por aplicaciones los DFs originales
df_virtual = filtrar_por_aplicaciones(
    df_virtual_orig, df_aplic_seleccion, "servicios virtual y mixto virtual"
)
df_esco = filtrar_por_aplicaciones(
    df_esco_orig, df_aplic_seleccion, "servicios escolarizados y licenciaturas ejecutivas"
)
df_prepa = filtrar_por_aplicaciones(df_prepa_orig, df_aplic_seleccion, "Preparatoria")

# Lista de carreras para el caso de director
todas_carreras = []
for df_tmp in (df_virtual_orig, df_esco_orig, df_prepa_orig):
    if COL_CARRERA in df_tmp.columns:
        todas_carreras.extend(df_tmp[COL_CARRERA].dropna().unique().tolist())
todas_carreras = sorted(list(set(todas_carreras)))

with col_v2:
    carrera_seleccionada = None
    if vista == "Director de carrera":
        if carrera_externa and carrera_externa in todas_carreras:
            carrera_seleccionada = carrera_externa
            st.write(f"**Carrera:** {carrera_seleccionada}")
        else:
            carrera_seleccionada = st.selectbox(
                "Selecciona la carrera",
                todas_carreras if todas_carreras else ["(sin carreras detectadas)"],
            )

# Filtro por carrera si aplica
if vista == "Director de carrera" and carrera_seleccionada and todas_carreras:
    for df_tmp in (df_virtual, df_esco, df_prepa):
        if not df_tmp.empty and COL_CARRERA in df_tmp.columns:
            mask = df_tmp[COL_CARRERA] == carrera_seleccionada
            df_tmp.drop(df_tmp[~mask].index, inplace=True)

st.markdown("---")

# --------------------------------------------------
# CÁLCULO DE SECCIONES POR MODALIDAD
# --------------------------------------------------
tablas_secciones: List[pd.DataFrame] = []

if not df_virtual.empty:
    tablas_secciones.append(obtener_secciones(df_virtual, "virtual"))

if not df_esco.empty:
    tablas_secciones.append(obtener_secciones(df_esco, "escolar"))

if not df_prepa.empty:
    tablas_secciones.append(obtener_secciones(df_prepa, "prepa"))

if not tablas_secciones:
    st.warning(
        "No hay respuestas que coincidan con los filtros actuales "
        "(año, aplicación, área y/o carrera)."
    )
    st.stop()

df_secciones = pd.concat(tablas_secciones, ignore_index=True)

# --------------------------------------------------
# KPIs GENERALES
# --------------------------------------------------
total_respuestas = len(df_virtual) + len(df_esco) + len(df_prepa)

df_valid = df_secciones.dropna(subset=["Promedio"])
if not df_valid.empty:
    prom_global = (
        df_valid["Promedio"] * df_valid["Respuestas"]
    ).sum() / df_valid["Respuestas"].sum()
else:
    prom_global = None

n_rojas = int((df_secciones["Semáforo"] == "🔴 Bajo").sum())
n_verdes = int((df_secciones["Semáforo"] == "🟢 Alto").sum())

col_k1, col_k2, col_k3, col_k4 = st.columns(4)

with col_k1:
    st.metric("Respuestas en el filtro", total_respuestas)

with col_k2:
    st.metric(
        "Promedio global",
        f"{prom_global:.2f}" if prom_global is not None else "—",
    )

with col_k3:
    st.metric("Secciones en verde", n_verdes)

with col_k4:
    st.metric("Secciones en rojo", n_rojas)

st.markdown("---")

# --------------------------------------------------
# TABLA Y GRÁFICA DE SECCIONES
# --------------------------------------------------
st.subheader("Resultados por sección")

st.dataframe(df_secciones, use_container_width=True)

try:
    chart = (
        alt.Chart(df_secciones)
        .mark_bar()
        .encode(
            x=alt.X("Sección:N", sort=None, title="Sección"),
            y=alt.Y("Promedio:Q", title="Promedio", scale=alt.Scale(domain=[1, 5])),
            color=alt.Color("Modalidad:N", title="Modalidad"),
            tooltip=[
                "Modalidad",
                "Sección",
                alt.Tooltip("Promedio:Q", format=".2f"),
                "Respuestas",
                "Semáforo",
            ],
        )
        .properties(height=350)
    )
    st.altair_chart(chart, use_container_width=True)
except Exception:
    st.info("No se pudo generar la gráfica de barras para las secciones.")
