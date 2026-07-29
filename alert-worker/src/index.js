// MarketDaily — Premium 即時重大新聞提醒 alert-worker(通道 = 自有 Web Push,LINE 已於 2026-07-06 全面退役)
// 每 2 分鐘:抓新聞 → 去重 → 規則粗篩 → 比對 Premium 持股 → AI 嚴重度 → web push 推播。
// 設計規格:specs/2026-05-22-premium-realtime-line-alerts-design.md(其中 LINE 段落已作廢)

import { fetchNews } from "./news_source.js";
import { displayName } from "./stock_names.js";
import { fetchPoliticalSignals, formatPoliticalMsg, analyzePoliticalPosts } from "./political_source.js";

const SEVERITY_THRESHOLD = 7;          // 已發生/已公告事件的推播門檻(新聞管線共用,勿隨意動)
const SPECULATIVE_THRESHOLD = 9;       // 傳言/觀點/臆測文門檻拉高,避免「If…will…」評論文當 🚨重大消息 轟炸
// 政治/總經「已宣布政策行動」單獨的推播門檻(比新聞的 7 低一階)——政治事件本質大盤級,
// 用戶要求「大盤級推全體」後,達標的政策行動一律推全體訂閱者(見 runPoliticalPipeline targets)。
// 言論/預告(statement)仍沿用 SPECULATIVE_THRESHOLD(9)高標防嘴砲轟炸;每日上限 4 則另做安全網。
const POLITICAL_ACTION_THRESHOLD = 6;
const DAILY_CAP = 5;
const MAX_AGE_HOURS = 24;     // 超過此時數的新聞視為舊聞,不評分、不推(即時提醒只推新鮮事)
const PRESCORE_FLOOR = 40;    // 規則預評分低於此值直接跳過 AI;調高=更省 AI,調低=更不漏新聞
const CLUSTER_WINDOW_MS = 6 * 3600 * 1000;
const LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push";
const SEEN_TTL = 48 * 3600;
const PUSHED_TTL = 48 * 3600;
const COUNT_TTL = 26 * 3600;

// 規則粗篩:重大事件關鍵字分組,命中才往下走。type 也用於 story cluster 去重。
// 含中英文關鍵字 — 中文台股新聞(UDN/LTN/經濟日報)也要能被分類,否則永遠不會進 AI 推播 pipeline。
const EVENT_RULES = [
  { type: "earnings", kw: [
    "earnings", "beats estimates", "misses estimates", "quarterly results", "profit jump", "profit drop",
    "財報", "營收", "季報", "法說會", "獲利", "EPS", "業績"
  ]},
  { type: "guidance", kw: [
    "guidance", "outlook", "forecast", "profit warning", "cuts target", "lowers", "slashes",
    "展望", "預測", "財測", "下修", "上修", "上調", "下調", "砍目標", "獲利警訊"
  ]},
  { type: "mna", kw: [
    "acquire", "acquisition", "merger", "buyout", "takeover", "to buy ", "agrees to buy",
    "併購", "收購", "合併", "入股", "收購案", "敵意併購"
  ]},
  { type: "regulatory", kw: [
    "fda", "approval", "recall", "antitrust", "investigation", "probe", "subpoena", "regulator", "fines",
    "公平會", "金管會", "證交所", "調查", "罰款", "違規", "停牌", "處分"
  ]},
  { type: "legal", kw: [
    "lawsuit", "sues", "sued", "settlement", "verdict", "court ruling",
    "訴訟", "提告", "敗訴", "勝訴", "判決", "和解"
  ]},
  { type: "trading", kw: [
    "halt", "halted", "suspended", "plunge", "soar", "surge", "tumble", "crash", "spike", "sell-off",
    "跳水", "暴跌", "暴漲", "飆漲", "重挫", "急殺", "噴出", "漲停", "跌停", "亮燈漲停", "崩跌"
  ]},
  { type: "distress", kw: [
    "bankruptcy", "chapter 11", "insolvency", "default", "delist",
    "破產", "重整", "倒閉", "下市", "違約", "聲請破產"
  ]},
  { type: "rating", kw: [
    "downgrade", "upgrade", "price target", "initiated coverage", "cut to",
    "調降", "調升", "評等", "目標價", "投資評等", "買進評等", "賣出評等"
  ]},
  { type: "leadership", kw: [
    "ceo", "chief executive", "resign", "steps down", "ousted", "appoints", "fired",
    "執行長", "董事長", "請辭", "下台", "任命", "卸任", "接班"
  ]},
  { type: "incident", kw: [
    "data breach", "hacked", "outage", "strike", "production halt",
    "駭客", "資料外洩", "停工", "罷工", "斷鏈", "工安", "停產"
  ]},
  // 政治/政策市場事件:川普等政治人物的市場級發言幾分鐘內就會變 Reuters/CNBC 頭條,
  // 走既有新聞管線即可推,不依賴 xAI key(Grok x_search 直抓 X 的版本見 political_source.js)。
  // 觀點/喊話類靠既有 speculative 降級門檻(9)把關,不會每條川普嘴砲都推。
  { type: "political", kw: [
    "trump", "white house", "tariff", "executive order", "export control", "export ban", "sanction",
    "trade war", "trade deal", "rate decision", "rate cut", "rate hike", "fomc", "fed chair", "powell",
    "treasury secretary", "chip ban", "chips act",
    "川普", "白宮", "關稅", "行政命令", "出口管制", "禁令", "制裁", "貿易戰", "貿易協議",
    "聯準會", "降息", "升息", "利率決議", "鮑爾", "晶片禁令"
  ]},
  // AI / 半導體 產業級題材:多半不會點名某支持股,但透過供應鏈(晶圓代工/封測/設備/IP)
  // 傳導到台美股一大票標的 → 走第二層(second-order)AI 比對推給真正被波及的持有者。
  { type: "ai_tech", kw: [
    "artificial intelligence", "generative ai", "large language model", "nvidia", "gpu", "accelerator",
    "semiconductor", "chip", "chipmaker", "foundry", "wafer", "node", "euv", "data center", "data centre",
    "cloud capex", "openai", "anthropic", "tsmc", "hbm", "advanced packaging",
    "人工智慧", "生成式", "半導體", "晶片", "晶圓", "代工", "先進製程", "封測", "設備廠", "資料中心",
    "算力", "輝達", "台積電", "記憶體", "伺服器", "先進封裝"
  ]},
  // 總經 / 大盤級:利率、通膨、原物料、匯率、就業、景氣 —— 影響所有人的持倉方向。
  { type: "macro", kw: [
    "inflation", "cpi", "ppi", "gdp", "recession", "jobs report", "payrolls", "unemployment",
    "yield", "treasury yield", "dollar index", "crude", "oil price", "opec", "gold price",
    "consumer confidence", "soft landing", "hard landing",
    "通膨", "通貨膨脹", "消費者物價", "景氣", "衰退", "非農", "就業數據", "失業率",
    "公債殖利率", "美元指數", "油價", "原油", "金價", "軟著陸", "硬著陸"
  ]},
  // 供應鏈事件:缺貨、斷鏈、產能、天災/地緣中斷 —— 透過上下游打到持股。
  { type: "supply_chain", kw: [
    "shortage", "supply chain", "supply disruption", "capacity", "production cut", "output cut",
    "backlog", "lead time", "raw material", "component shortage", "logistics",
    "缺貨", "供應鏈", "斷鏈", "產能", "減產", "缺料", "料況", "交期", "原物料", "物流中斷"
  ]},
];

// 各事件類型的平均重大度權重 —— 規則預評分用,只擋明顯偏弱的,真正嚴重度仍交給 AI 判。
const EVENT_WEIGHT = {
  distress: 95, mna: 88, guidance: 82, regulatory: 76, earnings: 72,
  political: 70, ai_tech: 68, macro: 66, incident: 66, supply_chain: 64,
  legal: 62, leadership: 56, rating: 48, trading: 46,
};

// 廣域衝擊類型:多半不直接點名個股,但會透過產業鏈/供應鏈/總經傳導打到持股。
// 這幾類若沒有直接持有者 → 走第二層 AI 比對(拿用戶持股清單判斷誰被波及),而不是直接丟掉。
const BROAD_TYPES = new Set(["political", "ai_tech", "macro", "supply_chain", "regulatory"]);

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// 台灣日期(UTC+8),用於每日推播上限的 key。
function twDate(d = new Date()) {
  return new Date(d.getTime() + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

// 詞界比對:英文 kw 用 \b 避免 "issues" 命中 "sues";中文沒 word boundary,
// 直接 substring 比對(中文字本身就是 token,不會誤判)。
const EVENT_MATCHERS = EVENT_RULES.map((r) => {
  const en = r.kw.filter(k => /^[\x00-\x7F]+$/.test(k));  // 純 ASCII
  const zh = r.kw.filter(k => !/^[\x00-\x7F]+$/.test(k)); // 含中文
  const regexes = [];
  if (en.length) regexes.push(new RegExp("\\b(?:" + en.map(k => k.trim()).join("|") + ")", "i"));
  if (zh.length) regexes.push(new RegExp("(?:" + zh.map(k => k.trim()).join("|") + ")"));
  return {
    type: r.type,
    re: { test: (s) => regexes.some(re => re.test(s)) },
  };
});

function classify(text) {
  const t = text || "";
  for (const m of EVENT_MATCHERS) {
    if (m.re.test(t)) return m.type;
  }
  return null;
}

// 是否為「廣域衝擊」新聞 —— 獨立於 classify() 的單一 first-match 判定:
// 只要文字命中任一 BROAD_TYPES 規則(AI/晶片/總經/政策/供應鏈)就算,
// 避免「油價飆漲」被 trading 先接走、失去第二層傳導比對(2026-07-01 修)。
function matchesBroad(text) {
  const t = text || "";
  return EVENT_MATCHERS.some((m) => BROAD_TYPES.has(m.type) && m.re.test(t));
}

// 臆測/觀點標記:標題出現條件式(If…will…)、傳言或評論語氣 → 視為「非已發生事件」,
// 推播門檻拉到 SPECULATIVE_THRESHOLD、標籤改「觀點／傳言」。
// 解 2026-05-31 出包:Yahoo「If Elon Musk merges SpaceX with Tesla he'll create a $3.4tn behemoth」
// 這種假設推演評論文被掛 🚨重大消息 推給訂閱者,稀釋紅色驚嘆號的信任(狼來了)。
const SPECULATIVE_MARKERS = [
  /\bif\s+\w+/i, /\bcould\b/i, /\bwould\b/i, /\bmight\b/i, /\bmay\s+\w+/i,
  /\brumor|speculat|reportedly|allegedly|what if\b/i,
  /\bhere'?s why\b/i, /\bopinion\b|\banalysis\b|\bcolumn\b/i,
  /^\s*(why|how|is|are|will|should|can|does|what|could)\b[^?]*\?/i, // 問句式標題
  /傳聞|傳言|據傳|市場傳|盛傳|揣測|猜測|臆測|傳出|據報導稱/,
  /專欄|評論|觀點|社論|分析師認為|外媒指/,
  /假如|倘若|若.{0,8}(將|恐|可能|有望)/,
];

function isSpeculative(text) {
  const t = text || "";
  return SPECULATIVE_MARKERS.some((re) => re.test(t));
}

function clusterKey(ticker, eventType, publishedAt) {
  let ms = Date.parse(publishedAt);
  if (isNaN(ms)) ms = Date.now();
  return `${ticker}:${eventType}:${Math.floor(ms / CLUSTER_WINDOW_MS)}`;
}

// 新聞距今幾小時(無法解析時間 → 0,當作新的)。
function newsAgeHours(publishedAt) {
  const ms = Date.parse(publishedAt);
  if (isNaN(ms)) return 0;
  return (Date.now() - ms) / 3600000;
}

// 規則預評分(0-100,不花 AI):事件權重 × 時效新鮮度。
// 6 小時內滿分,之後線性衰減,到 MAX_AGE_HOURS 時為 0.6 倍。
function ruleScore(eventType, ageHours) {
  const base = EVENT_WEIGHT[eventType] || 50;
  const decay = Math.min(1, Math.max(0, ageHours - 6) / (MAX_AGE_HOURS - 6));
  return Math.round(base * (1 - 0.4 * decay));
}

// 列出所有開了 web push 的用戶與持股。(訂閱者 LINE 推播已移除,通道只剩 web push)
// 合規結構(COMPLIANCE_STRUCTURE.md):推播含個股操作傾向=個股分析內容,不得付費限定,
// 對全體 push 用戶開放;函數名保留 premiumRecipients 免動所有 call site,語意=全體收件人。
async function premiumRecipients(env) {
  const map = new Map(); // email -> {email, pushSubs, holdings}
  async function ensure(email) {
    if (map.has(email)) return map.get(email);
    let holdings = new Set();
    const raw = await env.USER_PREFS.get(email);
    if (raw) {
      try {
        const p = JSON.parse(raw);
        for (const s of [...(p.us_stocks || []), ...(p.tw_stocks || [])]) {
          holdings.add(String(s).trim().toUpperCase());
        }
      } catch {}
    }
    const r = { email, pushSubs: [], holdings };
    map.set(email, r);
    return r;
  }
  async function scan(prefix, apply) {
    let cursor;
    do {
      const page = await env.USER_PREFS.list({ prefix, cursor });
      for (const k of page.keys) {
        const email = k.name.slice(prefix.length);
        const r = await ensure(email);
        if (r) await apply(r, k.name);
      }
      cursor = page.list_complete ? null : page.cursor;
    } while (cursor);
  }
  await scan("pushsub:", async (r, key) => {
    try { const p = JSON.parse(await env.USER_PREFS.get(key)); r.pushSubs = Array.isArray(p) ? p : [p]; } catch {}
  });
  return [...map.values()].filter((r) => r && r.pushSubs && r.pushSubs.length);
}

// 全球領先脈絡指數:鄰近市場(半導體SOX/亞洲/歐洲)當日/隔夜漲跌 —— 這些市場開盤早於台股、
// 半導體鏈跨市連動,是「會直接或經產業鏈下游波及使用者持股」的市場背景。每次排程抓一次餵給
// aiSeverity 當 severity/stance 判斷的背景(僅脈絡、不給買賣價位;同日報 analyzer._global_lead_context 精神)。
const GLOBAL_LEAD_INDICES = [
  ["%5ESOX", "費城半導體", "半導體"],
  ["%5EN225", "日經225", "亞洲"],
  ["%5EKS11", "韓國KOSPI", "亞洲"],
  ["%5EHSI", "恒生", "亞洲"],
  ["000001.SS", "上證", "亞洲"],
  ["%5ESTOXX50E", "歐洲Stoxx50", "歐洲"],
  ["%5EGDAXI", "德國DAX", "歐洲"],
  ["%5EFTSE", "英國FTSE", "歐洲"],
];

// Yahoo chart 端點(Worker 可打、無需 auth)抓全球指數,組成一行背景字串;抓不到就回空字串
// (背景缺了不影響提醒本身,graceful degradation)。KV 快取 15 分鐘,避免每次排程重打 8 檔。
async function fetchGlobalLead(env) {
  const CACHE_KEY = "alert:globallead";
  if (env && env.USER_PREFS) {
    try { const c = await env.USER_PREFS.get(CACHE_KEY); if (c !== null) return c; } catch (e) {}
  }
  const out = [];
  await Promise.all(GLOBAL_LEAD_INDICES.map(async ([sym, name, region]) => {
    try {
      const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=1d&range=1d`,
        { headers: { "User-Agent": "Mozilla/5.0" } });
      if (!r.ok) return;
      const meta = (await r.json())?.chart?.result?.[0]?.meta;
      const price = Number(meta?.regularMarketPrice);
      // previousClose = 官方昨收(對齊 Python _batch_prices 的 regularMarketPreviousClose);
      // chartPreviousClose 在多日 range 會指到視窗前一日 → 只當備援
      const prev = Number(meta?.previousClose ?? meta?.chartPreviousClose);
      if (!price || !prev) return;
      const pct = (price - prev) / prev * 100;
      if (Math.abs(pct) > 20) return;  // 指數單日 >20% 幾乎必為壞資料,寧缺勿假(同 _alt_sane)
      out.push({ name, region, pct });
    } catch (e) {}
  }));
  let line = "";
  if (out.length) {
    const byR = {};
    for (const o of out) (byR[o.region] ||= []).push(o);
    line = ["半導體", "亞洲", "歐洲"].filter((rk) => byR[rk]).map((rk) =>
      `${rk}:` + byR[rk].map((o) => `${o.name}${o.pct >= 0 ? "+" : ""}${o.pct.toFixed(2)}%`).join("、")
    ).join("｜");
  }
  if (env && env.USER_PREFS) {
    try { await env.USER_PREFS.put(CACHE_KEY, line, { expirationTtl: 900 }); } catch (e) {}
  }
  return line;
}

// 2026-07-28 LLM 免費鏈(Delvin「不要扣錢」令延伸到 alert-worker):
// Gemini flash(免費) → Gemini 2.5-flash-lite(免費,獨立 RPD 桶) → Groq llama-3.3-70b(免費)
// → Claude Haiku(付費,最後備援)。任一家成功即回,全敗才 throw。
async function llmComplete(env, prompt) {
  const jobs = [];
  if (env.GEMINI_API_KEY) {
    for (const model of ["gemini-flash-latest", "gemini-2.5-flash-lite"]) {
      jobs.push(async () => {
        const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${env.GEMINI_API_KEY}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0.2, maxOutputTokens: 2000 },
          }),
        });
        if (!r.ok) throw new Error(`gemini:${model} ${r.status}`);
        const d = await r.json();
        const parts = (((d.candidates || [])[0] || {}).content || {}).parts || [];
        const text = parts.map((c) => c.text || "").join("");
        if (!text) throw new Error(`gemini:${model} empty`);
        return text;
      });
    }
  }
  if (env.GROQ_API_KEY) {
    jobs.push(async () => {
      const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: { authorization: `Bearer ${env.GROQ_API_KEY}`, "content-type": "application/json" },
        body: JSON.stringify({
          model: "llama-3.3-70b-versatile",
          messages: [{ role: "user", content: prompt }],
          max_tokens: 500,
          temperature: 0.2,
        }),
      });
      if (!r.ok) throw new Error(`groq ${r.status}`);
      const d = await r.json();
      const text = (((d.choices || [])[0] || {}).message || {}).content || "";
      if (!text) throw new Error("groq empty");
      return text;
    });
  }
  if (env.ANTHROPIC_API_KEY) {
    jobs.push(async () => {
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
        body: JSON.stringify({
          model: "claude-haiku-4-5-20251001",
          max_tokens: 500,
          messages: [{ role: "user", content: prompt }],
        }),
      });
      if (!r.ok) throw new Error(`anthropic ${r.status}`);
      const d = await r.json();
      const text = (d.content || []).map((c) => c.text || "").join("");
      if (!text) throw new Error("anthropic empty");
      return text;
    });
  }
  let lastErr = null;
  for (const job of jobs) {
    try { return await job(); } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error("no LLM provider configured");
}

// LLM 嚴重度判定:輸入新聞 + 相關 ticker,輸出 {severity 0-10, reason}。
async function aiSeverity(env, news, tickers, universe = null, globalLead = "") {
  if (!env.ANTHROPIC_API_KEY && !env.GEMINI_API_KEY && !env.GROQ_API_KEY) return { severity: null, reason: "AI 未設定", skipped: true };
  const names = tickers.length
    ? tickers.map((t) => `${t}(${displayName(t)})`).join("、")
    : "台股/美股投資人的持股";
  // 第二層傳導:給 AI 一份「訂閱者持股清單」,請它判斷這則新聞會直接或經產業鏈/供應鏈/
  // 同產業/總經傳導打到清單裡的哪幾檔 → 回傳 affected,讓管線推給真正被波及的持有者。
  const uniList = Array.isArray(universe) && universe.length
    ? universe.map((t) => `${t}(${displayName(t)})`).join("、")
    : null;
  const affectedInstr = uniList ? `
- affected:從下面這份「訂閱者持股清單」中,挑出會被這則新聞【直接點名,或透過產業鏈/供應鏈(晶圓代工/封測/設備/IP)、同產業競合、總經(利率/匯率/原物料)傳導】而受影響的代碼,回傳陣列(沒有就給空陣列 [],寧缺勿濫、只放關聯明確的)。清單:${uniList}` : "";
  const affectedField = uniList ? `, "affected": ["<清單中被波及的代碼>", ...]` : "";
  const prompt = `你是財經新聞嚴重度評分員。判斷這則新聞對「持有 ${names} 的投資人」有多重大。

標題:${news.title}
摘要:${news.summary || "(無)"}
來源:${news.source}
${globalLead ? `
【🌏 全球領先脈絡(鄰近市場當日/隔夜漲跌,僅供市場背景參考)】${globalLead}
盤勢背景會放大或緩和這則新聞對持股的衝擊:半導體鏈(費半/日韓)走弱時,晶片/科技相關利空對持股的殺傷力提高;鄰近市場全面走強則對利空有緩衝。據此【微調】severity 與 stance,但這是背景不是主因——不可僅憑背景就升降級,新聞事件本身仍是主要依據。
` : ""}
評分標準(severity 0-10):
- 9-10:破產、重大併購、財測大幅下修、CEO 突然去職、重大訴訟敗訴等,股價可能立即大幅變動。
- 7-8:財報明顯優於/低於預期、重要評等調整、監管調查、產品重大事件。
- 4-6:一般財經報導、分析師例行評論、影響有限。
- 0-3:無實質影響、舊聞、與該公司關聯薄弱。

另外判斷:
- category:這則屬於「event」(已發生或已正式公告的事實)、「rumor」(未經證實的傳言/小道消息)、還是「opinion」(評論、分析、假設推演,例如「如果…將會…」「為什麼…」)。臆測與評論不是事件,即使聳動也不應給高分。
- stance:對受影響的投資人,你的操作傾向,從「加碼/續抱/觀望/減碼/賣出」擇一。
- action:一句繁體中文,說明此刻具體該怎麼做與理由。若 category 是 rumor 或 opinion,務必明說「尚未證實/僅為推測,對基本面無立即影響」,不要建議因此追高或殺低,可提示真正該盯的下一個事件(財報/官方說法等)。${affectedInstr}

只輸出 JSON,格式:{"severity": <0-10 整數>, "category": "event|rumor|opinion", "stance": "加碼|續抱|觀望|減碼|賣出", "reason": "<一句:為何跟投資人有關>", "action": "<一句:此刻該怎麼做與理由>"${affectedField}}`;
  try {
    const text = await llmComplete(env, prompt);
    const m = text.match(/\{[\s\S]*\}/);
    if (!m) return { severity: null, reason: "AI 回應無法解析", error: true };
    const parsed = JSON.parse(m[0]);
    let sev = Math.round(Number(parsed.severity));
    if (isNaN(sev)) sev = 0;
    const cat = ["event", "rumor", "opinion"].includes(parsed.category) ? parsed.category : "event";
    const stanceSet = ["加碼", "續抱", "觀望", "減碼", "賣出"];
    const stance = stanceSet.includes(parsed.stance) ? parsed.stance : "";
    // 第二層 affected:只保留確實在持股清單(universe)裡的代碼,防 AI 幻覺出清單外標的。
    let affected = [];
    if (Array.isArray(universe) && universe.length && Array.isArray(parsed.affected)) {
      const uni = new Set(universe.map((t) => String(t).trim().toUpperCase()));
      affected = [...new Set(parsed.affected.map((t) => String(t).trim().toUpperCase()).filter((t) => uni.has(t)))];
    }
    return {
      severity: Math.max(0, Math.min(10, sev)),
      category: cat,
      stance,
      reason: String(parsed.reason || "").slice(0, 200),
      action: String(parsed.action || "").slice(0, 200),
      affected,
    };
  } catch (e) {
    return { severity: null, reason: `AI 例外:${e.message}`, error: true };
  }
}

// 取 LINE Messaging API 推播 token。
// 預設順序:KV cache(alert:linetoken,動態 OAuth 結果)→ static env LINE_CHANNEL_ACCESS_TOKEN
// → 動態 OAuth swap(client_credentials)。force=true 跳過 cache 和 static,
// 直接動態換(alertAdmin 推 admin LINE 收 401 時用)。
async function lineToken(env, { force = false } = {}) {
  if (!force) {
    const cached = await env.USER_PREFS.get("alert:linetoken");
    if (cached) return cached;
    if (env.LINE_CHANNEL_ACCESS_TOKEN) return env.LINE_CHANNEL_ACCESS_TOKEN;
  }
  if (!env.LINE_CHANNEL_ID || !env.LINE_CHANNEL_SECRET) return null;
  const res = await fetch("https://api.line.me/v2/oauth/accessToken", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: env.LINE_CHANNEL_ID,
      client_secret: env.LINE_CHANNEL_SECRET,
    }),
  });
  if (!res.ok) return null;
  const data = await res.json();
  if (!data.access_token) return null;
  await env.USER_PREFS.put("alert:linetoken", data.access_token, { expirationTtl: 24 * 24 * 3600 });
  return data.access_token;
}

// ───────── 自有 Web Push 推播通道(VAPID + aes128gcm,零成本無上限,不經 LINE)─────────
function b64urlToBytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function bytesToB64url(bytes) {
  const b = new Uint8Array(bytes);
  let bin = "";
  for (let i = 0; i < b.length; i++) bin += String.fromCharCode(b[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function concatBytes(...arrs) {
  let len = 0;
  for (const a of arrs) len += a.length;
  const out = new Uint8Array(len);
  let off = 0;
  for (const a of arrs) { out.set(a, off); off += a.length; }
  return out;
}
async function hkdf(salt, ikm, info, len) {
  const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, key, len * 8);
  return new Uint8Array(bits);
}
async function vapidJwt(env, audience) {
  const enc = new TextEncoder();
  const header = bytesToB64url(enc.encode(JSON.stringify({ typ: "JWT", alg: "ES256" })));
  const payload = bytesToB64url(enc.encode(JSON.stringify({
    aud: audience,
    exp: Math.floor(Date.now() / 1000) + 12 * 3600,
    sub: env.VAPID_SUBJECT || "mailto:admin@marketdaily.ai",
  })));
  const unsigned = `${header}.${payload}`;
  const pub = b64urlToBytes(env.VAPID_PUBLIC_KEY);
  const jwk = {
    kty: "EC", crv: "P-256",
    x: bytesToB64url(pub.slice(1, 33)),
    y: bytesToB64url(pub.slice(33, 65)),
    d: env.VAPID_PRIVATE_KEY, ext: true,
  };
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(unsigned));
  return `${unsigned}.${bytesToB64url(sig)}`;
}
// RFC 8291 aes128gcm payload 加密。回傳完整 body(含 header)。
async function encryptWebPush(subscription, plaintextStr) {
  const enc = new TextEncoder();
  const plaintext = enc.encode(plaintextStr);
  const clientPub = b64urlToBytes(subscription.keys.p256dh);
  const auth = b64urlToBytes(subscription.keys.auth);
  const serverKeys = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const serverPubRaw = new Uint8Array(await crypto.subtle.exportKey("raw", serverKeys.publicKey));
  const clientKey = await crypto.subtle.importKey("raw", clientPub, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: clientKey }, serverKeys.privateKey, 256));
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const keyInfo = concatBytes(enc.encode("WebPush: info\0"), clientPub, serverPubRaw);
  const ikm = await hkdf(auth, shared, keyInfo, 32);
  const cek = await hkdf(salt, ikm, enc.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(salt, ikm, enc.encode("Content-Encoding: nonce\0"), 12);
  const padded = concatBytes(plaintext, new Uint8Array([0x02]));
  const aesKey = await crypto.subtle.importKey("raw", cek, { name: "AES-GCM" }, false, ["encrypt"]);
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, aesKey, padded));
  const header = new Uint8Array(16 + 4 + 1 + serverPubRaw.length);
  header.set(salt, 0);
  new DataView(header.buffer).setUint32(16, 4096, false); // record size
  header[20] = serverPubRaw.length;
  header.set(serverPubRaw, 21);
  return concatBytes(header, ciphertext);
}
async function webPush(env, subscription, payloadStr) {
  if (!env.VAPID_PUBLIC_KEY || !env.VAPID_PRIVATE_KEY) return { ok: false, status: 0 };
  try {
    const u = new URL(subscription.endpoint);
    const jwt = await vapidJwt(env, `${u.protocol}//${u.host}`);
    const body = await encryptWebPush(subscription, payloadStr);
    const res = await fetch(subscription.endpoint, {
      method: "POST",
      headers: {
        TTL: "86400",
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        Authorization: `vapid t=${jwt}, k=${env.VAPID_PUBLIC_KEY}`,
      },
      body,
    });
    return { ok: res.ok, status: res.status };
  } catch (e) {
    return { ok: false, status: 0, error: String(e).slice(0, 80) };
  }
}
// 瀏覽器通知 payload(service worker 解析用)
// 每則提醒的穩定短錨點(djb2 hash→base36)——push url 帶 #alert-<id>、收件匣 record 存同一 id,
// dashboard 據此捲到「被點的那則」而非只跳到列表頂端。同一則新聞/貼文永遠算出同一 id(冪等)。
function alertAnchor(seed) {
  let h = 5381;
  const s = String(seed || "");
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

function pushNotif(news, ticker, severity, reason, anchor = "") {
  const name = ticker === "大盤" ? "大盤" : displayName(ticker);
  return JSON.stringify({
    title: severity >= 9 ? `🚨 ${name}｜重大消息` : `📈 ${name}｜即時提醒`,
    body: (news.title || reason || "").slice(0, 160),
    url: "https://marketdaily.ai/dashboard.html#" + (anchor ? `alert-${anchor}` : "alerts"),
    tag: `md-${ticker}-${(news.publishedAt || "").slice(0, 13)}`,
  });
}
// 統一投遞:通道 = 自有 web push(免費無上限;LINE 已全面退役)。
async function deliverAlert(env, r, notifStr, opts = {}) {
  let ok = false; const channels = []; let lastStatus = 0;
  const severity = opts.severity || 0;
  const hasWebPush = !!(r.pushSubs && r.pushSubs.length);
  // 1) web push —— 所有人預設通道
  if (hasWebPush) {
    const dead = new Set();
    let sent = 0;
    for (const sub of r.pushSubs) {
      const wr = await webPush(env, sub, notifStr);
      if (wr.ok) { sent++; }
      else { lastStatus = wr.status || lastStatus; if (wr.status === 404 || wr.status === 410) dead.add(sub.endpoint); }
    }
    if (sent > 0) { ok = true; channels.push(`webpush×${sent}`); }
    // 清除失效裝置訂閱(逐台,不影響其他裝置)
    if (dead.size) {
      const alive = r.pushSubs.filter((s) => !dead.has(s.endpoint));
      r.pushSubs = alive;
      if (alive.length) await env.USER_PREFS.put(`pushsub:${r.email}`, JSON.stringify(alive));
      else await env.USER_PREFS.delete(`pushsub:${r.email}`);
    }
  }
  // 訂閱者與 admin 通道都只剩 web push(LINE 已全面退役)
  return { ok, channels, status: lastStatus };
}
// 寫入用戶的站內「提醒收件匣」(email-keyed;dashboard feed 讀這個)。留 90 天、上限 50 則。
async function recordAlertInbox(env, email, record) {
  try {
    const key = `alerthist:${email}`;
    let list = [];
    const raw = await env.USER_PREFS.get(key);
    if (raw) { try { list = JSON.parse(raw); } catch {} }
    list.push(record);
    if (list.length > 50) list = list.slice(-50);
    await env.USER_PREFS.put(key, JSON.stringify(list), { expirationTtl: 90 * 24 * 3600 });
  } catch {}
}

// 每次 admin 推播同步落 KV admin_events(最近 200 則,滾動 90 天),後台「系統告警」頁讀。
// 推播失敗/無訂閱也照樣留痕:歷史不依賴推播當下有沒有看到(admin.html /admin/events)。
// fullBody:admin-line-push 的完整訊息(push body 截 300 字,歷史留全文)。
async function recordAdminEvent(env, payloadStr, pushed, fullBody, evTs) {
  try {
    let p = {};
    try { p = JSON.parse(payloadStr) || {}; } catch {}
    let list = [];
    const raw = await env.USER_PREFS.get("admin_events");
    if (raw) { try { list = JSON.parse(raw); } catch {} }
    if (!Array.isArray(list)) list = [];
    list.unshift({
      ts: evTs || Date.now(),
      title: String(p.title || "").slice(0, 120),
      body: String(fullBody || p.body || "").slice(0, 2000),
      pushed: !!pushed,
    });
    await env.USER_PREFS.put("admin_events", JSON.stringify(list.slice(0, 200)), { expirationTtl: 90 * 24 * 3600 });
  } catch {}
}

// 對 admin 的所有裝置發 web push(讀 pushsub:${ADMIN_EMAIL} 陣列),回傳是否至少一台成功
async function webPushAdmin(env, payloadStr, fullBody, evTs) {
  let ok = false;
  try {
    if (env.ADMIN_EMAIL) {
      const raw = await env.USER_PREFS.get(`pushsub:${env.ADMIN_EMAIL}`);
      if (raw) {
        const p = JSON.parse(raw);
        const subs = Array.isArray(p) ? p : [p];
        for (const sub of subs) { const wr = await webPush(env, sub, payloadStr); if (wr.ok) ok = true; }
      }
    }
  } catch {}
  await recordAdminEvent(env, payloadStr, ok, fullBody, evTs);
  return ok;
}

function alertMessage(news, ticker, severity, reason, meta = {}) {
  const { speculative = false, stance = "", action = "" } = meta;
  const name = ticker === "大盤" ? "大盤" : displayName(ticker);
  const head = speculative
    ? "💬 觀點／傳言"
    : (severity >= 9 ? "🚨 重大消息｜⚠️ 高度重大" : "🚨 重大消息");
  const lines = [
    `${head}｜${ticker === "大盤" ? "影響整體市場(你的持倉)" : `你的持股 ${name}`}`,
    "",
    news.title,
    "",
    "💡 為什麼跟你有關",
    reason || `這則新聞與你持有的 ${name} 相關,留意股價反應。`,
  ];
  if (stance || action) {
    lines.push("", `📊 對你的部位:${stance}${stance && action ? " — " : ""}${action}`);
  }
  lines.push(
    "",
    `🔗 原文:${news.url}`,
    "—— MarketDaily 即時提醒｜僅供參考,非投資建議",
  );
  return lines.join("\n");
}


// 主動告訴 admin:推播出狀況。通道 = 自有 web push 到所有 admin 裝置(LINE 已退役,不再備援)。
// 節流:同小時最多 1 則,避免炸訊息。
// channel:預設共用 admin_alert:<hour> 節流閘(既有呼叫端行為不變)。
// 傳 channel 可讓某個子系統(如 political)有自己獨立的節流閘,不會被別條管線
// (如 news pipeline,*/2 觸發頻率高很多)搶先卡位同一小時的額度而被靜默吞掉。
async function alertAdmin(env, summary, { channel = "" } = {}) {
  const hourKey = `admin_alert:${channel ? channel + ":" : ""}${new Date().toISOString().slice(0, 13)}`;
  if (await env.USER_PREFS.get(hourKey)) return;
  // 一模一樣的告警內容 24h 只推一次:永久性故障(如 xAI 無 credits 的 403)在每小時節流下
  // 仍是 24 則/天轟炸;轟炸讓用戶關通知,真告警就再也到不了(2026-07-17 政壇 403 事故修)。
  let sig = 5381;
  const sigSrc = `${channel}|${summary}`;
  for (let i = 0; i < sigSrc.length; i++) sig = ((sig << 5) + sig + sigSrc.charCodeAt(i)) >>> 0;
  const sigKey = `admin_alert_sig:${sig.toString(36)}`;
  if (await env.USER_PREFS.get(sigKey)) return;
  let delivered = false;
  if (await webPushAdmin(env, JSON.stringify({
    title: "🚨 MarketDaily Alert",
    body: summary.slice(0, 300),
    url: "https://marketdaily.ai/dashboard.html#alerts",
  }))) delivered = true;
  if (delivered) {
    await env.USER_PREFS.put(hourKey, "1", { expirationTtl: 3700 });
    await env.USER_PREFS.put(sigKey, "1", { expirationTtl: 24 * 3600 });
  } else {
    await env.USER_PREFS.put(`admin_alert_failed:${Date.now()}`,
      JSON.stringify({ summary, reason: "all channels failed" }),
      { expirationTtl: 7 * 24 * 3600 });
  }
}

// Canary:不依賴真實事件,定期驗 token+LINE API 都活著。
// 失敗就 alertAdmin,在使用者察覺前就抓到。
async function canaryCheck(env) {
  await env.USER_PREFS.delete("alert:linetoken"); // 強制重抓最新
  const t = await lineToken(env, { force: true });
  const out = { ts: new Date().toISOString(), ok: false };
  if (!t) {
    out.reason = "OAuth swap 拿不到 token (channel id/secret 可能失效)";
    await alertAdmin(env, `Canary 失敗:${out.reason}\n請查 LINE Developer Console`);
    await env.USER_PREFS.put("alert:lastcanary", JSON.stringify(out));
    return out;
  }
  // 用一個一定無效的 userId 試推,期望回 400/403 表示 token 本身有效
  const probe = await fetch(LINE_PUSH_URL, {
    method: "POST",
    headers: { authorization: `Bearer ${t}`, "content-type": "application/json" },
    body: JSON.stringify({ to: "U0000000000000000000000000000000", messages: [{ type: "text", text: "x" }] }),
  });
  out.probeStatus = probe.status;
  if (probe.status === 401) {
    out.reason = "token 仍被 LINE 視為無效(401)";
    await alertAdmin(env, `Canary 失敗:${out.reason}\nchannel id/secret 可能要重生`);
  } else {
    out.ok = true;
  }
  await env.USER_PREFS.put("alert:lastcanary", JSON.stringify(out));
  return out;
}

// 完整偵測→推播管線。
//   push    —— true 才真的呼叫 LINE 推播。
//   persist —— true 才寫入 KV(seen / 推播計數 / 狀態紀錄)。
// scheduled() 一律 persist:true(每則新聞只評估一次,避免 AI 成本爆炸);
// /dry-run 端點 persist:false(純檢視,每次重新評估)。
async function runPipeline(env, { push, persist }) {
  const report = {
    ts: new Date().toISOString(),
    push, persist,
    counts: { fetched: 0, alreadySeen: 0, rulePassed: 0, preFiltered: 0, premiumMatched: 0, aiEvaluated: 0, wouldPush: 0, pushed: 0 },
    premiumUniverse: [],
    candidates: [],
    fired: [],
    errors: [],
  };

  const recipients = await premiumRecipients(env);
  const universe = [...new Set(recipients.flatMap((r) => [...r.holdings]))];
  report.premiumUniverse = universe;
  // 全球領先脈絡:每次排程抓一次,餵給 aiSeverity 當市場背景(會直接/下游波及持股的鄰近市場動向)
  const globalLead = await fetchGlobalLead(env);
  report.globalLead = globalLead;

  // 有 Premium 持股 → 用個股 RSS 精準抓;沒有 → 抓大盤綜合 feed(供觀察粗篩用)。
  const usUniverse = universe.filter((t) => /^[A-Z.\-]{1,6}$/.test(t));
  const { items, errors } = await fetchNews(usUniverse.length ? { tickers: usUniverse } : {});
  report.errors.push(...errors);
  report.counts.fetched = items.length;

  for (const news of items) {
    const seenKey = `seen:${news.id}`;
    if (await env.USER_PREFS.get(seenKey)) {
      report.counts.alreadySeen++;
      continue;
    }

    const eventType = classify(`${news.title} ${news.summary}`);
    if (!eventType) {
      if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
      continue;
    }
    report.counts.rulePassed++;

    // 規則預評分閘門 —— 不花 AI:擋掉舊聞與明顯偏弱的新聞,壓低 AI 呼叫量。
    const ageHours = newsAgeHours(news.publishedAt);
    const preScore = ruleScore(eventType, ageHours);
    if (ageHours > MAX_AGE_HOURS || preScore < PRESCORE_FLOOR) {
      if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
      report.counts.preFiltered++;
      report.candidates.push({
        title: news.title, source: news.source, url: news.url,
        tickers: news.tickers, eventType, preScore, severity: null,
        reason: ageHours > MAX_AGE_HOURS
          ? `規則預篩:新聞已 ${Math.round(ageHours)} 小時,過舊`
          : `規則預篩:預評分 ${preScore} 未達 ${PRESCORE_FLOOR}`,
        recipients: [],
      });
      continue;
    }

    // ── 比對 Premium 持有者(含第二層產業鏈/供應鏈/總經傳導)──────────
    // broadImpact 用 matchesBroad(全文)判,不綁 classify 的單一 first-match,
    // 免得「油價飆漲」被 trading 接走就漏掉總經第二層傳導。
    const broadImpact = matchesBroad(`${news.title} ${news.summary || ""}`);
    const directHolders = recipients.filter((r) => news.tickers.some((t) => r.holdings.has(t)));
    // 廣域衝擊類型(AI/晶片/總經/政策/供應鏈)→ 拿全體持股清單給 AI 判「第二層被波及標的」;
    // 一般公司級新聞只走直接點名,不多花 AI。
    const universe = broadImpact
      ? [...new Set(recipients.flatMap((r) => [...r.holdings]))]
      : null;

    // 沒有直接持有者、又不是廣域衝擊類型(或無任何持股可比對)→ 與持股無關,跳過(不花 AI)。
    if (!directHolders.length && (!broadImpact || !universe.length)) {
      if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
      report.candidates.push({
        title: news.title, source: news.source, url: news.url,
        tickers: news.tickers, eventType, preScore, severity: null,
        reason: "通過粗篩但無 Premium 持有者", recipients: [],
      });
      continue;
    }
    report.counts.premiumMatched++;

    // AI 嚴重度 + 第二層被波及標的(broadImpact 才傳 universe)
    const { severity, reason, category, stance, action, affected = [], skipped, error } =
      await aiSeverity(env, news, news.tickers, universe, globalLead);
    if (!skipped) report.counts.aiEvaluated++;
    // 臆測/觀點:標題標記命中 或 AI 判 rumor/opinion → 門檻拉高 + 標籤改「觀點／傳言」。
    const speculative = isSpeculative(`${news.title} ${news.summary || ""}`)
      || category === "rumor" || category === "opinion";
    const baseNeed = speculative ? SPECULATIVE_THRESHOLD : SEVERITY_THRESHOLD;

    // 逐用戶決定命中標的與所需門檻:直接點名 → 7;第二層傳導 / 大盤級 → 8(臆測一律 9)。
    const secondSet = new Set(affected);
    // 大盤級廣播(推全體)只保留給「總經/政策」型且沒點名個股、AI 也沒挑出特定持股時;
    // 同樣不綁單一 eventType,直接測 macro/political matcher,免得被 trading 先接走。
    const macroOrPolicy = EVENT_MATCHERS.some((m) =>
      (m.type === "macro" || m.type === "political") && m.re.test(`${news.title} ${news.summary || ""}`));
    const indexWide = broadImpact && !news.tickers.length && !secondSet.size && macroOrPolicy;
    const targets = [];
    for (const r of recipients) {
      const direct = news.tickers.find((t) => r.holdings.has(t));
      if (direct) { targets.push({ h: r, hit: direct, via: "direct", need: baseNeed }); continue; }
      const sec = [...r.holdings].find((t) => secondSet.has(t));
      if (sec) { targets.push({ h: r, hit: sec, via: "second", need: Math.max(baseNeed, 8) }); continue; }
      if (indexWide) targets.push({ h: r, hit: "大盤", via: "index", need: Math.max(baseNeed, 8) });
    }
    const minNeed = targets.length ? Math.min(...targets.map((t) => t.need)) : baseNeed;

    const cand = {
      title: news.title, source: news.source, url: news.url,
      tickers: news.tickers, eventType, preScore, severity, category, stance, action,
      speculative, threshold: minNeed, affected, reason,
      recipients: [],
    };

    if (error) {
      // AI 失敗:不標 seen,下一輪重試。
      report.errors.push(`ai:${news.id}:${reason}`);
      report.candidates.push(cand);
      continue;
    }
    if (skipped) {
      // 沒有 AI key:列出候選但不判定、不標 seen(待補 key 後重評)。
      report.candidates.push(cand);
      continue;
    }
    if (!targets.length) {
      // AI 判定沒有任何持股被直接或間接波及 → 不推。
      if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
      cand.reason = `${cand.reason || ""}(AI 判定無持股被直接/間接波及)`.trim();
      report.candidates.push(cand);
      continue;
    }
    if (severity < minNeed) {
      if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
      cand.reason = `${cand.reason || ""}(需 severity≥${minNeed} 才推,本則 ${severity})`.trim();
      report.candidates.push(cand);
      continue;
    }

    // 通過門檻 → 逐持有者推播(去重 + 每日上限)。訂閱者只走 web push
    const today = twDate();
    for (const { h, hit, via, need } of targets) {
      if (severity < need) {
        cand.recipients.push({ email: h.email, ticker: hit, status: `skip:未達門檻(需 ${need},本則 ${severity})` });
        continue;
      }
      // 第二層傳導在提醒理由前面標「間接影響」,誠實區分直接點名 vs 產業鏈/總經波及。
      const dispReason = via === "direct" ? reason : `【間接影響】${reason}`;
      const cluster = `pushed:${h.email}:${clusterKey(hit, eventType, news.publishedAt)}`;
      if (await env.USER_PREFS.get(cluster)) {
        cand.recipients.push({ email: h.email, status: "skip:已收過此事件" });
        continue;
      }
      const countKey = `alertcount:${h.email}:${today}`;
      const count = parseInt((await env.USER_PREFS.get(countKey)) || "0", 10);
      if (count >= DAILY_CAP) {
        cand.recipients.push({ email: h.email, status: "skip:已達每日上限" });
        continue;
      }
      report.counts.wouldPush++;
      if (!push) {
        cand.recipients.push({ email: h.email, ticker: hit, status: "would-push" });
        continue;
      }
      const aid = alertAnchor(`${hit}|${news.url || ""}|${news.publishedAt || ""}`);
      const pushed = await deliverAlert(env, h, pushNotif(news, hit, severity, dispReason, aid), { severity });
      if (pushed.ok) {
        await env.USER_PREFS.put(cluster, report.ts, { expirationTtl: PUSHED_TTL });
        await env.USER_PREFS.put(countKey, String(count + 1), { expirationTtl: COUNT_TTL });
        report.counts.pushed++;
        cand.recipients.push({ email: h.email, ticker: hit, status: `pushed:${pushed.channels.join("+")}` });
        // 站內提醒收件匣(dashboard feed 顯示用);id 與 push url 錨點一致,供深連結捲動
        await recordAlertInbox(env, h.email, {
          id: aid, ts: report.ts, kind: "news", ticker: hit,
          name: hit === "大盤" ? "大盤" : displayName(hit),
          title: news.title, url: news.url, reason: dispReason, stance, action,
          severity, category, speculative,
        });
      } else {
        // 所有通道都失敗(deliverAlert 已處理 stale/失效訂閱清除)
        cand.recipients.push({ email: h.email, status: `fail:${pushed.status}` });
        report.errors.push(`push:${h.email}:${pushed.status}`);
      }
    }

    report.candidates.push(cand);
    report.fired.push({
      ts: report.ts, title: news.title, url: news.url, source: news.source,
      severity, reason, tickers: news.tickers, eventType, recipients: cand.recipients,
    });
    // 全部持有者處理完才標 seen(推播失敗的會在 errors,但 seen 仍標,避免重複轟炸;
    // 失敗者個別重綁後由新事件觸發)。
    if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
  }

  if (persist) {
    await env.USER_PREFS.put("alert:laststatus", JSON.stringify({
      ts: report.ts, push, counts: report.counts, errors: report.errors.slice(0, 10),
    }));
    if (report.fired.length) {
      let recent = [];
      try { recent = JSON.parse((await env.USER_PREFS.get("alert:recent")) || "[]"); } catch {}
      await env.USER_PREFS.put("alert:recent", JSON.stringify([...report.fired, ...recent].slice(0, 40)));
    }
    // 推播炸了就告訴 admin。401 retry 之後還是失敗、或其他非 4xx 都會被計入。
    // 用 fired[].recipients[].status 判;只要不是 "pushed" / "would-push" / "skip:*" 都算失敗。
    if (push) {
      const failed = [];
      for (const f of report.fired) {
        for (const r of f.recipients || []) {
          const s = r.status || "";
          if (s.startsWith("fail:")) failed.push({ email: r.email, ticker: r.ticker, status: s, title: f.title });
        }
      }
      if (failed.length) {
        const lines = failed.slice(0, 3).map(f =>
          `• ${f.email}(${f.ticker}) ${f.status}\n  ${(f.title || "").slice(0, 50)}`);
        await alertAdmin(env,
          `推播失敗 ${failed.length} 筆(/${report.fired.length} 達標事件)\n${lines.join("\n")}` +
          (failed.length > 3 ? `\n…還有 ${failed.length - 3} 筆` : ""));
      }
    }
  }
  return report;
}

// ── 政壇市場訊號管線(政治人物 X 貼文 → LINE)──────────────────────
// 門檻:政策行動 ≥ POLITICAL_ACTION_THRESHOLD(6,比新聞的 7 低一階,因政治事件本質大盤級)、
// 言論/觀點 ≥ SPECULATIVE_THRESHOLD(9)且訊息掛「💬 言論觀點」標籤,不轟炸。達標即推全體訂閱者。
// 無 XAI_API_KEY → 安靜 no-op;KV alert:political = "off" 可單獨關掉這條線。
// signals 可由兩個來源餵入:不傳=Grok x_search 直抓(需 XAI_API_KEY+credits);
// 傳入=本機 Playwright 掃 X 後經 /political-ingest 送進來(零 xAI 成本路線)。
async function runPoliticalPipeline(env, { push, signals = null, source = "grok" }) {
  const report = { ts: new Date().toISOString(), source, skipped: null, found: 0, qualified: 0, pushed: 0, fired: [], errors: [] };
  // 不論結果如何都寫 laststatus heartbeat — 沒有它就無法證明 */15 cron 有在跑(可觀測性)
  const done = async () => {
    const k = source === "grok" ? "alert:pol_laststatus" : "alert:pol_laststatus_x";
    await env.USER_PREFS.put(k, JSON.stringify(report));
    return report;
  };
  if ((await env.USER_PREFS.get("alert:political")) === "off") {
    report.skipped = "alert:political=off";
    return done();
  }
  let sigList = signals;
  if (sigList === null) {
    const res = await fetchPoliticalSignals(env, 2);
    if (res.skipped) { report.skipped = res.skipped; return done(); }
    if (res.error) {
      report.errors.push(res.error);
      // 這條管線之前只把錯誤寫進 alert:pol_laststatus 沒人看,靜默壞掉不會被發現
      // (news 管線早就有等價的 alertAdmin,political 管線是漏網的那條)。
      if (push) await alertAdmin(env, `政壇訊號抓取失敗(*/15 cron)\n${res.error}`, { channel: "political" });
      return done();
    }
    sigList = res.signals;
  }
  const res = { signals: sigList };
  report.found = res.signals.length;
  if (!res.signals.length) return done();

  let recipients = null;
  for (const sig of res.signals) {
    const threshold = sig.kind === "action" ? POLITICAL_ACTION_THRESHOLD : SPECULATIVE_THRESHOLD;
    if (sig.severity < threshold) continue;
    // 去重:同一貼文(URL)48h 只推一次
    const seenKey = "pol:seen:" + encodeURIComponent(sig.post_url || sig.headline_zh).slice(0, 480);
    if (await env.USER_PREFS.get(seenKey)) continue;
    // 每日上限(與新聞推播分開計),避免炸訊息
    const capKey = "pol:count:" + new Date().toISOString().slice(0, 10);
    const sent = parseInt((await env.USER_PREFS.get(capKey)) || "0", 10);
    if (sent >= 4) { report.errors.push("daily political cap reached"); break; }

    report.qualified++;
    if (recipients === null) recipients = await premiumRecipients(env);
    // 政治/總經事件本質大盤級(用戶定調「大盤級推全體」)→ 達標即推全體訂閱者,
    // 不再因「沒持有被點名個股」而漏接;每日上限 4 則(上方 cap)防轟炸。
    const targets = recipients;
    const fired = { headline: sig.headline_zh, severity: sig.severity, kind: sig.kind, recipients: [] };
    const aid = alertAnchor(`pol|${sig.post_url || sig.headline_zh || ""}`);
    if (push && targets.length) {
      const notif = JSON.stringify({
        title: `🏛️ 政壇影響｜${(sig.headline_zh || "").slice(0, 36)}`,
        body: (sig.headline_zh || "").slice(0, 160),
        url: `https://marketdaily.ai/dashboard.html#alert-${aid}`,
        tag: `md-pol-${(sig.post_url || sig.headline_zh || "").slice(0, 40)}`,
      });
      for (const r of targets) {
        const out = await deliverAlert(env, r, notif, { severity: sig.severity });
        fired.recipients.push({ email: r.email, status: out.ok ? `pushed:${out.channels.join("+")}` : `fail:${out.status}` });
        if (out.ok) {
          report.pushed++;
          await recordAlertInbox(env, r.email, {
            id: aid, ts: new Date().toISOString(), kind: "political",
            ticker: (sig.affected && sig.affected[0]) || "大盤",
            name: (sig.affected && sig.affected[0]) ? displayName(sig.affected[0]) : "政壇/大盤",
            title: sig.headline_zh, url: sig.post_url || "https://marketdaily.ai/dashboard.html",
            reason: sig.reason_zh || sig.why_zh || "", stance: sig.stance || "", action: sig.action || "",
            severity: sig.severity, category: "political", speculative: sig.kind !== "action",
          });
        }
      }
    } else {
      for (const r of targets) fired.recipients.push({ email: r.email, status: "would-push" });
    }
    report.fired.push(fired);
    await env.USER_PREFS.put(seenKey, "1", { expirationTtl: SEEN_TTL });
    await env.USER_PREFS.put(capKey, String(sent + 1), { expirationTtl: COUNT_TTL });
  }
  // 推播炸了就告訴 admin(對齊 runPipeline 既有邏輯——political 管線之前完全沒有這段,
  // VAPID/push 若壞掉,這條頻道會一直沒人知道訂閱者早就收不到)。
  if (push) {
    const failed = [];
    for (const f of report.fired) {
      for (const r of f.recipients || []) {
        const s = r.status || "";
        if (s.startsWith("fail:")) failed.push({ email: r.email, status: s, headline: f.headline });
      }
    }
    if (failed.length) {
      const lines = failed.slice(0, 3).map((f) =>
        `• ${f.email} ${f.status}\n  ${(f.headline || "").slice(0, 50)}`);
      await alertAdmin(env,
        `政壇推播失敗 ${failed.length} 筆(/${report.fired.length} 達標事件)\n${lines.join("\n")}` +
        (failed.length > 3 ? `\n…還有 ${failed.length - 3} 筆` : ""), { channel: "political" });
    }
  }
  return done();
}

export default {
  async scheduled(event, env, ctx) {
    // 2 個 cron 分支(每小時 LINE canary 已隨 LINE 退役移除):
    //   "*/2 * * * *"  → 主管線(抓新聞 → 比對 → 推播)
    //   "*/15 * * * *" → 政壇市場訊號(政治人物 X 貼文 → web push,需 XAI_API_KEY)
    if (event.cron === "*/15 * * * *") {
      const enabled = (await env.USER_PREFS.get("alert:enabled")) === "true";
      ctx.waitUntil(runPoliticalPipeline(env, { push: enabled }));
      return;
    }
    const enabled = (await env.USER_PREFS.get("alert:enabled")) === "true";
    // 不論 dry/live 都 persist:每則新聞只評估一次,控 AI 成本。
    ctx.waitUntil(runPipeline(env, { push: enabled, persist: true }));
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    // Admin token check — /dry-run 會消耗 AI 額度,/recent 含訂閱者持股暗示,
    // /token-test 會洩漏 token metadata,/check 含 secret 開關+config。
    // 未設 ADMIN_TOKEN/INTERNAL_TOKEN secret 時 → fail-closed (回 403)。
    function authed() {
      const tok = env.ADMIN_TOKEN || env.INTERNAL_TOKEN;
      if (!tok) return false;
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
        || url.searchParams.get("token") || "";
      if (got.length !== tok.length) return false;
      let diff = 0;
      for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ tok.charCodeAt(i);
      return diff === 0;
    }

    if (url.pathname === "/check") {
      // 公開回最低限度健康狀態;敏感細節(secret 開關 / config / lastRun)要帶 token。
      let kvOk = true;
      try { await env.USER_PREFS.get("alert:enabled"); } catch { kvOk = false; }
      const mode = (await env.USER_PREFS.get("alert:enabled")) === "true" ? "live" : "dry";
      if (!authed()) {
        return json({ ok: true, ts: new Date().toISOString(), mode, kv: kvOk });
      }
      const lastRaw = await env.USER_PREFS.get("alert:laststatus");
      const canaryRaw = await env.USER_PREFS.get("alert:lastcanary");
      const lastPolRaw = await env.USER_PREFS.get("alert:pol_laststatus");
      return json({
        ok: true,
        ts: new Date().toISOString(),
        mode,
        kv: kvOk,
        secrets: {
          ANTHROPIC_API_KEY: !!env.ANTHROPIC_API_KEY,
          LINE_CHANNEL_ACCESS_TOKEN: !!env.LINE_CHANNEL_ACCESS_TOKEN,
          LINE_CHANNEL_ID: !!env.LINE_CHANNEL_ID,
          LINE_CHANNEL_SECRET: !!env.LINE_CHANNEL_SECRET,
          ADMIN_LINE_USER_ID: !!env.ADMIN_LINE_USER_ID,
          INTERNAL_TOKEN: !!env.INTERNAL_TOKEN,
          XAI_API_KEY: !!env.XAI_API_KEY,
        },
        config: {
          severityThreshold: SEVERITY_THRESHOLD, speculativeThreshold: SPECULATIVE_THRESHOLD,
          dailyCap: DAILY_CAP, maxAgeHours: MAX_AGE_HOURS, preScoreFloor: PRESCORE_FLOOR,
          // LINE canary 已隨 LINE 退役移除,現行兩條 cron 見 wrangler.toml [triggers]
          crons: ["*/2 * * * *(pipeline)", "*/15 * * * *(political)"],
        },
        lastRun: lastRaw ? JSON.parse(lastRaw) : null,
        lastCanary: canaryRaw ? JSON.parse(canaryRaw) : null,
        lastPolitical: lastPolRaw ? JSON.parse(lastPolRaw) : null,
      });
    }

    // 手動跑 canary(等同每小時自動排程的那個):驗 token + LINE API,失敗會 alertAdmin
    if (url.pathname === "/canary") {
      if (!authed()) return json({ error: "forbidden" }, 403);
      const result = await canaryCheck(env);
      return json(result);
    }

    // 診斷:查 LINE 官方月額度上限與已用量(回答「推播是否被額度卡住」)。
    // 接受廣義 token 候選(含本機備援 _2 把),timing-safe。
    if (url.pathname === "/quota") {
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
        || url.searchParams.get("token") || "";
      const candidates = [env.ADMIN_TOKEN, env.INTERNAL_TOKEN, env.ADMIN_PUSH_TOKEN, env.ADMIN_PUSH_TOKEN_2, env.INTERNAL_TOKEN_2, env.MARKETING_TARGETS_TOKEN].filter(Boolean);
      let okAuth = false;
      for (const t of candidates) {
        if (got.length !== t.length) continue;
        let diff = 0;
        for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ t.charCodeAt(i);
        if (diff === 0) { okAuth = true; break; }
      }
      if (!okAuth) return json({ error: "forbidden" }, 403);
      const token = await lineToken(env, { force: true });
      if (!token) return json({ ok: false, reason: "line_token_unavailable" }, 503);
      const h = { authorization: `Bearer ${token}` };
      const qRes = await fetch("https://api.line.me/v2/bot/message/quota", { headers: h });
      const cRes = await fetch("https://api.line.me/v2/bot/message/quota/consumption", { headers: h });
      const quota = qRes.ok ? await qRes.json() : { status: qRes.status, body: (await qRes.text()).slice(0, 200) };
      const consumption = cRes.ok ? await cRes.json() : { status: cRes.status, body: (await cRes.text()).slice(0, 200) };
      let remaining = null, exhausted = null;
      if (quota.type === "limited" && typeof quota.value === "number" && typeof consumption.totalUsage === "number") {
        remaining = quota.value - consumption.totalUsage;
        exhausted = remaining <= 0;
      } else if (quota.type === "none") {
        exhausted = false; // 無上限方案
      }
      return json({ ok: true, ts: new Date().toISOString(), quota, consumption, remaining, exhausted });
    }

    // 診斷:驗證 LINE 動態 OAuth swap 是否能拿到有效 token(不洩漏 token 本身)
    if (url.pathname === "/token-test") {
      if (!authed()) return json({ error: "forbidden" }, 403);
      try {
        await env.USER_PREFS.delete("alert:linetoken");
        const t = await lineToken(env, { force: true });
        if (!t) return json({ ok: false, reason: "OAuth swap returned no token" }, 500);
        // 用一個明顯無效的 userId 試推播,期望 LINE 回 400/403 而非 401(401 才是 token 問題)
        const probe = await fetch(LINE_PUSH_URL, {
          method: "POST",
          headers: { authorization: `Bearer ${t}`, "content-type": "application/json" },
          body: JSON.stringify({ to: "U0000000000000000000000000000000", messages: [{ type: "text", text: "x" }] }),
        });
        return json({
          ok: true,
          tokenLen: t.length,
          tokenHead: t.slice(0, 6) + "...",
          probeStatus: probe.status,
          probeBody: (await probe.text()).slice(0, 200),
          interpretation: probe.status === 401
            ? "❌ token 仍被 LINE 視為無效"
            : "✅ token 有效(non-401);400/403 屬無效 userId 是預期的",
        });
      } catch (e) {
        return json({ ok: false, error: e.message }, 500);
      }
    }

    // 推 LINE 訊息給 admin(daily digest pipeline / audit 失分通知用)
    // 認證:ADMIN_PUSH_TOKEN(daily pipeline 專用,GH secret MARKETDAILY_ALERT_TOKEN 同值)
    // 或 MARKETING_TARGETS_TOKEN / INTERNAL_TOKEN(timing-safe)。
    // 2026-06-11 修 admin LINE 403:GH 端舊值對不上;旋轉共用把會炸其他 caller,故加專用把。
    if (url.pathname === "/internal/admin-line-push" && request.method === "POST") {
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
      // ADMIN_PUSH_TOKEN_2:2026-06-12 GitHub Actions 被停用時為本機備援 runner 加的第二把
      const candidates = [env.ADMIN_PUSH_TOKEN, env.ADMIN_PUSH_TOKEN_2, env.MARKETING_TARGETS_TOKEN, env.INTERNAL_TOKEN].filter(Boolean);
      let okAuth = false;
      for (const t of candidates) {
        if (got.length !== t.length) continue;
        let diff = 0;
        for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ t.charCodeAt(i);
        if (diff === 0) { okAuth = true; break; }
      }
      if (!okAuth) return json({ error: "forbidden" }, 403);
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad_body" }, 400); }
      const message = String(body.message || "").slice(0, 4900);
      if (!message) return json({ error: "empty_message" }, 400);
      let ok = false; const channels = [];
      // 自有 web push 到所有 admin 裝置(LINE 已退役,唯一通道)
      // evTs 同時當 KV 事件 ts 與深連結錨點:點通知直跳後台告警該列(07-30 Delvin 要求,同新聞跳原文原理)
      const evTs = Date.now();
      if (await webPushAdmin(env, JSON.stringify({
        title: "🔔 MarketDaily", body: message.slice(0, 300), url: "https://marketdaily.ai/admin#alerts-" + evTs,
      }), message, evTs)) { ok = true; channels.push("webpush"); }
      // lineStatus 欄位保留 null 給既有呼叫端(watchdog/runner)解析相容
      return json({ ok, channels, lineStatus: null });
    }

    // 程式化標記告警已解決(解決問題的那一方呼叫:Claude session / winrig 自動修復腳本)。
    // Delvin 不該手動判斷解沒解決——修完事故必打這支,帶 note 說明怎麼解的(CLAUDE.md 慣例)。
    // body:{ts?: 精準定位, match?: 子字串找最新一則未解決, note?: 解決說明} 至少給 ts 或 match。
    if (url.pathname === "/internal/admin-events-resolve" && request.method === "POST") {
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
      const candidates = [env.ADMIN_PUSH_TOKEN, env.ADMIN_PUSH_TOKEN_2, env.MARKETING_TARGETS_TOKEN, env.INTERNAL_TOKEN].filter(Boolean);
      let okAuth = false;
      for (const t of candidates) {
        if (got.length !== t.length) continue;
        let diff = 0;
        for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ t.charCodeAt(i);
        if (diff === 0) { okAuth = true; break; }
      }
      if (!okAuth) return json({ error: "forbidden" }, 403);
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad_body" }, 400); }
      const ts = Number(body.ts) || 0;
      const match = String(body.match || "").slice(0, 200);
      if (!ts && !match) return json({ error: "need_ts_or_match" }, 400);
      let events = [];
      try { const raw = await env.USER_PREFS.get("admin_events"); if (raw) events = JSON.parse(raw); } catch {}
      if (!Array.isArray(events)) events = [];
      const ev = ts
        ? events.find((e) => e && e.ts === ts)
        : events.find((e) => e && !e.resolved && `${e.title}\n${e.body}`.includes(match));
      if (!ev) return json({ error: "not_found" }, 404);
      ev.resolved = Date.now();
      const note = String(body.note || "").slice(0, 300);
      if (note) ev.resolved_note = note;
      await env.USER_PREFS.put("admin_events", JSON.stringify(events), { expirationTtl: 90 * 24 * 3600 });
      return json({ ok: true, ts: ev.ts, title: ev.title, resolved: ev.resolved });
    }

    // 供應鏈事件(winrig intel/supply_chain_watch.py 上送):官方公告的新合作/新供應關係。
    // 每則:KV pending(dashboard 產業鏈🆕區塊經 stripe-webhook /supply-chain-updates 讀)
    // + 比對全體用戶持股發 web push + 站內收件匣 + admin 彙總通知。事件級去重(scdone marker),
    // 呼叫端可安全重送同批(上送失敗重試不會造成重複推播)。
    if (url.pathname === "/internal/supply-chain-event" && request.method === "POST") {
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
      const candidates = [env.ADMIN_PUSH_TOKEN, env.ADMIN_PUSH_TOKEN_2, env.INTERNAL_TOKEN].filter(Boolean);
      let okAuth = false;
      for (const t of candidates) {
        if (got.length !== t.length) continue;
        let diff = 0;
        for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ t.charCodeAt(i);
        if (diff === 0) { okAuth = true; break; }
      }
      if (!okAuth) return json({ error: "forbidden" }, 403);
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad_body" }, 400); }
      const events = Array.isArray(body.events) ? body.events.slice(0, 20) : [];
      if (!events.length) return json({ error: "no_events" }, 400);
      let recipients = null;
      const results = [];
      const adminLines = [];
      for (const ev of events) {
        if (!ev || typeof ev !== "object") {
          results.push({ id: "", stored: false, error: "bad_event" });
          continue;
        }
        const id = String(ev.id || "").replace(/[^a-z0-9]/gi, "").slice(0, 40);
        const code = String(ev.code || "").trim().toUpperCase();
        const headline = String(ev.headline || "").slice(0, 300);
        if (!id || !headline || !/^[A-Z0-9.\-]{1,12}$/.test(code)) {
          results.push({ id, stored: false, error: "bad_event" });
          continue;
        }
        if (await env.USER_PREFS.get(`scdone:${id}`)) {
          results.push({ id, stored: true, dup: true });
          continue;
        }
        const rec = {
          id,
          date: String(ev.date || "").slice(0, 10),
          market: ev.market === "us" ? "us" : "tw",
          code,
          name: String(ev.name || "").slice(0, 40),
          counterparty: ev.counterparty ? String(ev.counterparty).slice(0, 40) : null,
          headline,
          url: /^https:\/\//.test(ev.url || "") ? String(ev.url).slice(0, 300) : null,
          source_type: String(ev.source_type || "").slice(0, 10),
          ts: Date.now(),
        };
        // dashboard 產業鏈🆕區塊 pending 清單(每檔留最新 10 則)
        const pkey = `scpend:${code}`;
        let list = [];
        try { const raw = await env.USER_PREFS.get(pkey); if (raw) list = JSON.parse(raw); } catch {}
        list = [rec, ...(Array.isArray(list) ? list : []).filter((x) => x && x.id !== id)].slice(0, 10);
        await env.USER_PREFS.put(pkey, JSON.stringify(list), { expirationTtl: 120 * 24 * 3600 });
        // 比對全體用戶持股 → web push + 站內收件匣(事實揭露,全體用戶同權,合規)
        if (!recipients) recipients = await premiumRecipients(env);
        const holders = recipients.filter((r) => r.holdings.has(code));
        const label = rec.name && rec.name !== code ? `${rec.name}(${code})` : code;
        const scAnchor = alertAnchor(`sc-${id}`);
        let pushed = 0;
        const notifStr = JSON.stringify({
          title: `🔗 ${label}｜供應鏈動態`,
          body: (rec.counterparty ? `對手方:${rec.counterparty}｜` : "") + headline.slice(0, 150),
          url: rec.url || "https://marketdaily.ai/dashboard.html#alerts",
          tag: `md-sc-${id}`,
        });
        for (const r of holders) {
          const dr = await deliverAlert(env, r, notifStr);
          if (dr.ok) pushed++;
          await recordAlertInbox(env, r.email, {
            id: scAnchor, ts: new Date().toISOString(), kind: "supply_chain", ticker: code,
            name: rec.name || code, title: headline, url: rec.url,
            reason: rec.source_type === "8k" ? "官方申報:8-K 重大合約" : "官方公告:新合作/供應關係",
            severity: 6, category: "supply_chain", speculative: false,
          });
        }
        // admin 收得到每件彙總推播,提醒紀錄也要看得到全部事件(非持股者上面迴圈不會寫)
        if (env.ADMIN_EMAIL && !holders.some((h) => h.email === env.ADMIN_EMAIL)) {
          await recordAlertInbox(env, env.ADMIN_EMAIL, {
            id: scAnchor, ts: new Date().toISOString(), kind: "supply_chain", ticker: code,
            name: rec.name || code, title: headline, url: rec.url,
            reason: rec.source_type === "8k" ? "官方申報:8-K 重大合約" : "官方公告:新合作/供應關係",
            severity: 6, category: "supply_chain", speculative: false,
          });
        }
        await env.USER_PREFS.put(`scdone:${id}`, "1", { expirationTtl: 60 * 24 * 3600 });
        adminLines.push(`${label} ${headline.slice(0, 50)}${holders.length ? `(推${pushed}/${holders.length}人)` : ""}`);
        results.push({ id, stored: true, pushed, holders: holders.length });
      }
      if (adminLines.length) {
        await webPushAdmin(env, JSON.stringify({
          title: `🔗 供應鏈事件×${adminLines.length}`,
          body: adminLines.join(";").slice(0, 290),
          url: "https://marketdaily.ai/dashboard.html#alerts",
        }));
      }
      return json({ ok: true, results });
    }

    // 08:15 韓股開盤預警(外盤重挫閘 phase 2,2026-07-21):winrig intel/kospi_open_alert.py
    // 於 08:05-08:25 TW 掃 KOSPI 開盤 gap,<= -2%(預先登記門檻)即打這支推全體。
    // 回測 16.5 年(quant_lab/crash_gate_night/GLOBAL_LEAD.md):gap<=-2% 共 64 天,台股當日
    // 均 -2.21%、95% 收黑、P(<=-3%)=29.7%;頻率約 3.9 次/年,無轟炸疑慮。市場級警報非個股
    // 分析,全體用戶同內容(合規)。dry=true 只推 admin 不進用戶收件匣(測試/演練用)。
    if (url.pathname === "/internal/market-open-alert" && request.method === "POST") {
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
      // 候選清單對齊 admin-line-push:winrig .env MARKETDAILY_ALERT_TOKEN 實為 MARKETING_TARGETS_TOKEN 同值
      const candidates = [env.ADMIN_PUSH_TOKEN, env.ADMIN_PUSH_TOKEN_2, env.MARKETING_TARGETS_TOKEN, env.INTERNAL_TOKEN].filter(Boolean);
      let okAuth = false;
      for (const t of candidates) {
        if (got.length !== t.length) continue;
        let diff = 0;
        for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ t.charCodeAt(i);
        if (diff === 0) { okAuth = true; break; }
      }
      if (!okAuth) return json({ error: "forbidden" }, 403);
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad_body" }, 400); }
      const id = String(body.id || "").replace(/[^a-z0-9-]/gi, "").slice(0, 40);
      const gap = Number(body.gap_pct);
      const dry = body.dry === true;
      if (!id || !Number.isFinite(gap)) return json({ error: "bad_event" }, 400);
      // 門檻在 worker 端二次強制:scanner 出 bug 亂送也推不出去
      if (gap > -2.0) return json({ ok: true, skipped: "below_threshold", gap });
      if (!dry && (await env.USER_PREFS.get(`moadone:${id}`))) {
        return json({ ok: true, dup: true });
      }
      const gapStr = gap.toFixed(2);
      const anchor = alertAnchor(`moa-${id}`);
      const notifStr = JSON.stringify({
        title: `⚠️ 韓股開盤重挫 ${gapStr}%｜台股開盤前警報`,
        body: `台股 09:00 開盤前訊號:KOSPI 今晨開盤下殺 ${gapStr}%。` +
              `歷史統計(16 年)這種日子台股 95% 收黑、約三成跌逾 3%。` +
              `立場:防守｜動作:開盤別急著進場,持股守好停損,等企穩再考慮。`,
        url: "https://marketdaily.ai/dashboard.html#alerts",
        tag: `md-moa-${id}`,
      });
      const inboxRec = {
        id: anchor, ts: new Date().toISOString(), kind: "market_open", ticker: "TWII",
        name: "台股大盤", title: `韓股開盤重挫 ${gapStr}%——台股開盤前防守警報`,
        url: null, reason: `KOSPI 開盤 gap ${gapStr}%(門檻 -2%);16 年回測:此情境台股當日均 -2.21%、95% 收黑`,
        severity: 8, category: "market", speculative: false,
      };
      let pushed = 0, total = 0;
      if (dry) {
        await webPushAdmin(env, JSON.stringify({
          title: `[DRY] 韓股開盤預警演練 ${gapStr}%`,
          body: "dry run:未推任何用戶。管線端到端正常。",
          url: "https://marketdaily.ai/dashboard.html#alerts",
        }));
        return json({ ok: true, dry: true, gap });
      }
      const recipients = await premiumRecipients(env);
      total = recipients.length;
      for (const r of recipients) {
        const dr = await deliverAlert(env, r, notifStr);
        if (dr.ok) pushed++;
        await recordAlertInbox(env, r.email, inboxRec);
      }
      await env.USER_PREFS.put(`moadone:${id}`, "1", { expirationTtl: 7 * 24 * 3600 });
      await webPushAdmin(env, JSON.stringify({
        title: `⚠️ 韓股開盤預警已推全體(${pushed}/${total})`,
        body: `KOSPI 開盤 gap ${gapStr}%。id=${id}`,
        url: "https://marketdaily.ai/dashboard.html#alerts",
      }));
      return json({ ok: true, pushed, total, gap });
    }

    // 行銷貼文 multicast 目標清單:列出所有綁過 LINE 但 plan != premium 的 userId。
    // marketing/auto_post.py post_line 會打這支取得排除 premium 的 multicast targets。
    if (url.pathname === "/internal/marketing-line-targets") {
      // 接受 MARKETING_TARGETS_TOKEN 或 INTERNAL_TOKEN(timing-safe)
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "")
        || url.searchParams.get("token") || "";
      const candidates = [env.MARKETING_TARGETS_TOKEN, env.INTERNAL_TOKEN].filter(Boolean);
      let okAuth = false;
      for (const t of candidates) {
        if (got.length !== t.length) continue;
        let diff = 0;
        for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ t.charCodeAt(i);
        if (diff === 0) { okAuth = true; break; }
      }
      if (!okAuth) return json({ error: "forbidden" }, 403);
      const targets = [];
      let scanned = 0, excluded = 0;
      let cursor;
      do {
        const page = await env.USER_PREFS.list({ prefix: "line:", cursor });
        for (const k of page.keys) {
          scanned++;
          const email = k.name.slice(5);
          const plan = await env.USER_PREFS.get(`plan:${email}`);
          if (plan === "premium") { excluded++; continue; }
          const userId = await env.USER_PREFS.get(k.name);
          if (userId) targets.push(userId);
        }
        cursor = page.list_complete ? null : page.cursor;
      } while (cursor);
      return json({ count: targets.length, scanned, excludedPremium: excluded, targets });
    }

    if (url.pathname === "/dry-run") {
      if (!authed()) return json({ error: "forbidden" }, 403);
      try {
        return json(await runPipeline(env, { push: false, persist: false }));
      } catch (e) {
        // 不洩漏 stack;只回 generic message
        return json({ ok: false, error: String(e.message || "error").slice(0, 200) }, 500);
      }
    }

    // 本機 X 掃描器(political_watch/watch_x.py)送進原始貼文 → Claude 分析 → 推播。
    // 零 xAI 成本路線。auth:POLITICAL_INGEST_TOKEN(timing-safe),fail-closed。
    if (url.pathname === "/political-ingest" && request.method === "POST") {
      const tok = env.POLITICAL_INGEST_TOKEN || "";
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
      let ok = !!tok && got.length === tok.length;
      if (ok) { let d = 0; for (let i = 0; i < got.length; i++) d |= got.charCodeAt(i) ^ tok.charCodeAt(i); ok = d === 0; }
      if (!ok) return json({ error: "forbidden" }, 403);
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad json" }, 400); }
      // X 掃描器回報 session 失效 → 通知 admin 重登(web push 優先,alertAdmin 自帶每小時節流)
      if (body.session_dead) {
        await alertAdmin(env, "⚠️ 政壇 X 掃描器 session 失效，winrig 抓不到貼文。請在 Mac 跑 `python3 watch_x.py --login` 重登 X，再把 auth_state.json 搬回 winrig。", { channel: "political" });
        return json({ ok: true, alerted: true });
      }
      const posts = (body.posts || []).filter(p => p && p.handle && p.text).slice(0, 30);
      if (!posts.length) return json({ ok: true, analyzed: 0, note: "no posts" });
      // 原始層去重(pre-AI,省 Claude):同一貼文 URL 只分析一次
      const fresh = [];
      for (const p of posts) {
        const k = "pol:rawseen:" + encodeURIComponent(p.url || (p.handle + ":" + String(p.text).slice(0, 80))).slice(0, 480);
        if (await env.USER_PREFS.get(k)) continue;
        await env.USER_PREFS.put(k, "1", { expirationTtl: SEEN_TTL });
        fresh.push(p);
      }
      if (!fresh.length) return json({ ok: true, analyzed: 0, note: "all seen" });
      const ana = await analyzePoliticalPosts(env, fresh, await fetchGlobalLead(env));
      if (ana.error) return json({ ok: false, error: ana.error }, 502);
      const enabled = (await env.USER_PREFS.get("alert:enabled")) === "true";
      const report = await runPoliticalPipeline(env, {
        push: enabled && !body.dry, signals: ana.signals, source: "x-scrape",
      });
      return json({ ok: true, analyzed: fresh.length, signals: ana.signals, report });
    }

    // 政壇訊號 dry-run:抓 Grok 訊號+列「會推給誰」但不真推(消耗 xAI 額度,需 auth)。
    // ?window=24 可拉長搜尋窗(預設 2h),設好 XAI_API_KEY 後用這支驗收。
    if (url.pathname === "/political-dry") {
      if (!authed()) return json({ error: "forbidden" }, 403);
      try {
        const w = Math.min(48, parseInt(url.searchParams.get("window") || "2", 10) || 2);
        const sigs = await fetchPoliticalSignals(env, w);
        const pipeline = await runPoliticalPipeline(env, { push: false });
        return json({ raw_signals: sigs, pipeline });
      } catch (e) {
        return json({ ok: false, error: String(e.message || "error").slice(0, 200) }, 500);
      }
    }

    // 近期達標(severity≥7)的提醒紀錄 —— 含訂閱者持股暗示,需 auth。
    if (url.pathname === "/recent") {
      if (!authed()) return json({ error: "forbidden" }, 403);
      const raw = await env.USER_PREFS.get("alert:recent");
      return json({ recent: raw ? JSON.parse(raw) : [] });
    }

    return new Response("MarketDaily alert-worker — /check (token for detail) /dry-run /recent /token-test (token required)", {
      status: 200,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  },
};
