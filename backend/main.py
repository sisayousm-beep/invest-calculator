"""FastAPI 진입점 + API 라우트 (설계도 §9) + 프론트 정적 서빙.

실행: uvicorn backend.main:app --reload  (프로젝트 루트에서)
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as C
from . import data, indicators, engine

app = FastAPI(title="투자 판단 앱 API", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class Holding(BaseModel):
    ticker: str
    avg_price: float
    qty: float
    currency: str = "USD"  # 평단가 입력 통화: 'USD' | 'KRW'. 해외주에서만 의미(한국주는 항상 원).


class PortfolioReq(BaseModel):
    holdings: list[Holding]

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
    # yfinance는 dividendYield를 이미 퍼센트 단위로 반환한다 (NVDA 0.47 → 0.47%, KO 2.67 → 2.67%).
    div = info.get("dividendYield")
    div_str = f"{div:.2f}%" if div else "—"
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


def _analyze(raw_ticker: str, period: str = C.DATA_PERIOD, interval: str = C.DATA_INTERVAL):
    payload = data.load(raw_ticker, period, interval)
    df, info, symbol = payload["df"], payload["info"], payload["symbol"]
    ind = indicators.compute_all(df)
    trend = engine.analyze_trend(df, ind)
    timing = engine.analyze_timing(df, ind, trend)
    evaluation = engine.evaluate(df, ind, trend, timing)
    signals, consensus = engine.signal_summary(df, ind, trend)
    return payload, df, ind, trend, timing, evaluation, signals, consensus


# ── 라우트 ─────────────────────────────────────────────
def _stock_response(ticker: str) -> dict:
    """종목 1개 종합 분석 → 프론트 친화 dict. (get_stock / 포트폴리오에서 공용)."""
    payload, df, ind, trend, timing, evaluation, signals, consensus = _analyze(ticker)

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

    fetched_at = payload.get("fetched_at")
    return {
        "ticker": symbol,
        "name": name,
        "market": market,
        "kr": kr,
        "price": round(price, 2),
        "change_pct": round(change_pct, 2),
        "source": payload["source"],
        "updated_at": datetime.fromtimestamp(fetched_at).strftime("%Y-%m-%d %H:%M") if fetched_at else None,
        "last_bar": df.index[li].strftime("%Y-%m-%d"),
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


@app.get("/api/stock/{ticker}")
def get_stock(ticker: str):
    try:
        return _stock_response(ticker)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"티커를 확인해 주세요: {exc}")


# ── 관점별 요약 (장기/단기 독립 판정) ──────────────────────
def _verdict(raw_ticker: str, tf: dict) -> dict:
    """한 타임프레임의 압축 판정. 전체 분석 파이프라인을 해당 간격으로 1회 실행."""
    payload, df, ind, trend, timing, evaluation, signals, consensus = _analyze(
        raw_ticker, tf["period"], tf["interval"])
    li = len(df) - 1
    intraday = tf["interval"].endswith(("m", "h"))
    bar_fmt = "%m/%d %H:%M" if intraday else "%Y-%m-%d"
    return {
        "label": tf["label"],
        "interval_label": tf["interval_label"],
        "trend": trend["label"],
        "trend_confidence": trend["confidence"],
        "timing": timing["action"],
        "grade": evaluation["grade"],
        "score": evaluation["score"],
        "consensus": consensus,
        "source": payload["source"],
        "last_bar": df.index[li].strftime(bar_fmt),
    }


@app.get("/api/stock/{ticker}/timeframes")
def get_timeframes(ticker: str):
    """장기(일봉)·단기(시간봉) 판정을 함께 반환. 한 쪽이 실패해도 다른 쪽은 유지."""
    out = {}
    for key, tf in C.TIMEFRAMES.items():
        try:
            out[key] = _verdict(ticker, tf)
        except Exception:  # noqa: BLE001
            out[key] = None
    return out


# ── 포트폴리오 (보유 종목 기반 분석) ──────────────────────
def _portfolio_summary(rows, rate):
    """전체 보유를 원화(KRW) 기준으로 통합 집계. 비중을 rows에 주입하고 요약 dict 반환.

    미국주(외화)는 환율로 원화 환산해 한국주와 합산한다. 총합·비중은 전부 원화 기준이며,
    종목별 손익률(return_pct)은 각자의 통화로 계산된 값(환율 무관)을 그대로 쓴다."""
    total_cost = total_value = 0.0
    for r in rows:
        fx = 1.0 if r["kr"] else rate
        r["value_krw"] = round(r["eval_amount"] * fx, 2)
        total_cost += r["cost"] * fx
        total_value += r["eval_amount"] * fx
    for r in rows:  # 전체 포트폴리오(원화 환산) 기준 비중
        r["weight"] = round(r["value_krw"] / total_value, 4) if total_value else 0.0
    top = max((r["weight"] for r in rows), default=0.0)
    n = len(rows)
    if n <= 1:
        conc = "단일 종목"
    elif top >= 0.5:
        conc = "고집중"
    elif top >= 0.35:
        conc = "다소 집중"
    else:
        conc = "분산 양호"
    return {
        "value": round(total_value),
        "cost": round(total_cost),
        "pnl": round(total_value - total_cost),
        "return_pct": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0.0,
        "count": n,
        "top_weight": round(top, 4),
        "concentration": conc,
    }


def _portfolio_comment(rows):
    """보유자 액션 분포 기반 한 줄 종합 코멘트 (통화 무관)."""
    if not rows:
        return "보유 종목이 없습니다. 종목을 추가해 주세요."
    kinds = [r["action_kind"] for r in rows]
    n = len(rows)
    if "cut" in kinds:
        return "손실 + 약세 신호 종목이 있어요. 손절 기준을 먼저 점검하세요."
    exit_n = sum(k in ("trim", "reduce") for k in kinds)
    if exit_n >= max(1, n // 2):
        return "차익 실현·비중 축소 신호 종목이 많아요. 분할 매도를 검토하세요."
    if sum(k == "add" for k in kinds) >= max(1, n // 2):
        return "강세 지속 신호가 우세해요. 보유 지속·분할 추가에 우호적입니다."
    return "방향성이 혼재돼 있어요. 종목별 신호를 개별 확인하세요."


@app.post("/api/portfolio")
def post_portfolio(req: PortfolioReq):
    rate, fx_live = data.usdkrw_rate()
    rows, errors = [], []
    for h in req.holdings:
        if h.avg_price <= 0 or h.qty <= 0:
            errors.append({"ticker": h.ticker, "error": "평단가·수량은 0보다 커야 합니다"})
            continue
        try:
            s = _stock_response(h.ticker)
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": h.ticker, "error": f"{exc}"})
            continue
        price = s["price"]
        # 평단가를 종목 통화로 정규화: 해외주를 원화로 입력했으면 환율로 USD 환산.
        # (한국주는 항상 원화이므로 통화 선택 무시.)
        avg_price = h.avg_price
        if not s["kr"] and h.currency.upper() == "KRW":
            avg_price = h.avg_price / rate
        cost = avg_price * h.qty
        value = price * h.qty
        ret = (price / avg_price - 1) * 100
        action, kind, reason = engine.holder_action(s["evaluation"]["score"], ret)
        rows.append({
            "ticker": s["ticker"],
            "name": s["name"],
            "market": s["market"],
            "kr": s["kr"],
            "price": price,
            "change_pct": s["change_pct"],
            "source": s["source"],
            "avg_price": round(avg_price, 2),
            "qty": h.qty,
            "cost": round(cost, 2),
            "eval_amount": round(value, 2),
            "pnl": round(value - cost, 2),
            "return_pct": round(ret, 2),
            "weight": 0.0,  # _portfolio_summary에서 전체(원화 환산) 비중으로 채움
            "grade": s["evaluation"]["grade"],
            "score": s["evaluation"]["score"],
            "trend": s["trend"]["label"],
            "timing": s["timing"]["action"],
            "action": action,
            "action_kind": kind,
            "reason": reason,
        })
    summary = _portfolio_summary(rows, rate)
    return {
        "holdings": rows,
        "summary": summary,
        "fx_rate": round(rate, 2),
        "fx_live": fx_live,
        "comment": _portfolio_comment(rows),
        "errors": errors,
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
