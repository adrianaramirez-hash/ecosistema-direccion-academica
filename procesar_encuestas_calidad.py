import json
import re
from collections.abc import Mapping
from typing import Any, Dict, List, Tuple

import pandas as pd
import numpy as np  # <-- AJUSTE: necesario para np.nan
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIG
# ============================================================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ORIGINAL_KEY = "1WAk0Jv42MIyn0iImsAT2YuCsC8-YphKnFxgJYQZKjqU"
PROCESADO_KEY = "1zwa-cG8Bwn6IA0VBrW_gsIb-bB92nTpa2H5sS4LVvak"

# Hojas origen (búsqueda flexible, por si cambian mayúsculas)
ORIG_VIRTUAL = "servicios virtual y mixto virtual"
ORIG_ESCOLAR = "servicios escolarizados y licenciaturas ejecutivas"
ORIG_PREPA = "Preparatoria"

# Hojas destino (fijas)
DEST_VIRTUAL = "Virtual_num"
DEST_ESCOLAR = "Escolar_num"
DEST_PREPA = "Prepa_num"
DEST_COMENTARIOS = "Comentarios"
DEST_LOG = "Log_conversion"

# ============================================================
# CONVERSIÓN TEXTO -> NÚMERO
# ============================================================
COMENTARIOS_HINTS = [
    "¿por qué", "por qué", "porque", "por que",
    "coment", "suger", "observ", "explica", "describe", "descríb", "motivo",
    "en caso afirmativo", "escríbelo", "escribelo"
]

MAPA_TEXTO_A_NUM = {
    # “No aplica”
    "n/a": None,
    "na": None,
    "no aplica": None,

    # uso/no uso
    "no lo utilizo": 0,
    "no lo uso": 0,

    # escala de desempeño / satisfacción (1–5)
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

    # sí/no (recomendación)
    "sí": 5,
    "si": 5,
    "no": 1,
}

DIGIT_RE = re.compile(r"^\s*([0-5])\s*$")
LEADING_DIGIT_RE = re.compile(r"^\s*([0-5])\s*[-–—\.]\s*.*$")  # "5 - Excelente"


def _norm(x: Any) -> str:
    return str(x).strip().lower() if x is not None else ""


def es_columna_comentario(nombre_col: str) -> bool:
    t = _norm(nombre_col)
    return any(h in t for h in COMENTARIOS_HINTS)


def convertir_valor(v: Any) -> Tuple[Any, str]:
    """
    Retorna (valor_convertido, status)
    status:
      - "ok_num"     -> ya era número 0–5
      - "ok_map"     -> mapeo por diccionario
      - "ok_leading" -> "5 - Excelente"
      - "na"         -> vacío / no aplica
      - "unknown"    -> texto no convertible
    """
    t = _norm(v)

    if t in ("", "none", "nan"):
        return (None, "na")

    # número directo
    m = DIGIT_RE.match(t)
    if m:
        return (float(m.group(1)), "ok_num")

    # "5 - Excelente"
    m2 = LEADING_DIGIT_RE.match(t)
    if m2:
        return (float(m2.group(1)), "ok_leading")

    # mapa literal
    if t in MAPA_TEXTO_A_NUM:
        return (MAPA_TEXTO_A_NUM[t], "ok_map" if MAPA_TEXTO_A_NUM[t] is not None else "na")

    return (None, "unknown")


# ============================================================
# GOOGLE SHEETS HELPERS
# ============================================================
def _to_plain_dict(v: Any) -> Any:
    if isinstance(v, Mapping):
        return dict(v)
    return v


def _parse_service_account_info(gcp_service_account_json: Any) -> Dict[str, Any]:
    v = _to_plain_dict(gcp_service_account_json)
    if isinstance(v, str):
        return json.loads(v)
    if isinstance(v, dict):
        return v
    raise TypeError("gcp_service_account_json debe ser str(JSON) o dict")


def _authorize(gcp_service_account_json: Any):
    info = _parse_service_account_info(gcp_service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def _buscar_hoja_flexible(sh, nombre_hoja: str):
    objetivo = _norm(nombre_hoja)
    for ws in sh.worksheets():
        if _norm(ws.title) == objetivo:
            return ws
    for ws in sh.worksheets():
        if objetivo in _norm(ws.title):
            return ws
    return None


def leer_hoja_df(sh, nombre_hoja: str) -> pd.DataFrame:
    ws = None
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

    df = pd.DataFrame(data, columns=header_unique)
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    return df


def _get_or_create_worksheet(sh, title: str, rows: int = 2000, cols: int = 200):
    try:
        return sh.worksheet(title)
    except Exception:
        return sh.add_worksheet(title=title, rows=str(rows), cols=str(cols))


def _clear_and_write(ws, df: pd.DataFrame):
    ws.clear()
    if df.empty:
        ws.update([["SIN_DATOS"]])
        return

    out = df.copy()

    # Google Sheets no acepta NaN
    out = out.replace({np.nan: ""})

    values = [out.columns.tolist()] + out.astype(object).values.tolist()
    ws.update(values)


# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================
def procesar_formulario(df: pd.DataFrame, modalidad_label: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, pd.DataFrame(), pd.DataFrame()

    df_out = df.copy()
    logs: List[Dict[str, Any]] = []
    comentarios_rows: List[Dict[str, Any]] = []

    comentario_cols = [c for c in df_out.columns if es_columna_comentario(c)]

    if comentario_cols:
        if "Modalidad" not in df_out.columns:
            df_out["Modalidad"] = modalidad_label

        base_cols = [c for c in ["Marca temporal", "Carrera de procedencia", "Selecciona el programa académico que estudias", "Modalidad"] if c in df_out.columns]
        df_com = df_out[base_cols + comentario_cols].copy()
        comentarios_rows = df_com.to_dict(orient="records")

    for col in df_out.columns:
        if col == "Modalidad":
            continue
        if es_columna_comentario(col):
            continue

        col_vals = df_out[col].tolist()
        converted = []
        ok_count = 0

        for i, v in enumerate(col_vals):
            num, status = convertir_valor(v)

            if status == "unknown":
                if _norm(v) not in ("", "none", "nan"):
                    logs.append({
                        "Modalidad": modalidad_label,
                        "Columna": col,
                        "Fila": i + 2,
                        "Valor_original": v,
                        "Estatus": status,
                    })
            else:
                ok_count += 1

            converted.append(num)

        if ok_count > 0:
            df_out[col] = pd.to_numeric(pd.Series(converted), errors="coerce")

    df_log = pd.DataFrame(logs)
    df_com = pd.DataFrame(comentarios_rows)

    if "Modalidad" not in df_out.columns:
        df_out["Modalidad"] = modalidad_label

    return df_out, df_com, df_log


def procesar_todo(gcp_service_account_json: Any) -> Dict[str, Any]:
    client = _authorize(gcp_service_account_json)

    sh_orig = client.open_by_key(ORIGINAL_KEY)
    sh_dest = client.open_by_key(PROCESADO_KEY)

    df_v = leer_hoja_df(sh_orig, ORIG_VIRTUAL)
    df_e = leer_hoja_df(sh_orig, ORIG_ESCOLAR)
    df_p = leer_hoja_df(sh_orig, ORIG_PREPA)

    v_num, v_com, v_log = procesar_formulario(df_v, "Virtual")
    e_num, e_com, e_log = procesar_formulario(df_e, "Escolar")
    p_num, p_com, p_log = procesar_formulario(df_p, "Prepa")

    df_com_all = (
        pd.concat([v_com, e_com, p_com], ignore_index=True)
        if any([not v_com.empty, not e_com.empty, not p_com.empty])
        else pd.DataFrame()
    )
    df_log_all = (
        pd.concat([v_log, e_log, p_log], ignore_index=True)
        if any([not v_log.empty, not e_log.empty, not p_log.empty])
        else pd.DataFrame()
    )

    ws_v = _get_or_create_worksheet(sh_dest, DEST_VIRTUAL)
    ws_e = _get_or_create_worksheet(sh_dest, DEST_ESCOLAR)
    ws_p = _get_or_create_worksheet(sh_dest, DEST_PREPA)
    ws_c = _get_or_create_worksheet(sh_dest, DEST_COMENTARIOS)
    ws_l = _get_or_create_worksheet(sh_dest, DEST_LOG)

    _clear_and_write(ws_v, v_num)
    _clear_and_write(ws_e, e_num)
    _clear_and_write(ws_p, p_num)
    _clear_and_write(ws_c, df_com_all)
    _clear_and_write(ws_l, df_log_all)

    return {
        "status": "ok",
        "original": ORIGINAL_KEY,
        "procesado": PROCESADO_KEY,
        "rows_virtual": int(len(v_num)),
        "rows_escolar": int(len(e_num)),
        "rows_prepa": int(len(p_num)),
        "comentarios_rows": int(len(df_com_all)) if not df_com_all.empty else 0,
        "log_rows": int(len(df_log_all)) if not df_log_all.empty else 0,
        "sheets_written": [DEST_VIRTUAL, DEST_ESCOLAR, DEST_PREPA, DEST_COMENTARIOS, DEST_LOG],
    }


# ============================================================
# FUNCIÓN main (OBLIGATORIA PARA app.py)
# ============================================================
def main(gcp_service_account_json: Any) -> Dict[str, Any]:
    """
    Entry point esperado por app.py:
      resultado = proc.main(st.secrets["gcp_service_account_json"])
    """
    return procesar_todo(gcp_service_account_json)
