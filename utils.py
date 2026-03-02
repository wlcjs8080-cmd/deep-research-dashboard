# utils.py — 헬퍼 유틸리티 함수들
import datetime
import numpy as np
import pandas as pd


def fmt_num(val, prefix="", suffix="", decimals=2) -> str:
    """숫자를 K/M/B/T 단위로 포맷팅"""
    if val is None:
        return "N/A"
    try:
        v = float(val)
        if np.isnan(v):
            return "N/A"
        if abs(v) >= 1e12:
            return f"{prefix}{v/1e12:.{decimals}f}T{suffix}"
        if abs(v) >= 1e9:
            return f"{prefix}{v/1e9:.{decimals}f}B{suffix}"
        if abs(v) >= 1e6:
            return f"{prefix}{v/1e6:.{decimals}f}M{suffix}"
        return f"{prefix}{v:.{decimals}f}{suffix}"
    except Exception:
        return "N/A"


def safe_pct(val) -> str:
    try:
        return f"{float(val)*100:.1f}%"
    except Exception:
        return "N/A"


def safe_float(val, decimals=2) -> str:
    try:
        return f"{float(val):.{decimals}f}"
    except Exception:
        return "N/A"


def df_safe(obj) -> pd.DataFrame:
    """None이면 빈 DataFrame 반환"""
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj
    return pd.DataFrame()


def serialize_obj(obj):
    """JSON 직렬화 가능하도록 변환"""
    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return str(obj)
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): serialize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_obj(i) for i in obj]
    return obj
