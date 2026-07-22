// 看盤 v2:全市場搜尋+自選分組+產業/主題分類+排行(admin 永豐即時)+intel 訊號燈。
// 訂閱者=免費延遲源(/stock-quotes 15s);admin=台股經 quote bridge 5s(券商行情限本人)。
const WORKER_URL = "https://api.marketdaily.ai";

const I18N = {
  zh: {
    pg_title: "MarketDaily 看盤", pg_h1: "📈 看盤", back_dash: "← 回 Dashboard",
    src_delayed: "參考報價 · 15s 更新", src_live: "永豐即時 · 5s",
    search_ph: "搜尋任何股票:代號或名稱(台股+美股)…",
    tab_watch: "⭐ 自選", tab_cats: "🗂 分類", tab_ranks: "🏆 排行",
    sec_tw: "台股", sec_us: "美股",
    col_sym: "代號 / 名稱", col_px: "成交", col_chg: "漲跌", col_bid: "買進", col_ask: "賣出",
    col_hl: "高 / 低", col_vol: "量(張)", col_qty: "股數", col_avg: "均價", col_now: "現價", col_pnl: "損益",
    gate_msg: "請先登入", gate_link: "前往 Dashboard →",
    empty_msg: "這個清單目前是空的。", empty_link: "去新增自選 →", more: "顯示更多 ↓",
    grp_all: "全部", grp_new: "＋新群組", grp_prompt: "群組名稱?", grp_del_confirm: "刪除這個群組?",
    rank_change: "漲幅", rank_volume: "成交量", rank_amount: "成交額", rank_range: "振幅", rank_tick: "成交筆數",
    rank_title: "排行榜", rank_src: "永豐即時 · 30s",
    pos_title: "💼 我的部位", pos_unsigned: "帳戶尚未簽署 API 服務同意書,簽署後這裡會顯示真實持股部位與未實現損益。到永豐理財網 → API 申請頁完成線上簽署即可。",
    sheet_sigs: "📡 信息差訊號", sheet_nosig: "近期無 intel 訊號(24 個信息源監測中)",
    sheet_groups: "加入群組", limit_up: "🔥 漲停", limit_down: "❄️ 跌停",
    foot_note: "報價僅供參考,非即時交易依據。個股資訊與訊號為系統自動彙整,不構成投資建議。",
    theme_tag: "主題", ind_group: "產業別",
  },
  en: {
    pg_title: "MarketDaily Watch", pg_h1: "📈 Watch", back_dash: "← Dashboard",
    src_delayed: "Reference quotes · 15s", src_live: "SinoPac real-time · 5s",
    search_ph: "Search any stock: symbol or name (TW + US)…",
    tab_watch: "⭐ Watchlist", tab_cats: "🗂 Sectors", tab_ranks: "🏆 Ranks",
    sec_tw: "Taiwan", sec_us: "US",
    col_sym: "Symbol / Name", col_px: "Last", col_chg: "Chg", col_bid: "Bid", col_ask: "Ask",
    col_hl: "H / L", col_vol: "Vol", col_qty: "Shares", col_avg: "Avg", col_now: "Last", col_pnl: "P&L",
    gate_msg: "Please sign in first.", gate_link: "Go to Dashboard →",
    empty_msg: "This list is empty.", empty_link: "Add stocks →", more: "Show more ↓",
    grp_all: "All", grp_new: "+ New group", grp_prompt: "Group name?", grp_del_confirm: "Delete this group?",
    rank_change: "Gainers", rank_volume: "Volume", rank_amount: "Turnover", rank_range: "Range", rank_tick: "Ticks",
    rank_title: "Rankings", rank_src: "SinoPac real-time · 30s",
    pos_title: "💼 My Positions", pos_unsigned: "Your brokerage account has not signed the API service agreement yet. Once signed, real positions and unrealized P&L will appear here.",
    sheet_sigs: "📡 Intel Signals", sheet_nosig: "No recent intel signals (24 sources monitored)",
    sheet_groups: "Add to group", limit_up: "🔥 Limit Up", limit_down: "❄️ Limit Down",
    foot_note: "Quotes are for reference only, not a basis for live trading. Stock info and signals are auto-aggregated and are not investment advice.",
    theme_tag: "Theme", ind_group: "Industry",
  }
};
const LANG = (localStorage.getItem("md-lang-v2") || "zh");
const T = k => (I18N[LANG] || I18N.zh)[k] || I18N.zh[k] || k;
document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = T(el.getAttribute("data-i18n")); });
document.querySelectorAll("[data-i18n-html]").forEach(el => { el.innerHTML = T(el.getAttribute("data-i18n-html")); });
document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = T(el.getAttribute("data-i18n-placeholder")); });
document.title = T("pg_title");

const $ = id => document.getElementById(id);
const isTWSym = s => /^\d{4,6}[A-Z]?$/.test(String(s || ""));
const nameMap = new Map();
try { US_STOCKS_FULL.forEach(([s, n]) => nameMap.set(s, n)); TW_STOCKS_FULL.forEach(([s, n]) => nameMap.set(s, n)); } catch {}
const INDUSTRY = (typeof TW_INDUSTRY !== "undefined") ? TW_INDUSTRY : {};
const CATEGORIES = (typeof TW_CATEGORIES !== "undefined") ? TW_CATEGORIES : {};
const THEMES = (typeof TW_THEMES !== "undefined") ? TW_THEMES : {};

const email = localStorage.getItem("md-email");
const pwd = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
const isAdmin = localStorage.getItem("md-plan") === "admin";

let prefsTw = [], prefsUs = [];
let groups = {};
try { groups = JSON.parse(localStorage.getItem("md-watch-groups") || "{}") || {}; } catch {}
const saveGroups = () => localStorage.setItem("md-watch-groups", JSON.stringify(groups));

let curTab = "watch", curGroup = "all", curCat = "", curRank = "change", catPage = 1;
const CAT_PAGE = 60;
let quotes = {};
let signals = {};
let bridge = null, bridgeFails = 0;
let tick = 0, schedTimer = null, sheetSym = null;

/* ── helpers ── */
function fmtChg(c, sym) {
  if (c === null || c === undefined) return { dir: "neutral", label: "—" };
  if (isTWSym(sym) && c >= 9.9) return { dir: "up", label: T("limit_up") };
  if (isTWSym(sym) && c <= -9.9) return { dir: "down", label: T("limit_down") };
  return { dir: c >= 0 ? "up" : "down", label: `${c >= 0 ? "▲" : "▼"} ${Math.abs(c).toFixed(2)}%` };
}
const fp = v => v == null ? "—" : (v >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : (v >= 100 ? v.toFixed(1) : v.toFixed(2)));

function sigDot(sym) {
  const items = signals[sym];
  if (!items || !items.length) return "";
  const lvl = items.some(i => i.level === "red") ? "red" : "yellow";
  return `<span class="sig-dot ${lvl}"></span>`;
}

function rowHtml(sym) {
  const nm = nameMap.get(sym) || "";
  const ind = INDUSTRY[sym] ? `<span class="ind-tag">${INDUSTRY[sym]}</span>` : "";
  return `<tr data-sym="${sym}"><td>${sigDot(sym)}<span class="sym">${sym}</span>${ind}<span class="nm">${nm}</span></td>
    <td class="px" id="px-${sym}">—</td><td id="chg-${sym}" class="neutral">—</td>
    <td class="ext" id="bid-${sym}">—</td><td class="ext" id="ask-${sym}">—</td>
    <td class="ext hide-sm" id="hl-${sym}">—</td><td class="ext hide-sm" id="vol-${sym}">—</td></tr>`;
}

function paint(q) {
  const s = q.symbol;
  quotes[s] = Object.assign(quotes[s] || {}, q);
  const px = $("px-" + s);
  if (!px) return;
  if (q.price == null && px.textContent !== "—") return;
  const prev = px.textContent;
  px.textContent = fp(q.price);
  const { dir, label } = fmtChg(q.change, s);
  px.className = "px " + dir;
  const chg = $("chg-" + s);
  if (chg) { chg.textContent = label; chg.className = dir; }
  if (q.bid !== undefined && $("bid-" + s)) {
    $("bid-" + s).textContent = fp(q.bid);
    $("ask-" + s).textContent = fp(q.ask);
    $("hl-" + s).textContent = `${fp(q.high)} / ${fp(q.low)}`;
    $("vol-" + s).textContent = q.volume == null ? "—" : q.volume.toLocaleString();
  }
  if (prev !== "—" && prev !== px.textContent) {
    const tr = document.querySelector(`tr[data-sym="${s}"]`);
    if (tr) { tr.classList.remove("flash"); void tr.offsetWidth; tr.classList.add("flash"); }
  }
}

/* ── current view symbols ── */
function viewSyms() {
  if (curTab === "watch") {
    if (curGroup === "all") return prefsTw.concat(prefsUs);
    return (groups[curGroup] || []).slice();
  }
  if (curTab === "cats") {
    const list = CATEGORIES[curCat] || THEMES[curCat] || [];
    return list.slice(0, catPage * CAT_PAGE);
  }
  return [];
}

/* ── rendering ── */
function renderView() {
  const syms = viewSyms();
  const tw = syms.filter(isTWSym), us = syms.filter(s => !isTWSym(s));
  $("rank-sec").style.display = curTab === "ranks" ? "block" : "none";
  $("group-chips").style.display = curTab === "watch" ? "flex" : "none";
  $("cat-bar").style.display = curTab === "cats" ? "flex" : "none";
  $("rank-chips").style.display = curTab === "ranks" ? "flex" : "none";
  $("pos-wrap").style.display = (curTab === "watch" && isAdmin) ? "block" : "none";
  if (curTab === "ranks") {
    $("tw-sec").style.display = "none"; $("us-sec").style.display = "none"; $("empty").style.display = "none";
    renderRanks([]);
    fetchRanks();
    return;
  }
  $("tw-sec").style.display = tw.length ? "block" : "none";
  $("us-sec").style.display = us.length ? "block" : "none";
  $("empty").style.display = (tw.length || us.length) ? "none" : "block";
  $("tw-cnt").textContent = tw.length || "";
  $("us-cnt").textContent = us.length || "";
  document.querySelector("#tw-table tbody").innerHTML = tw.map(rowHtml).join("");
  document.querySelector("#us-table tbody").innerHTML = us.map(rowHtml).join("");
  const fullList = curTab === "cats" ? (CATEGORIES[curCat] || THEMES[curCat] || []) : [];
  $("tw-more").style.display = (curTab === "cats" && fullList.length > syms.length) ? "block" : "none";
  Object.values(quotes).forEach(q => paint(q));
  refreshNow();
}

function renderTabs() {
  document.querySelectorAll(".tab").forEach(b => {
    b.classList.toggle("on", b.dataset.tab === curTab);
  });
}

function renderGroupChips() {
  const el = $("group-chips");
  const names = Object.keys(groups);
  let html = `<button class="chip ${curGroup === "all" ? "on" : ""}" data-g="all">${T("grp_all")}</button>`;
  html += names.map(n => `<button class="chip ${curGroup === n ? "on" : ""}" data-g="${n}">${n}</button>`).join("");
  html += `<button class="chip" data-g="__new">${T("grp_new")}</button>`;
  el.innerHTML = html;
  el.querySelectorAll(".chip").forEach(c => c.onclick = () => {
    const g = c.dataset.g;
    if (g === "__new") {
      const name = prompt(T("grp_prompt"));
      if (name && !groups[name]) { groups[name] = []; saveGroups(); curGroup = name; }
    } else if (g !== "all" && curGroup === g) {
      if (confirm(`${T("grp_del_confirm")}(${g})`)) { delete groups[g]; saveGroups(); curGroup = "all"; }
    } else {
      curGroup = g;
    }
    renderGroupChips(); renderView();
  });
}

function renderCatSel() {
  const sel = $("cat-sel");
  const themeNames = Object.keys(THEMES);
  const catNames = Object.keys(CATEGORIES);
  sel.innerHTML =
    `<optgroup label="${T("theme_tag")}">` + themeNames.map(c => `<option value="${c}">${c}</option>`).join("") + `</optgroup>` +
    `<optgroup label="${T("ind_group")}">` + catNames.map(c => `<option value="${c}">${c}(${CATEGORIES[c].length})</option>`).join("") + `</optgroup>`;
  if (!curCat) curCat = themeNames[0] || catNames[0] || "";
  sel.value = curCat;
  sel.onchange = () => { curCat = sel.value; catPage = 1; renderView(); };
}

const RANK_LABELS = { change: "rank_change", volume: "rank_volume", amount: "rank_amount", range: "rank_range", tick: "rank_tick" };
function renderRankChips() {
  const el = $("rank-chips");
  el.innerHTML = Object.keys(RANK_LABELS).map(k =>
    `<button class="chip ${curRank === k ? "on" : ""}" data-r="${k}">${T(RANK_LABELS[k])}</button>`).join("");
  el.querySelectorAll(".chip").forEach(c => c.onclick = () => { curRank = c.dataset.r; renderRankChips(); renderView(); });
}

function renderRanks(rows) {
  $("rank-title").textContent = `${T(RANK_LABELS[curRank])} ${T("rank_title")}`;
  document.querySelector("#rank-table tbody").innerHTML = rows.map((r, i) => {
    const { dir, label } = fmtChg(r.change_pct, r.code);
    return `<tr data-sym="${r.code}"><td>${i + 1}</td>
      <td>${sigDot(r.code)}<span class="sym">${r.code}</span><span class="nm">${r.name || nameMap.get(r.code) || ""}</span></td>
      <td class="px ${dir}">${fp(r.close)}</td><td class="${dir}">${label}</td>
      <td class="hide-sm">${r.volume == null ? "—" : r.volume.toLocaleString()}</td></tr>`;
  }).join("");
}

/* ── data fetching ── */
async function fetchFree(syms) {
  const chunks = [];
  for (let i = 0; i < syms.length; i += 25) chunks.push(syms.slice(i, i + 25));
  const parts = await Promise.all(chunks.map(c =>
    fetch(`${WORKER_URL}/stock-quotes?tickers=${c.join(",")}`).then(r => r.json()).catch(() => ({ quotes: [] }))
  ));
  return parts.flatMap(p => p.quotes || []);
}

async function tickFree() {
  const syms = viewSyms();
  const bridgeOk = bridge && bridgeFails < 3;
  const target = bridgeOk ? syms.filter(s => !isTWSym(s)) : syms;
  if (!target.length) return;
  (await fetchFree(target.slice(0, 120))).forEach(paint);
}

async function tickLive() {
  if (!bridge) return;
  const tw = viewSyms().filter(isTWSym);
  if (!tw.length) return;
  try {
    const r = await fetch(`${bridge.url}/q?syms=${tw.slice(0, 60).join(",")}&t=${encodeURIComponent(bridge.token)}`);
    if (!r.ok) throw new Error(r.status);
    (await r.json()).quotes.forEach(paint);
    bridgeFails = 0;
  } catch { bridgeFails++; }
}

async function fetchRanks() {
  if (!bridge || curTab !== "ranks") return;
  try {
    const r = await fetch(`${bridge.url}/ranks?type=${curRank}&t=${encodeURIComponent(bridge.token)}`);
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    if (curTab === "ranks" && d.type === curRank) renderRanks(d.ranks || []);
  } catch {}
}

async function tickPositions() {
  if (!bridge) return;
  try {
    const r = await fetch(`${bridge.url}/positions?t=${encodeURIComponent(bridge.token)}`);
    const d = await r.json();
    const wrap = $("pos-wrap");
    if (d.status === "not_signed") {
      wrap.innerHTML = `<div class="pos-card"><p class="pos-title">${T("pos_title")}</p><p class="pos-hint">${T("pos_unsigned")}</p></div>`;
      return;
    }
    if (d.status === "ok") {
      const rows = d.positions.map(p => {
        const dir = (p.pnl || 0) >= 0 ? "up" : "down";
        return `<tr data-sym="${p.code}"><td>${sigDot(p.code)}<span class="sym">${p.code}</span><span class="nm">${nameMap.get(p.code) || ""}</span></td>
          <td>${p.quantity}</td><td>${fp(p.avg_price)}</td><td class="px">${fp(p.last_price)}</td>
          <td class="${dir}">${(p.pnl || 0) >= 0 ? "+" : ""}${Math.round(p.pnl || 0).toLocaleString()}</td></tr>`;
      }).join("");
      wrap.innerHTML = `<div class="sec"><div class="sec-title"><span>${T("pos_title")}</span></div>
        <table><thead><tr><th>${T("col_sym")}</th><th>${T("col_qty")}</th><th>${T("col_avg")}</th><th>${T("col_now")}</th><th>${T("col_pnl")}</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
    }
  } catch {}
}

async function loadSignals() {
  try {
    const r = await fetch(WORKER_URL + "/watch-signals");
    const d = await r.json();
    signals = d.by_code || {};
  } catch {}
}

function refreshNow() { tickFree(); tickLive(); }

/* ── scheduler ── */
function startSched() {
  if (schedTimer) clearInterval(schedTimer);
  schedTimer = setInterval(() => {
    tick++;
    if (document.hidden) return;
    const bridgeOk = bridge && bridgeFails < 3;
    if (bridgeOk && tick % 5 === 0) tickLive();
    if (tick % 15 === 0) tickFree();
    if (bridge && curTab === "ranks" && tick % 30 === 0) fetchRanks();
    if (bridge && isAdmin && tick % 60 === 0 && curTab === "watch") tickPositions();
  }, 1000);
}

/* ── sheet(個股詳情) ── */
function openSheet(sym) {
  sheetSym = sym;
  const q = quotes[sym] || {};
  const nm = nameMap.get(sym) || "";
  const ind = INDUSTRY[sym] || "";
  const sigs = signals[sym] || [];
  const gNames = Object.keys(groups);
  const gChips = gNames.map(g => {
    const on = (groups[g] || []).includes(sym);
    return `<button class="chip ${on ? "on" : ""}" data-sg="${g}">${on ? "✓ " : ""}${g}</button>`;
  }).join("") + `<button class="chip" data-sg="__new">${T("grp_new")}</button>`;
  $("sheet").innerHTML = `
    <h3>${sym} <span style="font-size:13px;color:var(--muted)">${nm}</span></h3>
    <div class="s-ind">${ind}</div>
    <div class="s-q">
      <span>${T("col_px")} <b id="sh-px">${fp(q.price)}</b></span>
      <span>${T("col_chg")} <b>${fmtChg(q.change, sym).label}</b></span>
      ${q.high != null ? `<span>${T("col_hl")} <b>${fp(q.high)} / ${fp(q.low)}</b></span>` : ""}
      ${q.volume != null ? `<span>${T("col_vol")} <b>${(q.volume || 0).toLocaleString()}</b></span>` : ""}
    </div>
    <div class="g-title">${T("sheet_sigs")}</div>
    ${sigs.length ? sigs.map(s => `<div class="sig-item"><div class="src">${s.level === "red" ? "🔴" : "🟡"} ${s.source}</div>${s.signal}</div>`).join("")
      : `<div class="sig-item" style="color:var(--muted)">${T("sheet_nosig")}</div>`}
    <div class="g-title">${T("sheet_groups")}</div>
    <div class="g-row">${gChips}</div>`;
  $("sheet").querySelectorAll("[data-sg]").forEach(c => c.onclick = () => {
    let g = c.dataset.sg;
    if (g === "__new") {
      g = prompt(T("grp_prompt"));
      if (!g) return;
      if (!groups[g]) groups[g] = [];
    }
    const arr = groups[g];
    const i = arr.indexOf(sym);
    if (i >= 0) arr.splice(i, 1); else arr.push(sym);
    saveGroups(); renderGroupChips(); openSheet(sym);
    if (curTab === "watch" && curGroup !== "all") renderView();
  });
  $("sheet").classList.add("open"); $("sheet-bg").classList.add("open");
}
$("sheet-bg").onclick = () => { $("sheet").classList.remove("open"); $("sheet-bg").classList.remove("open"); sheetSym = null; };

document.addEventListener("click", e => {
  const tr = e.target.closest("tbody tr[data-sym]");
  if (tr) openSheet(tr.dataset.sym);
});

/* ── search ── */
function searchUniverse(qstr) {
  const q = qstr.trim().toUpperCase();
  if (!q) return [];
  const out = [];
  const scan = (arr) => {
    for (const [c, n] of arr) {
      if (out.length >= 12) return;
      if (c.startsWith(q) || (n || "").toUpperCase().includes(q)) out.push([c, n]);
    }
  };
  try { scan(TW_STOCKS_FULL); scan(US_STOCKS_FULL); } catch {}
  return out;
}
$("search").addEventListener("input", () => {
  const res = searchUniverse($("search").value);
  const drop = $("sr-drop");
  if (!res.length) { drop.style.display = "none"; return; }
  drop.innerHTML = res.map(([c, n]) =>
    `<div class="sr-item" data-s="${c}"><span class="c">${sigDot(c)}${c}</span><span class="n">${n}</span></div>`).join("");
  drop.style.display = "block";
  drop.querySelectorAll(".sr-item").forEach(it => it.onclick = () => {
    drop.style.display = "none"; $("search").value = "";
    const sym = it.dataset.s;
    if (!quotes[sym]) fetchFree([sym]).then(qs => { qs.forEach(paint); if (sheetSym === sym) openSheet(sym); });
    if (bridge && isTWSym(sym)) {
      fetch(`${bridge.url}/q?syms=${sym}&t=${encodeURIComponent(bridge.token)}`)
        .then(r => r.json()).then(d => { (d.quotes || []).forEach(paint); if (sheetSym === sym) openSheet(sym); }).catch(() => {});
    }
    openSheet(sym);
  });
});
document.addEventListener("click", e => { if (!e.target.closest(".searchbox")) $("sr-drop").style.display = "none"; });

/* ── init ── */
async function initBridge() {
  if (!isAdmin || !pwd) return;
  try {
    const cached = sessionStorage.getItem("md-watch-bridge");
    if (cached) { bridge = JSON.parse(cached); }
    else {
      const r = await fetch(WORKER_URL + "/watch-token", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pwd }) });
      if (!r.ok) return;
      bridge = await r.json();
      sessionStorage.setItem("md-watch-bridge", JSON.stringify(bridge));
    }
    $("tw-table").classList.add("live-mode");
    $("src-badge").classList.add("live");
    $("src-label").textContent = T("src_live");
    $("tab-ranks").style.display = "";
    tickLive(); tickPositions();
  } catch {}
}

async function init() {
  if (!email || !pwd) { $("gate").style.display = "block"; return; }
  let data;
  try {
    const r = await fetch(WORKER_URL + "/get-preferences", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pwd }) });
    data = await r.json();
    if (r.status === 403 || data.error) { $("gate").style.display = "block"; return; }
  } catch { $("gate").style.display = "block"; return; }
  prefsTw = data.tw_stocks || [];
  prefsUs = data.us_stocks || [];
  $("app").style.display = "block";
  document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
    curTab = b.dataset.tab; catPage = 1; renderTabs(); renderView();
  });
  $("tw-more").onclick = () => { catPage++; renderView(); };
  renderTabs(); renderGroupChips(); renderCatSel(); renderRankChips();
  await loadSignals();
  renderView();
  startSched();
  initBridge();
}
init();
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshNow(); });
