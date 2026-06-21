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
_fx_cache: tuple[float, float] | None = None  # (조회시각, USD→KRW 환율)


def usdkrw_rate() -> tuple[float, bool]:
    """USD→KRW 환율. 반환: (rate, is_live). 실패 시 폴백 상수(is_live=False)."""
    global _fx_cache
    if _fx_cache and time.time() - _fx_cache[0] < C.CACHE_TTL:
        return _fx_cache[1], True
    try:
        import yfinance as yf

        hist = yf.Ticker("KRW=X").history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            rate = float(hist["Close"].iloc[-1])
            _fx_cache = (time.time(), rate)
            return rate, True
    except Exception:
        pass
    return C.FX_FALLBACK, False


def normalize_candidates(raw: str) -> list[str]:
    """입력 티커 → 시도할 yfinance 심볼 후보 목록.

    6자리 숫자 → 한국 종목: .KS, .KQ 순차 시도. 그 외 → 그대로.
    """
    t = raw.strip().upper()
    if t.isdigit() and len(t) == 6:
        return [f"{t}.KS", f"{t}.KQ"]
    return [t]


def _from_yfinance(symbol: str, period: str, interval: str):
    import yfinance as yf

    tk = yf.Ticker(symbol)
    hist = tk.history(period=period, interval=interval, auto_adjust=False)
    if hist is None or hist.empty or len(hist) < C.MIN_BARS:
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


def load(raw_ticker: str, period: str = C.DATA_PERIOD, interval: str = C.DATA_INTERVAL) -> dict:
    """티커 1회 스냅샷 로드. 반환: {symbol, df, info, source}.

    실패 시 ValueError. 캐시 TTL 내 동일 (심볼·간격)은 캐시 반환.
    간격(interval)이 다르면 다른 봉이므로 캐시 키를 분리한다.
    """
    candidates = normalize_candidates(raw_ticker)
    for symbol in candidates:
        key = f"{symbol}@{interval}"
        cached = _cache.get(key)
        if cached and time.time() - cached[0] < C.CACHE_TTL:
            return cached[1]
        try:
            res = _from_yfinance(symbol, period, interval)
        except Exception:
            res = None
        if res is not None:
            df, info = res
            now = time.time()
            payload = {"symbol": symbol, "df": df, "info": info, "source": "live", "fetched_at": now}
            _cache[key] = (now, payload)
            return payload

    # 전 후보 실패 → 합성 폴백 (첫 후보 심볼명 유지)
    symbol = candidates[0]
    df, info = _synthetic(symbol)
    now = time.time()
    payload = {"symbol": symbol, "df": df, "info": info, "source": "synthetic", "fetched_at": now}
    _cache[f"{symbol}@{interval}"] = (now, payload)
    return payload
