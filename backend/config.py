"""중앙 설정 — 모든 임계값 / 가중치 한곳에서 관리 (설계도 §11).

운영 중 백테스트로 조정할 값은 전부 여기 모은다.
"""

# ── 데이터 ─────────────────────────────────────────────
DATA_PERIOD = "1y"        # yfinance history 기간 (일목 워밍업 위해 1년)
DATA_INTERVAL = "1d"      # 일봉
CACHE_TTL = 600           # 캐시 유효시간(초) = 10분 (확인필요 2 → 10분 확정)
SERIES_POINTS = 210       # 프론트 차트에 넘길 최근 봉 개수

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
