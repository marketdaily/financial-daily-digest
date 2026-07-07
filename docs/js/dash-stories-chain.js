// dashboard.html 內嵌 JS 抽出(dash-stories-chain.js);7 檔按原始順序載入,順序不可換(全域相依)。2026-07-03 P5。
async function loadStories(email) {
  const row = document.getElementById("stories-row");
  const section = document.getElementById("stories-section");
  const allSelected = [...(selected.us || []), ...(selected.tw || [])];
  const tickers = allSelected.map(s => s.sym);
  if (!tickers.length) return;

  // Build sym→Chinese name map from local preferences
  const nameMap = {};
  allSelected.forEach(s => { nameMap[s.sym] = s.name; });

  try {
    const quotes = await fetchQuotesChunked(tickers);
    // Ensure every selected ticker appears, fallback to null data if API missed any
    const returnedSyms = new Set(quotes.map(q => q.symbol));
    allSelected.forEach(s => { if (!returnedSyms.has(s.sym)) quotes.push({ symbol: s.sym, name: s.name, price: null, change: null }); });
    if (!quotes.length) return;
    // Override with Chinese names from local prefs
    quotes.forEach(q => { if (nameMap[q.symbol]) q.name = nameMap[q.symbol]; });
    // Yahoo 偶發限流抓不到時,用本機留底的上一筆好報價(24h 內)頂上,首屏不再「···」
    try {
      const qc = JSON.parse(localStorage.getItem("md-quote-cache") || "{}");
      quotes.forEach(q => {
        const c = qc[q.symbol];
        if (q.price == null && c && Date.now() - c.ts < 86400e3) { q.price = c.price; q.change = c.change; }
      });
      quotes.forEach(q => { if (q.price != null) qc[q.symbol] = { price: q.price, change: q.change, ts: Date.now() }; });
      localStorage.setItem("md-quote-cache", JSON.stringify(qc));
    } catch {}
    _stories = quotes;
    if (_quotesRefreshTimer) clearInterval(_quotesRefreshTimer);
    _quotesRefreshTimer = setInterval(refreshQuotes, 15000);
    // 初次載入有股票還沒抓到價(Yahoo 偶發限流),4s/9s 各補抓一次,不乾等 15s
    if (quotes.some(q => q.price == null)) { setTimeout(refreshQuotes, 4000); setTimeout(refreshQuotes, 9000); }
    startCountdown();
    const seen = JSON.parse(sessionStorage.getItem("md-stories-seen") || "{}");
    row.innerHTML = quotes.map((q, i) => {
      let { dir, label: changeLabel } = fmtChange(q.change, q.symbol);
      if (q.price == null && q.change == null) { changeLabel = "···"; dir = "neutral"; }
      const isSeen = !!seen[q.symbol];
      const isTW = /^\d{4,6}$/.test(q.symbol);
      const bubbleLabel = isTW ? (nameMap[q.symbol] || q.symbol) : q.symbol;
      const innerLabel = isTW ? (nameMap[q.symbol] ? nameMap[q.symbol].slice(0,4) : q.symbol) : (q.symbol.length > 5 ? q.symbol.slice(0,4) : q.symbol);
      return `<div class="story-bubble" data-sym="${q.symbol}" onclick="openStory(${i})">
        <div class="story-ring ${dir}${isSeen ? " seen" : ""}">
          <div class="story-inner">${innerLabel}</div>
        </div>
        <div class="story-ticker-label">${bubbleLabel}</div>
        <div class="story-change-label ${dir}">${changeLabel}</div>
      </div>`;
    }).join("");
    section.style.display = "block";
    initStoriesScroller();
    requestAnimationFrame(updateStoriesNav);
  } catch {}
}

var _storiesScrollerInit = false;
var _storiesDragged = false;

function updateStoriesNav() {
  const row = document.getElementById("stories-row");
  const scroller = row && row.closest(".stories-scroller");
  if (!row || !scroller) return;
  const max = row.scrollWidth - row.clientWidth;
  const overflow = max > 8;
  scroller.classList.toggle("scrollable", overflow);
  const prev = document.getElementById("stories-nav-prev");
  const next = document.getElementById("stories-nav-next");
  if (prev) prev.hidden = !overflow || row.scrollLeft <= 4;
  if (next) next.hidden = !overflow || row.scrollLeft >= max - 4;
}

function scrollStories(dir) {
  const row = document.getElementById("stories-row");
  if (!row) return;
  row.scrollBy({ left: dir * Math.max(220, row.clientWidth * 0.7), behavior: "smooth" });
}

function initStoriesScroller() {
  if (_storiesScrollerInit) return;
  const row = document.getElementById("stories-row");
  if (!row) return;
  _storiesScrollerInit = true;

  row.addEventListener("wheel", (e) => {
    const max = row.scrollWidth - row.clientWidth;
    if (max <= 0) return;
    const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    if (!d) return;
    e.preventDefault();
    row.scrollLeft += d;
  }, { passive: false });

  let down = false, dragging = false, startX = 0, startLeft = 0, pid = null;
  row.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "touch") return;
    down = true; dragging = false; startX = e.clientX; startLeft = row.scrollLeft; pid = e.pointerId;
    _storiesDragged = false;
  });
  row.addEventListener("pointermove", (e) => {
    if (!down) return;
    const dx = e.clientX - startX;
    if (!dragging) {
      if (Math.abs(dx) <= 6) return; // 還沒超過門檻 = 視為單純點擊,不攔截
      dragging = true; _storiesDragged = true;
      row.classList.add("dragging");
      try { row.setPointerCapture(pid); } catch {}
    }
    row.scrollLeft = startLeft - dx;
  });
  const endDrag = () => {
    if (!down) return;
    down = false;
    if (dragging) {
      row.classList.remove("dragging");
      try { row.releasePointerCapture(pid); } catch {}
      setTimeout(() => { _storiesDragged = false; }, 0);
    }
    dragging = false;
  };
  row.addEventListener("pointerup", endDrag);
  row.addEventListener("pointercancel", endDrag);

  row.addEventListener("scroll", updateStoriesNav, { passive: true });
  window.addEventListener("resize", updateStoriesNav);
}

function openStory(idx) {
  if (_storiesDragged) return;
  _storyIdx = idx;
  const overlay = document.getElementById("story-overlay");
  overlay.classList.add("open");
  renderStoryCard();
}

function renderStoryCard() {
  const q = _stories[_storyIdx];
  if (!q) { closeStories(); return; }

  const changeVal = q.change !== null ? q.change : null;
  const isTW = /^\d{4,6}$/.test(String(q.symbol || ""));
  const ccy = isTW ? "" : "$";  // 台股慣例不加 $,美股加 $
  // 用 fmtChange 統一 (與 stories bubble 一致,含台股漲停/跌停標籤)
  const { dir, label: changeStr } = fmtChange(changeVal, q.symbol);
  const fmtPrice = (v) => v >= 100 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(2);
  const priceStr = q.price !== null ? `${ccy}${fmtPrice(q.price)}` : "";

  document.getElementById("sc-ticker").textContent = q.symbol;
  document.getElementById("sc-name").textContent = q.name;
  document.getElementById("sc-change").textContent = changeStr;
  document.getElementById("sc-change").className = `story-card-change ${dir}`;
  document.getElementById("sc-price").textContent = priceStr;

  // Signal + score (invest-skill style)
  const sig = storySignal(changeVal);
  const badge = document.getElementById("sc-sig-badge");
  badge.textContent = sig.label;
  badge.className = `sc-sig-badge ${sig.cls}`;
  document.getElementById("sc-sig-score").textContent = `${sig.score}/10`;

  // Key levels: prev close (support) + target (含貨幣符號,跟價格區一致)
  const levelsEl = document.getElementById("sc-levels");
  if (q.price !== null && changeVal !== null) {
    const prevClose = q.price / (1 + changeVal / 100);
    const target = q.price * (1 + sig.targetPct / 100);
    levelsEl.innerHTML =
      `<span class="sc-level-chip">${T('level_support')} ${ccy}${fmtPrice(prevClose)}</span>` +
      `<span class="sc-level-chip">${sig.targetPct >= 0 ? T('level_target') : T('level_stop')} ${ccy}${fmtPrice(target)} (${sig.targetPct > 0 ? "+" : ""}${sig.targetPct}%)</span>`;
  } else {
    levelsEl.innerHTML = "";
  }

  document.getElementById("sc-verdict").textContent = storyVerdict(changeVal);

  // Progress dots
  const progRow = document.getElementById("story-progress-row");
  progRow.innerHTML = _stories.map((_, i) =>
    `<div class="story-prog-bar"><div class="story-prog-fill ${i < _storyIdx ? "done" : i === _storyIdx ? "active" : ""}"></div></div>`
  ).join("");

  // Mark seen
  const seen = JSON.parse(sessionStorage.getItem("md-stories-seen") || "{}");
  seen[q.symbol] = 1;
  sessionStorage.setItem("md-stories-seen", JSON.stringify(seen));
  const bubble = document.querySelector(`[data-sym="${q.symbol}"] .story-ring`);
  if (bubble) bubble.classList.add("seen");

  // Chart — drawn from Yahoo data, same source as the quote card above
  const sym = q.symbol;
  const isTWsym = /^\d{4,6}$/.test(sym);
  const chartLink = isTWsym
    ? `https://finance.yahoo.com/quote/${sym}.TW/chart/`
    : `https://finance.yahoo.com/quote/${sym}/chart/`;

  const chartSection = `
    <div class="story-chart-section">
      <div class="story-chart-periods">
        <button class="scp-btn${_chartPeriod==="1D"?" active":""}" onclick="setChartPeriod('1D')">1D</button>
        <button class="scp-btn${_chartPeriod==="5D"?" active":""}" onclick="setChartPeriod('5D')">5D</button>
        <button class="scp-btn${_chartPeriod==="1M"?" active":""}" onclick="setChartPeriod('1M')">1M</button>
        <button class="scp-btn${_chartPeriod==="3M"?" active":""}" onclick="setChartPeriod('3M')">3M</button>
      </div>
      <div class="story-chart-wrap" style="position:relative;">
        <canvas id="story-chart-canvas" style="width:100%;height:100%;display:block;touch-action:none;cursor:crosshair;"></canvas>
        <div id="story-chart-msg" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:rgba(226,232,240,0.4);pointer-events:none;"></div>
        <a href="${chartLink}" target="_blank" rel="noopener" style="position:absolute;bottom:6px;right:8px;font-size:10px;color:rgba(165,180,252,0.55);text-decoration:none;z-index:2;background:rgba(0,0,0,0.4);padding:2px 6px;border-radius:4px;">${T('chart_full')}</a>
      </div>
    </div>`;

  const verdictEl = document.getElementById("sc-verdict");
  let chartEl = document.getElementById("sc-chart-section");
  if (!chartEl) {
    chartEl = document.createElement("div");
    chartEl.id = "sc-chart-section";
    verdictEl.parentNode.insertBefore(chartEl, verdictEl);
  }
  chartEl.innerHTML = chartSection;
  loadChart(sym, _chartPeriod);

  // 產業鏈 / 供應鏈區塊(走勢圖下方)
  let scEl = document.getElementById("sc-supplychain");
  if (!scEl) {
    scEl = document.createElement("div");
    scEl.id = "sc-supplychain";
    chartEl.parentNode.insertBefore(scEl, chartEl.nextSibling);
  }
  loadSupplyChain(sym);
}

// ── 產業鏈 / 供應鏈 ──────────────────────────────
let _scStaticDB = null;        // docs/data/supply_chain.json(核實資料), null=未載, {}=載入失敗
let _scStaticLoading = null;
const _scCache = {};           // session 內快取(含 AI 結果)

async function _loadScStaticDB() {
  if (_scStaticDB !== null) return _scStaticDB;
  if (!_scStaticLoading) {
    _scStaticLoading = fetch("data/supply_chain.json")
      .then(r => r.ok ? r.json() : {})
      .catch(() => ({}))
      .then(db => { _scStaticDB = db || {}; return _scStaticDB; });
  }
  return _scStaticLoading;
}

function _scLookupStatic(db, sym) {
  if (db[sym]) return db[sym];
  if (/^\d{4,6}$/.test(sym)) return db[`${sym}.TW`] || db[`${sym}.TWO`] || null;
  return null;
}

async function loadSupplyChain(sym) {
  const el = document.getElementById("sc-supplychain");
  if (!el) return;
  const reqSym = sym;
  el.innerHTML = `<div class="sc-loading">${T('sc_loading')}</div>`;

  let data = _scCache[sym];
  if (!data) {
    const db = await _loadScStaticDB();
    if (reqSym !== _stories[_storyIdx]?.symbol) return;  // 已切到別張卡
    data = _scLookupStatic(db, sym);
    if (!data) {
      try {
        const nm = _stories[_storyIdx]?.name || "";
        const res = await fetch(`${WORKER_URL}/supply-chain?ticker=${encodeURIComponent(sym)}&name=${encodeURIComponent(nm)}`);
        if (res.ok) data = await res.json();
      } catch {}
    }
    if (data) _scCache[sym] = data;
  }
  if (reqSym !== _stories[_storyIdx]?.symbol) return;
  if (!data || (!data.mid?.desc && !(data.upstream||[]).length && !(data.downstream||[]).length)) {
    el.innerHTML = `<div class="sc-empty">${T('sc_unavailable')}</div>`;
  } else {
    el.innerHTML = renderSupplyChain(data, sym);
  }
  // 🆕 最新供應鏈動態(官方公告事件,產業鏈圖之外非同步補上;沒有就不顯示)
  _loadScUpdates(sym).then(evts => {
    if (reqSym !== _stories[_storyIdx]?.symbol || !evts.length) return;
    const cur = document.getElementById("sc-supplychain");
    if (cur && !cur.querySelector(".sc-upd-label")) {
      cur.insertAdjacentHTML("beforeend", renderScUpdates(evts));
    }
  });
}

const _scUpdCache = {};

async function _loadScUpdates(sym) {
  if (_scUpdCache[sym] !== undefined) return _scUpdCache[sym];
  try {
    const r = await fetch(`${WORKER_URL}/supply-chain-updates?ticker=${encodeURIComponent(sym)}`);
    const j = r.ok ? await r.json() : null;
    _scUpdCache[sym] = (j && Array.isArray(j.events)) ? j.events : [];
  } catch { _scUpdCache[sym] = []; }
  return _scUpdCache[sym];
}

function renderScUpdates(evts) {
  const items = evts.slice(0, 5).map(e => {
    const cp = e.counterparty ? `<b>${_esc(e.counterparty)}</b> · ` : "";
    const safeUrl = (e.url && /^https:\/\//.test(e.url)) ? _esc(e.url).replace(/"/g, "%22") : "";
    const link = safeUrl ? ` <a class="sc-upd-src" href="${safeUrl}" target="_blank" rel="noopener">${T('sc_upd_src')}</a>` : "";
    return `<div class="sc-item sc-upd">
      <div class="sc-item-top"><span class="sc-upd-date">${_esc(e.date || "")}</span><span class="sc-upd-badge">${T('sc_upd_pending')}</span></div>
      <div class="sc-item-role">${cp}${_esc(e.headline || "")}${link}</div>
    </div>`;
  }).join("");
  return `<div class="sc-section-label sc-upd-label">🆕 ${T('sc_upd_heading')}</div><div class="sc-items">${items}</div>`;
}

function _scCritClass(c) {
  const s = String(c || "");
  if (s.includes("極高") || /very ?high/i.test(s)) return "crit-vh";
  if (s.includes("高") || /\bhigh\b/i.test(s)) return "crit-h";
  if (s.includes("中") || /\bmed/i.test(s)) return "crit-m";
  return "crit-l";
}

function _esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _scItem(p, side) {
  const lang = (localStorage.getItem("md-lang-v2") || "zh");
  const name = _esc(lang === "en" ? (p.name_en || p.name_zh) : (p.name_zh || p.name_en));
  const tk = p.ticker ? `<span class="sc-item-tk">${_esc(p.ticker)}</span>` : "";
  const crit = p.criticality ? `<span class="sc-item-crit ${_scCritClass(p.criticality)}">${_esc(p.criticality)}</span>` : "";
  const cat = p.category ? `<b>${_esc(p.category)}</b>` : "";
  const role = p.role ? _esc(p.role) : "";
  const detail = [cat, role].filter(Boolean).join(" · ");
  return `<div class="sc-item ${side}">
    <div class="sc-item-top"><span class="sc-item-name">${name}</span>${tk}${crit}</div>
    ${detail ? `<div class="sc-item-role">${detail}</div>` : ""}
  </div>`;
}

function renderSupplyChain(d, sym) {
  const upArr = d.upstream || [], downArr = d.downstream || [];
  const up = upArr.length ? `<div class="sc-items">${upArr.map(p => _scItem(p, "up")).join("")}</div>` : `<div class="sc-none">${T('sc_none')}</div>`;
  const down = downArr.length ? `<div class="sc-items">${downArr.map(p => _scItem(p, "down")).join("")}</div>` : `<div class="sc-none">${T('sc_none')}</div>`;
  const industry = d.industry ? `<span class="sc-industry">${_esc(d.industry)}</span>` : "";
  const srcLabel = d.source === "verified"
    ? `<span class="sc-src sc-src-ok">${T('sc_verified')}</span>`
    : `<span class="sc-src sc-src-ai">${T('sc_ai')}</span>`;
  return `
    <div class="sc-head">
      <span class="sc-title">${T('sc_heading')}</span>${industry}${srcLabel}
    </div>
    ${d.mid?.desc ? `<div class="sc-bizmodel">${_esc(d.mid.desc)}</div>` : ""}
    <div class="sc-section-label sc-up-label">▲ ${T('sc_upstream')}</div>
    ${up}
    <div class="sc-section-label sc-down-label">▼ ${T('sc_downstream')}</div>
    ${down}
    <div class="sc-disclaimer">${T('sc_disclaimer')}</div>`;
}

function storyNav(dir) {
  const next = _storyIdx + dir;
  if (next < 0) { closeStories(); return; }
  if (next >= _stories.length) { closeStories(); return; }
  _storyIdx = next;
  renderStoryCard();
}

function closeStories() {
  document.getElementById("story-overlay").classList.remove("open");
}
document.addEventListener("keydown", e => { if (e.key === "Escape") closeStories(); });

let _chartPeriod = "1M";
let _chartReqId = 0;
let _chartData = null;
let _chartGeom = null;
let _chartHover = null;
let _chartAnimId = null;

