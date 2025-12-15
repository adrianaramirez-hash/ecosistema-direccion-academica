import re
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# =========================
# CONFIG
# =========================
SCOPES_RW = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ORIGINAL (fuente)
ORIGINAL_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU/edit"
)

# PROCESADO (destino) – el que creaste
PROCESADO_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1zwa-cG8Bwn6IA0VBrW_gsIb-bB92nTpa2H5sS4LVvak/edit"
)

SRC_VIRTUAL = "servicios virtual y mixto virtual"
SRC_ESCOLAR = "servicios escolarizados y licenciaturas ejecutivas"
SRC_PREPA = "Preparatoria"

DST_VIRTUAL = "Virtual_num"
DST_ESCOLAR = "Escolar_num"
DST_PREPA = "Prepa_num"
DST_RES_FORM = "Resumen_formularios"
DST_RES_SEC = "Resumen_secciones"
DST_COMENT = "Comentarios"
DST_LOG = "Log_conversion"

COLUMNA_TIMESTAMP = "Marca temporal"
COLUMNA_CARRERA = "Carrera de procedencia"

# =========================
# SECCIONES (rangos Excel)
# =========================
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

# =========================
# Conversión texto → número
# =========================
MAPA_TEXTO_A_NUM = {
    "no lo utilizo": 0,
    "no lo uso": 0,
    "muy malo": 1,
    "malo": 2,
    "regular": 3,
    "bueno": 4,
    "excelente": 5,
    "muy insatisfecho": 1,
    "insatisfecho": 2,
    "neutral": 3,
    "satisfecho": 4,
    "muy satisfecho": 5,
    "sí": 5,
    "si": 5,
    "no": 1,
    "n/a": None,
    "na": None,
    "no aplica": None,
    "": None,
}

DIGIT_0_5 = re.compile(r"^\s*([0-5])\s*$")
LEADING_DIGIT = re.compile(r"^\s*([0-5])\s*[-–—\.:]\s*.*$")  # "5 - Excelente"

COMENTARIOS_HINTS = [
    "¿por qué", "por qué", "porque", "por que",
    "coment", "suger", "observ", "explica", "describe", "motivo",
]

def _norm(x) -> str:
    return "" if x is None else str(x).strip().lower()

def es_columna_comentario(nombre_col: str) -> bool:
    t = _norm(nombre_col)
    return any(h in t for h in COMENTARIOS_HINTS)

def convertir_valor_a_num(v):
    t = _norm(v)
    if t in ("", "nan", "none"):
        return None
    m = DIGIT_0_5.match(t)
    if m:
        return float(m.group(1))
    m2 = LEADING_DIGIT.match(t)
    if m2:
        return float(m2.group(1))
    if t in MAPA_TEXTO_A_NUM:
        return MAPA_TEXTO_A_NUM[t]
    return None

# =========================
# Excel col → índice
# =========================
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
    return cols[i:j+1]

# =========================
# Sheets IO
# =========================
def _buscar_hoja_flexible(sh, nombre: str):
    objetivo = _norm(nombre)
    for ws in sh.worksheets():
        if _norm(ws.title) == objetivo:
            return ws
    for ws in sh.worksheets():
        if objetivo in _norm(ws.title):
            return ws
    return None

def leer_sheet_df(sh, nombre_hoja: str) -> pd.DataFrame:
    try:
        ws = sh.worksheet(nombre_hoja)
    except Exception:
        ws = _buscar_hoja_flexible(sh, nombre_hoja)
    if ws is None:
        return pd.DataFrame()

    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame()

    header = values[0]
    data = values[1:]

    # headers únicos (evita problemas)
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

def asegurar_worksheet(sh, title: str, rows=2000, cols=200):
    try:
        return sh.worksheet(title)
    except Exception:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)

def escribir_df(ws, df: pd.DataFrame):
    ws.clear()
    if df.empty:
        ws.update([["(sin datos)"]])
        return

    df_out = df.copy()
    # Google Sheets no acepta NaN, los pasamos a ""
    df_out = df_out.astype(object).where(pd.notna(df_out), "")

    values = [df_out.columns.tolist()] + df_out.values.tolist()
    ws.update(values)

# =========================
# Procesamiento
# =========================
def convertir_df_a_numerico(df: pd.DataFrame, modalidad: str):
    """
    Convierte SOLO reactivos dentro de los rangos de secciones.
    Regresa df convertido + log de textos desconocidos.
    """
    if df.empty:
        return df, pd.DataFrame(columns=["Modalidad", "Columna", "Texto_no_reconocido", "Conteo"])

    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # timestamp
    if COLUMNA_TIMESTAMP in df.columns:
        df[COLUMNA_TIMESTAMP] = pd.to_datetime(df[COLUMNA_TIMESTAMP], dayfirst=True, errors="coerce")

    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    cols_en_secciones = []
    for _, (a, b) in secciones.items():
        cols_en_secciones.extend(cols_por_rango(df, a, b))
    cols_en_secciones = list(dict.fromkeys(cols_en_secciones))

    log_rows = []

    for col in cols_en_secciones:
        if col not in df.columns:
            continue
        if es_columna_comentario(col):
            continue

        originales = df[col].astype(str).fillna("").tolist()
        convertidos = []
        for v in originales:
            convertidos.append(convertir_valor_a_num(v))

            t = _norm(v)
            if t in ("", "nan", "none"):
                continue
            if DIGIT_0_5.match(t) or LEADING_DIGIT.match(t) or (t in MAPA_TEXTO_A_NUM):
                continue
            log_rows.append((modalidad, col, v))

        ser_num = pd.to_numeric(pd.Series(convertidos), errors="coerce")
        if ser_num.notna().sum() > 0:
            df[col] = ser_num

    df["Modalidad"] = modalidad

    if log_rows:
        dflog = pd.DataFrame(log_rows, columns=["Modalidad", "Columna", "Texto_no_reconocido"])
        dflog = dflog.value_counts().reset_index(name="Conteo")
    else:
        dflog = pd.DataFrame(columns=["Modalidad", "Columna", "Texto_no_reconocido", "Conteo"])

    return df, dflog

def resumen_formularios(df_v, df_e, df_p):
    def prom(df, modalidad):
        if df.empty:
            return None
        secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
        num_cols = []
        for _, (a, b) in secciones.items():
            cols = cols_por_rango(df, a, b)
            for c in cols:
                if c in df.columns and pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().sum() > 0:
                    num_cols.append(c)
        num_cols = list(dict.fromkeys(num_cols))
        if not num_cols:
            return None
        return float(df[num_cols].mean(axis=1).mean())

    return pd.DataFrame([
        {"Formulario": "Virtual y Mixto Virtual", "Modalidad": "virtual", "Respuestas": len(df_v), "Promedio": prom(df_v, "virtual")},
        {"Formulario": "Escolarizados y Lic. Ejecutivas", "Modalidad": "escolar", "Respuestas": len(df_e), "Promedio": prom(df_e, "escolar")},
        {"Formulario": "Preparatoria", "Modalidad": "prepa", "Respuestas": len(df_p), "Promedio": prom(df_p, "prepa")},
    ])

def resumen_secciones(df, modalidad: str):
    secciones = SECCIONES_POR_MODALIDAD.get(modalidad, {})
    rows = []
    for sec, (a, b) in secciones.items():
        cols = cols_por_rango(df, a, b)
        num_cols = [c for c in cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().sum() > 0]
        val = float(df[num_cols].mean(axis=1).mean()) if num_cols else None
        rows.append({
            "Modalidad": modalidad,
            "Sección": sec,
            "Promedio": val,
            "Reactivos_usados": len(num_cols),
            "Respuestas": len(df),
        })
    return pd.DataFrame(rows)

def extraer_comentarios(df: pd.DataFrame):
    if df.empty:
        return pd.DataFrame()
    cols_com = [c for c in df.columns if es_columna_comentario(c)]
    base = [c for c in [COLUMNA_TIMESTAMP, COLUMNA_CARRERA] if c in df.columns]
    keep = list(dict.fromkeys(["Modalidad"] + base + cols_com))
    if not keep:
        return pd.DataFrame()
    return df[keep].copy()

# =========================
# MAIN
# =========================
def main(service_account_json: str):
    creds_dict = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES_RW)
    client = gspread.authorize(creds)

    sh_src = client.open_by_url(ORIGINAL_URL)
    sh_dst = client.open_by_url(PROCESADO_URL)

    raw_v = leer_sheet_df(sh_src, SRC_VIRTUAL)
    raw_e = leer_sheet_df(sh_src, SRC_ESCOLAR)
    raw_p = leer_sheet_df(sh_src, SRC_PREPA)

    df_v, log_v = convertir_df_a_numerico(raw_v, "virtual")
    df_e, log_e = convertir_df_a_numerico(raw_e, "escolar")
    df_p, log_p = convertir_df_a_numerico(raw_p, "prepa")

    df_res_form = resumen_formularios(df_v, df_e, df_p)
    df_res_sec = pd.concat(
        [resumen_secciones(df_v, "virtual"),
         resumen_secciones(df_e, "escolar"),
         resumen_secciones(df_p, "prepa")],
        ignore_index=True
    )

    df_com = pd.concat(
        [extraer_comentarios(df_v), extraer_comentarios(df_e), extraer_comentarios(df_p)],
        ignore_index=True
    )

    df_log = pd.concat([log_v, log_e, log_p], ignore_index=True)
    if df_log.empty:
        df_log = pd.DataFrame([{
            "Modalidad": "",
            "Columna": "",
            "Texto_no_reconocido": "SIN_TEXTOS_NO_RECONOCIDOS",
            "Conteo": 0
        }])

    # asegurar hojas destino
    ws_v = asegurar_worksheet(sh_dst, DST_VIRTUAL)
    ws_e = asegurar_worksheet(sh_dst, DST_ESCOLAR)
    ws_p = asegurar_worksheet(sh_dst, DST_PREPA)
    ws_rf = asegurar_worksheet(sh_dst, DST_RES_FORM)
    ws_rs = asegurar_worksheet(sh_dst, DST_RES_SEC)
    ws_c = asegurar_worksheet(sh_dst, DST_COMENT)
    ws_l = asegurar_worksheet(sh_dst, DST_LOG)

    # escribir
    escribir_df(ws_v, df_v)
    escribir_df(ws_e, df_e)
    escribir_df(ws_p, df_p)
    escribir_df(ws_rf, df_res_form)
    escribir_df(ws_rs, df_res_sec)
    escribir_df(ws_c, df_com)
    escribir_df(ws_l, df_log)

    print("OK. Filas escritas:")
    print({"virtual": len(df_v), "escolar": len(df_e), "prepa": len(df_p), "comentarios": len(df_com), "log": len(df_log)})

# Ejecución local:
# 1) Exporta tu JSON como variable de entorno o pégalo en un archivo.
# 2) Llama main(<json_string>)
if __name__ == "__main__":
    # Si lo ejecutas fuera de Streamlit, pega aquí el JSON del service account
    # o cárgalo desde un archivo y pásalo como string.
    raise SystemExit(
        "Ejecuta main(service_account_json) desde tu entorno. "
        "Ejemplo: main(open('service_account.json','r',encoding='utf-8').read())"
    )
