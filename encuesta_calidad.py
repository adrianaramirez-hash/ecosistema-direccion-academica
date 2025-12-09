import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials
import numpy as np
import unicodedata
import altair as alt

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)


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
# UTILIDADES PARA RANGOS Y ESCALAS
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


def normalizar_texto(s: str) -> str:
    """Quita acentos y pasa a minúsculas para mapear respuestas tipo Likert."""
    if not isinstance(s, str):
        return ""
    s = s.strip()
    s_norm = unicodedata.normalize("NFD", s)
    s_norm = "".join(ch for ch in s_norm if unicodedata.category(ch) != "Mn")
    return s_norm.lower()


# Diccionarios de escalas (1 a 5)
MAP_LIKERT = {
    # Acuerdo
    "totalmente en desacuerdo": 1,
    "en desacuerdo": 2,
    "neutral": 3,
    "ni de acuerdo ni en desacuerdo": 3,
    "de acuerdo": 4,
    "totalmente de acuerdo": 5,
    # Satisfacción
    "muy insatisfecho": 1,
    "insatisfecho": 2,
    "poco satisfecho": 2,
    "ni satisfecho ni insatisfecho": 3,
    "satisfecho": 4,
    "muy satisfecho": 5,
    # Frecuencia
    "nunca": 1,
    "rara vez": 2,
    "raramente": 2,
    "casi nunca": 2,
    "a veces": 3,
    "ocasionalmente": 3,
    "frecuente": 4,
    "frecuentemente": 4,
    "muy frecuente": 5,
    "siempre": 5,
    "casi siempre": 4,
    # Calidad tipo malo–excelente
    "muy malo": 1,
    "malo": 2,
    "regular": 3,
    "bueno": 4,
    "excelente": 5,
}


def mapear_respuesta_a_numero(valor):
    """
    Convierte una respuesta a número:
    - Si es número o texto numérico -> float
    - Si es texto tipo Likert -> 1–5
    - Si no se reconoce -> NaN
    """
    if pd.isna(valor):
        return np.nan

    # 1) Intentar numérico directo
    try:
        num = float(str(valor).replace(",", "."))
        # Si el valor está en una escala tipo 1–10, lo podemos reescalar o dejar tal cual.
        # Por simplicidad lo dejamos tal cual, se promediará igual.
        return num
    except Exception:
        pass

    # 2) Intentar mapear texto Likert a 1–5
    texto = normalizar_texto(str(valor))
    return MAP_LIKERT.get(texto, np.nan)


# ============================================================
# DEFINICIÓN DE SECCIONES POR MODALIDAD (TU DICCIONARIO)
# ============================================================

SECCIONES_RANGOS = {
    # a) Servicios virtual y mixto virtual
    "virtual": {
        "Director / Coordinador": ("C", "G"),
        "Aprendizaje": ("H", "P"),
        "Materiales en la plataforma": ("Q", "U"),
        "Evaluación del conocimiento": ("V", "Y"),
        "Acceso a soporte académico": ("Z", "AD"),
        "Acceso a soporte administrativo": ("AE", "AI"),
        "Comunicación con compañeros": ("AJ", "AQ"),
        "Recomendación": ("AR", "AU"),
        "Plataforma SEAC": ("AV", "AZ"),
        "Comunicación con la universidad": ("BA", "BE"),
    },
    # b) Servicios escolarizados y licenciaturas ejecutivas
    "escolar": {
        "Servicios administrativos / apoyo": ("I", "V"),
        "Servicios académicos": ("W", "AH"),
        "Director / Coordinador": ("AI", "AM"),
        "Instalaciones y equipo tecnológico": ("AN", "AX"),
        "Ambiente escolar": ("AY", "BE"),
    },
    # c) Preparatoria
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
    definido por letras de Excel (p.ej. ('C', 'G')) usando posición (iloc)
    y mapeando las respuestas a valores numéricos.
    """
    if df.empty:
        return None

    col_ini, col_fin = rango_excel
    i = col_letter_to_index(col_ini)
    j = col_letter_to_index(col_fin)

    if i < 0 or j < 0 or i >= df.shape[1]:
        return None

    j = min(j, df.shape[1] - 1)
    sub = df.iloc[:, i : j + 1]

    # Mapeamos todas las celdas a escala numérica
    sub_num = sub.applymap(mapear_respuesta_a_numero)

    if sub_num.size == 0:
        return None

    arr = sub_num.to_numpy(dtype=float)
    if np.isnan(arr).all():
        return None

    return float(np.nanmean(arr))


def clasificar_semaforo(prom):
    """
    Asigna semáforo según el promedio:
    - 🟢 >= 4.0
    - 🟡 3.0 – 3.9
    - 🔴 < 3.0
    """
    if prom is None or np.isnan(prom):
        return ""
    if prom >= 4.0:
        return "🟢"
    if prom >= 3.0:
        return "🟡"
    return "🔴"


def construir_resumen_secciones(df: pd.DataFrame, tipo_modalidad: str) -> pd.DataFrame:
    """
    Construye un DataFrame con el promedio por sección para una modalidad.
    """
    filas = []
    rangos = SECCIONES_RANGOS.get(tipo_modalidad, {})
    for nombre_sec, rango in rangos.items():
        prom = promedio_seccion_por_rango(df, rango)
        if prom is not None:
            filas.append(
                {
                    "Sección": nombre_sec,
                    "Promedio": round(prom, 2),
                    "Semáforo": clasificar_semaforo(prom),
                }
            )
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
    # Selector de aplicación (por descripción, que incluye periodo/fecha)
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

    # Texto de fechas
    fi = fila_aplic.get("fecha_inicio")
    ff = fila_aplic.get("fecha_fin")
    fi_txt = fi.date() if isinstance(fi, pd.Timestamp) else fi
    ff_txt = ff.date() if isinstance(ff, pd.Timestamp) else ff

    st.caption(
        f"Aplicación seleccionada: **{aplic_sel}**  \n"
        f"Modalidad detectada: **{modalidad}**  \n"
        f"Rango de fechas considerado: {fi_txt} a {ff_txt}"
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
        serie_sat_num = df_base[col_satisf_global].apply(mapear_respuesta_a_numero)
        prom_sat = float(np.nanmean(serie_sat_num)) if not serie_sat_num.empty else None
        with col_k2:
            if prom_sat is not None and not np.isnan(prom_sat):
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

    # VISTAS: DIRECCIÓN GENERAL Y DIRECCIÓN ACADÉMICA
    if vista in ["Dirección General", "Dirección Académica"]:
        tab_res, tab_carr = st.tabs(
            ["📌 Promedio por sección (global)", "🎓 Promedio por sección y carrera"]
        )

        # 1) Promedio por sección (grupo completo)
        with tab_res:
            st.subheader("Promedio por sección (toda la modalidad en esta aplicación)")
            df_secciones = construir_resumen_secciones(df_base, modalidad)
            if df_secciones.empty:
                st.info("No se pudieron calcular secciones para esta modalidad.")
            else:
                col_t, col_g = st.columns([1, 1.5])

                with col_t:
                    st.dataframe(df_secciones, use_container_width=True)

                with col_g:
                    chart = (
                        alt.Chart(df_secciones)
                        .mark_bar()
                        .encode(
                            x=alt.X("Sección:N", sort="-y", title="Sección"),
                            y=alt.Y("Promedio:Q", title="Promedio"),
                            color=alt.value("#4c78a8"),
                            tooltip=["Sección", "Promedio", "Semáforo"],
                        )
                        .properties(height=350)
                    )
                    st.altair_chart(chart, use_container_width=True)

        # 2) Promedio por sección y carrera
        with tab_carr:
            if col_carrera is None:
                st.info("No se encontró la columna de 'Carrera de procedencia'.")
            else:
                st.subheader("Promedios por sección filtrando por carrera")
                carreras = sorted(df_base[col_carrera].dropna().unique().tolist())
                carrera_filtro = st.selectbox(
                    "Filtrar por carrera:",
                    ["Todas"] + carreras,
                )

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
                    if df_sec_c.empty:
                        st.info("No se pudieron calcular secciones para esta modalidad.")
                    else:
                        col_t2, col_g2 = st.columns([1, 1.5])
                        with col_t2:
                            st.dataframe(df_sec_c, use_container_width=True)
                        with col_g2:
                            chart2 = (
                                alt.Chart(df_sec_c)
                                .mark_bar()
                                .encode(
                                    x=alt.X("Sección:N", sort="-y", title="Sección"),
                                    y=alt.Y("Promedio:Q", title="Promedio"),
                                    color=alt.value("#72b7b2"),
                                    tooltip=["Sección", "Promedio", "Semáforo"],
                                )
                                .properties(height=350)
                            )
                            st.altair_chart(chart2, use_container_width=True)

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

            chart_dir = (
                alt.Chart(df_secc_dir)
                .mark_bar()
                .encode(
                    x=alt.X("Sección:N", sort="-y", title="Sección"),
                    y=alt.Y("Promedio:Q", title="Promedio"),
                    color=alt.value("#e45756"),
                    tooltip=["Sección", "Promedio", "Semáforo"],
                )
                .properties(height=350)
            )
            st.altair_chart(chart_dir, use_container_width=True)

    else:
        st.info("La vista seleccionada aún no está configurada para la Encuesta de calidad.")
