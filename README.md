# 투자 판단 앱 (invest-calculator)

한국·미국 주식 티커를 입력하면 일봉 기반 기술적 지표를 계산해 **추세 / 타이밍 / 종합 등급**을
토스증권 스타일 UI로 보여주는 앱. 설계도(`설계도.md`)를 그대로 구현했다.

> ⚠️ 본 분석은 기술적 지표의 **기계적 계산 결과**이며 투자 권유나 수익 보장이 아니다.
> 신뢰도·타이밍 %는 통계적 적중 확률이 아니라 **지표 신호의 일치 정도(휴리스틱 점수)**다.

## 구조

```
backend/                FastAPI — 모든 계산은 여기서 (프론트는 그리기만)
  config.py             임계값·가중치 중앙 관리
  data.py               yfinance 수집 + 메모리 캐시(10분) + 티커 정규화 + 합성 폴백
  indicators.py         RSI / MACD / 일목균형표 / 볼린저밴드 (설계도 §3 공식)
  engine.py             추세 판별 / 타이밍 포착 / 종합 평가 / 가격 역산
  main.py               API 라우트 + 프론트 정적 서빙
frontend/               바닐라 JS — 설계도의 캔버스 차트를 포팅, /api 호출
  index.html
  app.js
설계도.md               기술 명세서
Frontend design based on blueprints/   원본 디자인(참조)
```

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

브라우저에서 `http://127.0.0.1:8000` 접속. 백엔드가 프론트를 같이 서빙한다.

- 상단 검색창에 티커 입력 (예: `NVDA`, `005930`, `AAPL`). 한국 6자리 숫자는 `.KS`→`.KQ` 자동 시도.
- 좌측 관심 종목은 브라우저 `localStorage`에 저장(★ 토글).
- **네트워크가 막혀 yfinance가 실패하면** 결정론적 합성 데이터로 폴백하고 상단에 `데모 데이터`로 표시한다.

## API

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/stock/{ticker}` | 종목 종합 분석(추세·타이밍·평가·신호·상세) |
| GET | `/api/stock/{ticker}/ohlc` | 차트용 봉 + 지표 시계열 |
| GET | `/api/health` | 헬스체크 |

## 설계 결정 (설계도 §12 확인사항)

1. 백엔드: **FastAPI**
2. 캐시 TTL: **10분**
3. 스퀴즈 기준: **최근 120일 밴드폭 하위 25%** (상대 기준)
4. 등급 경계 `80/65/40/25` · 가중치 `추세 40 / 타이밍 40 / 지표 20` (초안대로 출발)
5. 차트: 원본 디자인의 **네이티브 캔버스 렌더러**를 그대로 사용 (lightweight-charts 미도입)

모든 임계값·가중치는 `backend/config.py` 한 곳에서 조정한다.
