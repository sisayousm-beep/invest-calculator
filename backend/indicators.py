"""지표 계산 — 설계도 §3의 공식을 그대로 구현.

모든 함수는 pandas Series(일봉 종가/고가/저가)를 받아 Series를 돌려준다.
선행스팬은 '미시프트(원본 인덱스 정렬)' 상태로 반환하고, 시프트는
표시·판정 단계에서 ICHIMOKU_SHIFT 만큼 적용한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def rsi(close: pd.Series, period: int = C.RSI_PERIOD) -> pd.Series:
    """RSI (Wilder 평활). 첫 값 단순평균 후 이전평균*(p-1)/p + 당일*(1/p)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    # Wilder = ewm(alpha=1/period) 이지만 첫 시드를 단순평균으로 맞춘다.
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out


def macd(close: pd.Series, fast=C.MACD_FAST, slow=C.MACD_SLOW, signal=C.MACD_SIGNAL):
    """MACD선 / 시그널선 / 히스토그램."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series):
    """일목균형표. 선행스팬은 미시프트 반환(시프트는 호출부 책임)."""
    conv = (high.rolling(C.ICHIMOKU_CONV).max() + low.rolling(C.ICHIMOKU_CONV).min()) / 2
    base = (high.rolling(C.ICHIMOKU_BASE).max() + low.rolling(C.ICHIMOKU_BASE).min()) / 2
    span_a = (conv + base) / 2
    span_b = (high.rolling(C.ICHIMOKU_SPAN_B).max() + low.rolling(C.ICHIMOKU_SPAN_B).min()) / 2
    lagging = close.shift(-C.ICHIMOKU_SHIFT)  # 후행스팬: 당일 종가를 26일 뒤로
    return {"conv": conv, "base": base, "span_a": span_a, "span_b": span_b, "lagging": lagging}


def bollinger(close: pd.Series, period=C.BB_PERIOD, num_std=C.BB_STD):
    """볼린저밴드. std는 모표준편차(ddof=0)."""
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    width = (upper - lower) / mid
    return {"mid": mid, "upper": upper, "lower": lower, "width": width}


def percent_b(close: pd.Series, upper: pd.Series, lower: pd.Series) -> pd.Series:
    """%B = (현재가 - 하단) / (상단 - 하단)."""
    span = (upper - lower).replace(0, np.nan)
    return (close - lower) / span


def compute_all(df: pd.DataFrame) -> dict:
    """OHLC DataFrame → 전 지표 dict (전부 원본 인덱스 정렬, 미시프트)."""
    close, high, low = df["close"], df["high"], df["low"]
    macd_line, signal_line, hist = macd(close)
    bb = bollinger(close)
    ich = ichimoku(high, low, close)
    return {
        "rsi": rsi(close),
        "macd": macd_line,
        "signal": signal_line,
        "hist": hist,
        "mid": bb["mid"],
        "upper": bb["upper"],
        "lower": bb["lower"],
        "width": bb["width"],
        "pb": percent_b(close, bb["upper"], bb["lower"]),
        "conv": ich["conv"],
        "base": ich["base"],
        "span_a": ich["span_a"],
        "span_b": ich["span_b"],
        "lagging": ich["lagging"],
    }
