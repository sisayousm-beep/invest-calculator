/* 투자판단 — 프론트엔드 로직.
   분석/지표는 전부 백엔드(/api)에서 계산. 여기선 그리기만 한다(설계도 §9). */

const API = '';  // 같은 오리진에서 서빙
const SHIFT = 26;

// ── 상태 ──────────────────────────────────────────────
const state = {
  ticker: 'NVDA',
  favorites: ['NVDA', '005930', 'AAPL', '247540', '035720'],
  sortBy: 'grade',
  cache: {},        // query -> stock 분석 JSON
  animScore: 0,
  animPrice: 0,
  meta: { kr: false, change: 0 },
  portfolio: [],    // [{ticker, avg_price, qty}] — localStorage 저장
};

// ── 포맷/색상 헬퍼 (설계도 §10.2 컬러 토큰) ───────────
const fmt = (v, kr) => kr ? Math.round(v).toLocaleString('en-US') : Number(v).toFixed(2);
const priceStr = (v, kr) => kr ? fmt(v, true) + '원' : '$' + fmt(v, false);
const changeStr = (c) => (c >= 0 ? '▲ ' : '▼ ') + Math.abs(c).toFixed(1) + '%';
const semColor = (c) => c >= 0 ? '#F04452' : '#3182F6';
const gradeColor = (g) => ({ '강한 추천': '#E0303C', '추천': '#F04452', '보류': '#8B95A1', '비추천': '#3182F6', '강한 비추천': '#1F63D6' }[g] || '#8B95A1');
const gradeBg = (g) => ({ '강한 추천': '#FBE3E5', '추천': '#FDECEE', '보류': '#F2F4F6', '비추천': '#EAF2FE', '강한 비추천': '#E4EDFC' }[g] || '#F2F4F6');
const gradeShort = (g) => ({ '강한 추천': '강추', '추천': '추천', '보류': '보류', '비추천': '비추', '강한 비추천': '강비' }[g] || g);
const gradeDesc = (g) => ({
  '강한 추천': '추세·타이밍·지표 신호가 강하게 일치합니다.',
  '추천': '다수 지표가 우호적으로 정렬되어 있습니다.',
  '보류': '신호가 혼재되어 방향성이 불분명합니다.',
  '비추천': '다수 지표가 부정적으로 정렬되어 있습니다.',
  '강한 비추천': '추세·지표 신호가 강하게 하방을 가리킵니다.',
}[g] || '');
const trendColor = (l) => l === '상승추세' ? '#F04452' : l === '하락추세' ? '#3182F6' : '#8B95A1';
const trendArrow = (l) => l === '상승추세' ? '↗' : l === '하락추세' ? '↘' : '→';
const sigColor = (l) => l === '매수' ? '#F04452' : l === '매도' ? '#3182F6' : '#8B95A1';
const sigBg = (l) => l === '매수' ? '#FDECEE' : l === '매도' ? '#EAF2FE' : '#F2F4F6';

const $ = (id) => document.getElementById(id);

// ── API ───────────────────────────────────────────────
async function fetchStock(q) {
  const r = await fetch(`${API}/api/stock/${encodeURIComponent(q)}`);
  if (!r.ok) throw new Error('not found');
  return r.json();
}
async function fetchOhlc(q) {
  const r = await fetch(`${API}/api/stock/${encodeURIComponent(q)}/ohlc`);
  if (!r.ok) throw new Error('not found');
  return r.json();
}
async function fetchTimeframes(q) {
  const r = await fetch(`${API}/api/stock/${encodeURIComponent(q)}/timeframes`);
  if (!r.ok) throw new Error('not found');
  return r.json();
}

// ── 캔버스 ─────────────────────────────────────────────
function setupCanvas(canvas) {
  const w = canvas.clientWidth || 360, h = canvas.clientHeight || 120;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function buildI(d) {
  const n = d.c.length, cd = [];
  for (let i = 0; i < n; i++) cd.push({ o: d.o[i], h: d.h[i], l: d.l[i], c: d.c[i] });
  return {
    n, cd, closes: d.c, kr: d.kr,
    bbU: d.upper, bbL: d.lower, mid: d.mid,
    conv: d.conv, base: d.base, spanA: d.span_a, spanB: d.span_b,
    macd: d.macd, sig: d.signal, hist: d.hist, rsi: d.rsi,
  };
}

function drawMain(I, meta) {
  const s = setupCanvas($('mainChart')); if (!s) return; const { ctx, w, h } = s;
  const n = I.n, vis = Math.min(96, n), start = n - vis, future = 24, slots = vis + future;
  const padL = 8, padR = 58, padT = 10, padB = 22, pw = w - padL - padR, ph = h - padT - padB, step = pw / slots;
  let mn = 1e18, mx = -1e18;
  for (let i = start; i < n; i++) { mn = Math.min(mn, I.cd[i].l, I.bbL[i] ?? 1e18); mx = Math.max(mx, I.cd[i].h, I.bbU[i] ?? -1e18); }
  for (let k = 0; k < slots; k++) { const vi = start + k - SHIFT; if (vi >= 0 && vi < n) { if (I.spanA[vi] != null) { mn = Math.min(mn, I.spanA[vi]); mx = Math.max(mx, I.spanA[vi]); } if (I.spanB[vi] != null) { mn = Math.min(mn, I.spanB[vi]); mx = Math.max(mx, I.spanB[vi]); } } }
  const pad = (mx - mn) * 0.06; mn -= pad; mx += pad;
  const X = k => padL + k * step + step / 2, Y = p => padT + (1 - (p - mn) / (mx - mn)) * ph;

  ctx.font = '11px Pretendard, sans-serif'; ctx.textBaseline = 'middle';
  for (let g = 0; g <= 4; g++) { const val = mn + (mx - mn) * g / 4, y = Y(val);
    ctx.strokeStyle = '#F4F6F8'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillStyle = '#B0B8C1'; ctx.textAlign = 'left'; ctx.fillText(fmt(val, meta.kr), w - padR + 6, y); }
  // 구름대
  for (let k = 0; k < slots - 1; k++) { const vi = start + k - SHIFT, vi2 = vi + 1; if (vi < 0 || vi2 >= n) continue;
    if (I.spanA[vi] == null || I.spanB[vi] == null || I.spanA[vi2] == null || I.spanB[vi2] == null) continue;
    const up = (I.spanA[vi] + I.spanA[vi2]) >= (I.spanB[vi] + I.spanB[vi2]);
    ctx.beginPath(); ctx.moveTo(X(k), Y(I.spanA[vi])); ctx.lineTo(X(k + 1), Y(I.spanA[vi2])); ctx.lineTo(X(k + 1), Y(I.spanB[vi2])); ctx.lineTo(X(k), Y(I.spanB[vi])); ctx.closePath();
    ctx.fillStyle = up ? 'rgba(240,68,82,.12)' : 'rgba(49,130,246,.12)'; ctx.fill(); }
  const line = (arr, off, color, wd) => { ctx.beginPath(); ctx.lineWidth = wd; ctx.strokeStyle = color; let started = false;
    for (let k = 0; k < slots; k++) { const vi = start + k - off; if (vi < 0 || vi >= n || arr[vi] == null) { started = false; continue; } const x = X(k), y = Y(arr[vi]); if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y); } ctx.stroke(); };
  line(I.spanA, SHIFT, 'rgba(240,68,82,.45)', 1); line(I.spanB, SHIFT, 'rgba(49,130,246,.45)', 1);
  const cline = (arr, color, wd, dash) => { ctx.beginPath(); ctx.lineWidth = wd; ctx.strokeStyle = color; ctx.setLineDash(dash || []); let started = false;
    for (let i = start; i < n; i++) { if (arr[i] == null) { started = false; continue; } const x = X(i - start), y = Y(arr[i]); if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y); } ctx.stroke(); ctx.setLineDash([]); };
  cline(I.bbU, 'rgba(176,184,193,.7)', 1); cline(I.bbL, 'rgba(176,184,193,.7)', 1); cline(I.mid, '#C8CDD3', 1, [3, 3]);
  cline(I.conv, '#F5A623', 1.4); cline(I.base, '#9B6DE3', 1.4);
  // 캔들
  const cw = Math.max(2.6, step * 0.62);
  for (let i = start; i < n; i++) { const c = I.cd[i], x = X(i - start), up = c.c >= c.o, col = up ? '#F04452' : '#3182F6';
    ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, Y(c.h)); ctx.lineTo(x, Y(c.l)); ctx.stroke();
    const yo = Y(c.o), yc = Y(c.c), top = Math.min(yo, yc), bh = Math.max(1.5, Math.abs(yc - yo));
    ctx.fillRect(x - cw / 2, top, cw, bh); }
  // 현재가 라인
  const last = I.closes[n - 1], ly = Y(last), lc = semColor(meta.change);
  ctx.setLineDash([4, 3]); ctx.strokeStyle = lc; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, ly); ctx.lineTo(w - padR, ly); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = lc; ctx.fillRect(w - padR, ly - 9, padR, 18); ctx.fillStyle = '#fff'; ctx.font = '10.5px Pretendard, sans-serif'; ctx.textAlign = 'center'; ctx.fillText(fmt(last, meta.kr), w - padR / 2, ly);
}

function drawRsi(I) {
  const s = setupCanvas($('rsiChart')); if (!s) return; const { ctx, w, h } = s;
  const n = I.n, vis = Math.min(96, n), start = n - vis, padL = 8, padR = 30, padT = 8, padB = 8, pw = w - padL - padR, ph = h - padT - padB, step = pw / vis;
  const Y = v => padT + (1 - v / 100) * ph, X = i => padL + i * step + step / 2;
  ctx.font = '10px Pretendard, sans-serif'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
  ctx.strokeStyle = 'rgba(240,68,82,.32)'; ctx.beginPath(); ctx.moveTo(padL, Y(70)); ctx.lineTo(w - padR, Y(70)); ctx.stroke(); ctx.fillStyle = '#D9A0A6'; ctx.fillText('70', w - padR + 5, Y(70));
  ctx.strokeStyle = 'rgba(49,130,246,.32)'; ctx.beginPath(); ctx.moveTo(padL, Y(30)); ctx.lineTo(w - padR, Y(30)); ctx.stroke(); ctx.fillStyle = '#9DB8E0'; ctx.fillText('30', w - padR + 5, Y(30));
  ctx.setLineDash([]);
  ctx.beginPath(); ctx.lineWidth = 1.8; ctx.strokeStyle = '#6B7684'; let started = false;
  for (let i = start; i < n; i++) { if (I.rsi[i] == null) { started = false; continue; } const x = X(i - start), y = Y(I.rsi[i]); if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y); } ctx.stroke();
  const last = I.rsi[n - 1]; if (last != null) { ctx.beginPath(); ctx.fillStyle = last >= 70 ? '#F04452' : last <= 30 ? '#3182F6' : '#6B7684'; ctx.arc(X(vis - 1), Y(last), 3, 0, 7); ctx.fill(); }
}

function drawMacd(I) {
  const s = setupCanvas($('macdChart')); if (!s) return; const { ctx, w, h } = s;
  const n = I.n, vis = Math.min(96, n), start = n - vis, padL = 8, padR = 30, padT = 8, padB = 8, pw = w - padL - padR, ph = h - padT - padB, step = pw / vis;
  let mx = 1e-6; for (let i = start; i < n; i++) for (const a of [I.macd[i], I.sig[i], I.hist[i]]) if (a != null) mx = Math.max(mx, Math.abs(a));
  const Y = v => padT + (1 - (v / (mx * 1.1) + 1) / 2) * ph, X = i => padL + i * step + step / 2;
  const z = Y(0); ctx.strokeStyle = '#E5E8EB'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, z); ctx.lineTo(w - padR, z); ctx.stroke();
  const bw = Math.max(1.8, step * 0.55);
  for (let i = start; i < n; i++) { if (I.hist[i] == null) continue; const x = X(i - start), y = Y(I.hist[i]); ctx.fillStyle = I.hist[i] >= 0 ? 'rgba(240,68,82,.5)' : 'rgba(49,130,246,.5)'; ctx.fillRect(x - bw / 2, Math.min(y, z), bw, Math.abs(y - z)); }
  const ml = (arr, color, wd) => { ctx.beginPath(); ctx.lineWidth = wd; ctx.strokeStyle = color; let st = false; for (let i = start; i < n; i++) { if (arr[i] == null) { st = false; continue; } const x = X(i - start), y = Y(arr[i]); if (!st) { ctx.moveTo(x, y); st = true; } else ctx.lineTo(x, y); } ctx.stroke(); };
  ml(I.macd, '#191F28', 1.5); ml(I.sig, '#F5A623', 1.4);
}

function drawScore(score, grade) {
  const s = setupCanvas($('scoreChart')); if (!s) return; const { ctx, w, h } = s;
  const cx = w / 2, cy = h / 2, r = w / 2 - 9, lw = 9;
  ctx.lineCap = 'round';
  ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.lineWidth = lw; ctx.strokeStyle = '#F2F4F6'; ctx.stroke();
  const frac = Math.max(0, Math.min(1, score / 100)), a0 = -Math.PI / 2, a1 = a0 + Math.PI * 2 * frac;
  ctx.beginPath(); ctx.arc(cx, cy, r, a0, a1); ctx.lineWidth = lw; ctx.strokeStyle = gradeColor(grade); ctx.stroke();
}

// ── 렌더 ───────────────────────────────────────────────
let animTimer = null;
function animateNumbers(stock) {
  clearInterval(animTimer);
  const toS = stock.evaluation.score, toP = stock.price, fromS = 0, fromP = toP * 0.93, dur = 620, t0 = Date.now();
  animTimer = setInterval(() => {
    const p = Math.min(1, (Date.now() - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    state.animScore = Math.round(fromS + (toS - fromS) * e);
    state.animPrice = fromP + (toP - fromP) * e;
    $('gradeScore').textContent = state.animScore;
    $('gradeScore').style.color = gradeColor(stock.evaluation.grade);
    $('stPrice').textContent = priceStr(state.animPrice, stock.kr);
    drawScore(state.animScore, stock.evaluation.grade);
    if (p >= 1) { clearInterval(animTimer); $('stPrice').textContent = priceStr(toP, stock.kr); $('gradeScore').textContent = toS; }
  }, 24);
}

function tfCard(key, v) {
  const card = document.createElement('div');
  if (!v) {
    card.style.cssText = 'background:#F8F9FB;border-radius:13px;padding:13px 14px;font-size:12px;color:#B0B8C1';
    card.innerHTML = `<div style="font-size:12.5px;font-weight:700;color:#8B95A1;margin-bottom:8px">${key === 'long' ? '장기' : '단기'}</div>데이터 없음`;
    return card;
  }
  card.style.cssText = `background:${gradeBg(v.grade)};border-radius:13px;padding:13px 14px`;
  card.title = `최종 봉 ${v.last_bar}${v.source === 'synthetic' ? ' · 데모 데이터' : ''}`;
  card.innerHTML = `
    <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:9px">
      <span style="font-size:12.5px;font-weight:700;color:#4E5968">${v.label}</span>
      <span style="font-size:10.5px;color:#8B95A1">${v.interval_label}</span>
    </div>
    <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:9px">
      <span style="font-size:15px;font-weight:800;color:${gradeColor(v.grade)};letter-spacing:-.2px">${v.grade}</span>
      <span class="tabnum" style="font-size:12px;font-weight:700;color:${gradeColor(v.grade)}">${v.score}</span>
    </div>
    <div style="display:flex;flex-direction:column;gap:5px;font-size:12px">
      <div style="display:flex;justify-content:space-between"><span style="color:#8B95A1">추세</span><span style="font-weight:700;color:${trendColor(v.trend)}">${trendArrow(v.trend)} ${v.trend}</span></div>
      <div style="display:flex;justify-content:space-between"><span style="color:#8B95A1">타이밍</span><span style="font-weight:700;color:#4E5968">${v.timing}</span></div>
    </div>`;
  return card;
}

function renderTimeframes(tf) {
  const box = $('tfCompare'); box.innerHTML = '';
  box.appendChild(tfCard('long', tf && tf.long));
  box.appendChild(tfCard('short', tf && tf.short));
}

function renderStock(stock) {
  $('stName').textContent = stock.name;
  $('stMarket').textContent = stock.market;
  $('stTicker').textContent = stock.ticker;
  $('stChange').textContent = changeStr(stock.change_pct);
  $('stChange').style.color = semColor(stock.change_pct);

  // 연결 상태 (합성 폴백이면 표시)
  if (stock.source === 'synthetic') {
    $('connDot').style.background = '#F5A623'; $('connText').textContent = '데모 데이터 · 일봉 기준';
  } else {
    $('connDot').style.background = '#15B47B'; $('connText').textContent = '실시간 연결됨 · 일봉 기준';
  }

  // 데이터 갱신 시각 (yfinance에서 마지막으로 받아온 시각)
  $('connTime').textContent = stock.updated_at ? `${stock.updated_at} 갱신` : '— 갱신';
  $('connTime').title = stock.last_bar
    ? `데이터를 마지막으로 받아온 시각 · 최종 봉 ${stock.last_bar}`
    : '데이터를 마지막으로 받아온 시각';

  // 종합 평가
  const ev = stock.evaluation;
  $('gradeBadge').textContent = ev.grade;
  $('gradeBadge').style.background = gradeColor(ev.grade);
  $('gradeDesc').textContent = gradeDesc(ev.grade);

  // 등급 전환 예상가 — 가격이 이 수준에 닿으면 종합 등급이 한 단계 바뀐다.
  if (ev.up_price != null) {
    $('upLabel').textContent = `상향 전환 → ${ev.up_grade}`;
    $('upZone').textContent = priceStr(ev.up_price, stock.kr);
  } else {
    $('upLabel').textContent = '상향 전환가';
    $('upZone').textContent = ev.grade === '강한 추천' ? '현재 최고 등급' : '—';
  }
  if (ev.down_price != null) {
    $('downLabel').textContent = `하향 전환 → ${ev.down_grade}`;
    $('downZone').textContent = priceStr(ev.down_price, stock.kr);
  } else {
    $('downLabel').textContent = '하향 전환가';
    $('downZone').textContent = ev.grade === '강한 비추천' ? '현재 최저 등급' : '—';
  }

  // 추세 게이지
  const tr = stock.trend;
  $('trendLabel').textContent = `${trendArrow(tr.label)} ${tr.label}`;
  $('trendLabel').style.color = trendColor(tr.label);
  $('confVal').textContent = `신뢰 ${tr.confidence}%`;
  $('confBar').style.width = tr.confidence + '%';
  $('confBar').style.background = trendColor(tr.label);

  // 타이밍 게이지
  const tm = stock.timing;
  const tmColor = tm.score >= 50 ? '#F04452' : '#3182F6';
  $('timingLabel').textContent = tm.action;
  $('timingLabel').style.color = tmColor;
  $('timingVal').textContent = tm.score + '%';
  $('timingBar').style.width = tm.score + '%';
  $('timingBar').style.background = tmColor;

  // 지표 신호 요약
  $('consensus').textContent = stock.consensus;
  $('consensus').style.color = sigColor(stock.consensus.includes('매수') ? '매수' : stock.consensus.includes('매도') ? '매도' : '중립');
  $('consensus').style.background = sigBg(stock.consensus.includes('매수') ? '매수' : stock.consensus.includes('매도') ? '매도' : '중립');
  const sigBox = $('signals'); sigBox.innerHTML = '';
  stock.signals.forEach((sig, i) => {
    const lineColor = i === stock.signals.length - 1 ? 'transparent' : '#F2F4F6';
    const row = document.createElement('div');
    row.style.cssText = `display:flex;align-items:center;justify-content:space-between;padding:11px 2px;border-bottom:1px solid ${lineColor}`;
    row.innerHTML = `<div><div style="font-size:13.5px;font-weight:600;color:#191F28">${sig.name}</div>
      <div style="font-size:11.5px;color:#B0B8C1;margin-top:2px">${sig.detail}</div></div>
      <span style="flex:none;display:inline-flex;align-items:center;justify-content:center;min-width:54px;font-size:12px;font-weight:700;color:${sigColor(sig.label)};background:${sigBg(sig.label)};padding:5px 10px;border-radius:8px;white-space:nowrap">${sig.label}</span>`;
    sigBox.appendChild(row);
  });

  // 상세 정보
  const d = stock.detail;
  const rows = [
    ['시가총액', d.market_cap], ['섹터', d.sector], ['PER', d.per], ['PBR', d.pbr],
    ['배당수익률', d.dividend_yield], ['거래량', d.volume], ['52주 최고', d.week52_high], ['52주 최저', d.week52_low],
  ];
  const detailBox = $('detail'); detailBox.innerHTML = '';
  rows.forEach(([label, value]) => {
    const el = document.createElement('div');
    el.innerHTML = `<div style="font-size:11.5px;color:#8B95A1;margin-bottom:4px">${label}</div>
      <div class="tabnum" style="font-size:14.5px;font-weight:700;color:#191F28">${value}</div>`;
    detailBox.appendChild(el);
  });

  // RSI / MACD 헤더
  const rsi = stock.indicators.rsi;
  $('rsiVal').textContent = rsi == null ? '—' : rsi.toFixed(1);
  $('rsiVal').style.color = rsi == null ? '#4E5968' : rsi >= 70 ? '#F04452' : rsi <= 30 ? '#3182F6' : '#4E5968';

  // 즐겨찾기 별
  updateStar();
}

function updateStar() {
  const fav = state.favorites.includes(state.ticker);
  $('starBtn').textContent = fav ? '★' : '☆';
  $('starBtn').style.color = fav ? '#3182F6' : '#C8CDD3';
}

async function renderWatchlist() {
  // 즐겨찾기 분석을 병렬로 확보(캐시)
  await Promise.all(state.favorites.map(async q => {
    if (!state.cache[q]) { try { state.cache[q] = await fetchStock(q); } catch (e) { /* skip */ } }
  }));
  const keys = state.favorites.filter(q => state.cache[q]);
  keys.sort((a, b) => state.sortBy === 'grade'
    ? state.cache[b].evaluation.score - state.cache[a].evaluation.score
    : state.cache[b].change_pct - state.cache[a].change_pct);

  $('favCount').textContent = keys.length;
  $('sortBtn').firstChild.textContent = state.sortBy === 'grade' ? '등급순 ' : '등락순 ';
  const box = $('watchlist'); box.innerHTML = '';
  keys.forEach(q => {
    const x = state.cache[q];
    const row = document.createElement('div');
    row.className = 'row-hover';
    row.style.cssText = `display:flex;align-items:center;gap:11px;padding:12px 10px;border-radius:12px;cursor:pointer;margin-bottom:2px;transition:background .12s;background:${q === state.ticker ? '#F4F8FF' : 'transparent'}`;
    row.innerHTML = `
      <div style="flex:none;width:38px;height:38px;border-radius:11px;background:${gradeBg(x.evaluation.grade)};display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;color:${gradeColor(x.evaluation.grade)}">${gradeShort(x.evaluation.grade)}</div>
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:6px">
          <span style="font-size:14px;font-weight:700;letter-spacing:-.2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${x.name}</span>
          <span style="font-size:12px;color:${trendColor(x.trend.label)};font-weight:700;flex:none">${trendArrow(x.trend.label)}</span>
        </div>
        <div class="tabnum" style="font-size:11.5px;color:#8B95A1;margin-top:2px">${x.ticker}</div>
      </div>
      <div style="text-align:right;flex:none">
        <div class="tabnum" style="font-size:13.5px;font-weight:700">${priceStr(x.price, x.kr)}</div>
        <div class="tabnum" style="font-size:11.5px;font-weight:700;color:${semColor(x.change_pct)};margin-top:2px">${changeStr(x.change_pct)}</div>
      </div>`;
    row.onclick = () => loadTicker(q);
    box.appendChild(row);
  });
}

// ── 액션 ───────────────────────────────────────────────
async function loadTicker(q) {
  state.ticker = q;
  try {
    const [stock, ohlc, tf] = await Promise.all([
      state.cache[q] ? Promise.resolve(state.cache[q]) : fetchStock(q),
      fetchOhlc(q),
      fetchTimeframes(q).catch(() => null),
    ]);
    state.cache[q] = stock;
    state.meta = { kr: stock.kr, change: stock.change_pct };
    renderStock(stock);
    renderTimeframes(tf);
    const I = buildI(ohlc); state._lastI = I;
    drawMain(I, state.meta); drawRsi(I); drawMacd(I);
    animateNumbers(stock);
    renderWatchlist();
  } catch (e) {
    const inp = $('search'); inp.style.color = '#F04452'; setTimeout(() => inp.style.color = '#191F28', 900);
  }
}

function toggleFav() {
  const t = state.ticker;
  if (state.favorites.includes(t)) state.favorites = state.favorites.filter(x => x !== t);
  else state.favorites.push(t);
  try { localStorage.setItem('tj_favs', JSON.stringify(state.favorites)); } catch (e) {}
  updateStar(); renderWatchlist();
}

// ── 포트폴리오 모달 ────────────────────────────────────
const pfActColor = k => ({ add: '#F04452', hold: '#8B95A1', trim: '#3182F6', reduce: '#3182F6', cut: '#1F63D6' }[k] || '#8B95A1');
const pfActBg = k => ({ add: '#FDECEE', hold: '#F2F4F6', trim: '#EAF2FE', reduce: '#EAF2FE', cut: '#E4EDFC' }[k] || '#F2F4F6');
const signedPct = v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
const signedMoney = (v, kr) => (v >= 0 ? '+' : '-') + priceStr(Math.abs(v), kr);

function pfRowEl(h) {
  const row = document.createElement('div');
  row.className = 'pf-row';
  row.style.cssText = 'display:grid;grid-template-columns:1fr 1.4fr .8fr 30px;gap:10px;align-items:center';
  const inp = 'border:1px solid #E5E8EB;outline:none;background:#fff;border-radius:9px;padding:9px 11px;font-family:inherit;font-size:13.5px;color:#191F28;width:100%';
  row.innerHTML =
    `<input class="pf-ticker" placeholder="예: NVDA, 005930" value="${h && h.ticker ? h.ticker : ''}" style="${inp}">
     <div style="display:flex;gap:5px;align-items:center">
       <input class="pf-avg tabnum" type="number" min="0" step="any" placeholder="평단가" value="${h && h.avg_price ? h.avg_price : ''}" style="${inp};flex:1;min-width:0">
       <select class="pf-cur" title="평단가 입력 통화" style="border:1px solid #E5E8EB;outline:none;background:#fff;border-radius:9px;padding:9px 4px;font-family:inherit;font-size:12.5px;color:#4E5968;flex:none;cursor:pointer">
         <option value="USD">USD</option>
         <option value="KRW">원</option>
       </select>
     </div>
     <input class="pf-qty tabnum" type="number" min="0" step="any" placeholder="수량" value="${h && h.qty ? h.qty : ''}" style="${inp}">
     <button class="pf-del" title="삭제" style="border:none;background:#F2F4F6;color:#8B95A1;width:30px;height:30px;border-radius:8px;cursor:pointer;font-size:15px;line-height:1">×</button>`;
  // 평단가 입력 통화: 6자리 숫자=한국주 → 원화 고정. 그 외=해외주 → USD/원 선택(증권사 표기에 맞춰).
  const tkInp = row.querySelector('.pf-ticker'), avgInp = row.querySelector('.pf-avg'), curSel = row.querySelector('.pf-cur');
  if (h && h.currency) curSel.value = h.currency;
  const syncCur = () => {
    const isKr = /^\d{6}$/.test(tkInp.value.trim());
    if (isKr) { curSel.value = 'KRW'; curSel.disabled = true; }
    else curSel.disabled = false;
    avgInp.placeholder = isKr ? '평단가 (원)' : '평단가';
  };
  tkInp.addEventListener('input', syncCur); syncCur();
  row.querySelector('.pf-del').onclick = () => { readPfRows(); state.portfolio.splice([...$('pfRows').children].indexOf(row), 1); renderPfRows(); };
  return row;
}

function renderPfRows() {
  const box = $('pfRows'); box.innerHTML = '';
  const list = state.portfolio.length ? state.portfolio : [null];
  list.forEach(h => box.appendChild(pfRowEl(h)));
}

function readPfRows() {
  state.portfolio = [...document.querySelectorAll('#pfRows .pf-row')].map(r => ({
    ticker: r.querySelector('.pf-ticker').value.trim(),
    avg_price: parseFloat(r.querySelector('.pf-avg').value),
    qty: parseFloat(r.querySelector('.pf-qty').value),
    currency: r.querySelector('.pf-cur').value,
  }));
}

function openPf() {
  renderPfRows();
  $('pfResult').innerHTML = '';
  $('pfOverlay').style.display = 'flex';
}
function closePf() { readPfRows(); savePf(); $('pfOverlay').style.display = 'none'; }
function savePf() { try { localStorage.setItem('tj_portfolio', JSON.stringify(state.portfolio)); } catch (e) {} }

async function analyzePf() {
  readPfRows();
  const holdings = state.portfolio.filter(h => h.ticker && h.avg_price > 0 && h.qty > 0);
  if (!holdings.length) {
    $('pfResult').innerHTML = `<div style="background:#FFF4E5;color:#B26A00;border-radius:12px;padding:14px 16px;font-size:13px;font-weight:600">종목·평단가·수량을 한 종목 이상 올바르게 입력해 주세요.</div>`;
    return;
  }
  savePf();
  const btn = $('pfAnalyze'); btn.disabled = true; btn.textContent = '분석 중…'; btn.style.background = '#A9C7F8';
  $('pfResult').innerHTML = `<div style="text-align:center;color:#8B95A1;font-size:13px;padding:18px">보유 종목을 분석하고 있어요…</div>`;
  try {
    const r = await fetch(`${API}/api/portfolio`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holdings }),
    });
    if (!r.ok) throw new Error('fail');
    renderPfResult(await r.json());
  } catch (e) {
    $('pfResult').innerHTML = `<div style="background:#FDECEE;color:#C0303C;border-radius:12px;padding:14px 16px;font-size:13px;font-weight:600">분석에 실패했어요. 잠시 후 다시 시도해 주세요.</div>`;
  } finally {
    btn.disabled = false; btn.textContent = '분석하기'; btn.style.background = '#3182F6';
  }
}

function renderPfResult(data) {
  const box = $('pfResult');
  if (!data.holdings.length) {
    box.innerHTML = `<div style="background:#fff;border-radius:14px;padding:18px;text-align:center;color:#8B95A1;font-size:13px">분석 가능한 종목이 없어요.</div>`;
    return;
  }
  let html = '';

  // 종합 코멘트
  html += `<div style="background:#EAF2FE;border-radius:14px;padding:15px 17px;font-size:13.5px;font-weight:600;color:#1B64C9;margin-bottom:14px">💡 ${data.comment}</div>`;

  // 통합 요약 (원화 기준 — 미국주는 환율 환산해 합산)
  const sm = data.summary;
  html += `<div style="background:#fff;border-radius:14px;padding:16px 18px;box-shadow:0 1px 3px rgba(20,30,50,.04);margin-bottom:16px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
      <span style="font-size:13px;font-weight:700;color:#4E5968">총 평가금액 · 원화 기준</span>
      <span style="font-size:11px;font-weight:600;color:#8B95A1;background:#F2F4F6;padding:3px 8px;border-radius:6px">${sm.count}종목 · ${sm.concentration}</span>
    </div>
    <div class="tabnum" style="font-size:25px;font-weight:800;letter-spacing:-.5px">${priceStr(sm.value, true)}</div>
    <div class="tabnum" style="font-size:12px;color:#8B95A1;margin-top:2px">매입 ${priceStr(sm.cost, true)}</div>
    <div class="tabnum" style="font-size:14.5px;font-weight:700;margin-top:8px;color:${semColor(sm.pnl)}">${signedMoney(sm.pnl, true)} · ${signedPct(sm.return_pct)}</div>
    <div style="font-size:11px;color:#B0B8C1;margin-top:9px">적용 환율 USD/KRW ${data.fx_rate.toLocaleString('en-US')}원${data.fx_live ? '' : ' · 오프라인 폴백'}</div>
  </div>`;

  // 종목별 카드
  data.holdings.forEach(h => {
    html += `<div style="background:#fff;border-radius:14px;padding:15px 17px;box-shadow:0 1px 3px rgba(20,30,50,.04);margin-bottom:10px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px">
        <div style="min-width:0">
          <div style="display:flex;align-items:center;gap:7px">
            <span style="font-size:15.5px;font-weight:800;letter-spacing:-.3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${h.name}</span>
            <span style="flex:none;font-size:10.5px;font-weight:600;color:#8B95A1;background:#F2F4F6;border-radius:6px;padding:2px 7px">${h.market}</span>
            <span style="flex:none;font-size:11px;font-weight:700;color:${gradeColor(h.grade)};background:${gradeBg(h.grade)};border-radius:6px;padding:2px 8px">${h.grade}</span>
          </div>
          <div class="tabnum" style="font-size:11.5px;color:#8B95A1;margin-top:3px">${h.qty}주 · 평단 ${priceStr(h.avg_price, h.kr)} → 현재 ${priceStr(h.price, h.kr)}</div>
        </div>
        <span style="flex:none;font-size:13.5px;font-weight:800;color:${pfActColor(h.action_kind)};background:${pfActBg(h.action_kind)};border-radius:9px;padding:8px 13px;white-space:nowrap">${h.action}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:11px">
        <div><div style="font-size:11px;color:#8B95A1;margin-bottom:3px">평가금액</div><div class="tabnum" style="font-size:14px;font-weight:700">${priceStr(h.eval_amount, h.kr)}</div>${h.kr ? '' : `<div class="tabnum" style="font-size:10.5px;color:#B0B8C1;margin-top:1px">≈ ${priceStr(h.value_krw, true)}</div>`}</div>
        <div><div style="font-size:11px;color:#8B95A1;margin-bottom:3px">평가손익</div><div class="tabnum" style="font-size:14px;font-weight:700;color:${semColor(h.pnl)}">${signedPct(h.return_pct)}</div></div>
        <div><div style="font-size:11px;color:#8B95A1;margin-bottom:3px">비중</div><div class="tabnum" style="font-size:14px;font-weight:700">${Math.round(h.weight * 100)}%</div></div>
      </div>
      <div style="font-size:12px;color:#6B7684;background:#F8F9FB;border-radius:9px;padding:10px 12px;line-height:1.5">${h.reason}</div>
    </div>`;
  });

  // 실패 종목
  if (data.errors && data.errors.length) {
    html += `<div style="background:#FFF4E5;color:#B26A00;border-radius:12px;padding:12px 15px;font-size:12.5px;margin-top:4px">분석하지 못한 종목: ${data.errors.map(e => e.ticker).join(', ')}</div>`;
  }
  box.innerHTML = html;
}

// ── 초기화 ─────────────────────────────────────────────
function init() {
  try { const f = JSON.parse(localStorage.getItem('tj_favs')); if (Array.isArray(f) && f.length) state.favorites = f; } catch (e) {}
  try { const p = JSON.parse(localStorage.getItem('tj_portfolio')); if (Array.isArray(p)) state.portfolio = p; } catch (e) {}

  $('search').addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const q = e.target.value.trim();
    if (!q) return;
    loadTicker(q); e.target.value = ''; e.target.blur();
  });
  $('starBtn').addEventListener('click', toggleFav);
  $('sortBtn').addEventListener('click', () => { state.sortBy = state.sortBy === 'grade' ? 'change' : 'grade'; renderWatchlist(); });
  window.addEventListener('resize', () => { if (state._lastI) { drawMain(state._lastI, state.meta); drawRsi(state._lastI); drawMacd(state._lastI); } });

  // 포트폴리오 모달
  $('pfBtn').addEventListener('click', openPf);
  $('pfClose').addEventListener('click', closePf);
  $('pfAdd').addEventListener('click', () => { readPfRows(); state.portfolio.push({ ticker: '', avg_price: '', qty: '', currency: 'USD' }); renderPfRows(); });
  $('pfAnalyze').addEventListener('click', analyzePf);
  $('pfOverlay').addEventListener('mousedown', e => { if (e.target === $('pfOverlay')) closePf(); });

  const first = state.favorites.includes('NVDA') ? 'NVDA' : state.favorites[0];
  loadTicker(first);
  renderWatchlist();
}

document.addEventListener('DOMContentLoaded', init);
