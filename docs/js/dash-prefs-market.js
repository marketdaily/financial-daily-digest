// dashboard.html 內嵌 JS 抽出(dash-prefs-market.js);7 檔按原始順序載入,順序不可換(全域相依)。2026-07-03 P5。
async function loadPreferences(email) {
  try {
    const pwd = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
    const res = await fetch(WORKER_URL + "/get-preferences", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pwd }) });
    const data = await res.json();
    if (res.status === 403 || data.error === "auth") {
      // session 密碼遺失/過期(sessionStorage 隨關瀏覽器清掉、又沒勾記住我)→ 無法載入用戶資料。
      // 不可停在半殘 dashboard(股票空白/限時動態消失/存檔失敗),送回登入重新輸入密碼。
      requireReauth(email);
      return;
    }
    if (data && data.plan) {
      // get-preferences 已過密碼驗證 → plan 是唯一權威來源,用它校正所有方案閘門。
      // (修:LINE/chat 卡原本吃會過期的 localStorage md-plan;用戶升級 premium 後 md-plan 還停在 free → 卡片消失/深度鎖死)
      // ⚠️ admin 是 ADMIN_EMAILS 賦予,get-preferences 只回 KV plan(admin 帳號 KV 多半=premium)→ 不可被覆寫掉 admin。
      const eff = localStorage.getItem("md-plan") === "admin" ? "admin" : data.plan;
      userPlan = eff;
      userCap = data.cap == null ? Infinity : data.cap;
      localStorage.setItem("md-plan", eff);
      const planBadge = document.getElementById("plan-badge");
      if (planBadge) {
        planBadge.textContent = eff === "admin" ? T('hdr_plan_admin') : eff === "free" ? T('hdr_plan_free') : T('hdr_plan_paid');
        planBadge.classList.toggle("admin", eff === "admin");
      }
      setupChatCard(email, eff);
    } else {
      // 密碼缺失 / 驗證失敗(403):不可靜默降級成 free —— 會讓 premium 用戶看起來像免費。沿用登入時的 plan。
      userPlan = localStorage.getItem("md-plan") || "free";
    }
    selectedDepth = data.digest_depth || "standard";
    setupDepthCard();
    selected.us = []; selected.tw = [];
    (data.us_stocks || []).forEach(sym => { const f = US_STOCKS.find(([s])=>s===sym); selected.us.push({ sym, name: f ? f[1] : sym }); });
    (data.tw_stocks || []).forEach(sym => { const f = TW_STOCKS.find(([s])=>s===sym); selected.tw.push({ sym, name: f ? f[1] : sym }); });
    renderTags("us"); renderTags("tw"); updateStats();
    if (typeof renderQuickRow === 'function') { renderQuickRow('us'); renderQuickRow('tw'); }
    _lastSaved = curPayload();
  } catch {}
}

/* ── MARKET OVERVIEW ── */
async function loadMarketOverview() {
  try {
    const res = await fetch(`${WORKER_URL}/market-overview`);
    const { overview } = await res.json();
    if (!overview.length) return;
    const row = document.getElementById("mo-row");
    row.innerHTML = overview.map(m => {
      const dir = m.change === null ? "flat" : m.change >= 0 ? "up" : "down";
      const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "—";
      const changeStr = m.change !== null ? `${arrow} ${Math.abs(m.change).toFixed(2)}%` : "—";
      const priceStr = m.price !== null ? (m.price >= 1000 ? m.price.toLocaleString(undefined, {maximumFractionDigits: 0}) : m.price.toFixed(2)) : "—";
      return `<div class="mo-card">
        <div class="mo-label">${m.label}</div>
        <div class="mo-price">${priceStr}</div>
        <div class="mo-change ${dir}">${changeStr}</div>
      </div>`;
    }).join("");
    document.getElementById("market-overview-section").style.display = "block";
  } catch {}
}

/* ── STORIES ── */
// 統一格式化股價漲跌:含台股漲停 (≥9.9%) / 跌停 (≤-9.9%) 標籤。
// 台股代號 = 4-6 位數字;美股不套漲跌停(美股沒有 ±10% 限制)。
function fmtChange(change, symbol) {
  if (change === null || change === undefined) return { dir: "neutral", label: "—" };
  const isTW = /^\d{4,6}$/.test(String(symbol || ""));
  if (isTW && change >= 9.9)  return { dir: "up",   label: "🔥 漲停" };
  if (isTW && change <= -9.9) return { dir: "down", label: "❄️ 跌停" };
  const dir = change >= 0 ? "up" : "down";
  return { dir, label: `${change >= 0 ? "▲" : "▼"} ${Math.abs(change).toFixed(2)}%` };
}

let _stories = [];
let _storyIdx = 0;
let _quotesRefreshTimer = null;
let _countdownTimer = null;
let _countdownVal = 60;

function startCountdown() {
  const el = document.getElementById("sync-counter");
  const wrap = document.getElementById("sync-countdown");
  if (!el || !wrap) return;
  if (_countdownTimer) clearInterval(_countdownTimer);
  _countdownVal = 60;
  wrap.style.display = "flex";
  el.textContent = _countdownVal;
  _countdownTimer = setInterval(() => {
    _countdownVal--;
    if (_countdownVal <= 0) _countdownVal = 60;
    el.textContent = _countdownVal;
  }, 1000);
}

// 追蹤超過 25 支時分批請求 quotes:worker 端有單請求支數上限
// (2026-06-10 實鍋:34美股+22台股=56 支被 slice(0,50) 砍掉最後 6 支 → 那幾檔永遠「···」)
async function fetchQuotesChunked(syms) {
  const chunks = [];
  for (let i = 0; i < syms.length; i += 25) chunks.push(syms.slice(i, i + 25));
  const parts = await Promise.all(chunks.map(c =>
    fetch(`${WORKER_URL}/stock-quotes?tickers=${c.join(",")}`).then(r => r.json()).catch(() => ({ quotes: [] }))
  ));
  return parts.flatMap(p => p.quotes || []);
}

async function refreshQuotes() {
  if (!_stories.length) return;
  try {
    const quotes = await fetchQuotesChunked(_stories.map(s => s.symbol));
    quotes.forEach(q => {
      const idx = _stories.findIndex(s => s.symbol === q.symbol);
      if (idx === -1) return;
      // 抓到空值時保留上一個好報價,不要把已顯示的數字蓋成「—」
      if (q.price == null && q.change == null && _stories[idx].price != null) return;
      _stories[idx].price = q.price;
      _stories[idx].change = q.change;
      // 好報價寫回本機留底,供下次首屏與限流時段使用
      if (q.price != null) {
        try {
          const qc = JSON.parse(localStorage.getItem("md-quote-cache") || "{}");
          qc[q.symbol] = { price: q.price, change: q.change, ts: Date.now() };
          localStorage.setItem("md-quote-cache", JSON.stringify(qc));
        } catch {}
      }
      // Update bubble
      const bubble = document.querySelector(`[data-sym="${q.symbol}"]`);
      if (bubble) {
        const { dir, label } = fmtChange(q.change, q.symbol);
        const ring = bubble.querySelector(".story-ring");
        if (ring) { ring.classList.remove("up","down","neutral"); ring.classList.add(dir); }
        const cl = bubble.querySelector(".story-change-label");
        if (cl) { cl.textContent = label; cl.className = `story-change-label ${dir}`; }
      }
    });
    // Update open story card if visible
    if (document.getElementById("story-overlay").classList.contains("open")) {
      const q = _stories[_storyIdx];
      if (q) {
        const { dir, label } = fmtChange(q.change, q.symbol);
        document.getElementById("sc-change").textContent = label;
        document.getElementById("sc-change").className = `story-card-change ${dir}`;
        const isTW = /^\d{4,6}$/.test(String(q.symbol || ""));
        const ccy = isTW ? "" : "$";
        const fp = (v) => v >= 100 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(2);
        document.getElementById("sc-price").textContent = q.price !== null ? `${ccy}${fp(q.price)}` : "";
      }
    }
  } catch {}
  startCountdown();
}

function storySignal(change) {
  if (change === null) return { label: T('sig_neutral'), cls: "neutral", score: "5.0", targetPct: 3 };
  if (change >= 5)   return { label: T('sig_bullish'),  cls: "bull",    score: (Math.min(9.5, 5 + change * 0.7)).toFixed(1), targetPct: 8 };
  if (change >= 2)   return { label: T('sig_bullish'),  cls: "bull",    score: (5 + change * 0.7).toFixed(1), targetPct: 5 };
  if (change >= 0.5) return { label: T('sig_bull_slight'), cls: "bull",    score: (5 + change * 0.7).toFixed(1), targetPct: 3 };
  if (change >= -0.5) return { label: T('sig_neutral'),  cls: "neutral", score: "5.0", targetPct: 3 };
  if (change >= -2)  return { label: T('sig_bear_slight'), cls: "bear",    score: (5 + change * 0.7).toFixed(1), targetPct: -3 };
  if (change >= -5)  return { label: T('sig_bearish'),   cls: "bear",    score: (Math.max(1.5, 5 + change * 0.7)).toFixed(1), targetPct: -5 };
  return { label: T('sig_bearish'), cls: "bear", score: "1.5", targetPct: -8 };
}

function storyVerdict(change) {
  if (change === null) return T('verdict_no_data');
  if (change >= 5)  return T('verdict_strong_up');
  if (change >= 2)  return T('verdict_up');
  if (change >= 0)  return T('verdict_slight_up');
  if (change >= -2) return T('verdict_slight_down');
  if (change >= -5) return T('verdict_down');
  return T('verdict_strong_down');
}

