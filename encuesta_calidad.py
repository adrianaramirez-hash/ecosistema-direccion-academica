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

# Tu Google Sheets de calidad
SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)

COLUMNA_CARRERA_LIMPIA = "Carrera de procedencia"


def _abrir_hoja_por_prefijo(sh, prefijo_busqueda):
    """
    Busca una hoja por prefijo en el título, ignorando espacios y mayúsculas.
    Esto hace el código más tolerante a cambios pequeños en el nombre de la hoja.
    """
    prefijo = prefijo_busqueda.strip().lower()
    for ws in sh.worksheets():
        titulo_norm = ws.title.strip().lower()
        if titulo_norm.startswith(prefijo):
            return ws
    raise ValueError(f"No se encontró una hoja cuyo nombre comience con: {prefijo_busqueda}")


@st.cache_data(ttl=60)
def cargar_datos_calidad():
    """Carga todas las hojas necesarias del Google Sheets de calidad."""
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_URL)

    # Hojas: buscamos por prefijo para tolerar espacios o recortes en el nombre
    ws_virtual = _abrir_hoja_por_prefijo(sh, "servicios virtual y mixto")
    ws_prepa = _abrir_hoja_por_prefijo(sh, "preparatoria")
    ws_esco = _abrir_hoja_por_prefijo(sh, "servicios escolarizados")
    ws_aplic = _abrir_hoja_por_prefijo(sh, "aplicaciones")

    df_virtual = pd.DataFrame(ws_virtual.get_all_records())
    df_prepa = pd.DataFrame(ws_prepa.get_all_records())
    df_esco = pd.DataFrame(ws_esco.get_all_records())
    df_aplic = pd.DataFrame(ws_aplic.get_all_records())

    # Normalizamos nombres de columnas: quitamos espacios al inicio/fin
    for df in [df_virtual, df_prepa, df_esco, df_aplic]:
        df.columns = df.columns.astype(str).str.strip()

    # Convertimos marca temporal a fecha, si existe
    for df in [df_virtual, df_prepa, df_esco]:
        if "Marca temporal" in df.columns:
            df["Marca temporal"] = pd.to_datetime(df["Marca temporal"], errors="coerce")

    # Fechas de aplicaciones
    if "fecha_inicio" in df_aplic.columns:
        df_aplic["fecha_inicio"] = pd.to_datetime(df_aplic["fecha_inicio"], errors="coerce")
    if "fecha_fin" in df_aplic.columns:
        df_aplic["fecha_fin"] = pd.to_datetime(df_aplic["fecha_fin"], errors="coerce")

    return df_virtual, df_esco, df_prepa, df_aplic


# ============================================================
# DEFINICIÓN DE SECCIONES POR MODALIDAD (USANDO LETRAS DE EXCEL)
# ============================================================

def col_letter_to_index(col_letter: str) -> int:
    """
    Convierte una letra de columna estilo Excel (A, B, ..., Z, AA, AB...) a índice 0-based.
    A -> 0, B -> 1, ..., Z -> 25, AA -> 26, etc.
    """
    col = col_letter.strip().upper()
    res = 0
    for ch in col:
        if "A" <= ch <= "Z":
            res = res * 26 + (ord(ch) - ord("A") + 1)
    return res - 1  # 0-based


# RANGOS DE COLUMNAS SEGÚN EL DICCIONARIO QUE ME COMPARTISTE
SECCIONES_RANGOS = {
    "virtual": {
        "Director / Coordinador": ("C", "G"),
        "Aprendizaje": ("H", "P"),
        "Materiales en plataforma": ("Q", "U"),
        "Evaluación del conocimiento": ("V", "Y"),
        "Acceso a soporte académico": ("Z", "AD"),
        "Acceso a soporte administrativo": ("AE", "AI"),
        "Comunicación con compañeros": ("AJ", "AQ"),
        "Recomendación": ("AR", "AU"),
        "Plataforma SEAC": ("AV", "AZ"),
        "Comunicación con la universidad": ("BA", "BE"),
    },
    "escolar": {
        "Servicios administrativos / apoyo": ("I", "V"),
        "Servicios académicos": ("W", "AH"),
        "Director / Coordinador": ("AI", "AM"),
        "Instalaciones y equipo tecnológico": ("AN", "AX"),
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


def promedio_seccion_por_rango(df: pd.DataFrame, rango_excel: tuple) -> float | None:
    """
    Calcula el promedio general de una sección tomando un rango de columnas
    definido por letras de Excel (p.ej. ('C', 'G')) usando posición (iloc).
    """
    if df.empty:
        return None

    col_ini, col_fin = rango_excel
    i = col_letter_to_index(col_ini)
    j = col_letter_to_index(col_fin)

    if i < 0 or j < 0 or i >= df.shape[1]:
        return None

    j = min(j, df.shape[1] - 1)
    sub = df.iloc[:, i : j + 1].apply(pd.to_numeric, errors="coerce")
    if sub.size == 0:
        return None
    return float(sub.mean().mean())


def construir_resumen_secciones(df: pd.DataFrame, tipo_modalidad: str) -> pd.DataFrame:
    """
    Construye un DataFrame con el promedio por sección para una modalidad.
    """
    filas = []
    rangos = SECCIONES_RANGOS.get(tipo_modalidad, {})
    for nombre_sec, rango in rangos.items():
        prom = promedio_seccion_por_rango(df, rango)
        if prom is not None:
            filas.append({"Sección": nombre_sec, "Promedio": round(prom, 2)})
    return pd.DataFrame(filas)


# ============================================================
# LÓGICA PRINCIPAL DE LA VISTA
# ============================================================

def _detectar_modalidad(formulario: str) -> str:
    f = (formulario or "").lower()
    if "virtual" in f:
        return "virtual"
    if "preparatoria" in f or "prepa" in f:
        return "prepa"
    # por descarte, lo tomamos como escolarizados / ejecutivas
    return "escolar"


def _filtrar_por_aplicacion(df: pd.DataFrame, fila_aplic: pd.Series) -> pd.DataFrame:
    """
    Filtra el DataFrame por el rango de fechas de la aplicación (si marca temporal existe).
    """
    if df.empty or "Marca temporal" not in df.columns:
        return df

    fi = fila_aplic.get("fecha_inicio")
    ff = fila_aplic.get("fecha_fin")

    if pd.isna(fi) or pd.isna(ff):
        return df

    mask = (df["Marca temporal"] >= fi) & (df["Marca temporal"] <= ff)
    return df.loc[mask].copy()


def render_encuesta_calidad(vista: str, carrera_seleccionada: str | None):
    """
    Punto de entrada desde app.py

    vista: "Dirección General" | "Dirección Académica" | "Director de carrera"
    carrera_seleccionada: texto de la carrera cuando la vista es Director de carrera
    """
    st.header("📊 Encuesta de calidad – Resultados")

    try:
        df_virtual, df_esco, df_prepa, df_aplic = cargar_datos_calidad()
    except Exception as e:
        st.error("No se pudieron cargar los datos desde el Google Sheets de calidad.")
        st.exception(e)
        return

    if df_aplic.empty or "descripcion" not in df_aplic.columns:
        st.warning("No se encontró información de aplicaciones en la hoja 'Aplicaciones'.")
        return

    # --------------------------------------------------
    # Selector de aplicación
    # --------------------------------------------------
    aplicaciones = df_aplic["descripcion"].astype(str).tolist()
    aplic_sel = st.selectbox("Selecciona la aplicación de la encuesta:", aplicaciones)

    fila_aplic = df_aplic[df_aplic["descripcion"] == aplic_sel]
    if fila_aplic.empty:
        st.warning("No se encontró la aplicación seleccionada en la hoja 'Aplicaciones'.")
        return

    fila_aplic = fila_aplic.iloc[0]
    formulario = fila_aplic.get("formulario", "")
    modalidad = _detectar_modalidad(str(formulario))

    st.caption(
        f"Formulario: **{formulario}**  |  Modalidad detectada: **{modalidad}**  \n"
        f"Vigencia de la aplicación: "
        f"{fila_aplic.get('fecha_inicio', '—')} a {fila_aplic.get('fecha_fin', '—')}"
    )
    st.divider()

    # --------------------------------------------------
    # Elegimos el DataFrame base según la modalidad
    # --------------------------------------------------
    if modalidad == "virtual":
        df_base = df_virtual.copy()
    elif modalidad == "prepa":
        df_base = df_prepa.copy()
    else:
        df_base = df_esco.copy()

    # Normalizamos nombre de columna de carrera
    df_base.columns = df_base.columns.astype(str).str.strip()
    col_carrera = None
    for c in df_base.columns:
        if c.strip().lower() == "carrera de procedencia":
            col_carrera = c
            break

    # Filtramos por rango de fechas de la aplicación
    df_base = _filtrar_por_aplicacion(df_base, fila_aplic)

    if df_base.empty:
        st.warning("No hay respuestas en el rango de fechas para esta aplicación.")
        return

    # ============================================================
    # KPIs RÁPIDOS
    # ============================================================
    total_respuestas = len(df_base)
    st.subheader("Resumen general de la aplicación")
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        st.metric("Respuestas totales", total_respuestas)

    # Intentamos tomar una pregunta global de satisfacción, si existe
    col_satisf_global = None
    for c in df_base.columns:
        if "qué tan satisfecho estás con el servicio" in c.lower():
            col_satisf_global = c
            break

    if col_satisf_global:
        serie_sat = pd.to_numeric(df_base[col_satisf_global], errors="coerce")
        prom_sat = float(serie_sat.mean()) if not serie_sat.empty else None
        with col_k2:
            if prom_sat is not None:
                st.metric("Promedio satisfacción global", f"{prom_sat:.2f}")
            else:
                st.metric("Promedio satisfacción global", "—")
    else:
        with col_k2:
            st.metric("Promedio satisfacción global", "N/D")

    st.markdown("---")

    # ============================================================
    # TABS PRINCIPALES SEGÚN LA VISTA
    # ============================================================

    if vista in ["Dirección General", "Dirección Académica"]:
        tab_res, tab_carr = st.tabs(["📌 Promedio por sección", "🎓 Promedio por sección y carrera"])

        # 1) Promedio por sección (grupo completo)
        with tab_res:
            st.subheader("Promedio por sección (toda la modalidad en esta aplicación)")
            df_secciones = construir_resumen_secciones(df_base, modalidad)
            if df_secciones.empty:
                st.info("No se pudieron calcular secciones para esta modalidad.")
            else:
                st.dataframe(df_secciones, use_container_width=True)

        # 2) Promedio por sección y carrera
        with tab_carr:
            if col_carrera is None:
                st.info("No se encontró la columna de 'Carrera de procedencia'.")
            else:
                st.subheader("Promedios por sección y carrera")
                carreras = sorted(df_base[col_carrera].dropna().unique().tolist())
                carrera_filtro = st.selectbox("Filtrar por carrera (opcional):", ["Todas"] + carreras)

                if carrera_filtro != "Todas":
                    df_c = df_base[df_base[col_carrera] == carrera_filtro].copy()
                    st.caption(f"Respuestas de **{carrera_filtro}**: {len(df_c)}")
                else:
                    df_c = df_base.copy()
                    st.caption(f"Respuestas de todas las carreras: {len(df_c)}")

                if df_c.empty:
                    st.warning("No hay respuestas para el filtro seleccionado.")
                else:
                    df_sec_c = construir_resumen_secciones(df_c, modalidad)
                    st.dataframe(df_sec_c, use_container_width=True)

    # ------------------------------------------------------------
    # VISTA: DIRECTOR DE CARRERA
    # ------------------------------------------------------------
    elif vista == "Director de carrera":
        if not carrera_seleccionada:
            st.info("Selecciona una carrera en la pantalla principal para ver esta vista.")
            return

        if col_carrera is None:
            st.warning(
                "No se encontró la columna de 'Carrera de procedencia' en esta modalidad. "
                "No es posible filtrar por carrera."
            )
            return

        st.subheader(f"Resultados para la carrera: **{carrera_seleccionada}**")

        df_dir = df_base[df_base[col_carrera] == carrera_seleccionada].copy()
        if df_dir.empty:
            st.warning("No hay respuestas de la carrera seleccionada para esta aplicación.")
            return

        st.caption(f"Respuestas registradas: **{len(df_dir)}**")

        df_secc_dir = construir_resumen_secciones(df_dir, modalidad)
        if df_secc_dir.empty:
            st.info("No se pudieron calcular secciones para esta modalidad.")
        else:
            st.dataframe(df_secc_dir, use_container_width=True)

    else:
        st.info("La vista seleccionada aún no está configurada para la Encuesta de calidad.")
