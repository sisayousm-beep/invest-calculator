"""FastAPI 진입점 + API 라우트 (설계도 §9) + 프론트 정적 서빙.

실행: uvicorn backend.main:app --reload  (프로젝트 루트에서)
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as C
from . import data, indicators, engine

app = FastAPI(title="투자 판단 앱 API", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# ── 포맷 헬퍼 ──────────────────────────────────────────
def _is_kr(symbol: str) -> bool:
    return symbol.upper().endswith((".KS", ".KQ"))


def _fmt_price(v, kr) -> str:
    if v is None:
        return "—"
    return f"{round(v):,}원" if kr else f"${v:,.2f}"


def _fmt_cap(v, kr) -> str:
    if not v:
        return "—"
    if kr:
        jo = v / 1e12
        return f"{jo:.1f}조" if jo >= 1 else f"{v / 1e8:,.0f}억"
    t = v / 1e12
    if t >= 1:
        return f"${t:.2f}T"
    b = v / 1e9
    return f"${b:.1f}B" if b >= 1 else f"${v / 1e6:.0f}M"


def _num(v, digits=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _build_detail(symbol, info, df):
    kr = _is_kr(symbol)
    li = len(df) - 1
    vol = df["volume"].iloc[li]
    w52_hi = info.get("fiftyTwoWeekHigh") or float(df["high"].iloc[-252:].max())
    w52_lo = info.get("fiftyTwoWeekLow") or float(df["low"].iloc[-252:].min())
    div = info.get("dividendYield")
    if div:
        div = div * 100 if div < 1 else div
        div_str = f"{div:.2f}%"
    else:
        div_str = "—"
    return {
        "market_cap": _fmt_cap(info.get("marketCap"), kr),
        "sector": info.get("sector") or "—",
        "per": _num(info.get("trailingPE")),
        "pbr": _num(info.get("priceToBook")),
        "dividend_yield": div_str,
        "volume": f"{int(vol):,}" if vol == vol else "—",
        "week52_high": _fmt_price(w52_hi, kr),
        "week52_low": _fmt_price(w52_lo, kr),
    }


def _analyze(raw_ticker: str):
    payload = data.load(raw_ticker)
    df, info, symbol = payload["df"], payload["info"], payload["symbol"]
    ind = indicators.compute_all(df)
    trend = engine.analyze_trend(df, ind)
    timing = engine.analyze_timing(df, ind, trend)
    evaluation = engine.evaluate(df, ind, trend, timing)
    signals, consensus = engine.signal_summary(df, ind, trend)
    return payload, df, ind, trend, timing, evaluation, signals, consensus


# ── 라우트 ─────────────────────────────────────────────
@app.get("/api/stock/{ticker}")
def get_stock(ticker: str):
    try:
        payload, df, ind, trend, timing, evaluation, signals, consensus = _analyze(ticker)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"티커를 확인해 주세요: {exc}")

    symbol = payload["symbol"]
    kr = _is_kr(symbol)
    li = len(df) - 1
    price = float(df["close"].iloc[li])
    prev = float(df["close"].iloc[li - 1]) if li >= 1 else price
    change_pct = (price / prev - 1) * 100 if prev else 0.0
    name = payload["info"].get("shortName") or payload["info"].get("longName") or symbol.split(".")[0]
    market = ("KOSPI" if symbol.endswith(".KS") else "KOSDAQ" if symbol.endswith(".KQ")
              else payload["info"].get("exchange") or "—")

    # 내부 키(_) 제거
    trend_out = {k: v for k, v in trend.items() if not k.startswith("_")}
    eval_out = {k: v for k, v in evaluation.items() if not k.startswith("_")}

    return {
        "ticker": symbol,
        "name": name,
        "market": market,
        "kr": kr,
        "price": round(price, 2),
        "change_pct": round(change_pct, 2),
        "source": payload["source"],
        "detail": _build_detail(symbol, payload["info"], df),
        "indicators": {
            "rsi": round(ind["rsi"].iloc[li], 1) if not math.isnan(ind["rsi"].iloc[li]) else None,
        },
        "trend": trend_out,
        "timing": timing,
        "evaluation": eval_out,
        "signals": signals,
        "consensus": consensus,
    }


def _series(s: pd.Series, n: int):
    """마지막 n개를 JSON 안전 리스트로 (NaN→None)."""
    tail = s.iloc[-n:]
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), 4) for v in tail]


@app.get("/api/stock/{ticker}/ohlc")
def get_ohlc(ticker: str):
    try:
        payload = data.load(ticker)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"티커를 확인해 주세요: {exc}")
    df, symbol = payload["df"], payload["symbol"]
    ind = indicators.compute_all(df)
    n = min(C.SERIES_POINTS, len(df))
    tail = df.iloc[-n:]
    return {
        "ticker": symbol,
        "kr": _is_kr(symbol),
        "shift": C.ICHIMOKU_SHIFT,
        "t": [d.strftime("%Y-%m-%d") for d in tail.index],
        "o": _series(df["open"], n),
        "h": _series(df["high"], n),
        "l": _series(df["low"], n),
        "c": _series(df["close"], n),
        "rsi": _series(ind["rsi"], n),
        "macd": _series(ind["macd"], n),
        "signal": _series(ind["signal"], n),
        "hist": _series(ind["hist"], n),
        "mid": _series(ind["mid"], n),
        "upper": _series(ind["upper"], n),
        "lower": _series(ind["lower"], n),
        "conv": _series(ind["conv"], n),
        "base": _series(ind["base"], n),
        "span_a": _series(ind["span_a"], n),
        "span_b": _series(ind["span_b"], n),
    }


@app.get("/api/health")
def health():
    return {"ok": True}


# 프론트 정적 파일 (마지막에 마운트해야 /api 가 가려지지 않음)
if FRONTEND_DIR.exists():
    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
