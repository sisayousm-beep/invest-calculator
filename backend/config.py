"""중앙 설정 — 모든 임계값 / 가중치 한곳에서 관리 (설계도 §11).

운영 중 백테스트로 조정할 값은 전부 여기 모은다.
"""

# ── 데이터 ─────────────────────────────────────────────
DATA_PERIOD = "1y"        # yfinance history 기간 (일목 워밍업 위해 1년)
DATA_INTERVAL = "1d"      # 일봉
CACHE_TTL = 600           # 캐시 유효시간(초) = 10분 (확인필요 2 → 10분 확정)
SERIES_POINTS = 210       # 프론트 차트에 넘길 최근 봉 개수
MIN_BARS = 20             # 라이브 데이터로 인정하는 최소 봉 수 (볼린저 20일선 기준).
                          # 신규 상장주(예: CBRS)는 1년치가 안 되므로 60→20으로 낮춰
                          # 합성 폴백 대신 실시간 데이터를 쓴다. 일목 등 장기 지표는
                          # 봉이 부족하면 자동으로 '데이터 부족' 처리된다.

# ── 관점별 타임프레임 (장기=일봉 / 단기=시간봉) ─────────
# 지표 기간은 '봉 개수'라 간격을 바꾸면 보는 시간 축이 바뀐다(같은 RSI14가
# 일봉=약 3주, 1시간봉=약 14시간). 단기는 yfinance 분/시간봉 제약상 1시간봉.
TIMEFRAMES = {
    "long":  {"label": "장기", "interval_label": "일봉",   "period": DATA_PERIOD, "interval": DATA_INTERVAL},
    "short": {"label": "단기", "interval_label": "1시간봉", "period": "60d",       "interval": "1h"},
}

# ── 환율 (포트폴리오 원화 통합) ─────────────────────────
FX_FALLBACK = 1380.0      # USD→KRW 환율 조회 실패 시 폴백 상수 (오프라인 한정)

# ── 지표 파라미터 ──────────────────────────────────────
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

ICHIMOKU_CONV = 9
ICHIMOKU_BASE = 26
ICHIMOKU_SPAN_B = 52
ICHIMOKU_SHIFT = 26       # 선행스팬 앞으로 / 후행스팬 뒤로

BB_PERIOD = 20
BB_STD = 2.0

# ── 추세 판별 ──────────────────────────────────────────
SQUEEZE_LOOKBACK = 120    # 밴드폭 상대 비교 구간
SQUEEZE_PCTL = 0.25       # 하위 25% 이내면 스퀴즈(횡보) (확인필요 3 → 상대기준 확정)
TREND_MIN_SCORE = 3       # 추세로 인정하는 최소 일치 조건 수

# ── 타이밍 가중치 (설계도 §5.3) ───────────────────────
W_TREND = {"ichimoku": 0.45, "macd": 0.40, "bb": 0.15}
W_RANGE = {"bollinger": 0.55, "rsi": 0.45}

# ── 종합 평가 (설계도 §6) ─────────────────────────────
W_EVAL = {"trend": 0.40, "timing": 0.40, "indicator": 0.20}

# 등급 경계 (확인필요 4 → 초안대로 출발)
GRADE_BOUNDS = [
    (80, "강한 추천"),
    (65, "추천"),
    (40, "보류"),
    (25, "비추천"),
    (0,  "강한 비추천"),
]
