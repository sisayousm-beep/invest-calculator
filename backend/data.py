"""데이터 레이어 — yfinance 수집 + 메모리 캐시 + 티커 정규화 (설계도 §2).

yfinance가 차단/오프라인이면 결정론적 합성 데이터로 폴백해 앱이 죽지 않게 한다.
폴백 여부는 source 필드('live'|'synthetic')로 표시한다.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import config as C

_cache: dict[str, tuple[float, dict]] = {}


def normalize_candidates(raw: str) -> list[str]:
    """입력 티커 → 시도할 yfinance 심볼 후보 목록.

    6자리 숫자 → 한국 종목: .KS, .KQ 순차 시도. 그 외 → 그대로.
    """
    t = raw.strip().upper()
    if t.isdigit() and len(t) == 6:
        return [f"{t}.KS", f"{t}.KQ"]
    return [t]


def _from_yfinance(symbol: str):
    import yfinance as yf

    tk = yf.Ticker(symbol)
    hist = tk.history(period=C.DATA_PERIOD, interval=C.DATA_INTERVAL, auto_adjust=False)
    if hist is None or hist.empty or len(hist) < 60:
        return None
    df = pd.DataFrame({
        "open": hist["Open"].astype(float),
        "high": hist["High"].astype(float),
        "low": hist["Low"].astype(float),
        "close": hist["Close"].astype(float),
        "volume": hist["Volume"].astype(float),
    })
    df.index = pd.to_datetime(hist.index).tz_localize(None)
    info = {}
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    return df, info


def _synthetic(symbol: str):
    """결정론적 합성 OHLC (티커 해시 시드). 프론트 디자인의 생성 로직과 동일 계열."""
    seed = abs(hash(symbol)) % (2**32)
    rng = np.random.default_rng(seed)
    n = 252
    bias = rng.choice([0.0018, -0.0019, 0.0002], p=[0.4, 0.3, 0.3])
    v, closes = 100.0, []
    for _ in range(n):
        v = v * (1 + bias + (rng.random() - 0.5) * 0.028)
        closes.append(v)
    closes = np.array(closes)
    base_price = 50 + (seed % 200000) / 1000.0
    closes *= base_price / closes[-1]
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + rng.random(n) * 0.013)
    lows = np.minimum(opens, closes) * (1 - rng.random(n) * 0.013)
    vols = rng.integers(1_000_000, 30_000_000, n).astype(float)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx)
    return df, {}


def load(raw_ticker: str) -> dict:
    """티커 1회 스냅샷 로드. 반환: {symbol, df, info, source}.

    실패 시 ValueError. 캐시 TTL 내 동일 심볼은 캐시 반환.
    """
    candidates = normalize_candidates(raw_ticker)
    for symbol in candidates:
        cached = _cache.get(symbol)
        if cached and time.time() - cached[0] < C.CACHE_TTL:
            return cached[1]
        try:
            res = _from_yfinance(symbol)
        except Exception:
            res = None
        if res is not None:
            df, info = res
            payload = {"symbol": symbol, "df": df, "info": info, "source": "live"}
            _cache[symbol] = (time.time(), payload)
            return payload

    # 전 후보 실패 → 합성 폴백 (첫 후보 심볼명 유지)
    symbol = candidates[0]
    df, info = _synthetic(symbol)
    payload = {"symbol": symbol, "df": df, "info": info, "source": "synthetic"}
    _cache[symbol] = (time.time(), payload)
    return payload
