import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2.service_account import Credentials
import altair as alt

# -------------------------------------------------------------------
# CONFIGURACIÓN BÁSICA
# -------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Archivo maestro de calidad
SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)

# Nombre estándar de columna de carrera (ya sin espacios al final)
COLUMNA_CARRERA = "Carrera de procedencia"

# -------------------------------------------------------------------
# ESCALAS DE CONVERSIÓN TEXTO → NÚMEROS
# -------------------------------------------------------------------

ESCALA_ACUERDO = {
    "totalmente de acuerdo": 4,
    "de acuerdo": 3,
    "en desacuerdo": 2,
    "totalmente en desacuerdo": 1,
}

ESCALA_FRECUENCIA = {
    "siempre": 4,
    "casi siempre": 3,
    "algunas veces": 2,
    "nunca": 1,
}

# Escala 0–5: No lo utilizo, Muy malo, Malo, Regular, Bueno, Excelente
ESCALA_DESEMPEÑO = {
    "no lo utilizo": 0,
    "muy malo": 1,
    "malo": 2,
    "regular": 3,
    "bueno": 4,
    "excelente": 5,
}

# Si tienes otras escalas, las podemos agregar aquí:
# ESCALA_OTRA = { ... }

# Unimos todas en un solo diccionario de reemplazo
MAPA_TEXTO_A_NUM = {}
MAPA_TEXTO_A_NUM.update(ESCALA_ACUERDO)
MAPA_TEXTO_A_NUM.update(ESCALA_FRECUENCIA)
MAPA_TEXTO_A_NUM.update(ESCALA_DESEMPEÑO)
# MAPA_TEXTO_A_NUM.update(ESCALA_OTRA)

# -------------------------------------------------------------------
# UTILIDADES
# -------------------------------------------------------------------


def _normalizar_texto(txt: str) -> str:
    if txt is None:
        return ""
    return str(txt).strip().lower()


def detectar_modalidad(formulario: str) -> str:
    t = _normalizar_texto(formulario)

    if "virtual" in t and "mixto" in t:
        return "virtual"
    if "escolarizados" in t or "licenciaturas ejecutivas" in t:
        return "escolar"
    if "preparatoria" in t or "prepa" in t:
        return "prepa"

    return "desconocida"


def obtener_nombre_hoja(formulario: str) -> str:
    t = _normalizar_texto(formulario)

    if "virtual" in t and "mixto" in t:
        return "servicios virtual y mixto virtual"
    if "escolarizados" in t or "licenciaturas ejecutivas" in t:
        return "servicios escolarizados y licenciaturas ejecutivas"
    if "preparatoria" in t or "prepa" in t:
        return "Preparatoria"

    return formulario


def _limpiar_nombres_columnas(df: pd.DataFrame) -> pd.DataFrame:
    cols_limpias = []
    for c in df.columns:
        if isinstance(c, str):
            cols_limpias.append(c.strip())
        else:
            cols_limpias.append(c)
    df.columns = cols_limpias
    return df


def _buscar_hoja_flexible(sh, nombre_hoja: str):
    try:
        hojas = sh.worksheets()
    except Exception as e:
        st.error("No se pudieron listar las hojas del archivo de encuestas.")
        st.exception(e)
        return None

    objetivo = _normalizar_texto(nombre_hoja)

    for ws in hojas:
        if _normalizar_texto(ws.title) == objetivo:
            return ws

    for ws in hojas:
        if objetivo in _normalizar_texto(ws.title):
            return ws

    return None


def leer_hoja_a_dataframe(sh, nombre_hoja: str) -> pd.DataFrame:
    try:
        ws = sh.worksheet(nombre_hoja)
    except Exception:
        ws = _buscar_hoja_flexible(sh, nombre_hoja)
        if ws is None:
            st.error(
                f"No se encontró la hoja '{nombre_hoja}' "
                "ni una coincidencia aproximada en el archivo."
            )
            try:
                nombres = [w.title for w in sh.worksheets()]
                st.info("Hojas disponibles en el archivo: " + ", ".join(nombres))
            except Exception:
                pass
            return pd.DataFrame()

    try:
        values = ws.get_all_values()
    except Exception as e:
        st.error(f"No se pudieron leer los datos de la hoja '{ws.title}'.")
        st.exception(e)
        return pd.DataFrame()

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

    df = pd.DataFrame(data, columns=header_unique)
    df = _limpiar_nombres_columnas(df)
    return df


def _convertir_textos_a_numeros(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    for col in df.columns:
        if df[col].dtype == "object":
            serie_lower = df[col].astype(str).str.lower().str.strip()
            serie_num = serie_lower.map(MAPA_TEXTO_A_NUM)

            if serie_num.notna().sum() > 0:
                df[col] = serie_num.where(serie_num.notna(), df[col])

    for col in df.columns:
        if df[col].dtype == "object":
            try:
                conv = pd.to_numeric(df[col], errors="coerce")
            except Exception:
                continue
            if conv.notna().sum() > 0:
                df[col] = conv

    return df


def _convertir_columnas_likert(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    likert_permitidos = {str(i) for i in range(0, 11)}  # 0 a 10

    for col in df.columns:
        if df[col].dtype == "object":
            valores = pd.Series(df[col].dropna().astype(str).str.strip())
            valores = valores[valores != ""]
            if valores.empty:
                continue

            unicos = set(valores.unique())
            if 1 <= len(unicos) <= 11 and unicos.issubset(likert_permitidos):
                df[col] = pd.to_numeric(df[col].str.strip(), errors="coerce")

    return df


# -------------------------------------------------------------------
# CARGA DE DATOS
# -------------------------------------------------------------------


@st.cache_data(ttl=60)
def cargar_datos_calidad():
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)

    try:
        sh = client.open_by_url(SPREADSHEET_URL)
    except Exception as e:
        st.error("No se pudo abrir el archivo de Google Sheets de encuestas.")
        st.exception(e)
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        )

    df_virtual = leer_hoja_a_dataframe(sh, "servicios virtual y mixto virtual")
    df_esco = leer_hoja_a_dataframe(
        sh, "servicios escolarizados y licenciaturas ejecutivas"
    )
    df_prepa = leer_hoja_a_dataframe(sh, "Preparatoria")
    df_aplic = leer_hoja_a_dataframe(sh, "Aplicaciones")

    if not df_aplic.empty:
        for col in ["fecha_inicio", "fecha_fin"]:
            if col in df_aplic.columns:
                df_aplic[col] = pd.to_datetime(
                    df_aplic[col], dayfirst=True, errors="coerce"
                )

        if "formulario" in df_aplic.columns:
            df_aplic["formulario"] = df_aplic["formulario"].astype(str).str.strip()
        else:
            df_aplic["formulario"] = ""

        if "hoja_respuestas" in df_aplic.columns:
            df_aplic["hoja_respuestas"] = (
                df_aplic["hoja_respuestas"].astype(str).str.strip()
            )

    def normalizar_respuestas(df, modalidad_label: str | None = None):
        if df.empty:
            return df

        if "Marca temporal" in df.columns:
            df["Marca temporal"] = pd.to_datetime(
                df["Marca temporal"], dayfirst=True, errors="coerce"
            )

        df = _convertir_textos_a_numeros(df)
        df = _convertir_columnas_likert(df)

        if modalidad_label is not None:
            df["Modalidad"] = modalidad_label

        return df

    df_virtual = normalizar_respuestas(df_virtual, "virtual")
    df_esco = normalizar_respuestas(df_esco, "escolar")
    df_prepa = normalizar_respuestas(df_prepa, "prepa")

    return df_virtual, df_esco, df_prepa, df_aplic


# -------------------------------------------------------------------
# INTERFAZ PRINCIPAL
# -------------------------------------------------------------------


def render_encuesta_calidad(vista: str, carrera_seleccionada: str | None):
    st.header("📊 Encuesta de calidad – Resultados")

    df_virtual, df_esco, df_prepa, df_aplic = cargar_datos_calidad()

    if df_aplic.empty:
        st.warning("No se pudieron cargar las aplicaciones de la encuesta.")
        return

    df_aplic = df_aplic.copy()

    if "descripcion" not in df_aplic.columns:
        if "aplicacion_id" in df_aplic.columns:
            df_aplic["descripcion"] = df_aplic["aplicacion_id"].astype(str)
        else:
            df_aplic["descripcion"] = "Aplicación sin descripción"

    df_aplic["label"] = df_aplic["descripcion"]

    opciones = df_aplic["label"].tolist()
    if not opciones:
        st.warning("No hay filas en la hoja 'Aplicaciones'.")
        return

    label_sel = st.selectbox(
        "Selecciona la aplicación de la encuesta:",
        opciones,
    )

    fila_aplic = df_aplic[df_aplic["label"] == label_sel].iloc[0]

    formulario = fila_aplic.get("formulario", "")
    aplic_id = fila_aplic.get("aplicacion_id", "")
    f_ini = fila_aplic.get("fecha_inicio", pd.NaT)
    f_fin = fila_aplic.get("fecha_fin", pd.NaT)

    hoja_respuestas_explicit = (
        fila_aplic.get("hoja_respuestas", "")
        if "hoja_respuestas" in df_aplic.columns
        else ""
    )
    hoja_respuestas_explicit = str(hoja_respuestas_explicit).strip()

    if hoja_respuestas_explicit:
        nombre_hoja = hoja_respuestas_explicit
        t_hoja = _normalizar_texto(nombre_hoja)
        if "virtual" in t_hoja:
            modalidad = "virtual"
        elif "escolarizados" in t_hoja or "ejecutivas" in t_hoja:
            modalidad = "escolar"
        elif "preparatoria" in t_hoja or "prepa" in t_hoja:
            modalidad = "prepa"
        else:
            modalidad = detectar_modalidad(formulario)
    else:
        modalidad = detectar_modalidad(formulario)
        nombre_hoja = obtener_nombre_hoja(formulario)

    st.write(
        f"Aplicación seleccionada: **{fila_aplic['descripcion']}**  "
        f"(ID: `{aplic_id}`)"
    )
    st.write(f"Formulario: `{formulario}` · Hoja de respuestas: `{nombre_hoja}`")
    st.write(f"Modalidad detectada: **{modalidad}**")
    st.write(
        "Rango de fechas considerado: "
        f"{f_ini.date() if pd.notna(f_ini) else '—'} a "
        f"{f_fin.date() if pd.notna(f_fin) else '—'}"
    )

    vista_lower = (vista or "").lower()
    es_vista_global = any(
        clave in vista_lower
        for clave in ["dirección general", "direccion general", "académica", "academica"]
    )

    if es_vista_global:
        df_base = pd.concat(
            [df_virtual.copy(), df_esco.copy(), df_prepa.copy()],
            ignore_index=True,
        )
    else:
        if modalidad == "virtual":
            df_base = df_virtual.copy()
        elif modalidad == "escolar":
            df_base = df_esco.copy()
        elif modalidad == "prepa":
            df_base = df_prepa.copy()
        else:
            st.warning(
                "No se pudo detectar claramente la modalidad. "
                "Se intenta usar el nombre de hoja derivado."
            )
            df_virtual2, df_esco2, df_prepa2, _ = cargar_datos_calidad()
            nombre_lower = nombre_hoja.lower()
            if nombre_lower.startswith("servicios virtual"):
                df_base = df_virtual2.copy()
            elif nombre_lower.startswith("servicios escolarizados"):
                df_base = df_esco2.copy()
            elif nombre_lower.startswith("preparatoria"):
                df_base = df_prepa2.copy()
            else:
                df_base = pd.DataFrame()

    if df_base.empty:
        st.warning(
            "La hoja de respuestas correspondiente está vacía "
            "o no se pudo leer. Verifica el nombre de las hojas en el archivo."
        )
        return

    total_original = len(df_base)

    df_filtrado = df_base.copy()

    if pd.notna(f_ini) and pd.notna(f_fin):
        if f_ini > f_fin:
            f_ini, f_fin = f_fin, f_ini

        if "Marca temporal" in df_filtrado.columns:
            f_fin_exclusivo = f_fin + pd.Timedelta(days=1)
            mask = (df_filtrado["Marca temporal"] >= f_ini) & (
                df_filtrado["Marca temporal"] < f_fin_exclusivo
            )
            df_filtrado = df_filtrado.loc[mask]

    if (
        vista == "Director de carrera"
        and carrera_seleccionada
        and COLUMNA_CARRERA in df_filtrado.columns
    ):
        df_filtrado = df_filtrado[
            df_filtrado[COLUMNA_CARRERA] == carrera_seleccionada
        ]

    total_filtrado = len(df_filtrado)

    st.caption(
        f"Respuestas totales en la hoja de esta modalidad / vista: **{total_original}** · "
        f"Respuestas después de aplicar fechas y filtros: **{total_filtrado}**"
    )

    if df_filtrado.empty:
        st.warning("No hay respuestas en el rango de fechas para esta aplicación.")
   
