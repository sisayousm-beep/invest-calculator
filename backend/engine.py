"""분석 엔진 — 추세 판별 / 타이밍 포착 / 종합 평가 / 가격 역산 (설계도 §4~6).

입력: OHLC DataFrame + 지표 dict. 출력: 프론트가 그대로 그릴 JSON 친화 dict.
프론트는 로직을 갖지 않는다 — 모든 판단은 여기서.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as C
from . import indicators

SHIFT = C.ICHIMOKU_SHIFT


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _val(series: pd.Series, i: int):
    """i번째 값(없거나 NaN이면 None)."""
    if i < 0 or i >= len(series):
        return None
    v = series.iloc[i]
    return None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)


def _cloud_at(ind, li):
    """현재 봉(li)에 걸리는 구름대 = 26일 전에 계산된 선행스팬."""
    a = _val(ind["span_a"], li - SHIFT)
    b = _val(ind["span_b"], li - SHIFT)
    if a is None or b is None:
        a = _val(ind["span_a"], li)
        b = _val(ind["span_b"], li)
    return a, b


# ──────────────────────────────────────────────────────
# 추세 판별 (§4)
# ──────────────────────────────────────────────────────
def analyze_trend(df, ind):
    li = len(df) - 1
    price = float(df["close"].iloc[li])
    ca, cb = _cloud_at(ind, li)
    cloud_top = max(ca, cb) if ca is not None else None
    cloud_bot = min(ca, cb) if ca is not None else None

    up = down = 0
    # C1 주가 vs 구름대
    if cloud_top is not None:
        if price > cloud_top:
            up += 1
        elif price < cloud_bot:
            down += 1
    # C2 구름 색 (양운/음운)
    if ca is not None:
        up += ca > cb
        down += ca < cb
    # C3 전환선 vs 기준선
    conv, base = _val(ind["conv"], li), _val(ind["base"], li)
    if conv is not None and base is not None:
        up += conv > base
        down += conv < base
    # C4 후행스팬(=당일 종가) vs 26일 전 주가
    prev = _val(df["close"], li - SHIFT)
    if prev is not None:
        up += price > prev
        down += price < prev
    # C5 볼린저 중심선 기울기
    m0, m1 = _val(ind["mid"], li), _val(ind["mid"], li - 1)
    if m0 is not None and m1 is not None:
        up += m0 > m1
        down += m0 < m1

    # 스퀴즈 판정: 최근 120일 밴드폭 하위 25%
    width = ind["width"].dropna()
    window = width.iloc[-C.SQUEEZE_LOOKBACK:]
    cur_w = _val(ind["width"], li)
    squeeze = False
    rank = 0.5
    if cur_w is not None and len(window) >= 10:
        thr = float(np.quantile(window, C.SQUEEZE_PCTL))
        squeeze = cur_w <= thr
        rank = float((window < cur_w).mean())  # 0=가장 좁음, 1=가장 넓음

    inside_cloud = cloud_top is not None and cloud_bot <= price <= cloud_top

    if inside_cloud or squeeze:
        label = "횡보"
    elif up >= C.TREND_MIN_SCORE and up > down:
        label = "상승추세"
    elif down >= C.TREND_MIN_SCORE and down > up:
        label = "하락추세"
    else:
        label = "횡보"

    if label == "상승추세":
        confidence = round(up / 5 * 100)
    elif label == "하락추세":
        confidence = round(down / 5 * 100)
    else:
        confidence = round((1 - rank) * 100)  # 좁을수록 횡보 신뢰 ↑

    return {
        "label": label,
        "confidence": int(confidence),
        "up_score": int(up),
        "down_score": int(down),
        "squeeze": bool(squeeze),
        "_cloud_top": cloud_top,
        "_cloud_bot": cloud_bot,
    }


# ──────────────────────────────────────────────────────
# 타이밍 포착 (§5)
# ──────────────────────────────────────────────────────
def analyze_timing(df, ind, trend):
    li = len(df) - 1
    price = float(df["close"].iloc[li])
    pb = _val(ind["pb"], li)
    pb1 = _val(ind["pb"], li - 1)
    rsi = _val(ind["rsi"], li)
    hist, hist1 = _val(ind["hist"], li), _val(ind["hist"], li - 1)
    label = trend["label"]

    if label in ("상승추세", "하락추세"):
        # 추세장: 일목 + MACD + 밴드워킹 (RSI 무시)
        w = C.W_TREND
        ich = 1.0 if (trend["_cloud_top"] is not None and price > trend["_cloud_top"]) else 0.0
        macd_sig = 1.0 if (hist is not None and hist > 0 and hist1 is not None and hist >= hist1) else 0.0
        walk = 1.0 if (pb is not None and pb >= 0.8 and pb1 is not None and pb1 >= 0.8) else 0.0
        score = (ich * w["ichimoku"] + macd_sig * w["macd"] + walk * w["bb"]) / sum(w.values()) * 100
        if label == "상승추세":
            action = "매수" if score >= 70 else ("홀딩" if score >= 45 else "관망")
            direction = 1.0 if action == "매수" else (0.3 if action == "홀딩" else -0.2)
        else:  # 하락추세 — 매수 신호 금지, 관망/회피
            action = "관망"
            direction = -1.0
        return {"action": action, "score": int(round(score)), "direction": direction}

    # 횡보장: 볼린저 + RSI (일목/MACD 무시), 점수는 그라데이션
    w = C.W_RANGE
    pb = pb if pb is not None else 0.5
    rsi = rsi if rsi is not None else 50.0
    buy = (w["bollinger"] * _clamp((0.30 - pb) / 0.30) + w["rsi"] * _clamp((50 - rsi) / 40)) / sum(w.values()) * 100
    sell = (w["bollinger"] * _clamp((pb - 0.70) / 0.30) + w["rsi"] * _clamp((rsi - 50) / 40)) / sum(w.values()) * 100
    if buy >= sell and buy >= 40:
        return {"action": "매수 관심", "score": int(round(buy)), "direction": 1.0}
    if sell > buy and sell >= 40:
        return {"action": "매도 관심", "score": int(round(sell)), "direction": -1.0}
    return {"action": "중립", "score": int(round(max(buy, sell))), "direction": 0.0}


# ──────────────────────────────────────────────────────
# 종합 평가 + 가격 역산 (§6)
# ──────────────────────────────────────────────────────
def _grade(score):
    for bound, name in C.GRADE_BOUNDS:
        if score >= bound:
            return name
    return C.GRADE_BOUNDS[-1][1]


def _grade_rank(score):
    """등급 순위 0(강한 비추천)~4(강한 추천). 높을수록 좋음."""
    n = len(C.GRADE_BOUNDS)
    for i, (bound, _) in enumerate(C.GRADE_BOUNDS):
        if score >= bound:
            return n - 1 - i
    return 0


def _score_core(df, ind, trend, timing):
    """종합 점수 계산 (가격 역산용으로 evaluate에서 분리). 반환: (score:int, breakdown)."""
    li = len(df) - 1
    label = trend["label"]

    # 추세 기여
    if label == "상승추세":
        trend_c = trend["confidence"]
    elif label == "하락추세":
        trend_c = 100 - trend["confidence"]
    else:
        trend_c = 50.0
    # 타이밍 기여 (0~100, 50=중립)
    if label == "하락추세":
        # 하락추세는 구조적 '매수 금지' 구간 → 매수 타이밍 score(≈0)로 계산하면
        # timing_c 가 50(중립)에 묶여 점수 하한이 생긴다. 하방 신뢰도에 비례해 하향 기여.
        timing_c = _clamp(50 - trend["confidence"] / 2, 0, 100)
    else:
        timing_c = _clamp(50 + timing["direction"] * (timing["score"] / 2), 0, 100)
    # 지표 보정 (RSI 극단 / MACD 0선 / %B 위치)
    rsi = _val(ind["rsi"], li) or 50.0
    macd_line = _val(ind["macd"], li) or 0.0
    hist = _val(ind["hist"], li) or 0.0
    pb = _val(ind["pb"], li)
    pb = 0.5 if pb is None else pb
    ind_c = 50.0
    ind_c += (50 - rsi) / 50 * 20          # 과매도 +, 과매수 -
    ind_c += 5 if hist > 0 else -5
    ind_c += 5 if macd_line > 0 else -5
    ind_c += (0.5 - pb) * 10               # 밴드 하단부 = 매력
    ind_c = _clamp(ind_c, 0, 100)

    w = C.W_EVAL
    score = trend_c * w["trend"] + timing_c * w["timing"] + ind_c * w["indicator"]
    score = int(round(_clamp(score, 0, 100)))
    return score, {"trend": round(trend_c, 1), "timing": round(timing_c, 1), "indicator": round(ind_c, 1)}


def _pipeline_score(base_df, P):
    """마지막 봉 종가를 P로 가정했을 때의 종합 점수. 전 지표/판정 재계산."""
    df = base_df.copy()
    i = len(df) - 1
    ci, hi, lo = df.columns.get_loc("close"), df.columns.get_loc("high"), df.columns.get_loc("low")
    df.iat[i, ci] = P
    if P > df.iat[i, hi]:
        df.iat[i, hi] = P
    if P < df.iat[i, lo]:
        df.iat[i, lo] = P
    ind = indicators.compute_all(df)
    tr = analyze_trend(df, ind)
    tm = analyze_timing(df, ind, tr)
    return _score_core(df, ind, tr, tm)[0]


def _scan_transition(df, p0, sign, cur_score, cur_rank):
    """현재가에서 sign 방향으로 등급이 실제로 한 단계 넘어가는 첫 가격을 역산.

    sign=+1: 위로 올려보며 등급이 올라가는 가격(상향). sign=−1: 아래로 내려보며
    등급이 내려가는 가격(하향). 1.5% 격자로 경계를 찾고 4회 이분탐색으로 좁힌다.
    국소 노이즈(한 칸 뒤 되돌아옴)는 건너뛴다. ±40% 안에 없으면 (None, None).
    반환: (전환가, 전환 후 등급명).
    """
    step, max_t = 0.015, 0.40

    def crossed(P):
        try:
            r = _grade_rank(_pipeline_score(df, P))
        except Exception:
            r = cur_rank
        return (r > cur_rank) if sign > 0 else (r < cur_rank)

    prev, t = p0, step
    while t <= max_t + 1e-9:
        P = p0 * (1 + sign * t)
        if crossed(P):
            # 한 칸 더 가서도 넘어간 채면 진짜 전환, 되돌아오면 노이즈 → 건너뜀
            tc = t + step
            if tc <= max_t + 1e-9 and not crossed(p0 * (1 + sign * tc)):
                prev, t = P, tc
                continue
            lo_p, hi_p = prev, P  # 전환점은 두 가격 사이
            for _ in range(4):
                mid = (lo_p + hi_p) / 2
                if crossed(mid):
                    hi_p = mid
                else:
                    lo_p = mid
            return round(hi_p, 2), _grade(_pipeline_score(df, hi_p))
        prev, t = P, t + step
    return None, None


def evaluate(df, ind, trend, timing):
    price = float(df["close"].iloc[len(df) - 1])
    score, breakdown = _score_core(df, ind, trend, timing)
    grade = _grade(score)
    cur_rank = _grade_rank(score)

    # 등급 전환 예상가: 이 가격에 닿으면 종합 등급이 한 단계 바뀐다.
    up_price, up_grade = _scan_transition(df, price, +1, score, cur_rank)
    down_price, down_grade = _scan_transition(df, price, -1, score, cur_rank)

    return {
        "grade": grade,
        "score": score,
        "up_price": up_price,
        "up_grade": up_grade,
        "down_price": down_price,
        "down_grade": down_grade,
        "_breakdown": breakdown,
    }


# ──────────────────────────────────────────────────────
# 보유자 관점 액션 (포트폴리오 분석)
# ──────────────────────────────────────────────────────
def _ret_str(r):
    return ("+" if r >= 0 else "-") + f"{abs(r):.1f}%"


def holder_action(score, return_pct):
    """이미 보유 중인 종목에 대한 액션 추천.

    종합점수(= 신규 매수 매력도)로 큰 방향을 잡고, 평단 대비 손익으로
    약세 구간에서 '익절'과 '손절'을 구분한다. 과열된 수익 종목은
    종합 엔진이 RSI·%B 보정으로 등급을 이미 낮추므로 별도 처리하지 않는다.
    반환: (action, kind, reason). kind ∈ {add, hold, trim, reduce, cut}.
    """
    rank = _grade_rank(int(round(score)))  # 0(강한 비추천)~4(강한 추천)
    rs = _ret_str(return_pct)
    if rank == 4:
        return "추가매수", "add", f"강세 지속 신호 · 비중 확대 고려 (평가손익 {rs})"
    if rank == 3:
        return "홀딩", "hold", f"우호적 신호 · 보유 유지, 분할 추가 고려 (평가손익 {rs})"
    if rank == 2:
        return "홀딩", "hold", f"방향성 불분명 · 관망하며 보유 (평가손익 {rs})"
    # rank 0~1: 약세 신호 → 손익으로 익절/손절 구분
    if return_pct >= 0:
        if rank == 0:
            return "익절", "trim", f"뚜렷한 약세 신호 + 수익 중 ({rs}) · 차익 실현 우선"
        return "분할 익절", "trim", f"약세 신호 + 수익 중 ({rs}) · 분할 차익 실현 검토"
    if rank == 0:
        return "손절 고려", "cut", f"뚜렷한 약세 신호 + 손실 중 ({rs}) · 손절 기준 점검"
    return "비중 축소", "reduce", f"약세 신호 + 손실 중 ({rs}) · 비중 축소 검토"


# ──────────────────────────────────────────────────────
# 지표 신호 요약 (우측 패널) — 설계도 §10.4
# ──────────────────────────────────────────────────────
def signal_summary(df, ind, trend):
    li = len(df) - 1
    price = float(df["close"].iloc[li])
    out = []

    def push(name, w, label, detail):
        out.append({"name": name, "weight": w, "label": label, "detail": detail})

    # 일목 구름
    ct, cb = trend["_cloud_top"], trend["_cloud_bot"]
    if ct is None:
        push("일목균형표", 0, "중립", "데이터 부족")
    elif price > ct:
        push("일목균형표", 1, "매수", "주가가 구름대 위 — 양호")
    elif price < cb:
        push("일목균형표", -1, "매도", "주가가 구름대 아래 — 약세")
    else:
        push("일목균형표", 0, "중립", "주가가 구름대 내부 — 혼조")

    # RSI
    rsi = _val(ind["rsi"], li)
    if rsi is None:
        push("RSI (14)", 0, "중립", "데이터 부족")
    elif rsi >= C.RSI_OVERBOUGHT:
        push("RSI (14)", -1, "매도", f"과매수 구간 ({rsi:.0f})")
    elif rsi <= C.RSI_OVERSOLD:
        push("RSI (14)", 1, "매수", f"과매도 구간 ({rsi:.0f})")
    else:
        push("RSI (14)", 0, "중립", f"중립 구간 ({rsi:.0f})")

    # MACD
    h, h1 = _val(ind["hist"], li), _val(ind["hist"], li - 1)
    if h is None or h1 is None:
        push("MACD", 0, "중립", "데이터 부족")
    elif h > 0 and h >= h1:
        push("MACD", 1, "매수", "시그널 상회 · 모멘텀 확대")
    elif h < 0 and h <= h1:
        push("MACD", -1, "매도", "시그널 하회 · 모멘텀 둔화")
    else:
        push("MACD", 0, "중립", "히스토그램 방향 전환 구간")

    # 볼린저
    pb = _val(ind["pb"], li)
    if pb is None:
        push("볼린저밴드", 0, "중립", "데이터 부족")
    elif pb > 0.85:
        push("볼린저밴드", -1, "매도", "상단 밴드 접근 — 과열")
    elif pb < 0.15:
        push("볼린저밴드", 1, "매수", "하단 밴드 접근 — 반등 기대")
    else:
        push("볼린저밴드", 0, "중립", "밴드 중앙 — 추세 진행")

    # 이동평균 20
    m20 = _val(ind["mid"], li)
    if m20 is None:
        push("이동평균 (20)", 0, "중립", "데이터 부족")
    elif price > m20 * 1.005:
        push("이동평균 (20)", 1, "매수", "20일선 상회")
    elif price < m20 * 0.995:
        push("이동평균 (20)", -1, "매도", "20일선 하회")
    else:
        push("이동평균 (20)", 0, "중립", "20일선 근접")

    total = sum(s["weight"] for s in out)
    if total >= 2:
        consensus = "매수 우위"
    elif total <= -2:
        consensus = "매도 우위"
    else:
        consensus = "혼조"
    return out, consensus
