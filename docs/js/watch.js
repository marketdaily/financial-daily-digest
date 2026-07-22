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
    col_hl: "高 / 低", col_vol: "量(張)", col_vol_us: "量(股)", col_qty: "股數", col_avg: "均價", col_now: "現價", col_pnl: "損益",
    gate_msg: "請先登入", gate_link: "前往 Dashboard →",
    empty_msg: "這個清單目前是空的。", empty_link: "去新增自選 →", more: "顯示更多 ↓",
    grp_all: "全部", grp_new: "＋新群組", grp_prompt: "群組名稱?", grp_del_confirm: "刪除這個群組?",
    rank_change: "漲幅", rank_volume: "成交量", rank_amount: "成交額", rank_range: "振幅", rank_tick: "成交筆數",
    rank_limit_up: "🔥 漲停", rank_near_up: "🚀 即將漲停", rank_limit_down: "❄️ 跌停", rank_near_dn: "⚠️ 即將跌停",
    rank_title: "排行榜", rank_src: "永豐即時 · 30s",
    pos_title: "💼 我的部位", pos_unsigned: "帳戶尚未簽署 API 服務同意書,簽署後這裡會顯示真實持股部位與未實現損益。到永豐理財網 → API 申請頁完成線上簽署即可。",
    sheet_sigs: "📡 信息差訊號", sheet_nosig: "近期無 intel 訊號(24 個信息源監測中)",
    sig_pop_foot: "🔴 強訊號 · 🟡 留意級|24 信息源自動偵測,非投資建議",
    sheet_groups: "加入群組", limit_up: "🔥 漲停", limit_down: "❄️ 跌停",
    foot_note: "報價僅供參考,非即時交易依據。個股資訊與訊號為系統自動彙整,不構成投資建議。",
    theme_tag: "主題", ind_group: "產業別",
    tf_1D: "分時", tf_5D: "5日", tf_3M: "日K·3月", tf_6M: "日K·6月", tf_1Y: "週K·1年", tf_m5: "5分K", tf_m30: "30分K",
    sec_tech: "📐 技術指標", sec_fund: "📊 基本面", sec_prof: "🏢 公司", sec_chain: "🔗 上下游產業鏈",
    chain_up: "上游", chain_down: "下游", chain_self: "本業",
    chain_verified: "✓ 公司級精修鏈", chain_generic: "產業通用鏈", chain_wip: "公司級產業鏈整理中,先參考公司簡介",
    fd_pe: "本益比", fd_dy: "殖利率", fd_pb: "股價淨值比", fd_mcap: "市值", fd_eps: "EPS(TTM)",
    fd_52: "52週高低", fd_beta: "Beta", fd_ind: "產業", fd_asof: "官方日更",
    prof_chair: "董事長", prof_gm: "總經理", prof_listed: "上市", prof_web: "官網",
    ti_over: "超買", ti_under: "超賣", ti_mid: "中性", ti_gold: "多方", ti_dead: "空方",
    ti_above: "站上", ti_below: "跌破",
    sec_depth: "📶 五檔報價", depth_bid: "買盤", depth_ask: "賣盤", depth_pending: "訂閱中…",
    sec_news: "📰 新聞", news_none: "近兩週無相關新聞",
    sort_def: "預設", sort_gain: "漲幅", sort_lose: "跌幅", sort_sig: "燈號優先",
    loading: "載入中…", chart_fail: "圖表載入失敗", vol_note: "下方=成交量",
    tab_screen: "🔎 選股", tab_news: "📰 新聞", tf_5Y: "月K·5年",
    sec_chips: "🧮 籌碼面", sec_findeep: "📑 財務體質", sec_diag: "🧭 多空總覽", sec_alerts: "🔔 到價警示",
    sec_ticks: "⚡ 內外盤 · 大單", scr_result: "篩選結果",
    chip_inst: "三大法人買賣超(張)", chip_margin: "融資 / 融券餘額(張)", chip_foreign: "外資持股比(%)", chip_dt: "當沖率(%)",
    fin_rev: "月營收(億) · 年增率", fin_eps: "每股盈餘 EPS(季)", fin_margin: "三率(%)", fin_per: "本益比 · 淨值比(1年)",
    diag_bull: "多方因子", diag_bear: "空方因子",
    al_above: "價格 ≥", al_below: "價格 ≤", al_chg_up: "漲幅 ≥%", al_chg_dn: "跌幅 ≥%", al_vol: "量 ≥ 張",
    al_add: "新增警示", al_none: "尚無警示條件,設定後價格達標會即時通知。", al_fired: "已觸發",
    al_rearm: "重新啟用", al_all_title: "全部警示", al_noperm: "瀏覽器通知未開啟,只有頁面開著才看得到提醒",
    io_out: "外盤", io_in: "內盤", big_buy: "大單買", big_sell: "大單賣", ticks_recent: "最近成交",
    scr_ind: "產業", scr_pe: "本益比 ≤", scr_dy: "殖利率 ≥%", scr_pb: "淨值比 ≤", scr_px: "價格範圍", scr_all: "全部",
    scr_run: "開始篩選", scr_sort: "排序", scr_sort_dy: "殖利率高→低", scr_sort_pe: "本益比低→高", scr_sort_pb: "淨值比低→高",
    nw_headline: "頭條", nw_tw: "台股", nw_wd: "國際", nw_forex: "外匯", nw_future: "期貨",
    sync_on: "雲端同步中", exp_ok: "已匯出", imp_ok: "已匯入", imp_bad: "檔案格式不對",
    boll_lbl: "布林", sub_vol: "量", grp_tools: "⚙",
    cb_theme: "可轉債",
    tab_heat: "🌡 熱力", heat_src: "TWSE 類股指數 · 收盤", heat_hint: "點類股 → 看成分股",
    ct_candle: "蠟燭", ct_ha: "平均K", ct_bar: "美國線", ct_area: "面積", log_lbl: "LOG",
    tool_trend: "╱ 趨勢線", tool_hline: "─ 水平線", tool_fib: "𝄃 斐波那契", tool_text: "T 文字", tool_erase: "⌫ 擦除", tool_clear: "🗑 清空",
    cmp_lbl: "⇄ 比較", cmp_prompt: "輸入要比較的代號(逗號分隔,最多3檔;留空=清除):",
    replay_lbl: "▶ 回放", replay_exit: "✕ 結束回放",
    fs_lbl: "⛶", snap_lbl: "📷",
    draw_hint: "點兩下圖表定位;再點工具取消",
    al_ma20_up: "站上 MA20", al_ma20_dn: "跌破 MA20", al_ma60_up: "站上 MA60", al_ma60_dn: "跌破 MA60",
    al_rsi_gt: "RSI ≥", al_rsi_lt: "RSI ≤", al_kd_gold: "KD 黃金交叉", al_kd_dead: "KD 死亡交叉",
    al_boll_up: "突破布林上軌", al_boll_dn: "跌破布林下軌",
    scr_tech: "技術條件", scr_ma20: "站上MA20", scr_ma60: "站上MA60", scr_rsi_lo: "RSI<30", scr_rsi_hi: "RSI>70", scr_volx: "量比≥2",
    scr_calc: "技術條件計算中…",
    fd_loss: "虧損", fd_loss_sub: "近12月 EPS 為負", fd_loss_sub_tw: "近4季 EPS ≤ 0", fd_nodiv: "無配息或無資料",
  },
  en: {
    pg_title: "MarketDaily Watch", pg_h1: "📈 Watch", back_dash: "← Dashboard",
    src_delayed: "Reference quotes · 15s", src_live: "SinoPac real-time · 5s",
    search_ph: "Search any stock: symbol or name (TW + US)…",
    tab_watch: "⭐ Watchlist", tab_cats: "🗂 Sectors", tab_ranks: "🏆 Ranks",
    sec_tw: "Taiwan", sec_us: "US",
    col_sym: "Symbol / Name", col_px: "Last", col_chg: "Chg", col_bid: "Bid", col_ask: "Ask",
    col_hl: "H / L", col_vol: "Vol", col_vol_us: "Vol", col_qty: "Shares", col_avg: "Avg", col_now: "Last", col_pnl: "P&L",
    gate_msg: "Please sign in first.", gate_link: "Go to Dashboard →",
    empty_msg: "This list is empty.", empty_link: "Add stocks →", more: "Show more ↓",
    grp_all: "All", grp_new: "+ New group", grp_prompt: "Group name?", grp_del_confirm: "Delete this group?",
    rank_change: "Gainers", rank_volume: "Volume", rank_amount: "Turnover", rank_range: "Range", rank_tick: "Ticks",
    rank_limit_up: "🔥 Limit Up", rank_near_up: "🚀 Near Limit Up", rank_limit_down: "❄️ Limit Down", rank_near_dn: "⚠️ Near Limit Down",
    rank_title: "Rankings", rank_src: "SinoPac real-time · 30s",
    pos_title: "💼 My Positions", pos_unsigned: "Your brokerage account has not signed the API service agreement yet. Once signed, real positions and unrealized P&L will appear here.",
    sheet_sigs: "📡 Intel Signals", sheet_nosig: "No recent intel signals (24 sources monitored)",
    sig_pop_foot: "🔴 strong · 🟡 watch-level — auto-detected from 24 intel sources; not investment advice",
    sheet_groups: "Add to group", limit_up: "🔥 Limit Up", limit_down: "❄️ Limit Down",
    foot_note: "Quotes are for reference only, not a basis for live trading. Stock info and signals are auto-aggregated and are not investment advice.",
    theme_tag: "Theme", ind_group: "Industry",
    tf_1D: "1D", tf_5D: "5D", tf_3M: "3M·D", tf_6M: "6M·D", tf_1Y: "1Y·W", tf_m5: "5min", tf_m30: "30min",
    sec_tech: "📐 Technicals", sec_fund: "📊 Fundamentals", sec_prof: "🏢 Company", sec_chain: "🔗 Supply Chain",
    chain_up: "Upstream", chain_down: "Downstream", chain_self: "Core",
    chain_verified: "✓ Company-verified chain", chain_generic: "Industry chain", chain_wip: "Company-level chain coming soon",
    fd_pe: "P/E", fd_dy: "Div Yield", fd_pb: "P/B", fd_mcap: "Mkt Cap", fd_eps: "EPS (TTM)",
    fd_52: "52W H/L", fd_beta: "Beta", fd_ind: "Industry", fd_asof: "official daily",
    prof_chair: "Chairman", prof_gm: "CEO/GM", prof_listed: "Listed", prof_web: "Web",
    ti_over: "Overbought", ti_under: "Oversold", ti_mid: "Neutral", ti_gold: "Bullish", ti_dead: "Bearish",
    ti_above: "above ", ti_below: "below ",
    sec_depth: "📶 Order Book", depth_bid: "Bids", depth_ask: "Asks", depth_pending: "Subscribing…",
    sec_news: "📰 News", news_none: "No recent news (2 weeks)",
    sort_def: "Default", sort_gain: "Gainers", sort_lose: "Losers", sort_sig: "Signals first",
    loading: "Loading…", chart_fail: "Chart failed to load", vol_note: "bottom = volume",
    tab_screen: "🔎 Screener", tab_news: "📰 News", tf_5Y: "5Y·M",
    sec_chips: "🧮 Chips", sec_findeep: "📑 Financials", sec_diag: "🧭 Bull / Bear", sec_alerts: "🔔 Price Alerts",
    sec_ticks: "⚡ In/Out · Big Lots", scr_result: "Results",
    chip_inst: "Institutional net buy (lots)", chip_margin: "Margin / Short balance", chip_foreign: "Foreign ownership (%)", chip_dt: "Day-trade ratio (%)",
    fin_rev: "Monthly revenue · YoY", fin_eps: "EPS (quarterly)", fin_margin: "Margins (%)", fin_per: "P/E · P/B (1Y)",
    diag_bull: "Bullish", diag_bear: "Bearish",
    al_above: "Price ≥", al_below: "Price ≤", al_chg_up: "Gain ≥%", al_chg_dn: "Drop ≥%", al_vol: "Vol ≥ lots",
    al_add: "Add alert", al_none: "No alerts yet. You'll be notified when triggered.", al_fired: "Fired",
    al_rearm: "Re-arm", al_all_title: "All alerts", al_noperm: "Browser notifications off — alerts only visible while page open",
    io_out: "Out", io_in: "In", big_buy: "Big buys", big_sell: "Big sells", ticks_recent: "Recent ticks",
    scr_ind: "Industry", scr_pe: "P/E ≤", scr_dy: "Yield ≥%", scr_pb: "P/B ≤", scr_px: "Price range", scr_all: "All",
    scr_run: "Run screen", scr_sort: "Sort", scr_sort_dy: "Yield high→low", scr_sort_pe: "P/E low→high", scr_sort_pb: "P/B low→high",
    nw_headline: "Top", nw_tw: "Taiwan", nw_wd: "Global", nw_forex: "FX", nw_future: "Futures",
    sync_on: "Cloud synced", exp_ok: "Exported", imp_ok: "Imported", imp_bad: "Bad file format",
    boll_lbl: "BOLL", sub_vol: "Vol", grp_tools: "⚙",
    cb_theme: "Convertible Bonds",
    tab_heat: "🌡 Heat", heat_src: "TWSE sector indices · EOD", heat_hint: "Tap a sector → constituents",
    ct_candle: "Candle", ct_ha: "Heikin", ct_bar: "Bar", ct_area: "Area", log_lbl: "LOG",
    tool_trend: "╱ Trend", tool_hline: "─ H-line", tool_fib: "𝄃 Fib", tool_text: "T Text", tool_erase: "⌫ Erase", tool_clear: "🗑 Clear",
    cmp_lbl: "⇄ Compare", cmp_prompt: "Symbols to compare (comma separated, max 3; empty = clear):",
    replay_lbl: "▶ Replay", replay_exit: "✕ Exit replay",
    fs_lbl: "⛶", snap_lbl: "📷",
    draw_hint: "Click twice to place; click tool again to cancel",
    al_ma20_up: "Above MA20", al_ma20_dn: "Below MA20", al_ma60_up: "Above MA60", al_ma60_dn: "Below MA60",
    al_rsi_gt: "RSI ≥", al_rsi_lt: "RSI ≤", al_kd_gold: "KD golden cross", al_kd_dead: "KD death cross",
    al_boll_up: "Break BOLL upper", al_boll_dn: "Break BOLL lower",
    scr_tech: "Technical", scr_ma20: "Above MA20", scr_ma60: "Above MA60", scr_rsi_lo: "RSI<30", scr_rsi_hi: "RSI>70", scr_volx: "Vol ratio≥2",
    scr_calc: "Computing technical filters…",
    fd_loss: "Loss-making", fd_loss_sub: "Negative TTM EPS", fd_loss_sub_tw: "Trailing 4Q EPS ≤ 0", fd_nodiv: "No dividend / no data",
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
if (!INDUSTRY["6806"]) INDUSTRY["6806"] = "綠能環保";
const CATEGORIES = (typeof TW_CATEGORIES !== "undefined") ? TW_CATEGORIES : {};
const THEMES = (typeof TW_THEMES !== "undefined") ? TW_THEMES : {};

const email = localStorage.getItem("md-email");
const pwd = sessionStorage.getItem("md-pwd") || localStorage.getItem("md-saved-pwd") || "";
const isAdmin = localStorage.getItem("md-plan") === "admin";

let prefsTw = [], prefsUs = [];
let groups = {};
try { groups = JSON.parse(localStorage.getItem("md-watch-groups") || "{}") || {}; } catch {}
const saveGroups = () => { localStorage.setItem("md-watch-groups", JSON.stringify(groups)); scheduleSync(); };

let curTab = "watch", curGroup = "all", curCat = "", curRank = "change", catPage = 1;
const CAT_PAGE = 60;
let quotes = {};
let signals = {};
let sigDate = null;
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

const escAttr = s => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

function sigDot(sym) {
  const items = signals[sym];
  if (!items || !items.length) return "";
  const lvl = items.some(i => i.level === "red") ? "red" : "yellow";
  // data-sig=可點(手機 tap 彈出說明);title=桌面 hover 原生提示(2026-07-22 Delvin:點了要講這是什麼)
  const tip = items.map(i => i.signal || i.source || "").filter(Boolean).join("\n");
  return `<span class="sig-dot ${lvl}" data-sig="${sym}" title="${escAttr(tip)}"></span>`;
}

function nameCell(sym, name) {
  const nm = name || nameMap.get(sym) || sym;
  const ind = INDUSTRY[sym] ? ` · ${INDUSTRY[sym]}` : "";
  // 訊號燈放進 nm-main 內:nm-main 是 block,inline 的點放外面會被擠成獨立一行浮在名字上方(版型破)
  return `<span class="nm-main">${sigDot(sym)}${nm}</span><span class="code-sub">${sym}${ind}</span>`;
}

function rowHtml(sym) {
  // 台股 7 欄(五檔 ext + 高低/量);美股 5 欄(高低/量,無五檔——券商即時只做台股)。
  // 高低量兩表都有,五檔 bid/ask 只台股產(美股表頭亦無)。
  const bidask = isTWSym(sym) ? `<td class="ext" id="bid-${sym}">—</td><td class="ext" id="ask-${sym}">—</td>` : "";
  const hlvol = `<td class="hide-sm" id="hl-${sym}">—</td><td class="hide-sm" id="vol-${sym}">—</td>`;
  return `<tr data-sym="${sym}"><td>${nameCell(sym)}</td>
    <td class="px" id="px-${sym}">—</td><td id="chg-${sym}" class="neutral">—</td>${bidask}${hlvol}</tr>`;
}
// 成交量顯示:台股=張(逗號分隔);美股=股(M/K 縮寫,避免千萬級數字過長)
function fmtVol(v, sym) {
  if (v == null) return "—";
  if (isTWSym(sym)) return v.toLocaleString();
  return v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : String(v);
}

function paint(q) {
  const s = q.symbol;
  quotes[s] = Object.assign(quotes[s] || {}, q);
  checkAlerts(quotes[s]);
  const px = $("px-" + s);
  if (!px) return;
  if (q.price == null && px.textContent !== "—") return;
  const prev = px.textContent;
  px.textContent = fp(q.price);
  const { dir, label } = fmtChg(q.change, s);
  px.className = "px " + dir;
  const chg = $("chg-" + s);
  if (chg) { chg.textContent = label; chg.className = dir; }
  // 買賣五檔:券商即時(admin)才有
  if (q.bid !== undefined && $("bid-" + s)) {
    $("bid-" + s).textContent = fp(q.bid);
    $("ask-" + s).textContent = fp(q.ask);
  }
  // 高/低、量:公開資訊,免費源與券商源皆填(訂閱者也看得到)
  if (q.high !== undefined && $("hl-" + s)) {
    $("hl-" + s).textContent = `${fp(q.high)} / ${fp(q.low)}`;
  }
  if (q.volume !== undefined && $("vol-" + s)) {
    $("vol-" + s).textContent = fmtVol(q.volume, s);
  }
  if (prev !== "—" && prev !== px.textContent) {
    const tr = document.querySelector(`tr[data-sym="${s}"]`);
    if (tr) { tr.classList.remove("flash"); void tr.offsetWidth; tr.classList.add("flash"); }
  }
  if (sheetSym === s) refreshSheetHead(s);
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
const show = (id, disp) => { const el = $(id); if (el) el.style.display = disp; };
function renderView() {
  const syms = viewSyms();
  const tw = syms.filter(isTWSym), us = syms.filter(s => !isTWSym(s));
  show("rank-sec", curTab === "ranks" ? "block" : "none");
  show("screen-sec", curTab === "screen" ? "block" : "none");
  show("news-sec", curTab === "news" ? "block" : "none");
  show("heat-sec", curTab === "heat" ? "block" : "none");
  show("group-chips", curTab === "watch" ? "flex" : "none");
  show("cat-bar", curTab === "cats" ? "flex" : "none");
  show("rank-chips", curTab === "ranks" ? "flex" : "none");
  show("sort-chips", (curTab === "watch" || curTab === "cats") ? "flex" : "none");
  show("pos-wrap", (curTab === "watch" && isAdmin) ? "block" : "none");
  if (curTab === "screen" || curTab === "news" || curTab === "heat") {
    show("tw-sec", "none"); show("us-sec", "none"); show("empty", "none");
    if (curTab === "screen") renderScreenForm();
    else if (curTab === "news") { renderNewsChips(); renderNewsTab(); }
    else renderHeat();
    return;
  }
  if (curTab === "ranks") {
    show("tw-sec", "none"); show("us-sec", "none"); show("empty", "none");
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
  applySortDom();
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
  html += `<button class="chip" data-g="__exp" title="匯出自選/警示">⭳</button><button class="chip" data-g="__imp" title="匯入">⭱</button>`;
  el.innerHTML = html;
  el.querySelectorAll(".chip").forEach(c => c.onclick = () => {
    const g = c.dataset.g;
    if (g === "__exp") { exportData(); return; }
    if (g === "__imp") { importData(); return; }
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

/* 智慧排序:chips(預設/燈號)+表頭欄位排序(價/漲跌/量,點一下降冪再點升冪) */
const SORT_CHIP_MODES = ["def", "sig"];
function sortKey(s) {
  const q = quotes[s] || {};
  const ch = q.change, px = q.price, vol = q.volume;
  const sg = signals[s] || [];
  const lvl = sg.some(i => i.level === "red") ? 0 : sg.length ? 1 : 2;
  switch (sortMode) {
    case "sig": return lvl * 1000 - Math.abs(ch || 0);
    case "chg_desc": return ch == null ? 999 : -ch;
    case "chg_asc": return ch == null ? 999 : ch;
    case "px_desc": return px == null ? 1e12 : -px;
    case "px_asc": return px == null ? 1e12 : px;
    case "vol_desc": return vol == null ? 1e15 : -vol;
    case "vol_asc": return vol == null ? 1e15 : vol;
    default: return 0;
  }
}
function setSort(mode) {
  sortMode = mode;
  localStorage.setItem("md-watch-sort", sortMode);
  renderSortChips(); renderSortHeaders(); applySortDom();
}
function renderSortChips() {
  const el = $("sort-chips");
  el.innerHTML = SORT_CHIP_MODES.map(m =>
    `<button class="chip ${sortMode === m ? "on" : ""}" data-so="${m}">${T("sort_" + m)}</button>`).join("");
  el.querySelectorAll(".chip").forEach(c => c.onclick = () => setSort(c.dataset.so));
}
function renderSortHeaders() {
  document.querySelectorAll("th[data-sort]").forEach(th => {
    const col = th.dataset.sort;
    const on = sortMode === col + "_desc" || sortMode === col + "_asc";
    th.classList.toggle("s-on", on);
    th.querySelector(".arr").textContent = on ? (sortMode.endsWith("_desc") ? "▼" : "▲") : "";
  });
}
function bindSortHeaders() {
  document.querySelectorAll("th[data-sort]").forEach(th => th.onclick = () => {
    const col = th.dataset.sort;
    setSort(sortMode === col + "_desc" ? col + "_asc" : col + "_desc");
  });
}
function applySortDom() {
  if (sortMode === "def" || curTab === "ranks") return;
  ["tw-table", "us-table"].forEach(id => {
    const tb = document.querySelector(`#${id} tbody`);
    if (!tb) return;
    Array.from(tb.querySelectorAll("tr[data-sym]"))
      .sort((a, b) => sortKey(a.dataset.sym) - sortKey(b.dataset.sym))
      .forEach(tr => tb.appendChild(tr));
  });
}

const RANK_LABELS = { change: "rank_change", limit_up: "rank_limit_up", near_up: "rank_near_up",
  limit_down: "rank_limit_down", near_dn: "rank_near_dn",
  volume: "rank_volume", amount: "rank_amount", range: "rank_range", tick: "rank_tick" };
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
      <td>${nameCell(r.code, r.name)}</td>
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
  // 有警示條件的股票就算不在當前畫面也要抓報價,否則警示永遠不會觸發
  const alSyms = Object.keys(alerts).filter(s => (alerts[s] || []).length);
  const syms = [...new Set(viewSyms().concat(alSyms))];
  const bridgeOk = bridge && bridgeFails < 3;
  const target = bridgeOk ? syms.filter(s => !isTWSym(s)) : syms;
  if (!target.length) return;
  // 同 tickLive:分類頁翻頁後超過舊上限的檔位要吃得到報價(fetchFree 內部本就 25 檔一批)
  (await fetchFree(target.slice(0, 300))).forEach(paint);
  applySortDom();
}

async function tickLive() {
  if (!bridge) return;
  // bridge /q 單次上限 60(server 端硬切)→ 必須分塊,否則分類頁「顯示更多」後
  // 第 61 檔起永遠抓不到報價整排「—」(2026-07-22 Delvin 回報)。總量 300 防巨型分類打爆 bridge。
  const alSyms = Object.keys(alerts).filter(s => (alerts[s] || []).length);
  const tw = [...new Set(viewSyms().concat(alSyms))].filter(isTWSym).slice(0, 300);
  if (!tw.length) return;
  try {
    const chunks = [];
    for (let i = 0; i < tw.length; i += 60) chunks.push(tw.slice(i, i + 60));
    const parts = await Promise.all(chunks.map(c =>
      fetch(`${bridge.url}/q?syms=${c.join(",")}&t=${encodeURIComponent(bridge.token)}`)
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    ));
    parts.flatMap(p => p.quotes || []).forEach(paint);
    bridgeFails = 0;
    applySortDom();
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
        return `<tr data-sym="${p.code}"><td>${nameCell(p.code)}</td>
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
    sigDate = d.date || null;
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
    if (tick % 60 === 0) tickMkt();
    if (tick % 300 === 0) refreshAlertCtx();
  }, 1000);
}

/* ── 個股詳情:K線/技術指標/基本面/公司/上下游 ── */
const PROFILE = (typeof TW_PROFILE !== "undefined") ? TW_PROFILE : {};
let twFund = {}, twFundDate = null;
let usFundCache = {};
let chainDB = null, chainIdx = null;
let chartCache = {};
let curTf = "6M";
let sortMode = { gain: "chg_desc", lose: "chg_asc" }[localStorage.getItem("md-watch-sort")] || localStorage.getItem("md-watch-sort") || "def";
let depthTimer = null;
let newsCache = {};
const TF_LIST = [
  { k: "1D", src: "worker", range: "1D", mode: "line" },
  { k: "5D", src: "worker", range: "5D", mode: "candle" },
  { k: "3M", src: "worker", range: "3M", mode: "candle", ma: true },
  { k: "6M", src: "worker", range: "6M", mode: "candle", ma: true },
  { k: "1Y", src: "worker", range: "1Y", mode: "candle", ma: true },
  { k: "5Y", src: "worker", range: "5Y", mode: "candle", ma: true },
  { k: "m5", src: "bridge", res: 5, days: 3, mode: "candle", twOnly: true },
  { k: "m30", src: "bridge", res: 30, days: 10, mode: "candle", twOnly: true },
];
let chartOpt = { boll: false, sub: "vol", ctype: "candle", log: false, ema: false, sar: false, ich: false, vwap: false };
try { chartOpt = Object.assign(chartOpt, JSON.parse(localStorage.getItem("md-watch-chartopt") || "{}")); } catch {}
const saveChartOpt = () => localStorage.setItem("md-watch-chartopt", JSON.stringify(chartOpt));
/* TradingView 對齊:視窗縮放/回放/比較/繪圖 狀態 */
let chartView = null;          // {n:可見根數, o:距末端偏移} null=全顯
let cmpSyms = [], cmpData = {}; // 比較疊圖(%正規化)
let replay = null;             // {on, idx, timer, speed}
let drawTool = null, drawPend = null;
let drawings = {};
try { drawings = JSON.parse(localStorage.getItem("md-watch-drawings") || "{}") || {}; } catch {}
const saveDrawings = () => localStorage.setItem("md-watch-drawings", JSON.stringify(drawings));

async function loadTwFund() {
  try {
    const d = await fetch(WORKER_URL + "/watch-fundamentals").then(r => r.json());
    twFund = d.by_code || {}; twFundDate = d.date;
  } catch {}
}

async function loadChain() {
  if (chainIdx) return;
  try {
    chainDB = await fetch("data/supply_chain.json").then(r => r.json());
    chainIdx = {};
    Object.entries(chainDB).forEach(([k, v]) => { chainIdx[k.replace(/\.(TW|TWO)$/, "")] = v; });
  } catch { chainIdx = {}; }
  // 預產公司級鏈(Claude 批次產,零 API 費):精修 DB 優先,預產補位
  try {
    const pg = await fetch("data/chain_pregen.json?v=20260722c").then(r => r.json());
    Object.entries(pg).forEach(([k, v]) => {
      if (!chainIdx[k]) chainIdx[k] = { source: "pregen", mid: { desc: v.mid },
        upstream: (v.up || []).map(x => ({ name_zh: x.n, ticker: x.t, role: x.r })),
        downstream: (v.down || []).map(x => ({ name_zh: x.n, ticker: x.t, role: x.r })) };
    });
  } catch {}
}

function normTicker(t) { return (t || "").replace(/\.(TW|TWO)$/, ""); }


async function fetchBars(sym, tfk) {
  const ck = `${sym}:${tfk}`;
  const hit = chartCache[ck];
  if (hit && Date.now() - hit.at < 60000) return hit.bars;
  const tf = TF_LIST.find(t => t.k === tfk);
  let bars = [];
  if (tf.src === "bridge" && bridge) {
    const d = await fetch(`${bridge.url}/kbars?sym=${sym}&res=${tf.res}&days=${tf.days}&t=${encodeURIComponent(bridge.token)}`).then(r => r.json());
    bars = d.bars || [];
  } else {
    const d = await fetch(`${WORKER_URL}/stock-chart?ticker=${sym}&range=${tf.range}&ohlc=1`).then(r => r.json());
    bars = (d.points || []).map(p => ({ t: p.t, o: p.o ?? p.c, h: p.h ?? p.c, l: p.l ?? p.c, c: p.c, v: p.v ?? 0 }));
    // 月K:worker 端「Yahoo 落後補最新價」會在月線尾端多一根同月 bar → 併回當月
    if (tf.range === "5Y" && bars.length >= 2) {
      const a = bars[bars.length - 2], b = bars[bars.length - 1];
      const ym = t => { const d2 = new Date(t * 1000); return d2.getFullYear() * 12 + d2.getMonth(); };
      if (ym(a.t) === ym(b.t)) {
        a.c = b.c; a.h = Math.max(a.h, b.h); a.l = Math.min(a.l, b.l); a.v += b.v || 0;
        bars.pop();
      }
    }
    bars.prevClose = d.prevClose;
  }
  chartCache[ck] = { at: Date.now(), bars };
  return bars;
}

/* 技術指標(純計算) */
function sma(vals, n) { const out = []; let s = 0; for (let i = 0; i < vals.length; i++) { s += vals[i]; if (i >= n) s -= vals[i - n]; out.push(i >= n - 1 ? s / n : null); } return out; }
function ema(vals, n) { const k = 2 / (n + 1); const out = []; let e = null; for (const v of vals) { e = e === null ? v : v * k + e * (1 - k); out.push(e); } return out; }
function rsi14(closes) {
  if (closes.length < 15) return null;
  let g = 0, l = 0;
  for (let i = 1; i <= 14; i++) { const d = closes[i] - closes[i - 1]; if (d > 0) g += d; else l -= d; }
  let ag = g / 14, al = l / 14;
  for (let i = 15; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    ag = (ag * 13 + Math.max(d, 0)) / 14; al = (al * 13 + Math.max(-d, 0)) / 14;
  }
  return al === 0 ? 100 : 100 - 100 / (1 + ag / al);
}
function kd9(bars) {
  if (bars.length < 9) return null;
  let K = 50, D = 50;
  for (let i = 8; i < bars.length; i++) {
    const w = bars.slice(i - 8, i + 1);
    const h9 = Math.max(...w.map(b => b.h)), l9 = Math.min(...w.map(b => b.l));
    const rsv = h9 === l9 ? 50 : (bars[i].c - l9) / (h9 - l9) * 100;
    K = K * 2 / 3 + rsv / 3; D = D * 2 / 3 + K / 3;
  }
  return { K, D };
}
function macd(closes) {
  if (closes.length < 30) return null;
  const e12 = ema(closes, 12), e26 = ema(closes, 26);
  const dif = e12.map((v, i) => v - e26[i]);
  const dea = ema(dif, 9);
  const i = closes.length - 1;
  return { dif: dif[i], dea: dea[i], hist: dif[i] - dea[i] };
}
/* 全序列指標(副圖/布林用) */
function macdArr(closes) {
  const e12 = ema(closes, 12), e26 = ema(closes, 26);
  const dif = e12.map((v, i) => v - e26[i]);
  const dea = ema(dif, 9);
  return { dif, dea, hist: dif.map((v, i) => v - dea[i]) };
}
function kdArr(bars) {
  const K = [], D = [];
  let k = 50, d = 50;
  for (let i = 0; i < bars.length; i++) {
    if (i < 8) { K.push(null); D.push(null); continue; }
    const w = bars.slice(i - 8, i + 1);
    const h9 = Math.max(...w.map(b => b.h)), l9 = Math.min(...w.map(b => b.l));
    const rsv = h9 === l9 ? 50 : (bars[i].c - l9) / (h9 - l9) * 100;
    k = k * 2 / 3 + rsv / 3; d = d * 2 / 3 + k / 3;
    K.push(k); D.push(d);
  }
  return { K, D };
}
function rsiArr(closes, n = 14) {
  const out = new Array(closes.length).fill(null);
  if (closes.length < n + 1) return out;
  let g = 0, l = 0;
  for (let i = 1; i <= n; i++) { const d = closes[i] - closes[i - 1]; if (d > 0) g += d; else l -= d; }
  let ag = g / n, al = l / n;
  out[n] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  for (let i = n + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    ag = (ag * (n - 1) + Math.max(d, 0)) / n; al = (al * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  }
  return out;
}
function bollArr(closes, n = 20, mult = 2) {
  const mid = sma(closes, n), up = [], dn = [];
  for (let i = 0; i < closes.length; i++) {
    if (mid[i] === null) { up.push(null); dn.push(null); continue; }
    const w = closes.slice(i - n + 1, i + 1);
    const m = mid[i];
    const sd = Math.sqrt(w.reduce((s, v) => s + (v - m) * (v - m), 0) / n);
    up.push(m + mult * sd); dn.push(m - mult * sd);
  }
  return { mid, up, dn };
}
function obvArr(bars) {
  const out = [0];
  for (let i = 1; i < bars.length; i++)
    out.push(out[i - 1] + (bars[i].c > bars[i - 1].c ? (bars[i].v || 0) : bars[i].c < bars[i - 1].c ? -(bars[i].v || 0) : 0));
  return out;
}
function dmi14(bars, n = 14) {
  if (bars.length < n + 2) return null;
  let trS = 0, pS = 0, mS = 0;
  const dxArr = [];
  let prev = bars[0];
  for (let i = 1; i < bars.length; i++) {
    const b = bars[i];
    const tr = Math.max(b.h - b.l, Math.abs(b.h - prev.c), Math.abs(b.l - prev.c));
    const up = b.h - prev.h, dn = prev.l - b.l;
    const pdm = up > dn && up > 0 ? up : 0, mdm = dn > up && dn > 0 ? dn : 0;
    if (i <= n) { trS += tr; pS += pdm; mS += mdm; }
    else { trS = trS - trS / n + tr; pS = pS - pS / n + pdm; mS = mS - mS / n + mdm; }
    if (i >= n) {
      const pdi = trS ? pS / trS * 100 : 0, mdi = trS ? mS / trS * 100 : 0;
      dxArr.push(pdi + mdi ? Math.abs(pdi - mdi) / (pdi + mdi) * 100 : 0);
    }
    prev = b;
  }
  const pdi = trS ? pS / trS * 100 : 0, mdi = trS ? mS / trS * 100 : 0;
  const adxW = dxArr.slice(-n);
  const adx = adxW.length ? adxW.reduce((a, b) => a + b, 0) / adxW.length : null;
  return { pdi, mdi, adx };
}
function sarArr(bars, step = 0.02, maxAf = 0.2) {
  const n = bars.length;
  const out = new Array(n).fill(null);
  if (n < 5) return out;
  let up = bars[1].c >= bars[0].c, af = step;
  let ep = up ? bars[0].h : bars[0].l;
  let sar = up ? bars[0].l : bars[0].h;
  for (let i = 1; i < n; i++) {
    sar = sar + af * (ep - sar);
    if (up) {
      if (bars[i].l < sar) { up = false; sar = ep; ep = bars[i].l; af = step; }
      else { if (bars[i].h > ep) { ep = bars[i].h; af = Math.min(af + step, maxAf); } }
    } else {
      if (bars[i].h > sar) { up = true; sar = ep; ep = bars[i].h; af = step; }
      else { if (bars[i].l < ep) { ep = bars[i].l; af = Math.min(af + step, maxAf); } }
    }
    out[i] = { v: sar, up };
  }
  return out;
}
function ichimokuArr(bars) {
  const n = bars.length, SH = 26;
  const hh = (i, p) => Math.max(...bars.slice(Math.max(0, i - p + 1), i + 1).map(b => b.h));
  const ll = (i, p) => Math.min(...bars.slice(Math.max(0, i - p + 1), i + 1).map(b => b.l));
  const tenkan = [], kijun = [];
  for (let i = 0; i < n; i++) {
    tenkan.push(i >= 8 ? (hh(i, 9) + ll(i, 9)) / 2 : null);
    kijun.push(i >= 25 ? (hh(i, 26) + ll(i, 26)) / 2 : null);
  }
  const spanA = new Array(n + SH).fill(null), spanB = new Array(n + SH).fill(null);
  for (let i = 0; i < n; i++) {
    if (tenkan[i] != null && kijun[i] != null) spanA[i + SH] = (tenkan[i] + kijun[i]) / 2;
    if (i >= 51) spanB[i + SH] = (hh(i, 52) + ll(i, 52)) / 2;
  }
  return { tenkan, kijun, spanA, spanB, SH };
}
function wprArr(bars, n = 14) {
  return bars.map((b, i) => {
    if (i < n - 1) return null;
    const w = bars.slice(i - n + 1, i + 1);
    const h = Math.max(...w.map(x => x.h)), l = Math.min(...w.map(x => x.l));
    return h === l ? -50 : (h - b.c) / (h - l) * -100;
  });
}
function cciArr(bars, n = 20) {
  return bars.map((b, i) => {
    if (i < n - 1) return null;
    const w = bars.slice(i - n + 1, i + 1).map(x => (x.h + x.l + x.c) / 3);
    const m = w.reduce((a, v) => a + v, 0) / n;
    const md = w.reduce((a, v) => a + Math.abs(v - m), 0) / n;
    const tp = (b.h + b.l + b.c) / 3;
    return md === 0 ? 0 : (tp - m) / (0.015 * md);
  });
}
function atr14(bars, n = 14) {
  if (bars.length < n + 1) return null;
  let s = 0;
  for (let i = bars.length - n; i < bars.length; i++) {
    const b = bars[i], pc = bars[i - 1].c;
    s += Math.max(b.h - b.l, Math.abs(b.h - pc), Math.abs(b.l - pc));
  }
  return s / n;
}
function vwapArr(bars) {
  const out = [];
  let day = null, pv = 0, vv = 0;
  for (const b of bars) {
    const d = new Date(b.t * 1000).toISOString().slice(0, 10);
    if (d !== day) { day = d; pv = 0; vv = 0; }
    const tp = (b.h + b.l + b.c) / 3;
    pv += tp * (b.v || 0); vv += b.v || 0;
    out.push(vv ? pv / vv : null);
  }
  return out;
}
function heikinAshi(bars) {
  const out = [];
  let po = null, pc = null;
  for (const b of bars) {
    const c = (b.o + b.h + b.l + b.c) / 4;
    const o = po === null ? (b.o + b.c) / 2 : (po + pc) / 2;
    out.push({ t: b.t, o, h: Math.max(b.h, o, c), l: Math.min(b.l, o, c), c, v: b.v });
    po = o; pc = c;
  }
  return out;
}
function mfi14(bars, n = 14) {
  if (bars.length < n + 1) return null;
  let pos = 0, neg = 0;
  for (let i = bars.length - n; i < bars.length; i++) {
    const tp = (bars[i].h + bars[i].l + bars[i].c) / 3;
    const ptp = (bars[i - 1].h + bars[i - 1].l + bars[i - 1].c) / 3;
    const mf = tp * (bars[i].v || 0);
    if (tp > ptp) pos += mf; else if (tp < ptp) neg += mf;
  }
  if (!neg) return 100;
  return 100 - 100 / (1 + pos / neg);
}

/* Canvas K線(hoverIdx=十字線位置) */
let curChart = null;
function visWindow(bars) {
  const total = bars.length;
  let vn = chartView && chartView.n ? Math.max(10, Math.min(chartView.n, total)) : total;
  let off = chartView ? Math.max(0, Math.min(chartView.o || 0, total - vn)) : 0;
  const end = total - off, start = Math.max(0, end - vn);
  return { start, end };
}
function drawChart(cv, bars, tf, hoverIdx) {
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  if (!bars || !bars.length) { ctx.fillStyle = "rgba(255,255,255,.3)"; ctx.font = "12px sans-serif"; ctx.fillText(T("chart_fail"), 16, H / 2); return; }
  const full = bars;
  let rBars = full;
  if (replay && replay.on) rBars = full.slice(0, Math.max(10, replay.idx));
  const candle = tf.mode !== "line";
  const ctype = candle ? (chartOpt.ctype || "candle") : "line";
  const plotBars = ctype === "ha" ? heikinAshi(rBars) : rBars;
  const { start, end } = visWindow(plotBars);
  const vis = plotBars.slice(start, end);
  const compare = candle && cmpSyms.length > 0;
  const padR = 46, padT = 8, volH = Math.round(H * 0.18), priceH = H - volH - padT - 14;
  const UP = "#ef4444", DN = "#22c55e";
  // 一目均衡表雲層要多留 26 根未來槽位
  const ich = candle && chartOpt.ich && !compare && rBars.length >= 52 ? ichimokuArr(rBars) : null;
  const futSlots = ich ? ich.SH : 0;
  const n = vis.length, nSlots = n + futSlots;
  const slotW = (W - padR - 6) / nSlots;
  const xAt = i => 4 + slotW * (i + 0.5);
  // 比較模式:全部轉「視窗起點=0%」的百分比線
  let cmpSeries = null, hi, lo;
  if (compare) {
    const base = vis.find(b => b.c != null).c;
    const main = vis.map(b => (b.c / base - 1) * 100);
    cmpSeries = [{ sym: sheetSym, data: main, color: "#818cf8" }];
    const palette = ["#fbbf24", "#38bdf8", "#f472b6"];
    cmpSyms.forEach((cs, ci) => {
      const cb = cmpData[cs];
      if (!cb || !cb.length) return;
      const map = new Map(cb.map(b => [b.t, b.c]));
      const raw = vis.map(b => map.get(b.t) ?? null);
      const cbase = raw.find(v => v != null);
      if (cbase == null) return;
      cmpSeries.push({ sym: cs, data: raw.map(v => v == null ? null : (v / cbase - 1) * 100), color: palette[ci % 3] });
    });
    const all = cmpSeries.flatMap(s => s.data).filter(v => v != null);
    hi = Math.max(...all); lo = Math.min(...all);
  } else {
    hi = Math.max(...vis.map(b => b.h)); lo = Math.min(...vis.map(b => b.l));
    if (ich) {
      const cloud = ich.spanA.concat(ich.spanB).slice(start, end + futSlots).filter(v => v != null);
      if (cloud.length) { hi = Math.max(hi, ...cloud); lo = Math.min(lo, ...cloud); }
    }
  }
  const span = (hi - lo) || 1;
  const useLog = chartOpt.log && !compare && lo > 0;
  const lgHi = useLog ? Math.log(hi) : 0, lgLo = useLog ? Math.log(lo) : 0, lgSpan = (lgHi - lgLo) || 1;
  const y = v => useLog
    ? padT + (lgHi - Math.log(v)) / lgSpan * priceH
    : padT + (hi - v) / span * priceH;
  const maxV = Math.max(...vis.map(b => b.v || 0)) || 1;
  // grid + 右軸
  ctx.font = "10px -apple-system,sans-serif"; ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const frac = i / 4;
    const v = useLog ? Math.exp(lgHi - lgSpan * frac) : hi - span * frac;
    const gy = padT + priceH * frac;
    ctx.strokeStyle = "rgba(255,255,255,.05)"; ctx.beginPath(); ctx.moveTo(4, gy); ctx.lineTo(W - padR, gy); ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,.4)";
    ctx.fillText(compare ? v.toFixed(1) + "%" : fp(v), W - padR + 4, gy);
  }
  const lineSeries = (arr, col, width) => {
    ctx.strokeStyle = col; ctx.lineWidth = width || 1; ctx.beginPath();
    let st = false;
    for (let i = 0; i < arr.length; i++) {
      const v = arr[i];
      if (v == null || !isFinite(v)) continue;
      st ? ctx.lineTo(xAt(i), y(v)) : ctx.moveTo(xAt(i), y(v)); st = true;
    }
    ctx.stroke(); ctx.lineWidth = 1;
  };
  if (compare) {
    const y0 = y(0);
    if (0 >= lo && 0 <= hi) { ctx.strokeStyle = "rgba(255,255,255,.18)"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(4, y0); ctx.lineTo(W - padR, y0); ctx.stroke(); ctx.setLineDash([]); }
    cmpSeries.forEach(s => lineSeries(s.data, s.color, s.sym === sheetSym ? 1.8 : 1.3));
    ctx.font = "10.5px -apple-system,sans-serif"; ctx.textBaseline = "alphabetic";
    let lx = 8;
    cmpSeries.forEach(s => {
      const last = [...s.data].reverse().find(v => v != null);
      const lbl = `${nameMap.get(s.sym) || s.sym} ${last == null ? "" : (last >= 0 ? "+" : "") + last.toFixed(1) + "%"}`;
      ctx.fillStyle = s.color; ctx.fillText(lbl, lx, padT + 10);
      lx += ctx.measureText(lbl).width + 14;
    });
  } else if (tf.mode === "line") {
    if (bars.prevClose != null || bars.pc != null) {
      const pc = bars.pc ?? bars.prevClose;
      if (pc >= lo && pc <= hi) {
        ctx.strokeStyle = "rgba(255,255,255,.25)"; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(4, y(pc)); ctx.lineTo(W - padR, y(pc)); ctx.stroke(); ctx.setLineDash([]);
      }
    }
    ctx.strokeStyle = "#818cf8"; ctx.lineWidth = 1.6; ctx.beginPath();
    vis.forEach((b, i) => { const x = xAt(i); i ? ctx.lineTo(x, y(b.c)) : ctx.moveTo(x, y(b.c)); });
    ctx.stroke(); ctx.lineWidth = 1;
  } else {
    // 一目雲層(先畫,墊底)
    if (ich) {
      const sA = ich.spanA.slice(start, end + futSlots), sB = ich.spanB.slice(start, end + futSlots);
      for (let i = 0; i < sA.length - 1; i++) {
        if (sA[i] == null || sB[i] == null || sA[i + 1] == null || sB[i + 1] == null) continue;
        ctx.fillStyle = sA[i] >= sB[i] ? "rgba(239,68,68,.09)" : "rgba(34,197,94,.09)";
        ctx.beginPath();
        ctx.moveTo(xAt(i), y(sA[i])); ctx.lineTo(xAt(i + 1), y(sA[i + 1]));
        ctx.lineTo(xAt(i + 1), y(sB[i + 1])); ctx.lineTo(xAt(i), y(sB[i]));
        ctx.closePath(); ctx.fill();
      }
      lineSeries(ich.tenkan.slice(start, end), "#f472b6", 1);
      lineSeries(ich.kijun.slice(start, end), "#60a5fa", 1);
    }
    if (chartOpt.boll && rBars.length >= 20) {
      const bl = bollArr(rBars.map(b => b.c));
      const su = bl.up.slice(start, end), sd = bl.dn.slice(start, end), sm = bl.mid.slice(start, end);
      ctx.beginPath();
      let st = false;
      su.forEach((v, i) => { if (v == null) return; st ? ctx.lineTo(xAt(i), y(v)) : ctx.moveTo(xAt(i), y(v)); st = true; });
      for (let i = sd.length - 1; i >= 0; i--) if (sd[i] != null) ctx.lineTo(xAt(i), y(sd[i]));
      ctx.closePath(); ctx.fillStyle = "rgba(167,139,250,.08)"; ctx.fill();
      lineSeries(su, "rgba(167,139,250,.5)"); lineSeries(sd, "rgba(167,139,250,.5)"); lineSeries(sm, "rgba(167,139,250,.85)");
    }
    if (ctype === "area") {
      ctx.beginPath();
      vis.forEach((b, i) => { const x = xAt(i); i ? ctx.lineTo(x, y(b.c)) : ctx.moveTo(x, y(b.c)); });
      ctx.lineTo(xAt(n - 1), padT + priceH); ctx.lineTo(xAt(0), padT + priceH); ctx.closePath();
      ctx.fillStyle = "rgba(129,140,248,.14)"; ctx.fill();
      ctx.strokeStyle = "#818cf8"; ctx.lineWidth = 1.6; ctx.beginPath();
      vis.forEach((b, i) => { const x = xAt(i); i ? ctx.lineTo(x, y(b.c)) : ctx.moveTo(x, y(b.c)); });
      ctx.stroke(); ctx.lineWidth = 1;
    } else {
      const bw = Math.max(Math.min(slotW * 0.65, 9), 1.4);
      vis.forEach((b, i) => {
        const x = xAt(i);
        const col = b.c >= b.o ? UP : DN;
        ctx.strokeStyle = col; ctx.fillStyle = col;
        ctx.beginPath(); ctx.moveTo(x, y(b.h)); ctx.lineTo(x, y(b.l)); ctx.stroke();
        if (ctype === "bar") {
          ctx.beginPath();
          ctx.moveTo(x - bw / 2, y(b.o)); ctx.lineTo(x, y(b.o));
          ctx.moveTo(x, y(b.c)); ctx.lineTo(x + bw / 2, y(b.c));
          ctx.stroke();
        } else {
          const top = y(Math.max(b.o, b.c)), bh = Math.max(Math.abs(y(b.o) - y(b.c)), 1);
          ctx.fillRect(x - bw / 2, top, bw, bh);
        }
      });
    }
    if (tf.ma) {
      const closes = rBars.map(b => b.c);
      [[5, "#fbbf24"], [20, "#818cf8"], [60, "#38bdf8"]].forEach(([p, col]) => {
        if (rBars.length < p) return;
        lineSeries(sma(closes, p).slice(start, end), col, 1);
      });
      if (chartOpt.ema && rBars.length >= 20) {
        lineSeries(ema(closes, 12).slice(start, end), "#f472b6", 1);
        lineSeries(ema(closes, 26).slice(start, end), "#34d399", 1);
      }
    }
    if (chartOpt.sar && rBars.length >= 5) {
      const sr = sarArr(rBars).slice(start, end);
      sr.forEach((s, i) => {
        if (!s) return;
        ctx.fillStyle = s.up ? UP : DN;
        ctx.beginPath(); ctx.arc(xAt(i), y(s.v), 1.5, 0, Math.PI * 2); ctx.fill();
      });
    }
    if (chartOpt.vwap && tf.src === "bridge") {
      lineSeries(vwapArr(rBars).slice(start, end), "#fde68a", 1.4);
    }
  }
  // 副圖:量(預設)/MACD/KD/RSI/W%R/CCI
  const vy0 = H - 14;
  const sub = chartOpt.sub || "vol";
  const drawSubLine = (arr, col, lo2, hi2) => {
    const sp = (hi2 - lo2) || 1;
    ctx.strokeStyle = col; ctx.beginPath();
    let st = false;
    arr.forEach((v, i) => {
      if (v === null || v === undefined) return;
      const yy = vy0 - (v - lo2) / sp * (volH - 4);
      st ? ctx.lineTo(xAt(i), yy) : ctx.moveTo(xAt(i), yy); st = true;
    });
    ctx.stroke();
  };
  const subRef = (vals) => vals.forEach(v0 => {
    const yy = vy0 - v0.f * (volH - 4);
    ctx.strokeStyle = "rgba(255,255,255,.08)"; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(4, yy); ctx.lineTo(W - padR, yy); ctx.stroke(); ctx.setLineDash([]);
  });
  if (sub === "macd" && rBars.length >= 30 && !compare) {
    const m = macdArr(rBars.map(b => b.c));
    const dif = m.dif.slice(start, end), dea = m.dea.slice(start, end), hist = m.hist.slice(start, end);
    const all = dif.concat(dea, hist).filter(v => v != null);
    const hi2 = Math.max(...all), lo2 = Math.min(...all), sp = (hi2 - lo2) || 1;
    const zeroY = vy0 - (0 - lo2) / sp * (volH - 4);
    hist.forEach((v, i) => {
      const yy = vy0 - (v - lo2) / sp * (volH - 4);
      ctx.fillStyle = v >= 0 ? UP + "88" : DN + "88";
      ctx.fillRect(xAt(i) - Math.max(slotW * 0.25, 0.6), Math.min(yy, zeroY), Math.max(slotW * 0.5, 1.2), Math.abs(zeroY - yy) || 1);
    });
    drawSubLine(dif, "#fbbf24", lo2, hi2); drawSubLine(dea, "#38bdf8", lo2, hi2);
  } else if (sub === "kd" && rBars.length >= 12 && !compare) {
    const kd = kdArr(rBars);
    subRef([{ f: 0.2 }, { f: 0.8 }]);
    drawSubLine(kd.K.slice(start, end), "#fbbf24", 0, 100); drawSubLine(kd.D.slice(start, end), "#38bdf8", 0, 100);
  } else if (sub === "rsi" && rBars.length >= 16 && !compare) {
    subRef([{ f: 0.3 }, { f: 0.7 }]);
    drawSubLine(rsiArr(rBars.map(b => b.c)).slice(start, end), "#a78bfa", 0, 100);
  } else if (sub === "wpr" && rBars.length >= 16 && !compare) {
    subRef([{ f: 0.2 }, { f: 0.8 }]);
    drawSubLine(wprArr(rBars).slice(start, end), "#f472b6", -100, 0);
  } else if (sub === "cci" && rBars.length >= 22 && !compare) {
    const cc = cciArr(rBars).slice(start, end);
    const vals = cc.filter(v => v != null);
    const hi2 = Math.max(100, ...vals), lo2 = Math.min(-100, ...vals);
    drawSubLine(cc, "#34d399", lo2, hi2);
  } else {
    vis.forEach((b, i) => {
      const vh = (b.v || 0) / maxV * (volH - 4);
      ctx.fillStyle = (b.c >= b.o ? UP : DN) + "55";
      ctx.fillRect(xAt(i) - Math.max(slotW * 0.3, 0.7), vy0 - vh, Math.max(slotW * 0.6, 1.4), vh);
    });
  }
  // 使用者繪圖(依 bar 時間錨定;replay/縮放下自動跟著座標走)
  const dws = (drawings[sheetSym] || []);
  if (dws.length && !compare) {
    const tIdx = new Map(plotBars.map((b, i) => [b.t, i]));
    const nearX = t => {
      if (tIdx.has(t)) return xAt(tIdx.get(t) - start);
      let best = -1, bd = Infinity;
      for (let i = 0; i < plotBars.length; i++) {
        const d = Math.abs(plotBars[i].t - t);
        if (d < bd) { bd = d; best = i; }
      }
      return best < 0 ? null : xAt(best - start);
    };
    ctx.font = "10.5px -apple-system,sans-serif";
    dws.forEach(d => {
      const col = "#fde68a";
      ctx.strokeStyle = col; ctx.fillStyle = col;
      if (d.ty === "h") {
        const yy = y(d.p1);
        ctx.setLineDash([5, 3]); ctx.beginPath(); ctx.moveTo(4, yy); ctx.lineTo(W - padR, yy); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillText(fp(d.p1), 8, yy - 4);
      } else if (d.ty === "t") {
        const x1 = nearX(d.t1);
        if (x1 != null) { ctx.beginPath(); ctx.moveTo(x1, y(d.p1)); ctx.lineTo(x1 + 2, y(d.p1)); ctx.stroke(); ctx.fillText(d.tx || "", x1 + 4, y(d.p1)); }
      } else if (d.ty === "l") {
        const x1 = nearX(d.t1), x2 = nearX(d.t2);
        if (x1 != null && x2 != null) { ctx.beginPath(); ctx.moveTo(x1, y(d.p1)); ctx.lineTo(x2, y(d.p2)); ctx.stroke(); }
      } else if (d.ty === "f") {
        const x1 = nearX(d.t1), x2 = nearX(d.t2);
        if (x1 == null || x2 == null) return;
        const xl = Math.min(x1, x2);
        [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach(f => {
          const pv = d.p1 + (d.p2 - d.p1) * f;
          const yy = y(pv);
          ctx.globalAlpha = f === 0 || f === 1 ? 0.9 : 0.55;
          ctx.beginPath(); ctx.moveTo(xl, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
          ctx.fillText(`${(f * 100).toFixed(1)}% ${fp(pv)}`, xl + 2, yy - 3);
        });
        ctx.globalAlpha = 1;
      }
    });
  }
  if (drawPend && drawPend.t1 != null) {
    ctx.fillStyle = "#fde68a";
    const ti = plotBars.findIndex(b => b.t === drawPend.t1);
    if (ti >= 0) { ctx.beginPath(); ctx.arc(xAt(ti - start), y(drawPend.p1), 3, 0, Math.PI * 2); ctx.fill(); }
  }
  // 時間軸首尾
  ctx.fillStyle = "rgba(255,255,255,.35)"; ctx.textBaseline = "alphabetic";
  const ft = t => { const d = new Date(t * 1000); return tf.src === "bridge" || tf.range === "1D" || tf.range === "5D" ? `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : `${d.getFullYear().toString().slice(2)}/${d.getMonth() + 1}/${d.getDate()}`; };
  if (vis.length) {
    ctx.fillText(ft(vis[0].t), 6, H - 3);
    const lastTxt = ft(vis[n - 1].t);
    ctx.fillText(lastTxt, W - padR - ctx.measureText(lastTxt).width - 2, H - 3);
  }
  // 十字線
  if (hoverIdx != null && vis[hoverIdx] && !compare) {
    const b = vis[hoverIdx];
    const x = xAt(hoverIdx), cy = y(b.c);
    ctx.setLineDash([3, 3]); ctx.strokeStyle = "rgba(232,237,247,.4)";
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - 14); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(4, cy); ctx.lineTo(W - padR, cy); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#818cf8"; ctx.beginPath(); ctx.arc(x, cy, 3.2, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "rgba(232,237,247,.9)"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(x, cy, 3.2, 0, Math.PI * 2); ctx.stroke(); ctx.lineWidth = 1;
    const tag = fp(b.c), tw2 = ctx.measureText(tag).width + 8;
    ctx.fillStyle = "#312e81"; ctx.fillRect(W - padR + 1, cy - 8, Math.max(tw2, padR - 2), 16);
    ctx.fillStyle = "#dbe3ff"; ctx.textBaseline = "middle"; ctx.fillText(tag, W - padR + 4, cy);
    ctx.textBaseline = "alphabetic";
  }
  curChart = { cv, bars: full, plotBars, vis, start, tf, slotW, n, yFn: y, hi, lo, useLog, lgHi, lgLo, lgSpan, padT, priceH };
}

function barInfoHtml(bars, idx, tf, sym) {
  const b = bars[idx];
  if (!b) return "";
  const prev = idx > 0 ? bars[idx - 1].c : (bars.pc != null ? bars.pc : b.o);
  const chg = prev ? (b.c - prev) / prev * 100 : null;
  const dir = chg == null ? "" : chg >= 0 ? "up" : "down";
  const d = new Date(b.t * 1000);
  const intraday = tf.src === "bridge" || tf.range === "1D" || tf.range === "5D";
  const ts = intraday
    ? `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
    : `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
  let v = b.v || 0;
  if (isTWSym(sym) && tf.src !== "bridge") v = Math.round(v / 1000);
  return `<b>${ts}</b>　開 <b>${fp(b.o)}</b>　高 <b>${fp(b.h)}</b>　低 <b>${fp(b.l)}</b>　收 <b class="${dir}">${fp(b.c)}</b>` +
    (chg == null ? "" : `　<b class="${dir}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%</b>`) +
    `　量 <b>${v.toLocaleString()}</b>`;
}

function yToPrice(yy) {
  const c = curChart;
  if (!c) return null;
  const f = (yy - c.padT) / c.priceH;
  return c.useLog ? Math.exp(c.lgHi - f * c.lgSpan) : c.hi - f * (c.hi - c.lo);
}
function startReplay(sym) {
  if (!curChart || replay) return;
  const bar = $("replay-bar");
  if (bar) bar.style.display = "flex";
  chartView = null;
  replay = { on: true, idx: Math.max(10, Math.round(curChart.bars.length * 0.1)), speed: 1, paused: false };
  replay.timer = setInterval(() => {
    if (!replay || replay.paused || !curChart) return;
    replay.idx += replay.speed;
    const total = curChart.bars.length;
    if (replay.idx >= total) { replay.idx = total; replay.paused = true; const t = $("rp-toggle"); if (t) t.textContent = "▶"; }
    const sl = $("rp-slider");
    if (sl) sl.value = Math.round(replay.idx / total * 100);
    redrawChart();
  }, 500);
  redrawChart();
}
function stopReplay() {
  if (replay && replay.timer) clearInterval(replay.timer);
  replay = null;
  const bar = $("replay-bar");
  if (bar) bar.style.display = "none";
  redrawChart();
}
function redrawChart() {
  if (!curChart || !sheetSym) return;
  drawChart(curChart.cv, curChart.bars, curChart.tf, null);
  const strip = $("d-ohlc");
  if (strip && curChart.vis && curChart.vis.length)
    strip.innerHTML = barInfoHtml(curChart.vis, curChart.vis.length - 1, curChart.tf, sheetSym);
}
function bindChartPointer(cv, sym) {
  const strip = $("d-ohlc");
  let dragging = null, pinch0 = null, moved = false;
  const idxAt = clientX => {
    const rect = cv.getBoundingClientRect();
    let idx = Math.floor((clientX - rect.left - 4) / curChart.slotW);
    return Math.max(0, Math.min(curChart.n - 1, idx));
  };
  const move = clientX => {
    if (!curChart || curChart.cv !== cv || dragging) return;
    const idx = idxAt(clientX);
    drawChart(cv, curChart.bars, curChart.tf, idx);
    if (strip) strip.innerHTML = barInfoHtml(curChart.vis, idx, curChart.tf, sym);
  };
  const reset = () => {
    if (!curChart || curChart.cv !== cv) return;
    redrawChart();
  };
  cv.addEventListener("mousemove", e => {
    if (dragging && curChart) {
      const dx = e.clientX - dragging.x;
      if (Math.abs(dx) > 3) moved = true;
      const total = curChart.plotBars.length;
      const vn = chartView && chartView.n ? chartView.n : total;
      let o = dragging.o + Math.round(dx / curChart.slotW);
      o = Math.max(0, Math.min(o, total - Math.min(vn, total)));
      chartView = { n: vn, o };
      redrawChart();
      return;
    }
    move(e.clientX);
  });
  cv.addEventListener("mousedown", e => { dragging = { x: e.clientX, o: (chartView && chartView.o) || 0 }; moved = false; });
  window.addEventListener("mouseup", () => { dragging = null; });
  cv.addEventListener("mouseleave", () => { if (!dragging) reset(); });
  cv.addEventListener("dblclick", () => { chartView = null; redrawChart(); });
  cv.addEventListener("wheel", e => {
    if (!curChart) return;
    e.preventDefault();
    const total = curChart.plotBars.length;
    const vn = chartView && chartView.n ? chartView.n : total;
    const nn = Math.round(Math.max(10, Math.min(total, vn * (e.deltaY > 0 ? 1.2 : 0.83))));
    chartView = { n: nn, o: (chartView && chartView.o) || 0 };
    redrawChart();
  }, { passive: false });
  cv.addEventListener("touchstart", e => {
    if (e.touches.length === 2 && curChart) {
      const d = Math.abs(e.touches[0].clientX - e.touches[1].clientX);
      const total = curChart.plotBars.length;
      pinch0 = { d: Math.max(d, 1), n: chartView && chartView.n ? chartView.n : total };
    } else { move(e.touches[0].clientX); }
  }, { passive: true });
  cv.addEventListener("touchmove", e => {
    if (e.touches.length === 2 && pinch0 && curChart) {
      const d = Math.max(Math.abs(e.touches[0].clientX - e.touches[1].clientX), 1);
      const total = curChart.plotBars.length;
      const nn = Math.round(Math.max(10, Math.min(total, pinch0.n * pinch0.d / d)));
      chartView = { n: nn, o: (chartView && chartView.o) || 0 };
      redrawChart();
      return;
    }
    move(e.touches[0].clientX);
  }, { passive: true });
  cv.addEventListener("touchend", () => { pinch0 = null; });
  // 繪圖工具:click 錨定
  cv.addEventListener("click", e => {
    if (!drawTool || !curChart || moved) return;
    const rect = cv.getBoundingClientRect();
    const idx = idxAt(e.clientX);
    const bar = curChart.vis[idx];
    if (!bar) return;
    const price = yToPrice(e.clientY - rect.top);
    if (price == null) return;
    const list = drawings[sym] = drawings[sym] || [];
    if (drawTool === "h") { list.push({ ty: "h", p1: Math.round(price * 100) / 100 }); }
    else if (drawTool === "t") {
      const tx = prompt("標註文字:");
      if (tx) list.push({ ty: "t", t1: bar.t, p1: price, tx: tx.slice(0, 30) });
    } else if (drawTool === "l" || drawTool === "f") {
      if (!drawPend) { drawPend = { t1: bar.t, p1: price }; redrawChart(); return; }
      list.push({ ty: drawTool, t1: drawPend.t1, p1: drawPend.p1, t2: bar.t, p2: price });
      drawPend = null;
    } else if (drawTool === "erase") {
      let best = -1, bd = Infinity;
      list.forEach((d, i) => {
        const dy = d.ty === "h" ? Math.abs(curChart.yFn(d.p1) - (e.clientY - rect.top))
          : Math.min(Math.abs((d.p1 != null ? curChart.yFn(d.p1) : 1e9) - (e.clientY - rect.top)),
                     Math.abs((d.p2 != null ? curChart.yFn(d.p2) : 1e9) - (e.clientY - rect.top)));
        if (dy < bd) { bd = dy; best = i; }
      });
      if (best >= 0 && bd < 24) list.splice(best, 1);
    }
    saveDrawings(); redrawChart();
  });
}

async function renderDetailChart(sym) {
  const cv = $("d-chart");
  if (!cv) return;
  const tf = TF_LIST.find(t => t.k === curTf);
  try {
    const bars = await fetchBars(sym, curTf);
    if (sheetSym !== sym) return;
    if (tf.range === "1D") bars.pc = bars.prevClose;
    drawChart(cv, bars, tf, null);
    const strip = $("d-ohlc");
    if (strip && curChart && curChart.vis.length)
      strip.innerHTML = barInfoHtml(curChart.vis, curChart.vis.length - 1, tf, sym);
    if (!cv.dataset.bound) { cv.dataset.bound = "1"; bindChartPointer(cv, sym); }
  } catch { drawChart(cv, [], tf, null); }
}

function tfChipsHtml(sym) {
  const isTW = isTWSym(sym);
  return TF_LIST.filter(t => !(t.twOnly && (!isTW || !bridge)))
    .map(t => `<button class="tf ${curTf === t.k ? "on" : ""}" data-tf="${t.k}">${T("tf_" + t.k)}</button>`).join("");
}

function tiTile(k, v, s, cls, id) {
  return `<div class="ti"${id ? ` id="${id}"` : ""}><div class="k">${k}</div><div class="v ${cls || ""}">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
}

async function renderTech(sym) {
  const el = $("d-tech");
  if (!el) return;
  try {
    const bars = await fetchBars(sym, "6M");
    if (sheetSym !== sym || !el.isConnected) return;
    const closes = bars.map(b => b.c);
    const last = closes[closes.length - 1];
    const m5 = sma(closes, 5).pop(), m20 = sma(closes, 20).pop(), m60 = sma(closes, 60).pop();
    const r = rsi14(closes), kd = kd9(bars), mc = macd(closes);
    const rState = r == null ? "" : r >= 70 ? T("ti_over") : r <= 30 ? T("ti_under") : T("ti_mid");
    const rCls = r == null ? "" : r >= 70 ? "up" : r <= 30 ? "down" : "";
    const kdState = kd ? (kd.K > kd.D ? T("ti_gold") : T("ti_dead")) : "";
    const mState = mc ? (mc.hist > 0 ? T("ti_gold") : T("ti_dead")) : "";
    const maS = (m, lbl) => m == null ? "" : (last > m ? `${T("ti_above")}${lbl}` : `${T("ti_below")}${lbl}`);
    const bl = bars.length >= 20 ? bollArr(closes) : null;
    const blUp = bl ? bl.up[bl.up.length - 1] : null, blDn = bl ? bl.dn[bl.dn.length - 1] : null;
    const blState = blUp == null ? "" : last >= blUp ? T("ti_over") : last <= blDn ? T("ti_under") : T("ti_mid");
    const dmi = dmi14(bars);
    const mfi = mfi14(bars);
    const obv = obvArr(bars);
    const obvUp = obv.length > 10 && obv[obv.length - 1] > obv[obv.length - 10];
    const bias = m20 ? (last - m20) / m20 * 100 : null;
    const sarL = sarArr(bars), sarLast = sarL[sarL.length - 1];
    const atrV = atr14(bars);
    const cciL = cciArr(bars), cciV = cciL[cciL.length - 1];
    const wprL = wprArr(bars), wprV = wprL[wprL.length - 1];
    el.innerHTML =
      tiTile("MA5", fp(m5), maS(m5, "MA5"), last > m5 ? "up" : "down") +
      tiTile("MA20", fp(m20), maS(m20, "MA20"), last > m20 ? "up" : "down") +
      tiTile("MA60", fp(m60), maS(m60, "MA60"), m60 ? (last > m60 ? "up" : "down") : "") +
      tiTile("RSI 14", r == null ? "—" : r.toFixed(1), rState, rCls) +
      tiTile("KD 9", kd ? `${kd.K.toFixed(0)} / ${kd.D.toFixed(0)}` : "—", kdState, kd && kd.K > kd.D ? "up" : "down") +
      tiTile("MACD", mc ? mc.hist.toFixed(2) : "—", mState, mc && mc.hist > 0 ? "up" : "down") +
      tiTile("BOLL 20", blUp == null ? "—" : `${fp(blDn)}~${fp(blUp)}`, blState, blState === T("ti_over") ? "up" : blState === T("ti_under") ? "down" : "") +
      tiTile("DMI 14", dmi && dmi.adx != null ? `ADX ${dmi.adx.toFixed(0)}` : "—",
        dmi ? `+DI ${dmi.pdi.toFixed(0)} / -DI ${dmi.mdi.toFixed(0)}` : "", dmi && dmi.pdi > dmi.mdi ? "up" : "down") +
      tiTile("MFI 14", mfi == null ? "—" : mfi.toFixed(1), mfi == null ? "" : mfi >= 80 ? T("ti_over") : mfi <= 20 ? T("ti_under") : T("ti_mid"), mfi != null && mfi >= 80 ? "up" : mfi != null && mfi <= 20 ? "down" : "") +
      tiTile("OBV", obv.length ? (obvUp ? "↗" : "↘") : "—", "10日能量潮", obvUp ? "up" : "down") +
      tiTile("乖離 20", bias == null ? "—" : `${bias >= 0 ? "+" : ""}${bias.toFixed(1)}%`, "", bias >= 0 ? "up" : "down") +
      tiTile("SAR", sarLast ? fp(sarLast.v) : "—", sarLast ? (sarLast.up ? "多方支撐" : "空方壓力") : "", sarLast && sarLast.up ? "up" : "down") +
      tiTile("ATR 14", atrV == null ? "—" : fp(atrV), atrV != null && last ? `波動 ${(atrV / last * 100).toFixed(1)}%` : "") +
      tiTile("CCI 20", cciV == null ? "—" : cciV.toFixed(0), cciV == null ? "" : cciV >= 100 ? T("ti_over") : cciV <= -100 ? T("ti_under") : T("ti_mid"), cciV != null && cciV >= 100 ? "up" : cciV != null && cciV <= -100 ? "down" : "") +
      tiTile("W%R 14", wprV == null ? "—" : wprV.toFixed(0), wprV == null ? "" : wprV >= -20 ? T("ti_over") : wprV <= -80 ? T("ti_under") : T("ti_mid"), wprV != null && wprV >= -20 ? "up" : wprV != null && wprV <= -80 ? "down" : "");
    techFactors[sym] = buildTechFactors(bars, { m5, m20, m60, r, kd, mc, last });
    renderDiag(sym);
  } catch { el.innerHTML = ""; }
}

/* 多空總覽:技術+籌碼+估值 因子彙整(確定性計算,非投資建議) */
let techFactors = {}, chipsFactors = {};
function buildTechFactors(bars, t) {
  const f = [];
  if (t.m5 != null && t.m20 != null && t.m60 != null) {
    if (t.last > t.m5 && t.m5 > t.m20 && t.m20 > t.m60) f.push(["均線多頭排列", 1]);
    else if (t.last < t.m5 && t.m5 < t.m20 && t.m20 < t.m60) f.push(["均線空頭排列", -1]);
    else f.push([t.last > t.m20 ? "價在月線上" : "價在月線下", t.last > t.m20 ? 1 : -1]);
  }
  if (t.r != null) f.push(t.r >= 70 ? ["RSI 超買", -1] : t.r <= 30 ? ["RSI 超賣", 1] : ["RSI 中性", 0]);
  if (t.kd) f.push(t.kd.K > t.kd.D ? ["KD 多方", 1] : ["KD 空方", -1]);
  if (t.mc) f.push(t.mc.hist > 0 ? ["MACD 紅柱", 1] : ["MACD 綠柱", -1]);
  return f;
}
function renderDiag(sym) {
  const el = $("d-diag");
  if (!el || sheetSym !== sym) return;
  const f = (techFactors[sym] || []).concat(chipsFactors[sym] || []);
  if (!f.length) { el.innerHTML = ""; return; }
  const nb = f.filter(x => x[1] > 0).length, ns = f.filter(x => x[1] < 0).length;
  el.innerHTML = `<p class="diag-sum">${T("diag_bull")} <b>${nb}</b> · ${T("diag_bear")} <b>${ns}</b></p>
    <div class="diag-wrap">${f.map(([n, s]) => `<span class="diag-chip ${s > 0 ? "bull" : s < 0 ? "bear" : "neu"}">${n}</span>`).join("")}</div>`;
}

function fmtMcapTWD(shares, price) {
  if (!shares || !price) return "—";
  const yi = shares * price / 1e8;
  return yi >= 10000 ? (yi / 10000).toFixed(2) + " 兆" : Math.round(yi).toLocaleString() + " 億";
}
function fmtMcapUSD(m) {
  if (!m) return "—";
  return m >= 1e6 ? "$" + (m / 1e6).toFixed(2) + "T" : m >= 1000 ? "$" + (m / 1000).toFixed(1) + "B" : "$" + Math.round(m) + "M";
}

async function renderFund(sym) {
  const el = $("d-fund");
  if (!el) return;
  const q = quotes[sym] || {};
  if (isTWSym(sym)) {
    const f = twFund[sym] || {};
    const prof = PROFILE[sym];
    el.innerHTML =
      tiTile(T("fd_pe"), f.pe != null ? f.pe : "—", T("fd_asof"), "", "ti-pe") +
      tiTile(T("fd_dy"), f.dy != null ? f.dy + "%" : "—", T("fd_asof")) +
      tiTile(T("fd_pb"), f.pb != null ? f.pb : "—", T("fd_asof")) +
      tiTile(T("fd_mcap"), fmtMcapTWD(prof && prof[3], q.price), "NT$");
    return;
  }
  el.innerHTML = `<div class="ti" style="grid-column:1/-1;color:var(--muted)">${T("loading")}</div>`;
  try {
    let f = usFundCache[sym];
    if (!f) { f = await fetch(`${WORKER_URL}/us-fundamentals?symbol=${sym}`).then(r => r.json()); usFundCache[sym] = f; }
    if (sheetSym !== sym || !el.isConnected) return;
    const usLoss = f.pe == null && f.eps != null && f.eps < 0;
    el.innerHTML =
      tiTile(T("fd_pe"), f.pe != null ? f.pe.toFixed(1) : (usLoss ? T("fd_loss") : "—"), usLoss ? T("fd_loss_sub") : "", usLoss ? "down" : "") +
      tiTile(T("fd_pb"), f.pb != null ? f.pb.toFixed(1) : "—") +
      tiTile(T("fd_dy"), f.dy != null && f.dy > 0 ? f.dy.toFixed(2) + "%" : "—", f.dy == null || f.dy === 0 ? T("fd_nodiv") : "") +
      tiTile(T("fd_eps"), f.eps != null ? "$" + f.eps.toFixed(2) : "—") +
      tiTile(T("fd_mcap"), fmtMcapUSD(f.market_cap_m)) +
      tiTile(T("fd_52"), f.high52 ? `${fp(f.high52)} / ${fp(f.low52)}` : "—") +
      tiTile(T("fd_beta"), f.beta != null ? f.beta.toFixed(2) : "—") +
      tiTile(T("fd_ind"), f.industry || "—");
  } catch { el.innerHTML = ""; }
}

const BIZ = (typeof TW_BIZ !== "undefined") ? TW_BIZ : {};
const CHAIN_GENERIC = (typeof TW_CHAIN_GENERIC !== "undefined") ? TW_CHAIN_GENERIC : {};
const USCG = (typeof US_CHAIN_GENERIC !== "undefined") ? US_CHAIN_GENERIC : {};

function renderProfile(sym) {
  const el = $("d-prof");
  if (!el) return;
  const entry = chainIdx && chainIdx[sym];
  const bizTxt = (entry && entry.mid && entry.mid.desc) || BIZ[sym] || "";
  const biz = bizTxt ? `<div class="biz">${bizTxt}</div>` : "";
  if (isTWSym(sym)) {
    const p = PROFILE[sym];
    if (!p && !biz) { el.style.display = "none"; return; }
    el.style.display = "";
    const rows = [];
    if (p) {
      if (p[0]) rows.push(`${T("prof_chair")} <b>${p[0]}</b>`);
      if (p[1]) rows.push(`${T("prof_gm")} <b>${p[1]}</b>`);
      if (p[2]) rows.push(`${T("prof_listed")} <b>${p[2]}</b>`);
      if (p[4]) rows.push(`<a href="${p[4]}" target="_blank" rel="noopener">${T("prof_web")} ↗</a>`);
    }
    el.innerHTML = `<div class="prof">${biz}${rows.length ? `<div class="kv">${rows.join("　")}</div>` : ""}</div>`;
    return;
  }
  const f = usFundCache[sym];
  const rows = [];
  if (f) {
    if (f.ipo) rows.push(`${T("prof_listed")} <b>${f.ipo.slice(0, 4)}</b>`);
    if (f.weburl) rows.push(`<a href="${f.weburl}" target="_blank" rel="noopener">${T("prof_web")} ↗</a>`);
  }
  if (!biz && !rows.length) { el.style.display = "none"; return; }
  el.style.display = "";
  el.innerHTML = `<div class="prof">${biz}${rows.length ? `<div class="kv">${rows.join("　")}</div>` : ""}</div>`;
}

function chainChip(p) {
  const tk = normTicker(p.ticker);
  const clickable = tk && nameMap.has(tk);
  const role = p.role || p.category || "";
  return `<span class="chain-chip" ${clickable ? `data-cs="${tk}"` : 'style="cursor:default;opacity:.8"'}>
    <span class="cc-n">${p.name_zh || p.name_en}</span>${tk ? ` <span class="code-sub">${tk}</span>` : ""}
    ${role ? `<span class="cc-r">${role}</span>` : ""}</span>`;
}

async function renderChainEvents(sym) {
  const el = $("d-chain-ev");
  if (!el) return;
  try {
    const d = await fetch(`${WORKER_URL}/supply-chain-updates?ticker=${sym}`).then(r => r.json());
    if (sheetSym !== sym || !el.isConnected) return;
    const evs = d.events || [];
    if (!evs.length) { el.innerHTML = ""; return; }
    el.innerHTML = `<div class="chain-lbl" style="margin-top:12px">🆕 供應鏈動態(官方公告)</div>` + evs.map(e => {
      const inner = `<div class="news-t">${escAttr(e.headline || "")}</div>
        <div class="news-m">${e.date || ""}${e.counterparty ? " · 對象:" + escAttr(e.counterparty) : ""}${e.source_type ? " · " + escAttr(e.source_type) : ""}</div>`;
      return e.url ? `<a class="news-item" href="${e.url}" target="_blank" rel="noopener">${inner}</a>` : `<div class="news-item">${inner}</div>`;
    }).join("");
  } catch {}
}
async function renderChain(sym) {
  await loadChain();
  const el = $("d-chain");
  if (!el || sheetSym !== sym) return;
  const h = $("d-chain-h");
  const entry = chainIdx[sym];
  const isETF = INDUSTRY[sym] === "ETF";
  const paint = (up, down, badge) => {
    if (sheetSym !== sym || !el.isConnected) return;
    el.style.display = ""; if (h) h.style.display = "";
    el.innerHTML = `<div style="margin-bottom:8px">${badge}</div>` +
      (up.length ? `<div class="chain-col"><div class="chain-lbl">⬆ ${T("chain_up")}</div>${up.map(chainChip).join("")}</div>` : "") +
      (down.length ? `<div class="chain-col"><div class="chain-lbl">⬇ ${T("chain_down")}</div>${down.map(chainChip).join("")}</div>` : "");
    el.querySelectorAll("[data-cs]").forEach(c => c.onclick = e => { e.stopPropagation(); openSheet(c.dataset.cs); });
  };
  const bchip = txt => `<span class="chip" style="cursor:default;font-size:10px;padding:2px 8px">${txt}</span>`;
  if (entry) {
    paint(entry.upstream || [], entry.downstream || [], bchip(entry.source === "pregen" ? "公司級產業鏈" : T("chain_verified")));
  } else if (isETF) {
    el.style.display = "none"; if (h) h.style.display = "none";
    renderProfile(sym);
    renderChainEvents(sym);
    return;
  } else {
    // 先墊產業通用鏈(或整理中),背景打既有 /supply-chain 管線升級成公司級 AI 鏈
    const conv = arr => (arr || []).map(x => ({ name_zh: x.n, ticker: x.t, role: x.r }));
    let painted = false;
    if (isTWSym(sym) && CHAIN_GENERIC[INDUSTRY[sym]]) {
      const g = CHAIN_GENERIC[INDUSTRY[sym]];
      paint(conv(g.up), conv(g.down), bchip(`${T("chain_generic")} · ${INDUSTRY[sym]}`));
      painted = true;
    } else if (!isTWSym(sym)) {
      const f = usFundCache[sym];
      const g = f && f.industry && USCG[f.industry];
      if (g) { paint(conv(g.up), conv(g.down), bchip(`${T("chain_generic")} · ${f.industry}`)); painted = true; }
    }
    if (!painted) {
      el.style.display = ""; if (h) h.style.display = "";
      el.innerHTML = `<div class="sig-item" style="color:var(--muted)">${T("chain_wip")}</div>`;
    }
  }
  renderProfile(sym);
  renderChainEvents(sym);
}

/* 五檔 */
async function renderDepth(sym) {
  if (!bridge || !isTWSym(sym) || sheetSym !== sym) return;
  const wrap = $("d-depth-wrap"), el = $("d-depth");
  if (!wrap || !el) return;
  try {
    const d = await fetch(`${bridge.url}/depth?sym=${sym}&t=${encodeURIComponent(bridge.token)}`).then(r => r.json());
    if (sheetSym !== sym || !el.isConnected) return;
    wrap.style.display = "";
    if (!d.depth) { el.innerHTML = `<div class="dp-col" style="grid-column:1/-1;color:var(--muted);font-size:12px">${T("depth_pending")}</div>`; return; }
    const maxV = Math.max(...d.depth.bid.map(x => x[1]), ...d.depth.ask.map(x => x[1]), 1);
    const rows = (arr, col) => arr.map(([p, v]) =>
      `<div class="dp-row"><div class="bar" style="width:${Math.round(v / maxV * 100)}%;background:${col}"></div>
       <b>${fp(p)}</b><span>${v.toLocaleString()}</span></div>`).join("");
    el.innerHTML =
      `<div class="dp-col"><div class="dp-h">${T("depth_bid")}</div>${rows(d.depth.bid, "#ef4444")}</div>` +
      `<div class="dp-col"><div class="dp-h">${T("depth_ask")}</div>${rows(d.depth.ask, "#22c55e")}</div>`;
  } catch {}
}

/* 新聞流 */
async function renderNews(sym) {
  const el = $("d-news");
  if (!el) return;
  try {
    let items = newsCache[sym] && Date.now() - newsCache[sym].at < 600000 ? newsCache[sym].items : null;
    if (!items) {
      const q = isTWSym(sym) ? `&q=${encodeURIComponent((nameMap.get(sym) || sym).slice(0, 12))}` : "";
      const d = await fetch(`${WORKER_URL}/stock-news?symbol=${sym}${q}`).then(r => r.json());
      items = d.news || [];
      newsCache[sym] = { at: Date.now(), items };
    }
    if (sheetSym !== sym || !el.isConnected) return;
    if (!items.length) { el.innerHTML = `<div class="sig-item" style="color:var(--muted)">${T("news_none")}</div>`; return; }
    const ago = ts => {
      if (!ts) return "";
      const h = (Date.now() / 1000 - ts) / 3600;
      return h < 1 ? `${Math.max(Math.round(h * 60), 1)}m` : h < 24 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`;
    };
    el.innerHTML = items.map(n =>
      `<a class="news-item" href="${n.url}" target="_blank" rel="noopener">
        <div class="news-t">${n.title}</div><div class="news-m">${n.source || ""} · ${ago(n.ts)}</div></a>`).join("");
  } catch { el.innerHTML = ""; }
}

/* ── 迷你圖(籌碼/財務):bars+lines 雙軸 canvas ── */
function miniChart(cv, cfg) {
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W) return;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  const n = cfg.n;
  if (!n) return;
  const padB = 13, ph = H - padB - 4;
  const slotW = W / n;
  const xAt = i => slotW * (i + 0.5);
  const scale = vals => {
    const vs = vals.filter(v => v != null && isFinite(v));
    if (!vs.length) return null;
    let hi = Math.max(...vs), lo = Math.min(...vs);
    if (cfg.zero) { hi = Math.max(hi, 0); lo = Math.min(lo, 0); }
    if (hi === lo) { hi += 1; lo -= 1; }
    return { hi, lo, y: v => 4 + (hi - v) / (hi - lo) * ph };
  };
  (cfg.bars || []).forEach(bs => {
    const sc = scale(bs.data.flat ? bs.data.flat() : bs.data);
    if (!sc) return;
    const zy = sc.y(Math.max(sc.lo, Math.min(0, sc.hi)));
    const groups = Array.isArray(bs.data[0]) ? bs.data : bs.data.map(v => [v]);
    const gw = Math.max(slotW * 0.7 / groups[0].length, 1);
    groups.forEach((g, i) => {
      g.forEach((v, j) => {
        if (v == null) return;
        const yy = sc.y(v);
        ctx.fillStyle = (bs.colors && (typeof bs.colors === "function" ? bs.colors(v, j) : bs.colors[j])) || "#818cf8";
        const x0 = xAt(i) - (groups[0].length * gw) / 2 + j * gw;
        ctx.fillRect(x0, Math.min(yy, zy), Math.max(gw - 0.6, 0.8), Math.abs(zy - yy) || 1);
      });
    });
    if (sc.lo < 0 && sc.hi > 0) { ctx.strokeStyle = "rgba(255,255,255,.15)"; ctx.beginPath(); ctx.moveTo(0, zy); ctx.lineTo(W, zy); ctx.stroke(); }
  });
  (cfg.lines || []).forEach(ln => {
    const sc = scale(ln.data);
    if (!sc) return;
    ctx.strokeStyle = ln.color; ctx.lineWidth = ln.width || 1.4; ctx.beginPath();
    let st = false;
    ln.data.forEach((v, i) => {
      if (v == null || !isFinite(v)) return;
      st ? ctx.lineTo(xAt(i), sc.y(v)) : ctx.moveTo(xAt(i), sc.y(v)); st = true;
    });
    ctx.stroke(); ctx.lineWidth = 1;
  });
  ctx.fillStyle = "rgba(255,255,255,.3)"; ctx.font = "9.5px -apple-system,sans-serif";
  if (cfg.x0) ctx.fillText(cfg.x0, 2, H - 3);
  if (cfg.x1) ctx.fillText(cfg.x1, W - ctx.measureText(cfg.x1).width - 2, H - 3);
}

/* ── 籌碼面(台股):/tw-chips ── */
let chipsCache = {};
async function renderChips(sym) {
  const el = $("d-chips");
  if (!el || !isTWSym(sym)) return;
  try {
    let d = chipsCache[sym] && Date.now() - chipsCache[sym].at < 1800000 ? chipsCache[sym].d : null;
    if (!d) {
      d = await fetch(`${WORKER_URL}/tw-chips?code=${sym}`).then(r => r.json());
      if (d.error) throw new Error(d.error);
      chipsCache[sym] = { at: Date.now(), d };
    }
    if (sheetSym !== sym || !el.isConnected) return;
    const inst = d.inst || [], mg = d.margin || [], fr = d.foreign || [], dt = d.daytrade || [], px = d.px || [];
    if (!inst.length && !mg.length) { el.innerHTML = ""; return; }
    const streak = (arr, pick) => {
      let s = 0;
      for (let i = arr.length - 1; i >= 0; i--) { const v = pick(arr[i]); if (s === 0) s = v > 0 ? 1 : v < 0 ? -1 : 0; else if ((s > 0 && v > 0) || (s < 0 && v < 0)) s += Math.sign(s); else break; if (s === 0) break; }
      return s;
    };
    const fS = streak(inst, r => r.f), tS = streak(inst, r => r.t);
    const mg5 = mg.length > 5 && mg[mg.length - 1].mb != null && mg[mg.length - 6].mb != null ? mg[mg.length - 1].mb - mg[mg.length - 6].mb : null;
    const frLast = fr.length ? fr[fr.length - 1].fr : null;
    const sTxt = s => s === 0 ? "—" : `連${Math.abs(s)}日${s > 0 ? "買超" : "賣超"}`;
    el.innerHTML =
      `<div class="ti-grid" style="margin-bottom:10px">` +
      tiTile("外資", sTxt(fS), inst.length ? `近1日 ${inst[inst.length - 1].f >= 0 ? "+" : ""}${inst[inst.length - 1].f.toLocaleString()} 張` : "", fS > 0 ? "up" : fS < 0 ? "down" : "") +
      tiTile("投信", sTxt(tS), inst.length ? `近1日 ${inst[inst.length - 1].t >= 0 ? "+" : ""}${inst[inst.length - 1].t.toLocaleString()} 張` : "", tS > 0 ? "up" : tS < 0 ? "down" : "") +
      tiTile("融資5日", mg5 == null ? "—" : `${mg5 >= 0 ? "+" : ""}${mg5.toLocaleString()} 張`, "餘額增減", mg5 > 0 ? "up" : mg5 < 0 ? "down" : "") +
      tiTile("外資持股", frLast == null ? "—" : frLast.toFixed(1) + "%", "官方日更", "") +
      `</div>` +
      `<div class="mini-card"><div class="mc-t"><span>${T("chip_inst")}</span></div><canvas id="mc-inst"></canvas></div>` +
      `<div class="mini-card"><div class="mc-t"><span>${T("chip_margin")}</span><span class="mc-v">${mg.length ? `融資 ${mg[mg.length - 1].mb?.toLocaleString() ?? "—"} · 融券 ${mg[mg.length - 1].sb?.toLocaleString() ?? "—"}` : ""}</span></div><canvas id="mc-margin"></canvas></div>` +
      (fr.length ? `<div class="mini-card"><div class="mc-t"><span>${T("chip_foreign")}</span><span class="mc-v">${frLast?.toFixed(2)}%</span></div><canvas id="mc-foreign"></canvas></div>` : "") +
      (dt.length ? `<div class="mini-card"><div class="mc-t"><span>${T("chip_dt")}</span><span class="mc-v">${dt[dt.length - 1].r}%</span></div><canvas id="mc-dt"></canvas></div>` : "");
    const closes = new Map(px.map(p => [p.d, p.c]));
    miniChart($("mc-inst"), {
      n: inst.length,
      bars: [{ data: inst.map(r => [r.f, r.t, r.dl]), colors: ["#818cf8", "#fbbf24", "#64748b"] }],
      lines: [{ data: inst.map(r => closes.get(r.d) ?? null), color: "rgba(232,237,247,.5)" }],
      x0: inst[0]?.d.slice(5), x1: inst[inst.length - 1]?.d.slice(5), zero: true,
    });
    miniChart($("mc-margin"), {
      n: mg.length,
      lines: [{ data: mg.map(r => r.mb), color: "#ef4444" }, { data: mg.map(r => r.sb), color: "#22c55e" }],
      x0: mg[0]?.d.slice(5), x1: mg[mg.length - 1]?.d.slice(5),
    });
    if (fr.length) miniChart($("mc-foreign"), {
      n: fr.length, lines: [{ data: fr.map(r => r.fr), color: "#a78bfa", width: 1.8 }],
      x0: fr[0]?.d.slice(5), x1: fr[fr.length - 1]?.d.slice(5),
    });
    if (dt.length) miniChart($("mc-dt"), {
      n: dt.length, bars: [{ data: dt.map(r => r.r), colors: () => "#f59e0b99" }],
      x0: dt[0]?.d.slice(5), x1: dt[dt.length - 1]?.d.slice(5), zero: true,
    });
    const cf = [];
    if (fS >= 3) cf.push([`外資連${fS}日買超`, 1]); else if (fS <= -3) cf.push([`外資連${-fS}日賣超`, -1]);
    if (tS >= 3) cf.push([`投信連${tS}日買超`, 1]); else if (tS <= -3) cf.push([`投信連${-tS}日賣超`, -1]);
    if (mg5 != null && mg.length > 5 && mg[mg.length - 6].mb) {
      const pct = mg5 / mg[mg.length - 6].mb * 100;
      if (pct > 8) cf.push(["融資急增", -1]); else if (pct < -8) cf.push(["融資大減", 1]);
    }
    if (fr.length > 20 && frLast != null) {
      const prev = fr[fr.length - 21].fr;
      if (frLast - prev > 0.5) cf.push(["外資持股走升", 1]); else if (frLast - prev < -0.5) cf.push(["外資持股走降", -1]);
    }
    chipsFactors[sym] = cf;
    renderDiag(sym);
  } catch { if (el) el.innerHTML = ""; }
}

/* ── 財務體質(台股):/tw-fin ── */
let finCache = {};
async function renderFinDeep(sym) {
  const el = $("d-findeep");
  if (!el || !isTWSym(sym)) return;
  try {
    let d = finCache[sym] && Date.now() - finCache[sym].at < 3600000 ? finCache[sym].d : null;
    if (!d) {
      d = await fetch(`${WORKER_URL}/tw-fin?code=${sym}`).then(r => r.json());
      if (d.error) throw new Error(d.error);
      finCache[sym] = { at: Date.now(), d };
    }
    if (sheetSym !== sym || !el.isConnected) return;
    const rev = d.rev || [], q = d.quarters || [], per = d.per || [];
    if (!rev.length && !q.length) { el.innerHTML = ""; return; }
    const yoy = rev.map((r, i) => {
      const prev = rev.find(x => {
        const [y2, m2] = x.m.split("-").map(Number), [y1, m1] = r.m.split("-").map(Number);
        return y2 === y1 - 1 && m2 === m1;
      });
      return prev && prev.v ? (r.v / prev.v - 1) * 100 : null;
    });
    const lastYoy = [...yoy].reverse().find(v => v != null);
    const eps4 = q.length >= 4 ? q.slice(-4).reduce((s, x) => s + (x.eps || 0), 0) : (q.length ? q.reduce((s, x) => s + (x.eps || 0), 0) : null);
    const peTile = $("ti-pe");
    if (peTile && eps4 != null && eps4 <= 0 && peTile.querySelector(".v") && peTile.querySelector(".v").textContent === "—") {
      peTile.querySelector(".v").textContent = T("fd_loss");
      peTile.querySelector(".v").className = "v down";
      const sEl = peTile.querySelector(".s");
      if (sEl) sEl.textContent = T("fd_loss_sub_tw");
    }
    const lastPer = per.length ? per[per.length - 1] : null;
    const perVals = per.map(p => p.per).filter(v => v != null).sort((a, b) => a - b);
    const perPctl = lastPer && lastPer.per != null && perVals.length > 10
      ? Math.round(perVals.filter(v => v <= lastPer.per).length / perVals.length * 100) : null;
    el.innerHTML =
      `<div class="ti-grid" style="margin-bottom:10px">` +
      tiTile("最新月營收", rev.length ? (rev[rev.length - 1].v / 1e8).toFixed(1) + " 億" : "—", rev.length ? rev[rev.length - 1].m : "") +
      tiTile("營收年增", lastYoy == null ? "—" : `${lastYoy >= 0 ? "+" : ""}${lastYoy.toFixed(1)}%`, "YoY", lastYoy >= 0 ? "up" : "down") +
      tiTile("EPS(近4季)", eps4 != null ? eps4.toFixed(2) : "—", "元", eps4 != null && eps4 < 0 ? "down" : "") +
      tiTile("PER 1年分位", perPctl == null ? "—" : perPctl + "%", lastPer && lastPer.per != null ? `目前 ${lastPer.per}` : "", perPctl != null && perPctl >= 80 ? "up" : perPctl != null && perPctl <= 20 ? "down" : "") +
      `</div>` +
      `<div class="mini-card"><div class="mc-t"><span>${T("fin_rev")}</span></div><canvas id="mc-rev"></canvas></div>` +
      (q.length ? `<div class="mini-card"><div class="mc-t"><span>${T("fin_eps")}</span></div><canvas id="mc-eps"></canvas></div>` : "") +
      (q.length ? `<div class="mini-card"><div class="mc-t"><span>${T("fin_margin")}</span><span class="mc-v">毛利 <span style="color:#fbbf24">─</span> 營益 <span style="color:#818cf8">─</span> 淨利 <span style="color:#38bdf8">─</span></span></div><canvas id="mc-mgn"></canvas></div>` : "") +
      (per.length ? `<div class="mini-card"><div class="mc-t"><span>${T("fin_per")}</span><span class="mc-v">PER <span style="color:#a78bfa">─</span> PBR <span style="color:#38bdf8">─</span></span></div><canvas id="mc-per"></canvas></div>` : "");
    miniChart($("mc-rev"), {
      n: rev.length,
      bars: [{ data: rev.map(r => r.v / 1e8), colors: () => "#818cf888" }],
      lines: [{ data: yoy, color: "#fbbf24", width: 1.6 }],
      x0: rev[0]?.m, x1: rev[rev.length - 1]?.m, zero: true,
    });
    if (q.length) {
      miniChart($("mc-eps"), {
        n: q.length,
        bars: [{ data: q.map(x => x.eps), colors: v => v >= 0 ? "#ef4444aa" : "#22c55eaa" }],
        x0: q[0].q, x1: q[q.length - 1].q, zero: true,
      });
      miniChart($("mc-mgn"), {
        n: q.length,
        lines: [{ data: q.map(x => x.gm), color: "#fbbf24" }, { data: q.map(x => x.om), color: "#818cf8" }, { data: q.map(x => x.nm), color: "#38bdf8" }],
        x0: q[0].q, x1: q[q.length - 1].q,
      });
    }
    if (per.length) miniChart($("mc-per"), {
      n: per.length,
      lines: [{ data: per.map(p => p.per), color: "#a78bfa", width: 1.6 }, { data: per.map(p => p.pbr), color: "#38bdf8" }],
      x0: per[0]?.d.slice(5), x1: per[per.length - 1]?.d.slice(5),
    });
  } catch { if (el) el.innerHTML = ""; }
}

/* ── 內外盤+大單(admin,bridge /ticks) ── */
async function renderTicks(sym) {
  if (!bridge || !isTWSym(sym) || sheetSym !== sym) return;
  const wrap = $("d-ticks-wrap"), el = $("d-ticks");
  if (!wrap || !el) return;
  try {
    const d = await fetch(`${bridge.url}/ticks?sym=${sym}&t=${encodeURIComponent(bridge.token)}`).then(r => r.json());
    if (sheetSym !== sym || !el.isConnected) return;
    if (d.status === "unsupported") { wrap.style.display = "none"; return; }
    wrap.style.display = "";
    if (!d.ticks || !d.ticks.length) { el.innerHTML = `<div class="sig-item" style="color:var(--muted)">${T("depth_pending")}</div>`; return; }
    const io = d.inout || { out: 0, in: 0 };
    const tot = (io.out + io.in) || 1;
    const op = Math.round(io.out / tot * 100);
    const big = d.big || { buy: 0, sell: 0, thresh: 50 };
    const rows = d.ticks.slice(-20).reverse().map(t => {
      const cls = t.io === 1 ? "up" : t.io === 2 ? "down" : "neutral";
      const hh = new Date(t.ts * 1000);
      return `<div class="tk"><span>${String(hh.getHours()).padStart(2, "0")}:${String(hh.getMinutes()).padStart(2, "0")}:${String(hh.getSeconds()).padStart(2, "0")}</span><b class="${cls}">${fp(t.c)}</b><span class="${cls}">${t.v}</span></div>`;
    }).join("");
    el.innerHTML =
      `<div class="io-bar"><div class="io-out" style="width:${op}%"></div><div class="io-in" style="flex:1"></div></div>
       <div class="io-lbl"><span class="up">${T("io_out")} ${op}% · ${io.out.toLocaleString()} 張</span><span class="down">${T("io_in")} ${100 - op}% · ${io.in.toLocaleString()} 張</span></div>
       <div class="io-lbl" style="margin-top:5px"><span class="up">${T("big_buy")}(≥${big.thresh}張) ${big.buy.toLocaleString()} 張</span><span class="down">${T("big_sell")} ${big.sell.toLocaleString()} 張</span></div>
       <div class="tick-list">${rows}</div>`;
  } catch {}
}

/* ── 到價警示 ── */
let alerts = {};
try { alerts = JSON.parse(localStorage.getItem("md-watch-alerts") || "{}") || {}; } catch {}
const AL_TYPES = ["above", "below", "chg_up", "chg_dn", "vol",
  "ma20_up", "ma20_dn", "ma60_up", "ma60_dn", "rsi_gt", "rsi_lt", "kd_gold", "kd_dead", "boll_up", "boll_dn"];
const AL_NOVAL = new Set(["ma20_up", "ma20_dn", "ma60_up", "ma60_dn", "kd_gold", "kd_dead", "boll_up", "boll_dn"]);
const alTypeLabel = t => ({ above: T("al_above"), below: T("al_below"), chg_up: T("al_chg_up"), chg_dn: T("al_chg_dn"), vol: T("al_vol"),
  ma20_up: T("al_ma20_up"), ma20_dn: T("al_ma20_dn"), ma60_up: T("al_ma60_up"), ma60_dn: T("al_ma60_dn"),
  rsi_gt: T("al_rsi_gt"), rsi_lt: T("al_rsi_lt"), kd_gold: T("al_kd_gold"), kd_dead: T("al_kd_dead"),
  boll_up: T("al_boll_up"), boll_dn: T("al_boll_dn") }[t] || t);
/* 指標警示的技術數值快取:每 10 分鐘用日K重算一次(站上/跌破均線等用 live 價 vs 這裡的水位) */
let alertCtx = {};
async function refreshAlertCtx() {
  const need = Object.keys(alerts).filter(s =>
    (alerts[s] || []).some(a => !["above", "below", "chg_up", "chg_dn", "vol"].includes(a.type)));
  for (const s of need) {
    const c = alertCtx[s];
    if (c && Date.now() - c.at < 600000) continue;
    try {
      const bars = await fetchBars(s, "6M");
      const closes = bars.map(b => b.c);
      const kd = kd9(bars);
      const bl = bars.length >= 20 ? bollArr(closes) : null;
      alertCtx[s] = {
        at: Date.now(),
        ma20: sma(closes, 20).pop(), ma60: sma(closes, 60).pop(),
        rsi: rsi14(closes), kGtD: kd ? kd.K > kd.D : null,
        bollUp: bl ? bl.up[bl.up.length - 1] : null, bollDn: bl ? bl.dn[bl.dn.length - 1] : null,
      };
    } catch {}
  }
}
function saveAlerts() { localStorage.setItem("md-watch-alerts", JSON.stringify(alerts)); renderBell(); scheduleSync(); }
function alertCount() { return Object.values(alerts).reduce((s, a) => s + a.length, 0); }
function renderBell() {
  const n = alertCount();
  const bn = $("bell-n");
  if (bn) { bn.style.display = n ? "block" : "none"; bn.textContent = n; }
}
function alertLabel(a) {
  return AL_NOVAL.has(a.type) ? alTypeLabel(a.type) : `${alTypeLabel(a.type)} ${a.val}`;
}
let toastTimer = null;
function showToast(msg) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.style.display = "block";
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = "none"; }, 6000);
}
function beep() {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const o = ac.createOscillator(), g = ac.createGain();
    o.connect(g); g.connect(ac.destination);
    o.frequency.value = 880; g.gain.value = 0.06;
    o.start(); o.stop(ac.currentTime + 0.18);
  } catch {}
}
function checkAlerts(q) {
  const s = q.symbol;
  const list = alerts[s];
  if (!list || !list.length) return;
  const today = new Date().toISOString().slice(0, 10);
  let dirty = false;
  for (const a of list) {
    if (a.fired === today) continue;
    let hit = false;
    const cx = alertCtx[s] || {};
    if (a.type === "above" && q.price != null) hit = q.price >= a.val;
    else if (a.type === "below" && q.price != null) hit = q.price <= a.val;
    else if (a.type === "chg_up" && q.change != null) hit = q.change >= a.val;
    else if (a.type === "chg_dn" && q.change != null) hit = q.change <= -Math.abs(a.val);
    else if (a.type === "vol" && q.volume != null) hit = q.volume >= a.val;
    else if (a.type === "ma20_up") hit = cx.ma20 != null && q.price != null && q.price >= cx.ma20;
    else if (a.type === "ma20_dn") hit = cx.ma20 != null && q.price != null && q.price <= cx.ma20;
    else if (a.type === "ma60_up") hit = cx.ma60 != null && q.price != null && q.price >= cx.ma60;
    else if (a.type === "ma60_dn") hit = cx.ma60 != null && q.price != null && q.price <= cx.ma60;
    else if (a.type === "rsi_gt") hit = cx.rsi != null && cx.rsi >= a.val;
    else if (a.type === "rsi_lt") hit = cx.rsi != null && cx.rsi <= a.val;
    else if (a.type === "kd_gold") hit = cx.kGtD === true;
    else if (a.type === "kd_dead") hit = cx.kGtD === false;
    else if (a.type === "boll_up") hit = cx.bollUp != null && q.price != null && q.price >= cx.bollUp;
    else if (a.type === "boll_dn") hit = cx.bollDn != null && q.price != null && q.price <= cx.bollDn;
    if (!hit) continue;
    a.fired = today;
    dirty = true;
    const nm = nameMap.get(s) || s;
    const msg = `🔔 ${nm} ${s}:${alertLabel(a)}(現價 ${fp(q.price)} / ${q.change == null ? "—" : q.change.toFixed(2) + "%"})`;
    showToast(msg);
    beep();
    if ("Notification" in window && Notification.permission === "granted") {
      try { new Notification("MarketDaily 看盤警示", { body: msg }); } catch {}
    }
  }
  if (dirty) { saveAlerts(); if (sheetSym === s) renderAlerts(s); }
}
function renderAlerts(sym) {
  const el = $("d-alerts");
  if (!el) return;
  const list = alerts[sym] || [];
  const today = new Date().toISOString().slice(0, 10);
  const rows = list.map((a, i) =>
    `<div class="alert-row ${a.fired === today ? "fired" : ""}">
      <span>${alertLabel(a)}${a.fired === today ? ` · ${T("al_fired")}` : ""}</span>
      <span>${a.fired === today ? `<span class="ar-x" data-re="${i}">↺ ${T("al_rearm")}</span>` : ""}<span class="ar-x" data-del="${i}">✕</span></span>
    </div>`).join("");
  const perm = ("Notification" in window && Notification.permission === "granted");
  el.innerHTML =
    (list.length ? rows : `<div class="sig-item" style="color:var(--muted)">${T("al_none")}</div>`) +
    `<div class="alert-form">
      <select id="al-type">${AL_TYPES.map(t => `<option value="${t}">${alTypeLabel(t)}</option>`).join("")}</select>
      <input id="al-val" type="number" step="any" inputmode="decimal" placeholder="數值">
      <button id="al-add">${T("al_add")}</button>
    </div>` +
    (perm ? "" : `<div class="draw-note">${T("al_noperm")}</div>`);
  el.querySelectorAll("[data-del]").forEach(b => b.onclick = () => {
    list.splice(+b.dataset.del, 1);
    if (!list.length) delete alerts[sym];
    saveAlerts(); renderAlerts(sym);
  });
  el.querySelectorAll("[data-re]").forEach(b => b.onclick = () => {
    delete list[+b.dataset.re].fired;
    saveAlerts(); renderAlerts(sym);
  });
  const sel = $("al-type"), valInp = $("al-val");
  if (sel && valInp) {
    const syncVal = () => { valInp.style.display = AL_NOVAL.has(sel.value) ? "none" : ""; };
    sel.onchange = syncVal; syncVal();
  }
  const add = $("al-add");
  if (add) add.onclick = () => {
    const ty = $("al-type").value;
    const v = parseFloat($("al-val").value);
    if (!AL_NOVAL.has(ty) && !isFinite(v)) return;
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    (alerts[sym] = alerts[sym] || []).push(AL_NOVAL.has(ty) ? { type: ty, val: 0 } : { type: ty, val: v });
    saveAlerts(); renderAlerts(sym);
    refreshAlertCtx();
  };
}
function showAllAlerts() {
  hideSigPop();
  const syms = Object.keys(alerts).filter(s => alerts[s].length);
  const el = document.createElement("div");
  el.className = "sig-pop";
  el.style.top = "70px"; el.style.right = "16px"; el.style.left = "auto";
  el.innerHTML = `<div class="sp-row" style="font-weight:800">${T("al_all_title")}(${alertCount()})</div>` +
    (syms.length ? syms.map(s => `<div class="sp-row" data-as="${s}" style="cursor:pointer">🔔 <b>${nameMap.get(s) || s}</b> ${s} — ${alerts[s].map(alertLabel).join("、")}</div>`).join("") : `<div class="sp-row" style="color:#8b8fb5">${T("al_none")}</div>`);
  document.body.appendChild(el);
  el.querySelectorAll("[data-as]").forEach(r => r.onclick = () => { el.remove(); openSheet(r.dataset.as); });
  sigPopEl = el;
}

/* ── 雲端同步(自選群組+警示)+匯入匯出 ── */
let syncTimer = null;
function scheduleSync() {
  if (!email || !pwd) return;
  if (syncTimer) clearTimeout(syncTimer);
  syncTimer = setTimeout(async () => {
    try {
      await fetch(WORKER_URL + "/watch-sync", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password: pwd, action: "save", data: { groups, alerts } }) });
      localStorage.setItem("md-watch-sync-ts", String(Date.now()));
    } catch {}
  }, 2500);
}
async function initSync() {
  if (!email || !pwd) return;
  try {
    const d = await fetch(WORKER_URL + "/watch-sync", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: pwd, action: "load" }) }).then(r => r.json());
    const localTs = parseInt(localStorage.getItem("md-watch-sync-ts") || "0", 10);
    if (d && d.ts && d.ts > localTs && (d.groups || d.alerts)) {
      if (d.groups && Object.keys(d.groups).length) { groups = d.groups; localStorage.setItem("md-watch-groups", JSON.stringify(groups)); }
      if (d.alerts && Object.keys(d.alerts).length) { alerts = d.alerts; localStorage.setItem("md-watch-alerts", JSON.stringify(alerts)); }
      localStorage.setItem("md-watch-sync-ts", String(d.ts));
      renderGroupChips(); renderBell();
      if (curTab === "watch") renderView();
    } else if (Object.keys(groups).length || Object.keys(alerts).length) {
      scheduleSync();
    }
  } catch {}
}
function exportData() {
  const blob = new Blob([JSON.stringify({ groups, alerts, exported: new Date().toISOString() }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "marketdaily-watch.json";
  a.click();
  showToast(T("exp_ok"));
}
function importData() {
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = ".json,application/json";
  inp.onchange = () => {
    const f = inp.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        const d = JSON.parse(rd.result);
        if (d.groups && typeof d.groups === "object") Object.assign(groups, d.groups);
        if (d.alerts && typeof d.alerts === "object") Object.assign(alerts, d.alerts);
        saveGroups(); saveAlerts();
        renderGroupChips(); renderView();
        showToast(T("imp_ok"));
      } catch { showToast(T("imp_bad")); }
    };
    rd.readAsText(f);
  };
  inp.click();
}

/* ── 市場總覽列(指數/匯率/商品,免費源) ── */
const MKT_SYMS = [
  ["^TWII", "加權指數"], ["^TWOII", "櫃買指數"], ["^SOX", "費城半導體"], ["^GSPC", "S&P 500"],
  ["^IXIC", "那斯達克"], ["^DJI", "道瓊"], ["^N225", "日經 225"], ["TWD=X", "美元/台幣"],
  ["BTC-USD", "比特幣"], ["GC=F", "黃金"], ["CL=F", "WTI 原油"],
];
MKT_SYMS.forEach(([s, n]) => { if (!nameMap.has(s)) nameMap.set(s, n); });
async function tickMkt() {
  const el = $("mkt-strip");
  if (!el) return;
  try {
    const d = await fetch(`${WORKER_URL}/stock-quotes?tickers=${encodeURIComponent(MKT_SYMS.map(m => m[0]).join(","))}`).then(r => r.json());
    const qs = {};
    (d.quotes || []).forEach(q => { qs[q.symbol] = q; });
    el.innerHTML = MKT_SYMS.map(([s, n]) => {
      const q = qs[s];
      if (!q || q.price == null) return "";
      const dir = q.change == null ? "neutral" : q.change >= 0 ? "up" : "down";
      return `<div class="mkt-chip" data-mk="${s}"><div class="mk-n">${n}</div>
        <div class="mk-p ${dir}">${fp(q.price)}</div>
        <div class="mk-c ${dir}">${q.change == null ? "—" : (q.change >= 0 ? "▲" : "▼") + Math.abs(q.change).toFixed(2) + "%"}</div></div>`;
    }).join("");
    el.querySelectorAll("[data-mk]").forEach(c => c.onclick = () => openSheet(c.dataset.mk));
  } catch {}
}

/* ── 選股器(官方基本面全市場) ── */
function renderScreenForm() {
  const el = $("scr-form");
  if (!el || el.dataset.built) return;
  el.dataset.built = "1";
  const inds = Object.keys(CATEGORIES);
  el.innerHTML = `
    <div><label>${T("scr_ind")}</label><select id="sc-ind"><option value="">${T("scr_all")}</option>${inds.map(i => `<option>${i}</option>`).join("")}</select></div>
    <div><label>${T("scr_pe")}</label><input id="sc-pe" type="number" step="any" placeholder="如 15"></div>
    <div><label>${T("scr_dy")}</label><input id="sc-dy" type="number" step="any" placeholder="如 4"></div>
    <div><label>${T("scr_pb")}</label><input id="sc-pb" type="number" step="any" placeholder="如 1.5"></div>
    <div><label>${T("scr_px")}</label><div style="display:flex;gap:4px"><input id="sc-p0" type="number" placeholder="低"><input id="sc-p1" type="number" placeholder="高"></div></div>
    <div><label>${T("scr_sort")}</label><select id="sc-sort"><option value="dy">${T("scr_sort_dy")}</option><option value="pe">${T("scr_sort_pe")}</option><option value="pb">${T("scr_sort_pb")}</option></select></div>
    <div style="grid-column:1/-1"><label>${T("scr_tech")}</label>
      <div class="chips" style="margin:0">${[["ma20", T("scr_ma20")], ["ma60", T("scr_ma60")], ["rsi_lo", T("scr_rsi_lo")], ["rsi_hi", T("scr_rsi_hi")], ["volx", T("scr_volx")]].map(([k, lb]) =>
        `<button type="button" class="chip" data-tf2="${k}">${lb}</button>`).join("")}</div></div>
    <button class="scr-run" id="sc-run">${T("scr_run")}</button>`;
  el.querySelectorAll("[data-tf2]").forEach(c => c.onclick = () => c.classList.toggle("on"));
  $("sc-run").onclick = runScreen;
}
let scrSyms = [];
function runScreen() {
  const ind = $("sc-ind").value, peMax = parseFloat($("sc-pe").value), dyMin = parseFloat($("sc-dy").value),
    pbMax = parseFloat($("sc-pb").value), p0 = parseFloat($("sc-p0").value), p1 = parseFloat($("sc-p1").value),
    sortBy = $("sc-sort").value;
  let out = [];
  for (const [code, f] of Object.entries(twFund)) {
    if (ind && INDUSTRY[code] !== ind) continue;
    if (isFinite(peMax) && !(f.pe != null && f.pe > 0 && f.pe <= peMax)) continue;
    if (isFinite(dyMin) && !(f.dy != null && f.dy >= dyMin)) continue;
    if (isFinite(pbMax) && !(f.pb != null && f.pb > 0 && f.pb <= pbMax)) continue;
    if (!nameMap.has(code)) continue;
    out.push([code, f]);
  }
  out.sort((a, b) => {
    const fa = a[1], fb = b[1];
    if (sortBy === "dy") return (fb.dy ?? -1) - (fa.dy ?? -1);
    if (sortBy === "pe") return (fa.pe ?? 1e9) - (fb.pe ?? 1e9);
    return (fa.pb ?? 1e9) - (fb.pb ?? 1e9);
  });
  out = out.slice(0, 120);
  scrSyms = out.map(o => o[0]);
  $("scr-cnt").textContent = out.length + (out.length >= 120 ? "+" : "");
  document.querySelector("#scr-table tbody").innerHTML = out.slice(0, 60).map(([code, f]) =>
    `<tr data-sym="${code}"><td>${nameCell(code)}</td>
     <td class="px" id="spx-${code}">—</td><td id="schg-${code}" class="neutral">—</td>
     <td>${f.pe ?? "—"}</td><td>${f.dy != null ? f.dy + "%" : "—"}</td><td class="hide-sm">${f.pb ?? "—"}</td></tr>`).join("");
  const syms = scrSyms.slice(0, 60);
  const paintScr = q => {
    quotes[q.symbol] = Object.assign(quotes[q.symbol] || {}, q);
    const tr = document.querySelector(`#scr-table tr[data-sym="${q.symbol}"]`);
    if (!tr || q.price == null) return;
    if ((isFinite(p0) && q.price < p0) || (isFinite(p1) && q.price > p1)) { tr.remove(); return; }
    const { dir, label } = fmtChg(q.change, q.symbol);
    const px = $("spx-" + q.symbol), ch = $("schg-" + q.symbol);
    if (px) { px.textContent = fp(q.price); px.className = "px " + dir; }
    if (ch) { ch.textContent = label; ch.className = dir; }
  };
  fetchFree(syms).then(qs => qs.forEach(paintScr));
  if (bridge) {
    const chunks = [];
    for (let i = 0; i < syms.length; i += 60) chunks.push(syms.slice(i, i + 60));
    chunks.forEach(c => fetch(`${bridge.url}/q?syms=${c.join(",")}&t=${encodeURIComponent(bridge.token)}`)
      .then(r => r.json()).then(d => (d.quotes || []).forEach(paintScr)).catch(() => {}));
  }
  const techOn = [...document.querySelectorAll("[data-tf2].on")].map(c => c.dataset.tf2);
  if (techOn.length) applyTechScreen(syms.slice(0, 40), techOn);
}

/* 技術條件過濾:抓 3 個月日K逐檔計算(併發 6,上限 40 檔誠實標示) */
async function applyTechScreen(syms, conds) {
  const cnt = $("scr-cnt");
  if (cnt) cnt.textContent = T("scr_calc");
  const seq = syms.slice();
  let done = 0;
  const passSet = new Set();
  const worker = async () => {
    while (seq.length) {
      const s = seq.shift();
      try {
        const bars = await fetchBars(s, "3M");
        const closes = bars.map(b => b.c);
        const last = closes[closes.length - 1];
        const m20 = sma(closes, 20).pop(), m60 = sma(closes, 60).pop();
        const r = rsi14(closes);
        const v20 = bars.length > 21 ? bars.slice(-21, -1).reduce((a, b) => a + (b.v || 0), 0) / 20 : null;
        const volx = v20 ? (bars[bars.length - 1].v || 0) / v20 : null;
        let ok = true;
        if (conds.includes("ma20") && !(m20 != null && last > m20)) ok = false;
        if (conds.includes("ma60") && !(m60 != null && last > m60)) ok = false;
        if (conds.includes("rsi_lo") && !(r != null && r < 30)) ok = false;
        if (conds.includes("rsi_hi") && !(r != null && r > 70)) ok = false;
        if (conds.includes("volx") && !(volx != null && volx >= 2)) ok = false;
        if (ok) passSet.add(s);
      } catch {}
      done++;
      if (cnt) cnt.textContent = `${T("scr_calc")} ${done}/${syms.length}`;
    }
  };
  await Promise.all([1, 2, 3, 4, 5, 6].map(worker));
  document.querySelectorAll("#scr-table tbody tr[data-sym]").forEach(tr => {
    if (!passSet.has(tr.dataset.sym)) tr.remove();
  });
  const left = document.querySelectorAll("#scr-table tbody tr").length;
  if (cnt) cnt.textContent = `${left}(技術條件僅套用前40檔)`;
}

/* ── 產業熱力圖(TWSE 類股指數,收盤) ── */
let heatCache = null;
async function renderHeat() {
  const el = $("heat-grid");
  if (!el) return;
  try {
    if (!heatCache || Date.now() - heatCache.at > 1800000) {
      const d = await fetch(WORKER_URL + "/tw-sectors").then(r => r.json());
      heatCache = { at: Date.now(), d };
    }
    const { date, sectors } = heatCache.d;
    if (!sectors || !sectors.length) { el.innerHTML = ""; return; }
    const hd = $("heat-date");
    if (hd) hd.textContent = `${T("heat_src")}${date ? " · " + date : ""}`;
    const maxAbs = Math.max(...sectors.map(s => Math.abs(s.chg)), 0.1);
    el.innerHTML = sectors.slice().sort((a, b) => b.chg - a.chg).map(s => {
      const a = Math.min(Math.abs(s.chg) / maxAbs, 1);
      const bg = s.chg > 0 ? `rgba(239,68,68,${0.12 + a * 0.5})` : s.chg < 0 ? `rgba(34,197,94,${0.12 + a * 0.5})` : "rgba(255,255,255,.05)";
      return `<div class="heat-cell" data-hs="${s.n}" style="background:${bg}">
        <div class="hc-n">${s.n}</div>
        <div class="hc-c">${s.chg > 0 ? "+" : ""}${s.chg.toFixed(2)}%</div>
        <div class="hc-v">${s.v.toLocaleString()}</div></div>`;
    }).join("");
    el.querySelectorAll("[data-hs]").forEach(c => c.onclick = () => {
      const n = c.dataset.hs;
      const cats = Object.keys(CATEGORIES);
      const hit = cats.find(k => k.replace(/(工業|事業|業)$/, "") === n) || cats.find(k => k.includes(n)) || cats.find(k => n.includes(k.replace(/(工業|事業|業)$/, "")));
      if (!hit) return;
      curTab = "cats"; curCat = hit; catPage = 1;
      renderTabs(); renderCatSel();
      const sel = $("cat-sel");
      if (sel) sel.value = hit;
      renderView();
    });
  } catch { el.innerHTML = ""; }
}

/* ── 市場新聞頁 ── */
let curNewsCat = "headline";
let mktNewsCache = {};
const NEWS_CATS = [["headline", "nw_headline"], ["tw_stock", "nw_tw"], ["wd_stock", "nw_wd"], ["forex", "nw_forex"], ["future", "nw_future"]];
function renderNewsChips() {
  const el = $("news-chips");
  if (!el) return;
  el.innerHTML = NEWS_CATS.map(([k, lk]) =>
    `<button class="chip ${curNewsCat === k ? "on" : ""}" data-nc="${k}">${T(lk)}</button>`).join("");
  el.querySelectorAll(".chip").forEach(c => c.onclick = () => { curNewsCat = c.dataset.nc; renderNewsChips(); renderNewsTab(); });
}
async function renderNewsTab() {
  const el = $("news-list");
  if (!el) return;
  el.innerHTML = `<div class="sig-item" style="color:var(--muted)">${T("loading")}</div>`;
  try {
    let items = mktNewsCache[curNewsCat] && Date.now() - mktNewsCache[curNewsCat].at < 300000 ? mktNewsCache[curNewsCat].items : null;
    if (!items) {
      const d = await fetch(`${WORKER_URL}/market-news?cat=${curNewsCat}`).then(r => r.json());
      items = d.news || [];
      mktNewsCache[curNewsCat] = { at: Date.now(), items };
    }
    const ago = ts => {
      if (!ts) return "";
      const h = (Date.now() / 1000 - ts) / 3600;
      return h < 1 ? `${Math.max(Math.round(h * 60), 1)}m` : h < 24 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`;
    };
    el.innerHTML = items.length ? items.map(n =>
      `<a class="news-item" href="${n.url}" target="_blank" rel="noopener">
        <div class="news-t">${n.title}</div><div class="news-m">${n.source || ""} · ${ago(n.ts)}</div></a>`).join("")
      : `<div class="sig-item" style="color:var(--muted)">${T("news_none")}</div>`;
  } catch { el.innerHTML = ""; }
}

function closeSheet() {
  $("sheet").classList.remove("open"); $("sheet-bg").classList.remove("open");
  document.body.classList.remove("sheet-open");
  if (replay) stopReplay();
  drawTool = null; drawPend = null;
  sheetSym = null;
  if (depthTimer) { clearInterval(depthTimer); depthTimer = null; }
  if (ticksTimer) { clearInterval(ticksTimer); ticksTimer = null; }
}
let ticksTimer = null;

function openSheet(sym) {
  if (depthTimer) { clearInterval(depthTimer); depthTimer = null; }
  if (ticksTimer) { clearInterval(ticksTimer); ticksTimer = null; }
  if (replay) stopReplay();
  chartView = null; cmpSyms = []; cmpData = {}; drawTool = null; drawPend = null;
  sheetSym = sym;
  curTf = "6M";
  const q = quotes[sym] || {};
  const nm = nameMap.get(sym) || sym;
  const ind = INDUSTRY[sym] || "";
  const sigs = signals[sym] || [];
  const { dir, label } = fmtChg(q.change, sym);
  const gChips = Object.keys(groups).map(g => {
    const on = (groups[g] || []).includes(sym);
    return `<button class="chip ${on ? "on" : ""}" data-sg="${g}">${on ? "✓ " : ""}${g}</button>`;
  }).join("") + `<button class="chip" data-sg="__new">${T("grp_new")}</button>`;
  $("sheet").innerHTML = `
    <div class="d-head">
      <div><span class="d-name">${nm}</span><span class="d-code">${sym}</span>
        <div class="d-ind">${ind}${sigs.length ? " " + sigDot(sym) : ""}</div></div>
      <div style="display:flex;align-items:flex-start;gap:12px">
        <div class="d-price"><div class="d-px ${dir}" id="d-px">${fp(q.price)}</div>
          <div class="d-chg ${dir}" id="d-chg">${label}</div></div>
        <button class="sheet-x" id="sheet-x" title="關閉">✕</button>
      </div>
    </div>
    <div class="d-quote-strip" id="d-strip">
      ${q.open != null ? `<span>開 <b>${fp(q.open)}</b></span>` : ""}
      ${q.high != null ? `<span>高 <b>${fp(q.high)}</b></span><span>低 <b>${fp(q.low)}</b></span>` : ""}
      ${q.bid != null ? `<span>買 <b>${fp(q.bid)}</b></span><span>賣 <b>${fp(q.ask)}</b></span>` : ""}
      ${q.volume != null ? `<span>量 <b>${(q.volume || 0).toLocaleString()}</b></span>` : ""}
    </div>
    <div id="d-depth-wrap" style="display:none">
      <div class="g-title">${T("sec_depth")}</div>
      <div class="depth-wrap" id="d-depth"></div>
    </div>
    <div id="d-ticks-wrap" style="display:none">
      <div class="g-title">${T("sec_ticks")}</div>
      <div id="d-ticks"></div>
    </div>
    <div class="tf-chips" id="tf-chips">${tfChipsHtml(sym)}</div>
    <div class="tf-chips" id="opt-chips">
      <button class="tf ${chartOpt.boll ? "on" : ""}" data-opt="boll">${T("boll_lbl")}</button>
      <button class="tf ${chartOpt.ema ? "on" : ""}" data-ov="ema">EMA</button>
      <button class="tf ${chartOpt.sar ? "on" : ""}" data-ov="sar">SAR</button>
      <button class="tf ${chartOpt.ich ? "on" : ""}" data-ov="ich">一目</button>
      ${isTWSym(sym) && bridge ? `<button class="tf ${chartOpt.vwap ? "on" : ""}" data-ov="vwap">VWAP</button>` : ""}
      <span style="width:8px"></span>
      ${[["vol", T("sub_vol")], ["macd", "MACD"], ["kd", "KD"], ["rsi", "RSI"], ["wpr", "W%R"], ["cci", "CCI"]].map(([k, lb]) =>
        `<button class="tf ${chartOpt.sub === k ? "on" : ""}" data-sub="${k}">${lb}</button>`).join("")}
    </div>
    <div class="tf-chips ct-row" id="ct-chips">
      ${[["candle", T("ct_candle")], ["ha", T("ct_ha")], ["bar", T("ct_bar")], ["area", T("ct_area")]].map(([k, lb]) =>
        `<button class="tf ${chartOpt.ctype === k ? "on" : ""}" data-ct="${k}">${lb}</button>`).join("")}
      <button class="tf ${chartOpt.log ? "on" : ""}" data-log="1">${T("log_lbl")}</button>
      <span style="width:8px"></span>
      <button class="tf" data-cmp="1">${T("cmp_lbl")}</button>
      <button class="tf" data-replay="1">${T("replay_lbl")}</button>
      <span style="width:8px"></span>
      ${[["l", "╱"], ["h", "─"], ["f", "𝄃"], ["t", "T"], ["erase", "⌫"]].map(([k, lb]) =>
        `<button class="tf" data-tool="${k}" title="${{ l: T("tool_trend"), h: T("tool_hline"), f: T("tool_fib"), t: T("tool_text"), erase: T("tool_erase") }[k]}">${lb}</button>`).join("")}
      <button class="tf" data-dclear="1" title="${T("tool_clear")}">🗑</button>
      <span style="width:8px"></span>
      <button class="tf" data-fs="1">${T("fs_lbl")}</button>
      <button class="tf" data-snap="1">${T("snap_lbl")}</button>
    </div>
    <div class="tf-chips" id="replay-bar" style="display:none">
      <button class="tf" id="rp-toggle">⏸</button>
      ${[1, 3, 10].map(s => `<button class="tf rp-speed ${s === 1 ? "on" : ""}" data-spd="${s}">${s}x</button>`).join("")}
      <input id="rp-slider" type="range" min="10" max="100" value="10" style="flex:1;min-width:80px">
      <button class="tf" id="rp-exit">${T("replay_exit")}</button>
    </div>
    <div class="ohlc-strip" id="d-ohlc"></div>
    <div id="chart-box"><canvas id="d-chart"></canvas></div>
    <div class="chart-note">MA5 <span style="color:#fbbf24">─</span> MA20 <span style="color:#818cf8">─</span> MA60 <span style="color:#38bdf8">─</span> · ${T("vol_note")}</div>
    <div class="g-title">${T("sec_tech")}</div>
    <div class="ti-grid" id="d-tech"></div>
    <div class="g-title">${T("sec_diag")}</div>
    <div id="d-diag"></div>
    ${isTWSym(sym) ? `<div class="g-title">${T("sec_chips")}</div><div id="d-chips"><div class="sig-item" style="color:var(--muted)">${T("loading")}</div></div>` : ""}
    <div class="g-title">${T("sec_fund")}</div>
    <div class="ti-grid fd-grid" id="d-fund"></div>
    ${isTWSym(sym) ? `<div class="g-title">${T("sec_findeep")}</div><div id="d-findeep"><div class="sig-item" style="color:var(--muted)">${T("loading")}</div></div>` : ""}
    <div class="g-title">${T("sec_prof")}</div>
    <div id="d-prof"></div>
    <div class="g-title" id="d-chain-h">${T("sec_chain")}</div>
    <div id="d-chain"></div>
    <div id="d-chain-ev"></div>
    <div class="g-title">${T("sec_news")}</div>
    <div id="d-news"><div class="sig-item" style="color:var(--muted)">${T("loading")}</div></div>
    <div class="g-title">${T("sheet_sigs")}</div>
    ${sigs.length ? sigs.map(s => `<div class="sig-item"><div class="src">${s.level === "red" ? "🔴" : "🟡"} ${s.source}</div>${s.signal}</div>`).join("")
      : `<div class="sig-item" style="color:var(--muted)">${T("sheet_nosig")}</div>`}
    <div class="g-title">${T("sec_alerts")}</div>
    <div id="d-alerts"></div>
    <div class="g-title">${T("sheet_groups")}</div>
    <div class="g-row">${gChips}</div>`;
  $("opt-chips").querySelectorAll("[data-opt]").forEach(b => b.onclick = () => {
    chartOpt.boll = !chartOpt.boll; saveChartOpt();
    b.classList.toggle("on", chartOpt.boll);
    renderDetailChart(sym);
  });
  $("opt-chips").querySelectorAll("[data-sub]").forEach(b => b.onclick = () => {
    chartOpt.sub = b.dataset.sub; saveChartOpt();
    $("opt-chips").querySelectorAll("[data-sub]").forEach(x => x.classList.toggle("on", x.dataset.sub === chartOpt.sub));
    renderDetailChart(sym);
  });
  $("opt-chips").querySelectorAll("[data-ov]").forEach(b => b.onclick = () => {
    const k = b.dataset.ov;
    chartOpt[k] = !chartOpt[k]; saveChartOpt();
    b.classList.toggle("on", chartOpt[k]);
    renderDetailChart(sym);
  });
  $("ct-chips").querySelectorAll("[data-ct]").forEach(b => b.onclick = () => {
    chartOpt.ctype = b.dataset.ct; saveChartOpt();
    $("ct-chips").querySelectorAll("[data-ct]").forEach(x => x.classList.toggle("on", x.dataset.ct === chartOpt.ctype));
    renderDetailChart(sym);
  });
  $("ct-chips").querySelector("[data-log]").onclick = e => {
    chartOpt.log = !chartOpt.log; saveChartOpt();
    e.currentTarget.classList.toggle("on", chartOpt.log);
    renderDetailChart(sym);
  };
  $("ct-chips").querySelector("[data-cmp]").onclick = async e => {
    const inp = prompt(T("cmp_prompt"), cmpSyms.join(","));
    if (inp === null) return;
    cmpSyms = inp.split(",").map(s => s.trim().toUpperCase()).filter(Boolean).slice(0, 3);
    e.currentTarget.classList.toggle("on", cmpSyms.length > 0);
    for (const cs of cmpSyms) {
      try { cmpData[cs] = await fetchBars(cs, curTf); } catch { cmpData[cs] = []; }
    }
    renderDetailChart(sym);
  };
  $("ct-chips").querySelectorAll("[data-tool]").forEach(b => b.onclick = () => {
    drawTool = drawTool === b.dataset.tool ? null : b.dataset.tool;
    drawPend = null;
    $("ct-chips").querySelectorAll("[data-tool]").forEach(x => x.classList.toggle("on", x.dataset.tool === drawTool));
    if (drawTool) showToast(T("draw_hint"));
  });
  $("ct-chips").querySelector("[data-dclear]").onclick = () => {
    if (drawings[sym] && drawings[sym].length && confirm(T("tool_clear") + "?")) {
      delete drawings[sym]; saveDrawings(); redrawChart();
    }
  };
  $("ct-chips").querySelector("[data-fs]").onclick = () => {
    const box = $("chart-box");
    if (document.fullscreenElement) document.exitFullscreen();
    else if (box.requestFullscreen) box.requestFullscreen();
  };
  $("ct-chips").querySelector("[data-snap]").onclick = () => {
    const cv = $("d-chart");
    if (!cv) return;
    cv.toBlob(bl => {
      if (!bl) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(bl);
      a.download = `${sym}-${curTf}-${new Date().toISOString().slice(0, 10)}.png`;
      a.click();
    });
  };
  $("ct-chips").querySelector("[data-replay]").onclick = () => startReplay(sym);
  $("rp-exit").onclick = stopReplay;
  $("rp-toggle").onclick = () => {
    if (!replay) return;
    replay.paused = !replay.paused;
    $("rp-toggle").textContent = replay.paused ? "▶" : "⏸";
  };
  $("sheet").querySelectorAll(".rp-speed").forEach(b => b.onclick = () => {
    if (!replay) return;
    replay.speed = +b.dataset.spd;
    $("sheet").querySelectorAll(".rp-speed").forEach(x => x.classList.toggle("on", +x.dataset.spd === replay.speed));
  });
  $("rp-slider").oninput = () => {
    if (!replay || !curChart) return;
    replay.idx = Math.round(curChart.bars.length * (+$("rp-slider").value) / 100);
    redrawChart();
  };
  $("tf-chips").querySelectorAll(".tf").forEach(b => b.onclick = async () => {
    curTf = b.dataset.tf;
    chartView = null;
    if (replay) stopReplay();
    $("tf-chips").querySelectorAll(".tf").forEach(x => x.classList.toggle("on", x.dataset.tf === curTf));
    for (const cs of cmpSyms) {
      try { cmpData[cs] = await fetchBars(cs, curTf); } catch { cmpData[cs] = []; }
    }
    renderDetailChart(sym);
  });
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
  document.body.classList.add("sheet-open");
  const xb = $("sheet-x");
  if (xb) xb.onclick = closeSheet;
  $("sheet").scrollTop = 0;
  renderDetailChart(sym);
  renderTech(sym);
  renderFund(sym).then(() => { if (sheetSym === sym) { renderProfile(sym); if (!isTWSym(sym)) renderChain(sym); } });
  renderChain(sym);
  renderNews(sym);
  renderAlerts(sym);
  if (isTWSym(sym)) { chipsFactors[sym] = chipsFactors[sym] || []; renderChips(sym); renderFinDeep(sym); }
  if (bridge && isTWSym(sym)) {
    renderDepth(sym);
    depthTimer = setInterval(() => renderDepth(sym), 3000);
    renderTicks(sym);
    ticksTimer = setInterval(() => renderTicks(sym), 3000);
  }
  if (!quotes[sym]) {
    fetchFree([sym]).then(qs => { qs.forEach(paint); if (sheetSym === sym) refreshSheetHead(sym); });
    if (bridge && isTWSym(sym)) {
      fetch(`${bridge.url}/q?syms=${sym}&t=${encodeURIComponent(bridge.token)}`)
        .then(r => r.json()).then(d => { (d.quotes || []).forEach(paint); if (sheetSym === sym) refreshSheetHead(sym); }).catch(() => {});
    }
  }
}

function refreshSheetHead(sym) {
  const q = quotes[sym] || {};
  const { dir, label } = fmtChg(q.change, sym);
  const px = $("d-px"), chg = $("d-chg");
  if (px) { px.textContent = fp(q.price); px.className = "d-px " + dir; }
  if (chg) { chg.textContent = label; chg.className = "d-chg " + dir; }
}
$("sheet-bg").onclick = closeSheet;

document.addEventListener("click", e => {
  const tr = e.target.closest("tbody tr[data-sym]");
  if (tr) openSheet(tr.dataset.sym);
});

/* ── 訊號燈說明 popover(2026-07-22):點/tap 紅黃點 → 白話講這顆燈是什麼訊號 ──
   capture 層攔截:row 的 openSheet 綁在 bubble 層,stopPropagation 才不會點燈誤開個股詳情 */
let sigPopEl = null;
function hideSigPop() { if (sigPopEl) { sigPopEl.remove(); sigPopEl = null; } }
function showSigPop(dot, sym) {
  hideSigPop();
  const items = signals[sym] || [];
  if (!items.length) return;
  const el = document.createElement("div");
  el.className = "sig-pop";
  el.innerHTML = items.map(i =>
    `<div class="sp-row"><span class="sig-dot ${i.level === "red" ? "red" : "yellow"}"></span>${escAttr(i.signal || i.source || "")}</div>`).join("")
    + `<div class="sp-foot">${T("sig_pop_foot")}${sigDate ? ` · ${sigDate}` : ""}</div>`;
  document.body.appendChild(el);
  const r = dot.getBoundingClientRect();
  el.style.top = `${Math.min(window.innerHeight - el.offsetHeight - 12, r.bottom + 8)}px`;
  el.style.left = `${Math.max(8, Math.min(r.left - 10, window.innerWidth - el.offsetWidth - 8))}px`;
  sigPopEl = el;
}
document.addEventListener("click", e => {
  const d = e.target.closest(".sig-dot[data-sig]");
  if (d) { e.stopPropagation(); e.preventDefault(); showSigPop(d, d.dataset.sig); return; }
  hideSigPop();
}, true);

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
    `<div class="sr-item" data-s="${c}"><span class="c">${sigDot(c)}${n || c}</span><span class="n">${c}${INDUSTRY[c] ? " · " + INDUSTRY[c] : ""}</span></div>`).join("");
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
    // 可轉債分類:報價僅永豐 bridge 有(TSE/OTC/OES 逐所解析),免費源無 CB → 只在 live 模式亮
    try {
      if (typeof TW_CB !== "undefined" && TW_CB.length) {
        THEMES[T("cb_theme")] = TW_CB.map(([c]) => c);
        TW_CB.forEach(([c, n]) => { if (!nameMap.has(c)) nameMap.set(c, n); if (!INDUSTRY[c]) INDUSTRY[c] = "可轉債"; });
        renderCatSel();
      }
    } catch {}
    tickLive(); tickPositions();
  } catch {}
}

async function init() {
  /* 分析師 guest 模式(analyst.marketdaily.ai 過來帶 ?src=analyst):免會員登入,
     走免費延遲源;sessionStorage 記住,站內換頁不掉。合規不變:guest 永遠拿不到 bridge 即時源 */
  /* 看盤頁預設免登入直接可用(guest):未登入只影響「自選雲端同步/持股偏好」,
     用一條小提示取代整頁登入牆(擋牆=分析師與新用戶第一眼死路,2026-07-22 Delvin 截圖打槍)。
     合規不變:guest 永遠只有免費延遲源,bridge 即時源仍需 admin/白名單 token */
  function guestHint() {
    const g = $("gate");
    g.innerHTML = '💡 未登入:自選清單只存在這台裝置。<a href="dashboard.html">登入即可雲端同步 →</a>';
    g.style.display = "block";
  }
  if (!email || !pwd) {
    guestHint(); prefsTw = []; prefsUs = [];
  } else {
    let data = null;
    try {
      const r = await fetch(WORKER_URL + "/get-preferences", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: pwd }) });
      data = await r.json();
      if (r.status === 403 || data.error) data = null;
    } catch { data = null; }
    if (!data) {
      guestHint(); prefsTw = []; prefsUs = [];
    } else {
      prefsTw = data.tw_stocks || [];
      prefsUs = data.us_stocks || [];
    }
  }
  $("app").style.display = "block";
  document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
    curTab = b.dataset.tab; catPage = 1; renderTabs(); renderView();
  });
  $("tw-more").onclick = () => { catPage++; renderView(); };
  renderTabs(); renderGroupChips(); renderCatSel(); renderRankChips(); renderSortChips();
  bindSortHeaders(); renderSortHeaders();
  renderBell();
  const bell = $("bell");
  if (bell) bell.onclick = e => { e.stopPropagation(); sigPopEl ? hideSigPop() : showAllAlerts(); };
  loadTwFund();
  await loadSignals();
  renderView();
  startSched();
  initBridge();
  initSync().then(() => refreshAlertCtx());
  tickMkt();
  document.addEventListener("fullscreenchange", () => setTimeout(redrawChart, 80));
  /* 桌機 dock:視窗大小改變→canvas 寬度隨父容器變,重畫一次;Esc 關閉詳情面板 */
  let dockRszTimer = null;
  window.addEventListener("resize", () => {
    if (!sheetSym) return;
    if (dockRszTimer) clearTimeout(dockRszTimer);
    dockRszTimer = setTimeout(redrawChart, 180);
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && sheetSym) closeSheet(); });
  /* ?c=<代碼> 深連結（desk 工作台 analyst.marketdaily.ai 的 📈 鈕）：init 完成後自動開
     該股詳情 sheet。白名單字元才收——sym 會進 openSheet 的 innerHTML，不吃任意字串 */
  const dlSym = (new URLSearchParams(location.search).get("c") || "").trim().toUpperCase();
  if (dlSym && /^[A-Z0-9.]{1,12}$/.test(dlSym)) openSheet(dlSym);
}
init();
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshNow(); });
