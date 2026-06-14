// MarketDaily — Premium 即時 LINE 重大新聞提醒 alert-worker
// 每 2 分鐘:抓新聞 → 去重 → 規則粗篩 → 比對 Premium 持股 → AI 嚴重度 → LINE 推播。
// 設計規格:specs/2026-05-22-premium-realtime-line-alerts-design.md

import { fetchNews } from "./news_source.js";
import { displayName } from "./stock_names.js";
import { fetchPoliticalSignals, formatPoliticalMsg, analyzePoliticalPosts } from "./political_source.js";

const SEVERITY_THRESHOLD = 7;          // 已發生/已公告事件的推播門檻
const SPECULATIVE_THRESHOLD = 9;       // 傳言/觀點/臆測文門檻拉高,避免「If…will…」評論文當 🚨重大消息 轟炸
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
];

// 各事件類型的平均重大度權重 —— 規則預評分用,只擋明顯偏弱的,真正嚴重度仍交給 AI 判。
const EVENT_WEIGHT = {
  distress: 95, mna: 88, guidance: 82, regulatory: 76, earnings: 72,
  political: 70, incident: 66, legal: 62, leadership: 56, rating: 48, trading: 46,
};

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

// 列出所有 plan=premium 且至少綁了一個推播通道(LINE 或 自有 web push)的用戶與持股。
async function premiumRecipients(env) {
  const map = new Map(); // email -> {email, userId, pushSub, holdings}
  async function ensure(email) {
    if (map.has(email)) return map.get(email);
    const plan = await env.USER_PREFS.get(`plan:${email}`);
    if (plan !== "premium") { map.set(email, null); return null; }
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
    const r = { email, userId: null, pushSub: null, holdings };
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
  await scan("line:", async (r, key) => { r.userId = await env.USER_PREFS.get(key); });
  await scan("pushsub:", async (r, key) => {
    try { r.pushSub = JSON.parse(await env.USER_PREFS.get(key)); } catch {}
  });
  return [...map.values()].filter((r) => r && (r.userId || r.pushSub));
}

// Claude 嚴重度判定:輸入新聞 + 相關 ticker,輸出 {severity 0-10, reason}。
async function aiSeverity(env, news, tickers) {
  if (!env.ANTHROPIC_API_KEY) return { severity: null, reason: "AI 未設定", skipped: true };
  const names = tickers.map((t) => `${t}(${displayName(t)})`).join("、");
  const prompt = `你是財經新聞嚴重度評分員。判斷這則新聞對「持有 ${names} 的投資人」有多重大。

標題:${news.title}
摘要:${news.summary || "(無)"}
來源:${news.source}

評分標準(severity 0-10):
- 9-10:破產、重大併購、財測大幅下修、CEO 突然去職、重大訴訟敗訴等,股價可能立即大幅變動。
- 7-8:財報明顯優於/低於預期、重要評等調整、監管調查、產品重大事件。
- 4-6:一般財經報導、分析師例行評論、影響有限。
- 0-3:無實質影響、舊聞、與該公司關聯薄弱。

另外判斷三件事:
- category:這則屬於「event」(已發生或已正式公告的事實)、「rumor」(未經證實的傳言/小道消息)、還是「opinion」(評論、分析、假設推演,例如「如果…將會…」「為什麼…」)。臆測與評論不是事件,即使聳動也不應給高分。
- stance:對持有 ${names} 的投資人,你的操作傾向,從「加碼/續抱/觀望/減碼/賣出」擇一。
- action:一句繁體中文,說明此刻具體該怎麼做與理由。若 category 是 rumor 或 opinion,務必明說「尚未證實/僅為推測,對基本面無立即影響」,不要建議因此追高或殺低,可提示真正該盯的下一個事件(財報/官方說法等)。

只輸出 JSON,格式:{"severity": <0-10 整數>, "category": "event|rumor|opinion", "stance": "加碼|續抱|觀望|減碼|賣出", "reason": "<一句:為何跟投資人有關>", "action": "<一句:此刻該怎麼做與理由>"}`;
  try {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 256,
        messages: [{ role: "user", content: prompt }],
      }),
    });
    if (!res.ok) return { severity: null, reason: `AI 錯誤 ${res.status}`, error: true };
    const data = await res.json();
    const text = (data.content || []).map((c) => c.text || "").join("");
    const m = text.match(/\{[\s\S]*\}/);
    if (!m) return { severity: null, reason: "AI 回應無法解析", error: true };
    const parsed = JSON.parse(m[0]);
    let sev = Math.round(Number(parsed.severity));
    if (isNaN(sev)) sev = 0;
    const cat = ["event", "rumor", "opinion"].includes(parsed.category) ? parsed.category : "event";
    const stanceSet = ["加碼", "續抱", "觀望", "減碼", "賣出"];
    const stance = stanceSet.includes(parsed.stance) ? parsed.stance : "";
    return {
      severity: Math.max(0, Math.min(10, sev)),
      category: cat,
      stance,
      reason: String(parsed.reason || "").slice(0, 200),
      action: String(parsed.action || "").slice(0, 200),
    };
  } catch (e) {
    return { severity: null, reason: `AI 例外:${e.message}`, error: true };
  }
}

// 取 LINE Messaging API 推播 token。
// 預設順序:KV cache(alert:linetoken,動態 OAuth 結果)→ static env LINE_CHANNEL_ACCESS_TOKEN
// → 動態 OAuth swap(client_credentials)。force=true 跳過 cache 和 static,
// 直接動態換(linePush 收 401 時用)。
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
function pushNotif(news, ticker, severity, reason) {
  const name = ticker === "大盤" ? "大盤" : displayName(ticker);
  return JSON.stringify({
    title: severity >= 9 ? `🚨 ${name}｜重大消息` : `📈 ${name}｜即時提醒`,
    body: (news.title || reason || "").slice(0, 160),
    url: news.url || "https://marketdaily.ai/dashboard.html",
    tag: `md-${ticker}-${(news.publishedAt || "").slice(0, 13)}`,
  });
}
// 統一投遞:對單一收件者嘗試所有可用通道(LINE + 自有 web push),任一成功即算送達。
async function deliverAlert(env, r, lineTok, text, notifStr) {
  let ok = false; const channels = []; let lastStatus = 0;
  if (r.userId && lineTok) {
    const lr = await linePush(env, lineTok, r.userId, text);
    if (lr.ok) { ok = true; channels.push("line"); }
    else { lastStatus = lr.status; if (lr.status === 400 || lr.status === 403) await env.USER_PREFS.put(`linestale:${r.email}`, new Date().toISOString()); }
  }
  if (r.pushSub) {
    const wr = await webPush(env, r.pushSub, notifStr);
    if (wr.ok) { ok = true; channels.push("webpush"); }
    else { lastStatus = wr.status || lastStatus; if (wr.status === 404 || wr.status === 410) await env.USER_PREFS.delete(`pushsub:${r.email}`); }
  }
  return { ok, channels, status: lastStatus };
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

async function linePush(env, token, userId, text) {
  const tryOnce = (t) => fetch(LINE_PUSH_URL, {
    method: "POST",
    headers: { authorization: `Bearer ${t}`, "content-type": "application/json" },
    body: JSON.stringify({ to: userId, messages: [{ type: "text", text }] }),
  });
  let res = await tryOnce(token);
  // 401 = token 失效(過期或被 LINE 撤銷)。清 cache、強制動態換,重試一次。
  // 2026-05-24 17:54 UTC 起 static LINE_CHANNEL_ACCESS_TOKEN 失效,28 筆推播全炸,
  // 因此加 self-healing fallback。
  if (res.status === 401) {
    await env.USER_PREFS.delete("alert:linetoken");
    const fresh = await lineToken(env, { force: true });
    if (fresh && fresh !== token) {
      res = await tryOnce(fresh);
    }
  }
  if (res.ok) return { ok: true };
  return { ok: false, status: res.status, body: (await res.text()).slice(0, 300) };
}

// 主動告訴 admin(Delvin 的 LINE):推播 / canary 出狀況。
// 節流:同小時最多 1 則,避免炸訊息;ADMIN_LINE_USER_ID 沒設就跳過。
async function alertAdmin(env, summary) {
  const hourKey = `admin_alert:${new Date().toISOString().slice(0, 13)}`;
  if (await env.USER_PREFS.get(hourKey)) return;
  let delivered = false;
  // 1) 自有 web push(無額度限制,優先)
  if (env.ADMIN_EMAIL) {
    try {
      const raw = await env.USER_PREFS.get(`pushsub:${env.ADMIN_EMAIL}`);
      if (raw) {
        const wr = await webPush(env, JSON.parse(raw), JSON.stringify({
          title: "🚨 MarketDaily Alert",
          body: summary.slice(0, 300),
          url: "https://marketdaily.ai/dashboard.html",
        }));
        if (wr.ok) delivered = true;
      }
    } catch {}
  }
  // 2) LINE(備援,受 200/月額度限制)
  if (env.ADMIN_LINE_USER_ID) {
    const token = await lineToken(env, { force: true });
    if (token) {
      try {
        const res = await fetch(LINE_PUSH_URL, {
          method: "POST",
          headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
          body: JSON.stringify({
            to: env.ADMIN_LINE_USER_ID,
            messages: [{ type: "text", text: `🚨 MarketDaily Alert\n\n${summary}\n\n— alert-worker` }],
          }),
        });
        if (res.ok) delivered = true;
      } catch {}
    }
  }
  if (delivered) {
    await env.USER_PREFS.put(hourKey, "1", { expirationTtl: 3700 });
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

    // 比對 Premium 持有者
    let holders = recipients.filter((r) => news.tickers.some((t) => r.holdings.has(t)));
    // 政治/政策市場級事件(全面關稅、利率決議這類沒點名個股的)→ 影響所有人的持倉,
    // 推給全體綁定者;雜訊防線=門檻加嚴到 8(點名個股的照常 7)。
    const marketWide = eventType === "political" && !news.tickers.length;
    if (!holders.length && marketWide) holders = recipients;
    if (!holders.length) {
      if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
      report.candidates.push({
        title: news.title, source: news.source, url: news.url,
        tickers: news.tickers, eventType, preScore, severity: null,
        reason: "通過粗篩但無 Premium 持有者", recipients: [],
      });
      continue;
    }
    report.counts.premiumMatched++;

    // AI 嚴重度
    const { severity, reason, category, stance, action, skipped, error } = await aiSeverity(env, news, news.tickers);
    if (!skipped) report.counts.aiEvaluated++;
    // 臆測/觀點:標題標記命中 或 AI 判 rumor/opinion → 門檻拉高 + 標籤改「觀點／傳言」。
    const speculative = isSpeculative(`${news.title} ${news.summary || ""}`)
      || category === "rumor" || category === "opinion";
    let threshold = speculative ? SPECULATIVE_THRESHOLD : SEVERITY_THRESHOLD;
    if (marketWide) threshold = Math.max(threshold, 8);
    const cand = {
      title: news.title, source: news.source, url: news.url,
      tickers: news.tickers, eventType, preScore, severity, category, stance, action,
      speculative, threshold, reason,
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
    if (severity < threshold) {
      if (persist) await env.USER_PREFS.put(seenKey, report.ts, { expirationTtl: SEEN_TTL });
      if (speculative) cand.reason = `${cand.reason || ""}(傳言/觀點,需 severity≥${threshold} 才推,本則 ${severity})`.trim();
      report.candidates.push(cand);
      continue;
    }

    // 通過門檻 → 逐持有者推播(去重 + 每日上限)
    const today = twDate();
    const token = push ? await lineToken(env) : null;
    if (push && !token) report.errors.push("line:無推播 token(web push 仍會嘗試)");
    for (const h of holders) {
      const hit = news.tickers.find((t) => h.holdings.has(t)) || (marketWide ? "大盤" : undefined);
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
      const msg = alertMessage(news, hit, severity, reason, { speculative, stance, action });
      const pushed = await deliverAlert(env, h, token, msg, pushNotif(news, hit, severity, reason));
      if (pushed.ok) {
        await env.USER_PREFS.put(cluster, report.ts, { expirationTtl: PUSHED_TTL });
        await env.USER_PREFS.put(countKey, String(count + 1), { expirationTtl: COUNT_TTL });
        report.counts.pushed++;
        cand.recipients.push({ email: h.email, ticker: hit, status: `pushed:${pushed.channels.join("+")}` });
        // 把推播訊息同時寫進兩個 KV,讓 stripe-webhook 的 chat bot 認得「剛剛那則」:
        //  (A) linechat:${userId} —— 塞進對話歷史(role:assistant + [系統主動推播] 前綴)
        //  (B) alerthistory:${userId} —— per-user push 清單(結構化),chat bot 開場直接注入 system
        // 雙保險:即使 chat history 滿 20 輪被擠掉,alerthistory 仍獨立留 24h。
        try {
          const chatKey = `linechat:${h.userId}`;
          let history = [];
          const raw = await env.USER_PREFS.get(chatKey);
          if (raw) { try { history = JSON.parse(raw); } catch {} }
          history.push({
            role: "assistant",
            content: `[系統主動推播] ${msg}`,
          });
          if (history.length > 20) history = history.slice(-20);
          await env.USER_PREFS.put(chatKey, JSON.stringify(history),
            { expirationTtl: 24 * 3600 });
        } catch (e) {
          report.errors.push(`chat-session-write:${h.email}:${String(e).slice(0,80)}`);
        }
        try {
          const alertHistKey = `alerthistory:${h.userId}`;
          let alertList = [];
          const raw = await env.USER_PREFS.get(alertHistKey);
          if (raw) { try { alertList = JSON.parse(raw); } catch {} }
          alertList.push({
            ts: report.ts,
            ticker: hit,
            title: news.title,
            url: news.url,
            reason: reason,
            stance: stance,
            action: action,
            category: category,
            severity: severity,
            body: msg.slice(0, 1200),
          });
          if (alertList.length > 8) alertList = alertList.slice(-8);
          await env.USER_PREFS.put(alertHistKey, JSON.stringify(alertList),
            { expirationTtl: 24 * 3600 });
        } catch (e) {
          report.errors.push(`alert-history-write:${h.email}:${String(e).slice(0,80)}`);
        }
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
// 門檻沿用新聞管線同一套紀律:政策行動 ≥ SEVERITY_THRESHOLD(7)、
// 言論/觀點 ≥ SPECULATIVE_THRESHOLD(9)且訊息掛「💬 言論觀點」標籤,不轟炸。
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
    if (res.error) { report.errors.push(res.error); return done(); }
    sigList = res.signals;
  }
  const res = { signals: sigList };
  report.found = res.signals.length;
  if (!res.signals.length) return done();

  let recipients = null;
  for (const sig of res.signals) {
    const threshold = sig.kind === "action" ? SEVERITY_THRESHOLD : SPECULATIVE_THRESHOLD;
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
    // 點名個股 → 推給持有者;severity ≥9 的大事 → 全體綁定 Premium 都推
    const targets = recipients.filter(r =>
      sig.severity >= 9 || !sig.affected.length || sig.affected.some(t => r.holdings.has(t)));
    const msg = formatPoliticalMsg(sig, displayName);
    const fired = { headline: sig.headline_zh, severity: sig.severity, kind: sig.kind, recipients: [] };
    if (push && targets.length) {
      const token = await lineToken(env);
      const notif = JSON.stringify({
        title: `🏛️ 政壇影響｜${(sig.headline_zh || "").slice(0, 36)}`,
        body: (sig.headline_zh || "").slice(0, 160),
        url: sig.post_url || "https://marketdaily.ai/dashboard.html",
        tag: `md-pol-${(sig.post_url || sig.headline_zh || "").slice(0, 40)}`,
      });
      for (const r of targets) {
        const out = await deliverAlert(env, r, token, msg, notif);
        fired.recipients.push({ email: r.email, status: out.ok ? `pushed:${out.channels.join("+")}` : `fail:${out.status}` });
        if (out.ok) report.pushed++;
      }
    } else {
      for (const r of targets) fired.recipients.push({ email: r.email, status: "would-push" });
    }
    report.fired.push(fired);
    await env.USER_PREFS.put(seenKey, "1", { expirationTtl: SEEN_TTL });
    await env.USER_PREFS.put(capKey, String(sent + 1), { expirationTtl: COUNT_TTL });
  }
  return done();
}

export default {
  async scheduled(event, env, ctx) {
    // 3 個 cron 分支:
    //   "*/2 * * * *"  → 主管線(抓新聞 → 比對 → 推播)
    //   "0 * * * *"    → 每小時 canary,自動驗 token 健康度,失敗就 LINE 告 admin
    //   "*/15 * * * *" → 政壇市場訊號(政治人物 X 貼文 → LINE,需 XAI_API_KEY)
    if (event.cron === "0 * * * *") {
      ctx.waitUntil(canaryCheck(env));
      return;
    }
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
        },
        config: {
          severityThreshold: SEVERITY_THRESHOLD, speculativeThreshold: SPECULATIVE_THRESHOLD,
          dailyCap: DAILY_CAP, maxAgeHours: MAX_AGE_HOURS, preScoreFloor: PRESCORE_FLOOR,
          crons: ["*/2 * * * *(pipeline)", "0 * * * *(canary)"],
        },
        lastRun: lastRaw ? JSON.parse(lastRaw) : null,
        lastCanary: canaryRaw ? JSON.parse(canaryRaw) : null,
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
      let ok = false; const channels = []; let lineStatus = null;
      // 1) 自有 web push(無額度限制,優先)
      if (env.ADMIN_EMAIL) {
        try {
          const raw = await env.USER_PREFS.get(`pushsub:${env.ADMIN_EMAIL}`);
          if (raw) {
            const wr = await webPush(env, JSON.parse(raw), JSON.stringify({
              title: "🔔 MarketDaily", body: message.slice(0, 300), url: "https://marketdaily.ai/dashboard.html",
            }));
            if (wr.ok) { ok = true; channels.push("webpush"); }
          }
        } catch {}
      }
      // 2) LINE 備援
      if (env.ADMIN_LINE_USER_ID) {
        const token = await lineToken(env, { force: true });
        if (token) {
          const res = await fetch(LINE_PUSH_URL, {
            method: "POST",
            headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
            body: JSON.stringify({ to: env.ADMIN_LINE_USER_ID, messages: [{ type: "text", text: message }] }),
          });
          lineStatus = res.status;
          if (res.ok) { ok = true; channels.push("line"); }
        }
      }
      return json({ ok, channels, lineStatus });
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
      const ana = await analyzePoliticalPosts(env, fresh);
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
