import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials
import altair as alt
import unicodedata

# --------------------------------------------------
# CONFIG BÁSICA DE CONEXIÓN
# --------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)


def normalizar_texto(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s


def get_worksheet_flexible(sh, target_prefix: str):
    """
    Busca una hoja cuyo nombre COMIENCE con el prefijo indicado,
    ignorando mayúsculas, acentos y espacios.
    """
    target = normalizar_texto(target_prefix)

    for ws in sh.worksheets():
        name_norm = normalizar_texto(ws.title)
        if name_norm.startswith(target):
            return ws

    raise gspread.WorksheetNotFound(target_prefix)


# --------------------------------------------------
# MAPEO DE RESPUESTAS A PUNTAJE (1–5)
# --------------------------------------------------


def respuesta_a_puntos_calidad(valor):
    """
    Convierte respuestas tipo satisfacción / frecuencia / acuerdo
    a escala 1–5, donde 5 = mejor.
    """
    if pd.isna(valor):
        return None

    t = normalizar_texto(str(valor))

    mapa = {
        # Satisfacción
        "totalmente satisfecho": 5,
        "muy satisfecho": 5,
        "satisfecho": 4,
        "regularmente satisfecho": 3,
        "ni uno ni otro": 3,
        "neutral": 3,
        "poco satisfecho": 2,
        "insatisfecho": 2,
        "totalmente insatisfecho": 1,
        "nada satisfecho": 1,
        # Frecuencia
        "siempre": 5,
        "casi siempre": 4,
        "algunas veces": 3,
        "ocasionalmente": 3,
        "regularmente": 3,
        "rara vez": 2,
        "casi nunca": 2,
        "nunca": 1,
        # Acuerdo
        "totalmente de acuerdo": 5,
        "muy de acuerdo": 5,
        "de acuerdo": 4,
        "ni de acuerdo ni en desacuerdo": 3,
        "en desacuerdo": 2,
        "totalmente en desacuerdo": 1,
    }

    if t in mapa:
        return mapa[t]

    return None


# --------------------------------------------------
# CONSTRUCCIÓN DE ÁREAS POR TIPO DE SERVICIO
# (Basado en tu diccionario de columnas)
# --------------------------------------------------


def construir_areas_virtual(df):
    cols = list(df.columns)
    areas = {
        "Director / Coordinador": cols[2:7],  # C–G
        "Aprendizaje": cols[7:16],  # H–P
        "Materiales en la plataforma": cols[16:21],  # Q–U
        "Evaluación del conocimiento": cols[21:25],  # V–Y
        "Acceso a soporte académico": cols[25:30],  # Z–AD
        "Acceso a soporte administrativo": cols[30:35],  # AE–AI
        "Comunicación con compañeros": cols[35:43],  # AJ–AQ
        "Recomendación": cols[43:47],  # AR–AU
        "Plataforma SEAC": cols[47:52],  # AV–AZ
        "Comunicación con la universidad": cols[52:57],  # BA–BE
    }
    return areas


def construir_areas_escolarizados(df):
    cols = list(df.columns)
    areas = {
        "Servicios administrativos / apoyo": cols[8:22],  # I–V
        "Servicios académicos": cols[22:34],  # W–AH
        "Director / Coordinador": cols[34:39],  # AI–AM
        "Instalaciones y equipo tecnológico": cols[39:50],  # AN–AX
        "Ambiente escolar": cols[50:57],  # AY–BE
    }
    return areas


def construir_areas_preparatoria(df):
    cols = list(df.columns)
    areas = {
        "Servicios administrativos / apoyo": cols[7:17],  # H–Q
        "Servicios académicos": cols[17:29],  # R–AC
        "Directores y coordinadores": cols[29:54],  # AD–BB
        "Instalaciones y equipo tecnológico": cols[54:66],  # BC–BN
        "Ambiente escolar": cols[66:73],  # BO–BU
    }
    return areas


# --------------------------------------------------
# CARGA DE DATOS DESDE GOOGLE SHEETS
# --------------------------------------------------


@st.cache_data(ttl=60)
def cargar_datos_calidad():
    """
    Carga:
    - Hojas de respuestas de los 3 servicios.
    - Hoja 'Aplicaciones' con cortes (aplicacion_id, fechas).
    - Diccionarios de áreas.
    """
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    sh = client.open_by_url(SPREADSHEET_URL)

    # Hojas específicas (búsqueda flexible)
    ws_virtual = get_worksheet_flexible(sh, "servicios virtual y mixto")
    ws_esco = get_worksheet_flexible(sh, "servicios escolarizados y licen")
    ws_prep = get_worksheet_flexible(sh, "preparatoria")
    ws_aplic = get_worksheet_flexible(sh, "aplicaciones")

    df_virtual = pd.DataFrame(ws_virtual.get_all_records())
    df_esco = pd.DataFrame(ws_esco.get_all_records())
    df_prep = pd.DataFrame(ws_prep.get_all_records())
    df_aplic = pd.DataFrame(ws_aplic.get_all_records())

    # Parseo fechas de aplicaciones
    if not df_aplic.empty:
        if "fecha_inicio" in df_aplic.columns:
            df_aplic["fecha_inicio"] = pd.to_datetime(
                df_aplic["fecha_inicio"], errors="coerce"
            )
        if "fecha_fin" in df_aplic.columns:
            df_aplic["fecha_fin"] = pd.to_datetime(
                df_aplic["fecha_fin"], errors="coerce"
            )

        # Normalizamos nombres de columnas por si acaso
        if "formulario" in df_aplic.columns:
            df_aplic["formulario"] = df_aplic["formulario"].astype(str)
        if "aplicacion_id" in df_aplic.columns:
            df_aplic["aplicacion_id"] = df_aplic["aplicacion_id"].astype(str)

    # Diccionarios de áreas
    areas_virtual = construir_areas_virtual(df_virtual)
    areas_esco = construir_areas_escolarizados(df_esco)
    areas_prep = construir_areas_preparatoria(df_prep)

    return (
        df_virtual,
        df_esco,
        df_prep,
        df_aplic,
        areas_virtual,
        areas_esco,
        areas_prep,
    )


# --------------------------------------------------
# FUNCIONES DE CÁLCULO
# --------------------------------------------------


def calcular_promedios_areas(df, areas_por_tipo):
    """
    Calcula promedio por área combinando todos los tipos de servicio
    según las áreas definidas por tipo.
    """
    acumulados = {}
    total_suma = 0
    total_n = 0

    for tipo, areas in areas_por_tipo.items():
        df_tipo = df[df["Tipo_servicio"] == tipo]
        if df_tipo.empty:
            continue

        for area, columnas in areas.items():
            suma_area = 0
            n_area = 0

            for col in columnas:
                if col not in df_tipo.columns:
                    continue
                serie = df_tipo[col].apply(respuesta_a_puntos_calidad).dropna()
                if serie.empty:
                    continue
                suma_area += serie.sum()
                n_area += serie.count()

            if n_area == 0:
                continue

            if area not in acumulados:
                acumulados[area] = {"suma": 0, "n": 0}
            acumulados[area]["suma"] += suma_area
            acumulados[area]["n"] += n_area

            total_suma += suma_area
            total_n += n_area

    filas = []
    for area, info in acumulados.items():
        prom = info["suma"] / info["n"] if info["n"] > 0 else None
        filas.append({"Área": area, "Promedio": prom})

    df_areas = pd.DataFrame(filas)
    promedio_general = total_suma / total_n if total_n > 0 else None

    return df_areas, promedio_general


def calcular_promedio_por_programa(df, areas_por_tipo):
    """
    Calcula el promedio general por programa / servicio,
    usando todas las áreas correspondientes a su tipo de servicio.
    """
    filas = []

    for (prog, tipo), df_sub in df.groupby(["Programa", "Tipo_servicio"]):
        if tipo not in areas_por_tipo:
            continue
        areas_tipo = {tipo: areas_por_tipo[tipo]}
        _, prom_general = calcular_promedios_areas(df_sub, areas_tipo)
        filas.append(
            {
                "Programa": prog,
                "Tipo_servicio": tipo,
                "Promedio_general": prom_general,
                "Encuestas": len(df_sub),
            }
        )

    return pd.DataFrame(filas)


# --------------------------------------------------
# FUNCIÓN PRINCIPAL DEL MÓDULO
# --------------------------------------------------


def render_encuesta_calidad(vista, carrera):
    try:
        (
            df_virtual,
            df_esco,
            df_prep,
            df_aplic,
            areas_virtual,
            areas_esco,
            areas_prep,
        ) = cargar_datos_calidad()
    except Exception as e:
        st.error("No se pudieron cargar los datos de la Encuesta de calidad.")
        st.exception(e)
        st.stop()

    st.title("📝 Encuesta de calidad – Resultados")

    # --------------------------------------------------
    # NORMALIZAR Y UNIFICAR DATAFRAMES
    # --------------------------------------------------

    # Virtual / mixto
    df_v = df_virtual.copy()
    if "Marca temporal" in df_v.columns:
        df_v["Fecha"] = pd.to_datetime(df_v["Marca temporal"], errors="coerce")
    else:
        df_v["Fecha"] = pd.NaT

    col_programa_v = "Selecciona el programa académico que estudias"
    if col_programa_v in df_v.columns:
        df_v["Programa"] = df_v[col_programa_v].astype(str)
    else:
        df_v["Programa"] = "Sin programa"

    df_v["Tipo_servicio"] = "Virtual/Mixto"

    # Escolarizados / ejecutivas
    df_e = df_esco.copy()
    if "Marca temporal" in df_e.columns:
        df_e["Fecha"] = pd.to_datetime(df_e["Marca temporal"], errors="coerce")
    else:
        df_e["Fecha"] = pd.NaT

    col_programa_e = "Carrera de procedencia"
    if col_programa_e in df_e.columns:
        df_e["Programa"] = df_e[col_programa_e].astype(str)
    else:
        df_e["Programa"] = "Sin programa"

    df_e["Tipo_servicio"] = "Escolarizado/Ejecutivo"

    # Preparatoria
    df_p = df_prep.copy()
    if "Marca temporal" in df_p.columns:
        df_p["Fecha"] = pd.to_datetime(df_p["Marca temporal"], errors="coerce")
    else:
        df_p["Fecha"] = pd.NaT

    df_p["Programa"] = "Preparatoria"
    df_p["Tipo_servicio"] = "Preparatoria"

    # Unificar todo
    df_all = pd.concat([df_v, df_e, df_p], ignore_index=True)

    AREAS_POR_TIPO = {
        "Virtual/Mixto": areas_virtual,
        "Escolarizado/Ejecutivo": areas_esco,
        "Preparatoria": areas_prep,
    }

    # --------------------------------------------------
    # 🎛️ FILTROS: APLICACIÓN, TIPO, PROGRAMA
    # --------------------------------------------------

    st.markdown("### 🎛️ Filtros")

    # Filtro de aplicación (corte)
    col_app = st.columns(1)[0]

    if df_aplic.empty or "aplicacion_id" not in df_aplic.columns:
        aplic_sel = "Todas las aplicaciones"
        df_base = df_all.copy()
    else:
        aplicaciones_ids = (
            df_aplic["aplicacion_id"].dropna().astype(str).unique().tolist()
        )
        aplicaciones_ids = sorted(aplicaciones_ids)
        opciones_aplic = ["Todas las aplicaciones"] + aplicaciones_ids

        aplic_sel = col_app.selectbox(
            "Aplicación de la encuesta (corte)", opciones_aplic
        )

        df_base = df_all.copy()
        if aplic_sel != "Todas las aplicaciones":
            df_aplic_sel = df_aplic[df_aplic["aplicacion_id"] == aplic_sel]
            if not df_aplic_sel.empty:
                fecha_ini = df_aplic_sel["fecha_inicio"].min()
                fecha_fin = df_aplic_sel["fecha_fin"].max()
                if pd.notna(fecha_ini) and pd.notna(fecha_fin):
                    mask = (df_base["Fecha"] >= fecha_ini) & (
                        df_base["Fecha"] <= fecha_fin
                    )
                    df_base = df_base[mask]

    if df_base.empty:
        st.warning(
            "No hay encuestas en el rango de fechas de la aplicación seleccionada."
        )
        st.stop()

    # Filtros de tipo de servicio y programa
    col_f1, col_f2 = st.columns(2)

    tipos_disponibles = sorted(df_base["Tipo_servicio"].dropna().unique().tolist())
    opciones_tipos = ["Todos los tipos"] + tipos_disponibles

    with col_f1:
        tipo_sel = st.selectbox("Tipo de servicio", opciones_tipos)

    df_filtrado = df_base.copy()
    if tipo_sel != "Todos los tipos":
        df_filtrado = df_filtrado[df_filtrado["Tipo_servicio"] == tipo_sel]

    # Programa / carrera
    if vista == "Director de carrera" and carrera:
        programa_sel = carrera
        with col_f2:
            st.markdown(
                f"**Programa / servicio:** {carrera}  \n"
                f"*(fijado por vista de Director de carrera)*"
            )
        df_filtrado = df_filtrado[df_filtrado["Programa"] == programa_sel]
    else:
        programas_disp = (
            ["Todos los programas"]
            + sorted(df_filtrado["Programa"].dropna().unique().tolist())
        )
        with col_f2:
            programa_sel = st.selectbox("Programa / servicio", programas_disp)
        if programa_sel != "Todos los programas":
            df_filtrado = df_filtrado[df_filtrado["Programa"] == programa_sel]

    if df_filtrado.empty:
        st.warning("No hay encuestas para el filtro seleccionado.")
        st.stop()

    # Info rápida
    rango_fechas = df_filtrado["Fecha"].agg(["min", "max"])
    st.caption(
        f"Encuestas en el filtro actual: **{len(df_filtrado)}**  |  "
        f"Rango de fechas: "
        f"{rango_fechas['min'].date() if pd.notna(rango_fechas['min']) else '—'} "
        f"a {rango_fechas['max'].date() if pd.notna(rango_fechas['max']) else '—'}"
    )

    st.markdown("---")

    # --------------------------------------------------
    # KPIs + CÁLCULO DE ÁREAS
    # --------------------------------------------------

    df_areas, promedio_general = calcular_promedios_areas(df_filtrado, AREAS_POR_TIPO)

    total_encuestas = len(df_filtrado)
    area_mejor = df_areas.loc[df_areas["Promedio"].idxmax()] if not df_areas.empty else None
    area_peor = df_areas.loc[df_areas["Promedio"].idxmin()] if not df_areas.empty else None

    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    with col_k1:
        st.metric("Encuestas totales", total_encuestas)
    with col_k2:
        st.metric(
            "Promedio general",
            f"{promedio_general:.2f}" if promedio_general is not None else "—",
        )
    with col_k3:
        st.metric(
            "Área mejor evaluada",
            area_mejor["Área"] if area_mejor is not None else "—",
        )
    with col_k4:
        st.metric(
            "Área con menor puntuación",
            area_peor["Área"] if area_peor is not None else "—",
        )

    st.markdown("---")

    # --------------------------------------------------
    # TABS: ÁREAS, PROGRAMAS, COMENTARIOS
    # --------------------------------------------------

    tab_resumen, tab_programas, tab_comentarios = st.tabs(
        ["📊 Resumen por áreas", "🏫 Promedio por programa", "💬 Comentarios cualitativos"]
    )

    # --- TAB 1: RESUMEN POR ÁREAS ---
    with tab_resumen:
        st.subheader("Promedio por área de evaluación")

        if df_areas.empty:
            st.info("No hay información suficiente para calcular promedios por área.")
        else:
            df_areas_ord = df_areas.sort_values("Promedio", ascending=False)
            st.dataframe(df_areas_ord, use_container_width=True)

            chart_areas = (
                alt.Chart(df_areas_ord)
                .mark_bar()
                .encode(
                    x=alt.X("Área:N", sort="-y", title="Área"),
                    y=alt.Y("Promedio:Q", title="Promedio (1–5)"),
                    tooltip=["Área", alt.Tooltip("Promedio:Q", format=".2f")],
                )
                .properties(height=350)
            )
            st.altair_chart(chart_areas, use_container_width=True)

    # --- TAB 2: PROMEDIO POR PROGRAMA ---
    with tab_programas:
        st.subheader("Promedio general por programa / servicio")

        df_prog = calcular_promedio_por_programa(df_filtrado, AREAS_POR_TIPO)

        if df_prog.empty:
            st.info("No hay datos suficientes para mostrar promedios por programa.")
        else:
            df_prog_ord = df_prog.sort_values("Promedio_general", ascending=False)
            st.dataframe(df_prog_ord, use_container_width=True)

            chart_prog = (
                alt.Chart(df_prog_ord)
                .mark_bar()
                .encode(
                    x=alt.X("Programa:N", sort="-y", title="Programa"),
                    y=alt.Y("Promedio_general:Q", title="Promedio general (1–5)"),
                    color=alt.Color("Tipo_servicio:N", title="Tipo de servicio"),
                    tooltip=[
                        "Programa",
                        "Tipo_servicio",
                        alt.Tooltip("Promedio_general:Q", format=".2f"),
                        "Encuestas",
                    ],
                )
                .properties(height=350)
            )
            st.altair_chart(chart_prog, use_container_width=True)

    # --- TAB 3: COMENTARIOS CUALITATIVOS ---
    with tab_comentarios:
        st.subheader("Comentarios cualitativos")

        columnas_comentarios = [
            c
            for c in df_filtrado.columns
            if ("comentario" in normalizar_texto(c))
            or ("sugerencia" in normalizar_texto(c))
            or ("¿por que" in normalizar_texto(c))
        ]

        if not columnas_comentarios:
            st.info("No se encontraron columnas de comentarios en este conjunto de datos.")
        else:
            st.caption("Solo se muestran filas con al menos un comentario registrado.")
            df_com = df_filtrado[["Fecha", "Programa"] + columnas_comentarios].copy()

            mask_tiene_com = df_com[columnas_comentarios].apply(
                lambda row: any(isinstance(v, str) and v.strip() for v in row.values),
                axis=1,
            )
            df_com = df_com[mask_tiene_com]

            if df_com.empty:
                st.info("No hay comentarios registrados para el filtro actual.")
            else:
                st.dataframe(df_com, use_container_width=True)
