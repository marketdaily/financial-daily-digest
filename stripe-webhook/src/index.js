const ADMIN_EMAILS = ["delvin.12345678@gmail.com"];

const INVITE_CODES = [
  "DELVIN-FE8FZ1","DELVIN-XKNJ4N","DELVIN-F4ONQQ","DELVIN-RBIG9S",
  "DELVIN-WYW4IP","DELVIN-BE2O13","DELVIN-OVMFHN","DELVIN-AV3VIB",
  "DELVIN-06U59N","DELVIN-CVRBWF",
  "MD-4SJWK4","MD-UN81FB","MD-F3KQ11","MD-3A111V","MD-HZBXA1",
  "MD-O9GFBT","MD-3BVD3O","MD-XTKXU8","MD-XETLNK","MD-OAF39F"
];

const TIER_BY_AMOUNT = { 19900: "Pro", 190800: "Pro", 29900: "Pro", 287000: "Pro", 49900: "Premium", 478800: "Premium" };

const PLAN_CAPS = { free: 5, pro: 15, premium: Infinity };
function planCap(plan) { return PLAN_CAPS[plan] || PLAN_CAPS.free; }
function applyCap(us, tw, cap) {
  if (cap === Infinity || us.length + tw.length <= cap) return [us, tw];
  if (us.length >= cap) return [us.slice(0, cap), []];
  return [us, tw.slice(0, cap - us.length)];
}

// Legacy SHA-256(無 salt)— 僅供驗證舊密碼 + 自動升級用
async function hashPassword(password) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(password));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

// PBKDF2 + salt(新格式)
async function hashPbkdf2(password, salt) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: enc.encode(salt), iterations: 100000, hash: "SHA-256" },
    key, 256
  );
  return Array.from(new Uint8Array(bits)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function makePwdHash(password) {
  const salt = (crypto.randomUUID && crypto.randomUUID()) ||
    (Date.now().toString(36) + Math.random().toString(36).slice(2));
  const hash = await hashPbkdf2(password, salt);
  return `pbkdf2$${salt}$${hash}`;
}

async function verifyPwd(password, stored) {
  if (!stored) return false;
  if (stored.startsWith("pbkdf2$")) {
    const parts = stored.split("$");
    if (parts.length !== 3) return false;
    return (await hashPbkdf2(password, parts[1])) === parts[2];
  }
  return (await hashPassword(password)) === stored;
}

async function maybeUpgradeHash(env, email, password, stored) {
  if (!stored || stored.startsWith("pbkdf2$")) return;
  try {
    const fresh = await makePwdHash(password);
    await env.USER_PREFS.put(`pwd:${email}`, fresh);
  } catch {}
}

// Gmail alias 正規化:bob+a@gmail.com → bob@gmail.com,b.o.b@gmail.com → bob@gmail.com
function normalizeEmail(email) {
  const e = (email || "").toLowerCase().trim();
  const at = e.indexOf("@");
  if (at < 0) return e;
  const domain = e.slice(at + 1);
  let local = e.slice(0, at).split("+")[0];
  if (domain === "gmail.com" || domain === "googlemail.com") {
    local = local.replace(/\./g, "");
    return `${local}@gmail.com`;
  }
  return `${local}@${domain}`;
}

// 統一 admin 端點驗證:email 必須在 ADMIN_EMAILS,且 password 必須正確
async function requireAdmin(env, body) {
  const email = ((body && (body.email || body.admin_email || body.auth_email)) || "").trim().toLowerCase();
  if (!ADMIN_EMAILS.includes(email)) return null;
  const password = (body && body.password) || "";
  const stored = await env.USER_PREFS.get(`pwd:${email}`);
  if (!stored) return null;
  const ok = await verifyPwd(password, stored);
  if (!ok) return null;
  await maybeUpgradeHash(env, email, password, stored);
  return email;
}

function generateRefCode(email) {
  const prefix = email.replace(/[^a-z0-9]/gi, '').substring(0, 3).toUpperCase();
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let code = 'REF' + prefix;
  for (let i = 0; i < 5; i++) code += chars[Math.floor(Math.random() * chars.length)];
  return code;
}

// --- LINE Login(Premium 即時提醒綁定)---
const LINE_LOGIN_CHANNEL_ID = "2010167489";
const LINE_LOGIN_CALLBACK = "https://marketdaily-webhook.delvin-12345678.workers.dev/line/callback";
const DASHBOARD_URL = "https://marketdaily.ai/dashboard.html";

function b64urlEncode(bytes) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlToBytes(s) {
  return Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
}
async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}
async function signState(payload, secret) {
  const data = b64urlEncode(new TextEncoder().encode(JSON.stringify(payload)));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), new TextEncoder().encode(data));
  return data + "." + b64urlEncode(new Uint8Array(sig));
}
async function verifyState(state, secret) {
  const [data, sig] = (state || "").split(".");
  if (!data || !sig) return null;
  const ok = await crypto.subtle.verify("HMAC", await hmacKey(secret),
    b64urlToBytes(sig), new TextEncoder().encode(data));
  if (!ok) return null;
  try {
    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(data)));
    if (payload.exp && Date.now() > payload.exp) return null;
    return payload;
  } catch { return null; }
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

// 歸一化 utm_source 到固定集合,讓 daily aggregate 桶數可控
const ATTR_SOURCES = ["ig", "fb", "threads", "line", "x", "tiktok", "youtube", "email", "direct", "other"];
function normalizeSource(s) {
  const v = (s || "").toString().trim().toLowerCase();
  if (!v) return "direct";
  if (v === "instagram") return "ig";
  if (v === "facebook") return "fb";
  if (v === "twitter") return "x";
  if (v === "yt") return "youtube";
  if (v === "tt") return "tiktok";
  return ATTR_SOURCES.includes(v) ? v : "other";
}

// 寫一筆 convert + 更新當日聚合。Worker 沒有 KV 原子操作,
// 同秒兩個寫入會互蓋 —— 我們可接受小幅低估(訂閱量級小);要強一致再上 D1。
async function recordConvert(env, { email, event, visit_id, utm_source, utm_medium, utm_campaign }) {
  if (!email || !event) return;
  let attr = { utm_source: null, utm_medium: null, utm_campaign: null };
  if (visit_id) {
    try {
      const raw = await env.USER_PREFS.get(`attr:visit:${visit_id}`);
      if (raw) {
        const v = JSON.parse(raw);
        attr.utm_source = v.utm_source || null;
        attr.utm_medium = v.utm_medium || null;
        attr.utm_campaign = v.utm_campaign || null;
      }
    } catch {}
  }
  if (utm_source && !attr.utm_source) attr.utm_source = utm_source;
  if (utm_medium && !attr.utm_medium) attr.utm_medium = utm_medium;
  if (utm_campaign && !attr.utm_campaign) attr.utm_campaign = utm_campaign;

  const ts = Date.now();
  const record = { visit_id: visit_id || null, email, event, ts, ...attr };
  await env.USER_PREFS.put(
    `attr:convert:${ts}_${email}`,
    JSON.stringify(record),
    { expirationTtl: 86400 * 365 }
  );

  const day = new Date(ts + 8 * 3600 * 1000).toISOString().slice(0, 10);
  const aggKey = `attr:daily:${day}`;
  let agg = { by_source: {}, by_event: {}, total: 0 };
  try {
    const raw = await env.USER_PREFS.get(aggKey);
    if (raw) agg = JSON.parse(raw);
  } catch {}
  const src = normalizeSource(attr.utm_source);
  agg.by_source[src] = (agg.by_source[src] || 0) + 1;
  agg.by_event[event] = (agg.by_event[event] || 0) + 1;
  agg.total = (agg.total || 0) + 1;
  await env.USER_PREFS.put(aggKey, JSON.stringify(agg), { expirationTtl: 86400 * 400 });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);

    // Check if email is a subscriber
    if (url.pathname === "/check-subscriber" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch {
        return json({ error: "Invalid request" }, 400);
      }
      const email = (body.email || "").trim().toLowerCase();
      const password = body.password || "";
      if (!email) return json({ subscribed: false });

      if (ADMIN_EMAILS.includes(email)) {
        return json({ subscribed: true, plan: "admin" });
      }

      const res = await fetch(`https://api.brevo.com/v3/contacts/${encodeURIComponent(email)}`, {
        headers: { "api-key": env.BREVO_API_KEY }
      });
      if (!res.ok) return json({ subscribed: false });
      const contact = await res.json();
      const listIds = contact.listIds || [];
      const targetList = parseInt(env.BREVO_LIST_ID) || 2;
      if (!listIds.includes(targetList)) return json({ subscribed: false });

      const isPaid = (contact.attributes?.PAID === true || contact.attributes?.PLAN === "paid");
      // KV plan:${email} 是方案唯一真實來源(premium/pro/free);Brevo PAID 僅作 KV 未設時的後援
      const explicitPlan = await env.USER_PREFS.get(`plan:${email}`);
      const plan = explicitPlan || (isPaid ? "premium" : "free");
      const hasKvPlan = !!explicitPlan || isPaid;
      const since = contact.createdAt || null;

      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash) {
        return json({ subscribed: true, plan, since, needsPasswordSetup: true, hasKvPlan });
      }
      if (!password) {
        return json({ subscribed: true, needsPasswordEntry: true, hasKvPlan });
      }
      if (!(await verifyPwd(password, storedHash))) {
        return json({ subscribed: true, error: "wrong_password" });
      }
      await maybeUpgradeHash(env, email, password, storedHash);
      return json({ subscribed: true, plan, since, hasKvPlan });
    }

    // Set subscriber password (first-time setup)
    if (url.pathname === "/set-password" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const password = body.password || "";
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      if (password.length < 6) return json({ error: "too_short" }, 400);

      const res = await fetch(`https://api.brevo.com/v3/contacts/${encodeURIComponent(email)}`, {
        headers: { "api-key": env.BREVO_API_KEY }
      });
      if (!res.ok) return json({ error: "not_subscriber" }, 403);
      const contact = await res.json();
      const listIds = contact.listIds || [];
      const targetList = parseInt(env.BREVO_LIST_ID) || 2;
      if (!listIds.includes(targetList)) return json({ error: "not_subscriber" }, 403);

      const hash = await makePwdHash(password);
      await env.USER_PREFS.put(`pwd:${email}`, hash);

      const isPaid = (contact.attributes?.PAID === true || contact.attributes?.PLAN === "paid");
      const plan = (await env.USER_PREFS.get(`plan:${email}`)) || (isPaid ? "premium" : "free");
      return json({ ok: true, plan, since: contact.createdAt || null });
    }

    // Change password (authenticated users)
    if (url.pathname === "/change-password" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const oldPassword = body.old_password || "";
      const newPassword = body.new_password || "";
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      if (newPassword.length < 6) return json({ error: "too_short" }, 400);

      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash) return json({ error: "not_found" }, 404);

      if (!(await verifyPwd(oldPassword, storedHash))) return json({ error: "wrong_password" }, 403);

      const newHash = await makePwdHash(newPassword);
      await env.USER_PREFS.put(`pwd:${email}`, newHash);
      return json({ ok: true });
    }

    // LINE 綁定:啟動 OAuth,回傳授權 URL
    if (url.pathname === "/line/login" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const password = body.password || "";
      if (!email) return json({ error: "invalid_email" }, 400);
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash || !(await verifyPwd(password, storedHash))) {
        return json({ error: "auth" }, 403);
      }
      await maybeUpgradeHash(env, email, password, storedHash);
      const state = await signState({ email, exp: Date.now() + 600000 }, env.LINE_LOGIN_CHANNEL_SECRET);
      const authUrl = "https://access.line.me/oauth2/v2.1/authorize?response_type=code"
        + "&client_id=" + LINE_LOGIN_CHANNEL_ID
        + "&redirect_uri=" + encodeURIComponent(LINE_LOGIN_CALLBACK)
        + "&state=" + encodeURIComponent(state)
        + "&scope=profile";
      return json({ authUrl });
    }

    // LINE 綁定:OAuth 回呼
    if (url.pathname === "/line/callback" && request.method === "GET") {
      const code = url.searchParams.get("code");
      const payload = await verifyState(url.searchParams.get("state"), env.LINE_LOGIN_CHANNEL_SECRET);
      if (!code || !payload) return Response.redirect(DASHBOARD_URL + "?line=error", 302);
      const tokenRes = await fetch("https://api.line.me/oauth2/v2.1/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "authorization_code", code,
          redirect_uri: LINE_LOGIN_CALLBACK,
          client_id: LINE_LOGIN_CHANNEL_ID,
          client_secret: env.LINE_LOGIN_CHANNEL_SECRET,
        }),
      });
      if (!tokenRes.ok) return Response.redirect(DASHBOARD_URL + "?line=error", 302);
      const tok = await tokenRes.json();
      const profRes = await fetch("https://api.line.me/v2/profile", {
        headers: { "Authorization": "Bearer " + tok.access_token },
      });
      if (!profRes.ok) return Response.redirect(DASHBOARD_URL + "?line=error", 302);
      const prof = await profRes.json();
      if (!prof.userId) return Response.redirect(DASHBOARD_URL + "?line=error", 302);
      await env.USER_PREFS.put(`line:${payload.email}`, prof.userId);
      await env.USER_PREFS.put(`linemap:${prof.userId}`, payload.email);
      return Response.redirect(DASHBOARD_URL + "?line=bound", 302);
    }

    // LINE 綁定:解除
    if (url.pathname === "/line/unbind" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash || !(await verifyPwd(body.password || "", storedHash))) {
        return json({ error: "auth" }, 403);
      }
      await maybeUpgradeHash(env, email, body.password || "", storedHash);
      const userId = await env.USER_PREFS.get(`line:${email}`);
      if (userId) await env.USER_PREFS.delete(`linemap:${userId}`);
      await env.USER_PREFS.delete(`line:${email}`);
      return json({ ok: true });
    }

    // LINE 綁定:查詢狀態
    if (url.pathname === "/line/status" && request.method === "GET") {
      const email = (url.searchParams.get("email") || "").trim().toLowerCase();
      return json({ bound: !!email && !!(await env.USER_PREFS.get(`line:${email}`)) });
    }

    // LINE Bot Messaging API webhook:接收訊息 → AI Q&A → reply
    if (url.pathname === "/line/webhook" && request.method === "POST") {
      const bodyText = await request.text();
      let payload;
      try { payload = JSON.parse(bodyText); } catch { return new Response("OK", { status: 200 }); }
      const events = payload.events || [];
      // LINE Console 的 Verify 按鈕送空 events 連通性測試 — 不驗簽,直接 200
      if (events.length === 0) return new Response("OK", { status: 200 });
      // 真實事件:嚴格驗 HMAC-SHA256 簽名
      const sig = request.headers.get("x-line-signature");
      const channelSecret = env.LINE_MESSAGING_CHANNEL_SECRET || env.LINE_CHANNEL_SECRET;
      if (!await verifyLineSignature(bodyText, sig, channelSecret)) {
        console.log("line webhook signature mismatch");
        return new Response("Bad signature", { status: 401 });
      }
      ctx.waitUntil(processLineEvents(events, env));
      return new Response("OK", { status: 200 });
    }

    // AI 投資助手:聊天(Premium 專屬)
    if (url.pathname === "/chat" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const password = body.password || "";
      const msgs = Array.isArray(body.messages) ? body.messages : [];
      if (!email) return json({ error: "invalid_email" }, 400);

      const isAdmin = ADMIN_EMAILS.includes(email);
      {
        const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
        if (!storedHash || !(await verifyPwd(password, storedHash))) {
          return json({ error: "auth" }, 403);
        }
        await maybeUpgradeHash(env, email, password, storedHash);
      }
      const plan = await env.USER_PREFS.get(`plan:${email}`);
      if (!isAdmin && plan !== "premium") return json({ error: "not_premium" }, 403);

      const day = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
      const countKey = `chatcount:${email}:${day}`;
      const used = parseInt((await env.USER_PREFS.get(countKey)) || "0", 10);
      if (used >= 30) return json({ error: "daily_limit" }, 429);

      const convo = msgs
        .filter(m => m && (m.role === "user" || m.role === "assistant")
          && typeof m.content === "string" && m.content.trim())
        .slice(-20)
        .map(m => ({ role: m.role, content: m.content.slice(0, 4000) }));
      if (!convo.length || convo[convo.length - 1].role !== "user") {
        return json({ error: "no_message" }, 400);
      }

      // 持股優先用前端帶來的字串(含公司名);取不到才退回 KV 純代號。
      let holdings = "";
      if (typeof body.holdings === "string" && body.holdings.trim()) {
        holdings = body.holdings.trim().slice(0, 800);
      } else {
        const prefRaw = await env.USER_PREFS.get(email);
        if (prefRaw) {
          try {
            const p = JSON.parse(prefRaw);
            const us = (p.us_stocks || []).join("、");
            const tw = (p.tw_stocks || []).join("、");
            const parts = [us && `美股:${us}`, tw && `台股:${tw}`].filter(Boolean);
            if (parts.length) holdings = parts.join(";");
          } catch {}
        }
      }
      if (!holdings) holdings = "(尚未設定持股)";

      const system = `你是 MarketDaily 的 AI 投資助手。MarketDaily 是給台灣投資人的每日財經 AI 日報平台。

你的任務:用繁體中文,針對「這位用戶的持股」回答市場、個股、財經概念,以及如何解讀每日日報的問題。

規則:
- 一律繁體中文,語氣專業、精簡、好懂,適度分段。
- 可以分析、解釋、提供觀點與資訊,但不做保證、不喊進喊出。只要回答涉及買賣判斷,結尾務必加一句「以上為資訊整理,非投資建議」。
- 你沒有即時報價與盤中數據;需要即時價格才能回答時,誠實說明,並建議用戶看當日日報或券商報價。
- 與投資、財經、用戶持股無關的問題,簡短禮貌帶過,引導回投資主題。
- 提到台股時,一律用公司名稱稱呼(可附代號,如「台積電 2330」),絕不只報數字代號。

這位用戶目前在 MarketDaily 追蹤的持股:${holdings}`;

      let aiRes;
      try {
        aiRes = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "x-api-key": env.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
          },
          body: JSON.stringify({
            model: "claude-haiku-4-5-20251001",
            max_tokens: 1024,
            system,
            messages: convo,
          }),
        });
      } catch {
        return json({ error: "ai_unreachable" }, 502);
      }
      if (!aiRes.ok) return json({ error: "ai_error", status: aiRes.status }, 502);
      const data = await aiRes.json();
      const reply = (data.content || []).map(c => c.text || "").join("").trim();
      if (!reply) return json({ error: "ai_empty" }, 502);
      await env.USER_PREFS.put(countKey, String(used + 1), { expirationTtl: 26 * 3600 });
      return json({ reply, remaining: Math.max(0, 30 - used - 1) });
    }

    // AI 投資助手:狀態查詢(前端決定卡片顯示)
    if (url.pathname === "/chat-status" && request.method === "GET") {
      const email = (url.searchParams.get("email") || "").trim().toLowerCase();
      const isAdmin = ADMIN_EMAILS.includes(email);
      const plan = await env.USER_PREFS.get(`plan:${email}`);
      const premium = isAdmin || plan === "premium";
      const day = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
      const used = parseInt((await env.USER_PREFS.get(`chatcount:${email}:${day}`)) || "0", 10);
      return json({ premium, remaining: Math.max(0, 30 - used) });
    }

    // Admin stats
    if (url.pathname === "/admin-stats" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      try {
        const listId = parseInt(env.BREVO_LIST_ID) || 2;
        const res = await fetch(`https://api.brevo.com/v3/contacts/lists/${listId}/contacts`, {
          headers: { "api-key": env.BREVO_API_KEY }
        });
        const data = await res.json();
        const contacts = data.contacts || [];
        const total = data.count || contacts.length;
        const subscribers = await Promise.all(contacts.slice(0, 50).map(async c => {
          const em = (c.email || "").toLowerCase();
          const kvPlan = await env.USER_PREFS.get(`plan:${em}`);
          return {
            email: c.email,
            plan: kvPlan || (c.attributes?.PAID ? "premium" : "free"),
            since: c.createdAt,
          };
        }));
        return json({ totalSubscribers: total, subscribers });
      } catch { return json({ totalSubscribers: 0, subscribers: [] }); }
    }

    // Get admin global config
    if (url.pathname === "/admin/get-config" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      const raw = await env.USER_PREFS.get("admin:global-config");
      return json({ config: raw ? JSON.parse(raw) : null });
    }

    // Save admin global config
    if (url.pathname === "/admin/save-config" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      const config = body.config;
      if (!config || typeof config !== "object") return json({ error: "no config" }, 400);
      config.updated_at = new Date().toISOString();
      await env.USER_PREFS.put("admin:global-config", JSON.stringify(config));
      return json({ ok: true, updated_at: config.updated_at });
    }

    // Admin:設定單一用戶方案(free / pro / premium)
    if (url.pathname === "/admin/set-plan" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      const target = (body.target || "").trim().toLowerCase();
      const plan = (body.plan || "").trim().toLowerCase();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return json({ error: "invalid_target" }, 400);
      if (!["free", "pro", "premium"].includes(plan)) return json({ error: "invalid_plan" }, 400);
      await env.USER_PREFS.put(`plan:${target}`, plan);
      // Brevo 屬性同步:KV 才是真實來源,但 Brevo 屬性影響 mass mail segmentation 必須跟著改
      const listId = parseInt(env.BREVO_LIST_ID) || 2;
      const isPaid = plan !== "free";
      ctx.waitUntil(addToBrevo(target, env.BREVO_API_KEY, listId,
        { PAID: isPaid, PLAN: isPaid ? "paid" : "free", PLAN_TIER: plan }));
      return json({ ok: true, target, plan });
    }

    // 一次性把所有 KV plan 的真實狀態推到 Brevo 屬性(修補手動改 KV 後 Brevo 沒跟上的情況)
    if (url.pathname === "/admin/sync-brevo-plans" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      const listId = parseInt(env.BREVO_LIST_ID) || 2;
      const results = { ok: 0, fail: 0, by_plan: {} };
      let cursor = undefined;
      do {
        const page = await env.USER_PREFS.list({ prefix: "plan:", cursor, limit: 1000 });
        for (const k of page.keys) {
          const target = k.name.slice(5);
          const plan = (await env.USER_PREFS.get(k.name)) || "free";
          const isPaid = plan !== "free";
          const ok = await addToBrevo(target, env.BREVO_API_KEY, listId,
            { PAID: isPaid, PLAN: isPaid ? "paid" : "free", PLAN_TIER: plan });
          if (ok) results.ok++; else results.fail++;
          results.by_plan[plan] = (results.by_plan[plan] || 0) + 1;
        }
        cursor = page.list_complete ? undefined : page.cursor;
      } while (cursor);
      return json(results);
    }

    // Admin:lifecycle email 手動測試(不檢查 days_since_signup、不寫防呆 flag)
    if (url.pathname === "/admin/lifecycle-test" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      const target = (body.target || body.to || "").trim().toLowerCase();
      const type = (body.type || "").trim().toLowerCase();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return json({ error: "invalid_target" }, 400);
      const handlers = { d1: sendD1Email, d7: sendD7Email, d14: sendD14Email, d21: sendD21Email, d45: sendD45Email };
      if (!handlers[type]) return json({ error: "invalid_type" }, 400);
      try {
        await handlers[type](target, env.BREVO_API_KEY, env);
        return json({ ok: true, target, type });
      } catch (e) {
        return json({ error: "send_failed", detail: String(e) }, 502);
      }
    }

    // Attribution: 記錄首次訪問(UTM)
    if (url.pathname === "/track/visit" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const visit_id = (crypto.randomUUID && crypto.randomUUID()) ||
        (Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
      const record = {
        utm_source: (body.utm_source || "").toString().slice(0, 64) || null,
        utm_medium: (body.utm_medium || "").toString().slice(0, 64) || null,
        utm_campaign: (body.utm_campaign || "").toString().slice(0, 128) || null,
        utm_term: (body.utm_term || "").toString().slice(0, 128) || null,
        utm_content: (body.utm_content || "").toString().slice(0, 128) || null,
        ts: typeof body.ts === "number" ? body.ts : Date.now(),
        ip_country: request.headers.get("cf-ipcountry") || null,
      };
      await env.USER_PREFS.put(
        `attr:visit:${visit_id}`,
        JSON.stringify(record),
        { expirationTtl: 7776000 }
      );
      return json({ visit_id });
    }

    // Attribution: 訂閱事件轉換
    if (url.pathname === "/track/convert" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const event = (body.event || "").toString();
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      const allowed = ["subscribe_free", "subscribe_pro", "subscribe_premium", "invite_used"];
      if (!allowed.includes(event)) return json({ error: "invalid_event" }, 400);
      await recordConvert(env, {
        email, event,
        visit_id: body.visit_id || null,
        utm_source: body.utm_source,
        utm_medium: body.utm_medium,
        utm_campaign: body.utm_campaign,
      });
      return json({ ok: true });
    }

    // Admin: 歸因摘要(最近 30 天 daily stats + 最近 50 筆 convert)
    if (url.pathname === "/admin/analytics-summary" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);

      const days = [];
      const totals = { by_source: {}, by_event: {}, total: 0 };
      for (let i = 0; i < 30; i++) {
        const d = new Date(Date.now() + 8 * 3600 * 1000 - i * 86400 * 1000)
          .toISOString().slice(0, 10);
        const raw = await env.USER_PREFS.get(`attr:daily:${d}`);
        const agg = raw ? JSON.parse(raw) : { by_source: {}, by_event: {}, total: 0 };
        days.push({ date: d, ...agg });
        for (const [k, v] of Object.entries(agg.by_source || {})) {
          totals.by_source[k] = (totals.by_source[k] || 0) + v;
        }
        for (const [k, v] of Object.entries(agg.by_event || {})) {
          totals.by_event[k] = (totals.by_event[k] || 0) + v;
        }
        totals.total += agg.total || 0;
      }

      // 最近 50 筆 convert(key 用 timestamp prefix,list reverse 取最新)
      const list = await env.USER_PREFS.list({ prefix: "attr:convert:", limit: 1000 });
      const sortedKeys = list.keys
        .map(k => k.name)
        .sort()
        .reverse()
        .slice(0, 50);
      const recent = [];
      for (const k of sortedKeys) {
        const raw = await env.USER_PREFS.get(k);
        if (raw) {
          try { recent.push(JSON.parse(raw)); } catch {}
        }
      }
      return json({ days, totals, recent });
    }

    // === Reactive Content MVP ===

    // Admin:列出所有 pending hot take(最新在前)
    if (url.pathname === "/admin/reactive-list" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      const list = await env.USER_PREFS.list({ prefix: "reactive:pending:", limit: 200 });
      const items = [];
      for (const k of list.keys) {
        const raw = await env.USER_PREFS.get(k.name);
        if (!raw) continue;
        try { items.push(JSON.parse(raw)); } catch {}
      }
      items.sort((a, b) => (b.ts || 0) - (a.ts || 0));
      return json({ items });
    }

    // Admin:通過 hot take → 發 LINE broadcast + Threads
    if (url.pathname === "/admin/reactive-approve" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = await requireAdmin(env, body);
      if (!email) return json({ error: "Forbidden" }, 403);
      const id = (body.id || "").toString();
      if (!/^[a-z0-9]{6,32}$/.test(id)) return json({ error: "invalid_id" }, 400);
      const raw = await env.USER_PREFS.get(`reactive:pending:${id}`);
      if (!raw) return json({ error: "not_found" }, 404);
      let item;
      try { item = JSON.parse(raw); } catch { return json({ error: "corrupt" }, 500); }

      // 允許前端編輯後傳回 — 覆蓋 AI 原稿
      if (body.headline) item.ai.headline = String(body.headline).slice(0, 120);
      if (body.body) item.ai.body = String(body.body).slice(0, 500);
      if (body.bias && ["bullish", "bearish", "neutral"].includes(body.bias)) item.ai.bias = body.bias;
      if (Array.isArray(body.tickers)) item.ai.tickers = body.tickers.slice(0, 10).map(t => String(t).toUpperCase().slice(0, 10));

      item.status = "approved";
      item.approved_at = Date.now();
      item.approved_by = email;

      const caption =
        `⚡ Hot Take | ${item.ai.headline}\n\n${item.ai.body}\n\n` +
        `來源:${item.source_url}\n\n#美股 #台股 #財經`;

      const results = { line: null, threads: null };
      // 開發階段:發送先 mock 成 log,避免誤推訂戶。設 env.REACTIVE_LIVE_SEND="1" 才真寄。
      const live = env.REACTIVE_LIVE_SEND === "1";
      try {
        results.line = await sendLineBroadcast(env, caption, live);
      } catch (e) { results.line = { ok: false, error: String(e) }; }
      try {
        results.threads = await sendThreadsPost(env, caption, live);
      } catch (e) { results.threads = { ok: false, error: String(e) }; }

      item.publish_results = results;
      item.publish_live = live;

      await env.USER_PREFS.put(`reactive:approved:${id}`, JSON.stringify(item),
        { expirationTtl: 86400 * 30 });
      await env.USER_PREFS.put(`reactive:queue:${id}`, JSON.stringify({
        id, caption, ts: item.approved_at, tickers: item.ai.tickers,
        bias: item.ai.bias, source_url: item.source_url,
      }), { expirationTtl: 86400 * 7 });
      await env.USER_PREFS.delete(`reactive:pending:${id}`);

      const anyFail = (results.line && results.line.ok === false) || (results.threads && results.threads.ok === false);
      if (anyFail) {
        await env.USER_PREFS.put(`reactive:failed:${id}`, JSON.stringify(results),
          { expirationTtl: 86400 * 14 });
      }
      return json({ ok: true, id, live, results });
    }

    // Admin:拒絕 hot take
    if (url.pathname === "/admin/reactive-reject" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body)) return json({ error: "Forbidden" }, 403);
      const id = (body.id || "").toString();
      if (!/^[a-z0-9]{6,32}$/.test(id)) return json({ error: "invalid_id" }, 400);
      const raw = await env.USER_PREFS.get(`reactive:pending:${id}`);
      if (!raw) return json({ error: "not_found" }, 404);
      await env.USER_PREFS.put(`reactive:rejected:${id}`, raw,
        { expirationTtl: 86400 * 14 });
      await env.USER_PREFS.delete(`reactive:pending:${id}`);
      return json({ ok: true, id });
    }

    // Save user preferences
    if (url.pathname === "/save-preferences" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch {
        return json({ error: "Invalid request" }, 400);
      }
      const email = (body.email || "").trim().toLowerCase();
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        return json({ error: "invalid_email" }, 400);
      }
      const plan = (await env.USER_PREFS.get(`plan:${email}`)) || "free";
      const cap = planCap(plan);
      let us = Array.isArray(body.us_stocks) ? body.us_stocks : [];
      let tw = Array.isArray(body.tw_stocks) ? body.tw_stocks : [];
      const submitted = us.length + tw.length;
      [us, tw] = applyCap(us, tw, cap);
      const saved = us.length + tw.length;
      const prefs = {
        us_stocks: us,
        tw_stocks: tw,
        updated_at: new Date().toISOString(),
      };
      await env.USER_PREFS.put(email, JSON.stringify(prefs));
      // dropped > 0 表示超過方案上限被截斷 —— 前端必須明確告知,不可靜默
      return json({
        ok: true, plan,
        cap: cap === Infinity ? null : cap,
        count: saved,
        dropped: submitted - saved,
      });
    }

    // Get user preferences
    if (url.pathname === "/get-preferences" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch {
        return json({ error: "Invalid request" }, 400);
      }
      const email = (body.email || "").trim().toLowerCase();
      if (!email) return json({ error: "invalid_email" }, 400);
      const plan = (await env.USER_PREFS.get(`plan:${email}`)) || "free";
      const cap = planCap(plan);
      const raw = await env.USER_PREFS.get(email);
      const prefs = raw ? JSON.parse(raw) : {};
      return json({
        us_stocks: prefs.us_stocks || [],
        tw_stocks: prefs.tw_stocks || [],
        plan,
        cap: cap === Infinity ? null : cap,
      });
    }

    // Save a personalized digest HTML; returns a shareable web URL
    if (url.pathname === "/save-digest" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const token = (body.token || "").trim();
      const html = body.html || "";
      if (!/^[A-Za-z0-9_-]{8,64}$/.test(token)) return json({ error: "invalid_token" }, 400);
      if (!html || html.length > 5000000) return json({ error: "invalid_html" }, 400);
      await env.USER_PREFS.put(`digest:${token}`, html, { expirationTtl: 86400 * 45 });
      return json({ ok: true, url: `${url.origin}/digest/${token}` });
    }

    // Serve a hosted digest page by token
    if (url.pathname.startsWith("/digest/") && request.method === "GET") {
      const token = url.pathname.slice(8);
      if (!/^[A-Za-z0-9_-]{8,64}$/.test(token)) {
        return new Response("Not found", { status: 404 });
      }
      const html = await env.USER_PREFS.get(`digest:${token}`);
      if (!html) {
        return new Response(
          "<meta charset=utf-8><p style='font-family:sans-serif;text-align:center;margin-top:60px;color:#555;'>這份日報連結已過期或不存在。</p>",
          { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } }
        );
      }
      return new Response(html, {
        headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=3600" },
      });
    }

    // Free subscription endpoint
    if (url.pathname === "/free-subscribe" && request.method === "POST") {
      let body;
      try {
        body = await request.json();
      } catch {
        return json({ error: "Invalid request" }, 400);
      }

      const email = (body.email || "").trim().toLowerCase();
      const code = (body.code || "").trim().toUpperCase();

      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        return json({ error: "invalid_email" }, 400);
      }
      if (!INVITE_CODES.includes(code)) {
        return json({ error: "invalid_code" }, 400);
      }
      // 邀請碼 single-use:同一碼只能被兌一次
      const usedKey = `invite:used:${code}`;
      const usedBy = await env.USER_PREFS.get(usedKey);
      if (usedBy && usedBy !== email) {
        return json({ error: "code_already_used" }, 400);
      }

      const listId = parseInt(env.BREVO_LIST_ID) || 2;
      const added = await addToBrevo(email, env.BREVO_API_KEY, listId);
      if (!added) return json({ error: "brevo_error" }, 502);

      // 標記碼已用(允許同 email 重複嘗試但不能轉給別人)
      if (!usedBy) {
        await env.USER_PREFS.put(usedKey, email);
      }
      // 邀請碼註冊者 = 免費方案(5 檔上限);Premium 需付費升級或管理員手動開通
      await env.USER_PREFS.put(`plan:${email}`, "free");
      // 歡迎信、補寄日報、推薦轉換全部背景化 —— 任一失敗都不影響「註冊成功」的回應
      ctx.waitUntil(postSignupTasks(email, body.ref, env));
      ctx.waitUntil(recordConvert(env, {
        email, event: "invite_used",
        visit_id: body.visit_id, utm_source: body.utm_source,
        utm_medium: body.utm_medium, utm_campaign: body.utm_campaign,
      }));
      return json({ ok: true });
    }

    // Market overview (indices + macro)
    if (url.pathname === "/market-overview" && request.method === "GET") {
      const markets = [
        { sym: "^GSPC",   label: "S&P 500" },
        { sym: "^TWII",   label: "台灣加權" },
        { sym: "^VIX",    label: "VIX 恐慌" },
        { sym: "BTC-USD", label: "Bitcoin" },
        { sym: "GC=F",    label: "黃金" },
      ];
      const yfH = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json", "Referer": "https://finance.yahoo.com/"
      };
      const results = await Promise.allSettled(markets.map(async ({ sym, label }) => {
        try {
          const res = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1d&range=5d`, { headers: yfH });
          if (!res.ok) return null;
          const data = await res.json();
          const meta = data?.chart?.result?.[0]?.meta;
          if (!meta) return null;
          const price = meta.regularMarketPrice ?? null;
          const prev = meta.chartPreviousClose ?? null;
          const change = (price !== null && prev !== null && prev !== 0) ? ((price - prev) / prev * 100) : null;
          return { sym, label, price, change };
        } catch { return null; }
      }));
      const overview = results.filter(r => r.status === "fulfilled" && r.value !== null).map(r => r.value);
      return new Response(JSON.stringify({ overview }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300" }
      });
    }

    // Real-time stock quotes proxy (Yahoo Finance)
    if (url.pathname === "/stock-quotes" && request.method === "GET") {
      const raw = (url.searchParams.get("tickers") || "").split(",").map(t => t.trim()).filter(Boolean).slice(0, 20);
      if (!raw.length) return json({ quotes: [] });
      const fh = env.FINNHUB_API_KEY;
      const yfHeaders = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://finance.yahoo.com/"
      };
      const results = await Promise.allSettled(raw.map(async (t) => {
        const isTW = /^\d{4,6}$/.test(t);
        // US stocks: Finnhub real-time last-trade quote (subrequest cached 15s to stay under rate limit)
        if (fh && !isTW) {
          try {
            const r = await fetch(
              `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(t)}&token=${fh}`,
              { cf: { cacheTtl: 15, cacheEverything: true } }
            );
            if (r.ok) {
              const d = await r.json();
              if (d && typeof d.c === "number" && d.c > 0) {
                return { symbol: t, name: t, price: d.c, change: typeof d.dp === "number" ? d.dp : null };
              }
            }
          } catch {}
        }
        // Yahoo:台股(.TW 上市 / .TWO 上櫃 自動切換)+ Finnhub 未設或失敗時的後援
        const r = await fetchYahooChart(t, isTW, "1d", "5d", yfHeaders, 15);
        if (!r) return { symbol: t, name: t, price: null, change: null };
        const meta = r.meta;
        const price = meta.regularMarketPrice ?? null;
        const prev = meta.chartPreviousClose ?? null;
        const change = (price !== null && prev !== null && prev !== 0) ? ((price - prev) / prev * 100) : null;
        return { symbol: t, name: meta.shortName || meta.longName || t, price, change };
      }));
      const quotes = results.map((r, i) => r.status === "fulfilled" ? r.value : { symbol: raw[i], name: raw[i], price: null, change: null });
      return new Response(JSON.stringify({ quotes }), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=15" }
      });
    }

    // Historical chart series proxy (Yahoo Finance) — same source as /stock-quotes
    if (url.pathname === "/stock-chart" && request.method === "GET") {
      const t = (url.searchParams.get("ticker") || "").trim();
      if (!t) return json({ error: "ticker required" }, 400);
      const cfg = {
        "1D": { interval: "5m",  range: "1d"  },
        "5D": { interval: "30m", range: "5d"  },
        "1M": { interval: "1d",  range: "1mo" },
        "3M": { interval: "1d",  range: "3mo" },
      }[url.searchParams.get("range") || "1M"] || { interval: "1d", range: "1mo" };
      const isTW = /^\d{4,6}$/.test(t);
      const yfHeaders = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://finance.yahoo.com/"
      };
      try {
        const r = await fetchYahooChart(t, isTW, cfg.interval, cfg.range, yfHeaders, 300);
        if (!r) return json({ error: "no data" }, 404);
        const ts = r.timestamp || [];
        const closes = r.indicators?.quote?.[0]?.close || [];
        const points = [];
        for (let i = 0; i < ts.length; i++) {
          if (closes[i] !== null && closes[i] !== undefined) points.push({ t: ts[i], c: closes[i] });
        }
        return new Response(JSON.stringify({
          symbol: t,
          prevClose: r.meta?.chartPreviousClose ?? null,
          price: r.meta?.regularMarketPrice ?? null,
          points
        }), {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300" }
        });
      } catch {
        return json({ error: "error" }, 500);
      }
    }

    // Direct free signup (no invite code required)
    if (url.pathname === "/subscribe-free-direct" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      const listId = parseInt(env.BREVO_LIST_ID) || 2;
      const added = await addToBrevo(email, env.BREVO_API_KEY, listId);
      if (!added) return json({ error: "brevo_error" }, 502);
      // 必寫 KV plan:${email} —— 不然 check-subscriber 會視為「未完成註冊」陷入循環
      const existing = await env.USER_PREFS.get(`plan:${email}`);
      if (!existing) await env.USER_PREFS.put(`plan:${email}`, "free");
      ctx.waitUntil(postSignupTasks(email, body.ref, env));
      ctx.waitUntil(recordConvert(env, {
        email, event: "subscribe_free",
        visit_id: body.visit_id, utm_source: body.utm_source,
        utm_medium: body.utm_medium, utm_campaign: body.utm_campaign,
      }));
      return json({ ok: true });
    }

    // Stripe Checkout Session for Premium 試讀 (coupon baked in,客戶不需輸碼)
    if (url.pathname === "/stripe/checkout-trial" && request.method === "POST") {
      let body = {};
      try { body = await request.json(); } catch {}
      const email = (body.email || "").trim().toLowerCase();
      const refCode = (body.ref || "").trim();
      const utm = {
        utm_source: body.utm_source || "",
        utm_medium: body.utm_medium || "",
        utm_campaign: body.utm_campaign || "",
      };
      if (!env.STRIPE_SECRET_KEY) return json({ error: "missing_stripe_key" }, 500);
      const params = new URLSearchParams();
      params.set("mode", "subscription");
      params.set("line_items[0][price]", "price_1TZAUyBdHwgNDiM7rpsa0HDB");
      params.set("line_items[0][quantity]", "1");
      params.set("discounts[0][coupon]", "premium_trial_v2");
      params.set("success_url", "https://marketdaily.ai/dashboard.html?welcome=premium&sid={CHECKOUT_SESSION_ID}");
      params.set("cancel_url", "https://marketdaily.ai/pricing.html?cancel=1");
      params.set("billing_address_collection", "auto");
      if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) params.set("customer_email", email);
      if (refCode) params.set("metadata[ref]", refCode);
      if (utm.utm_source) params.set("metadata[utm_source]", utm.utm_source);
      if (utm.utm_medium) params.set("metadata[utm_medium]", utm.utm_medium);
      if (utm.utm_campaign) params.set("metadata[utm_campaign]", utm.utm_campaign);
      try {
        const r = await fetch("https://api.stripe.com/v1/checkout/sessions", {
          method: "POST",
          headers: {
            "Authorization": "Bearer " + env.STRIPE_SECRET_KEY,
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: params.toString(),
        });
        const data = await r.json();
        if (!r.ok || !data.url) {
          console.log("stripe session error:", JSON.stringify(data));
          return json({ error: "stripe_error", detail: data.error?.message || "unknown" }, 502);
        }
        return json({ url: data.url });
      } catch (e) {
        return json({ error: "network", detail: String(e) }, 502);
      }
    }

    // AI Customer Support endpoint
    if (url.pathname === "/support" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch {
        return json({ error: "Invalid request" }, 400);
      }
      const { name, email, topic, message } = body;
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !message) {
        return json({ error: "missing_fields" }, 400);
      }

      const aiReply = await generateSupportResponse(name, topic, message, env.ANTHROPIC_API_KEY);
      await sendSupportReply(email, name, topic, message, aiReply, env.BREVO_API_KEY);
      await notifyAdmin(email, name, topic, message, aiReply, env.BREVO_API_KEY);
      return json({ ok: true });
    }

    // Get or generate referral code for a user
    if (url.pathname === "/get-referral" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email) return json({ error: "invalid_email" }, 400);

      let userData = await env.USER_PREFS.get(`referral:user:${email}`);
      if (userData) {
        return json(JSON.parse(userData));
      }

      // Generate new referral code
      let code = generateRefCode(email);
      // Ensure uniqueness
      let existing = await env.USER_PREFS.get(`referral:code:${code}`);
      if (existing) {
        code = generateRefCode(email) + Math.floor(Math.random()*9);
      }

      const newData = { code, clicks: 0, conversions: 0, created_at: new Date().toISOString() };
      await env.USER_PREFS.put(`referral:user:${email}`, JSON.stringify(newData));
      await env.USER_PREFS.put(`referral:code:${code}`, email);
      return json(newData);
    }

    // Aggregated referral stats for dashboard
    if (url.pathname === "/referral-stats" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email) return json({ error: "invalid_email" }, 400);

      let userRaw = await env.USER_PREFS.get(`referral:user:${email}`);
      let user;
      if (userRaw) {
        user = JSON.parse(userRaw);
      } else {
        let code = generateRefCode(email);
        const existing = await env.USER_PREFS.get(`referral:code:${code}`);
        if (existing) code = generateRefCode(email) + Math.floor(Math.random()*9);
        user = { code, clicks: 0, conversions: 0, created_at: new Date().toISOString() };
        await env.USER_PREFS.put(`referral:user:${email}`, JSON.stringify(user));
        await env.USER_PREFS.put(`referral:code:${code}`, email);
      }

      const bonusRaw = await env.USER_PREFS.get(`bonus:${email}`);
      const bonus = bonusRaw ? JSON.parse(bonusRaw) : { days_credit: 0, history: [] };
      const refs = Array.isArray(user.referrals) ? user.referrals.slice(-5).reverse() : [];

      return json({
        code: user.code,
        link: `https://marketdaily.ai/?ref=${user.code}&utm_source=referral&utm_medium=user&utm_campaign=share`,
        total_referrals: user.total_referrals || (Array.isArray(user.referrals) ? user.referrals.length : 0) || 0,
        clicks: user.clicks || 0,
        total_bonus_days: bonus.days_credit || 0,
        recent_referrals: refs.map(r => ({ email: maskEmail(r.email), ts: r.ts })),
      });
    }

    // Track referral click (called from landing page when ?ref= param present)
    if (url.pathname === "/track-referral-click" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const code = (body.code || "").trim().toUpperCase();
      if (!code) return json({ ok: false });

      const ownerEmail = await env.USER_PREFS.get(`referral:code:${code}`);
      if (!ownerEmail) return json({ ok: false, error: "invalid_code" });

      const raw = await env.USER_PREFS.get(`referral:user:${ownerEmail}`);
      if (raw) {
        const data = JSON.parse(raw);
        data.clicks = (data.clicks || 0) + 1;
        await env.USER_PREFS.put(`referral:user:${ownerEmail}`, JSON.stringify(data));
      }
      return json({ ok: true });
    }

    // Stripe webhook endpoint
    if (request.method !== "POST") {
      return new Response("MarketDaily Webhook OK", { status: 200 });
    }

    const payload = await request.text();
    const sig = request.headers.get("stripe-signature");

    const valid = await verifyStripeSignature(payload, sig, env.STRIPE_WEBHOOK_SECRET);
    if (!valid) {
      return new Response("Invalid signature", { status: 401 });
    }

    const event = JSON.parse(payload);
    const listId = parseInt(env.BREVO_LIST_ID) || 2;

    if (event.type === "checkout.session.completed") {
      const session = event.data.object || {};
      const email = (session.customer_details?.email || session.customer_email || "").trim().toLowerCase();
      if (email) {
        const tier = TIER_BY_AMOUNT[session.amount_total] || "付費";
        await addToBrevo(email, env.BREVO_API_KEY, listId, { PAID: true, PLAN: "paid", PLAN_TIER: tier });
        // Pro 改為「Premium 試讀首月」定位 — Pro 購買者立即享 Premium 全功能(LINE 推播 + AI Q&A 等)
        await env.USER_PREFS.put(`plan:${email}`, "premium");
        // 標記試讀者,給後續續訂提醒 / 帳務追蹤用
        if (tier === "Pro") {
          await env.USER_PREFS.put(`premium_trial:${email}`, JSON.stringify({
            started_at: Date.now(),
            iso: new Date().toISOString(),
            stripe_amount: session.amount_total,
          }));
        }
        if (session.customer) await env.USER_PREFS.put(`stripe-cust:${session.customer}`, email);
        // 歡迎信與補寄日報背景化 —— webhook 快速回 200,避免 Stripe 因逾時重送
        ctx.waitUntil((async () => {
          // 付費用戶也記 signup_ts,讓 lifecycle email 系統涵蓋他們(D7 會自動跳過 paid)
          try {
            const existing = await env.USER_PREFS.get(`signup:${email}`);
            if (!existing) {
              await env.USER_PREFS.put(`signup:${email}`, JSON.stringify({
                ts: Date.now(),
                iso: new Date().toISOString(),
                is_paid: true,
                tier: tier || "paid",
                ref: (session.metadata || {}).ref || null,
              }));
            }
          } catch (e) { console.log("stripe signup ts error:", String(e)); }
          try { await sendWelcomeEmail(email, env.BREVO_API_KEY, true, tier); }
          catch (e) { console.log("stripe welcome error:", String(e)); }
          try { await sendTodayDigestToOne(email, env.BREVO_API_KEY, env.USER_PREFS); }
          catch (e) { console.log("stripe digest error:", String(e)); }
        })());
        // Attribution: Stripe Checkout 透過 session.metadata 帶 visit_id / utm / ref
        const md = session.metadata || {};
        if (md.ref) ctx.waitUntil(grantReferralReward(env, md.ref, email));
        ctx.waitUntil(recordConvert(env, {
          email,
          event: tier === "Premium" ? "subscribe_premium" : "subscribe_pro",
          visit_id: md.visit_id, utm_source: md.utm_source,
          utm_medium: md.utm_medium, utm_campaign: md.utm_campaign,
        }));
        // Meta Conversions API:server-side Purchase event(iOS14+ pixel 遮蔽必做)
        ctx.waitUntil(sendMetaPurchase(env, {
          email,
          value: (session.amount_total || 0) / 100,
          currency: (session.currency || "twd").toUpperCase(),
          eventId: session.id,  // 用 stripe session id 當 event_id,跟 client-side dedupe
          fbp: md.fbp || null,
          fbc: md.fbc || null,
          clientIp: request.headers.get("cf-connecting-ip") || null,
          clientUA: request.headers.get("user-agent") || null,
        }));
      }
    }

    if (event.type === "customer.subscription.deleted") {
      const custId = event.data.object?.customer;
      if (custId) {
        const email = await env.USER_PREFS.get(`stripe-cust:${custId}`);
        if (email) {
          await addToBrevo(email, env.BREVO_API_KEY, listId, { PAID: false, PLAN: "free" });
          await env.USER_PREFS.put(`plan:${email}`, "free");
        }
      }
    }

    return new Response("OK", { status: 200 });
  },

  // 兩條 cron:lifecycle(22:30 UTC 每日)+ reactive 偵測(每 15 分鐘)
  async scheduled(event, env, ctx) {
    if (event.cron === "30 22 * * *") {
      ctx.waitUntil(runLifecycleSweep(env));
    } else if (event.cron === "*/15 * * * *") {
      ctx.waitUntil(runReactiveDetection(env));
    } else {
      // 未知 cron(理論不會發生)— 兩個都跑保險
      ctx.waitUntil(runLifecycleSweep(env));
      ctx.waitUntil(runReactiveDetection(env));
    }
  }
};

// 掃所有訂戶,按 daysSinceSignup 派發 D1/D7/D14。
// 每位用戶 try/catch,單一失敗不擋下一個。每封信寫 lc_${type}_sent flag 防重複。
async function runLifecycleSweep(env) {
  const dayMs = 86400000;
  let cursor = undefined;
  let scanned = 0, sent = { d1: 0, d7: 0, d14: 0, d21: 0, d45: 0 }, errors = 0;
  // KV list 一頁 1000 筆;用 cursor 翻頁直到 list_complete 才停 —— 別把規模上限寫死。
  do {
    const opts = { prefix: "signup:", limit: 1000 };
    if (cursor) opts.cursor = cursor;
    const page = await env.USER_PREFS.list(opts);
    for (const key of page.keys) {
      scanned++;
      const email = key.name.slice("signup:".length);
      try {
        const raw = await env.USER_PREFS.get(key.name);
        if (!raw) continue;
        const meta = JSON.parse(raw);
        if (!meta.ts) continue;
        const days = Math.floor((Date.now() - meta.ts) / dayMs);
        if (days === 1) {
          if (!(await env.USER_PREFS.get(`lc_d1_sent:${email}`))) {
            await sendD1Email(email, env.BREVO_API_KEY, env);
            await env.USER_PREFS.put(`lc_d1_sent:${email}`, String(Date.now()));
            sent.d1++;
          }
        } else if (days === 7) {
          // 即時讀當下 plan,而不是註冊時的 tier —— 用戶 D1~D7 之間升級了就不該收 D7 折扣
          const plan = (await env.USER_PREFS.get(`plan:${email}`)) || "free";
          if (plan === "free" && !(await env.USER_PREFS.get(`lc_d7_sent:${email}`))) {
            await sendD7Email(email, env.BREVO_API_KEY, env);
            await env.USER_PREFS.put(`lc_d7_sent:${email}`, String(Date.now()));
            sent.d7++;
          }
        } else if (days === 14) {
          if (!(await env.USER_PREFS.get(`lc_d14_sent:${email}`))) {
            await sendD14Email(email, env.BREVO_API_KEY, env);
            await env.USER_PREFS.put(`lc_d14_sent:${email}`, String(Date.now()));
            sent.d14++;
          }
        } else if (days === 21) {
          // D21:習慣養成里程碑(已讀 ~15-18 封日報)+ 軟銷 Premium 試讀
          const plan = (await env.USER_PREFS.get(`plan:${email}`)) || "free";
          if (plan === "free" && !(await env.USER_PREFS.get(`lc_d21_sent:${email}`))) {
            await sendD21Email(email, env.BREVO_API_KEY, env);
            await env.USER_PREFS.put(`lc_d21_sent:${email}`, String(Date.now()));
            sent.d21 = (sent.d21 || 0) + 1;
          }
        } else if (days === 45) {
          // D45:重新介入 — 強化 Premium 升級(限時誘因)
          const plan = (await env.USER_PREFS.get(`plan:${email}`)) || "free";
          if (plan === "free" && !(await env.USER_PREFS.get(`lc_d45_sent:${email}`))) {
            await sendD45Email(email, env.BREVO_API_KEY, env);
            await env.USER_PREFS.put(`lc_d45_sent:${email}`, String(Date.now()));
            sent.d45 = (sent.d45 || 0) + 1;
          }
        }
      } catch (e) {
        errors++;
        console.log("lifecycle sweep error for", email, String(e));
      }
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);
  console.log("lifecycle sweep done:", JSON.stringify({ scanned, sent, errors }));
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

// 抓 Yahoo Finance chart。台股先試 .TW(上市)再試 .TWO(上櫃),
// 回傳第一個有實際報價的 result —— 任何台股(含上櫃、新加入的)都抓得到。
async function fetchYahooChart(base, isTW, interval, range, headers, cacheTtl) {
  const symbols = isTW ? [`${base}.TW`, `${base}.TWO`] : [base];
  for (const sym of symbols) {
    try {
      const res = await fetch(
        `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${interval}&range=${range}`,
        { headers, cf: { cacheTtl, cacheEverything: true } }
      );
      if (!res.ok) continue;
      const data = await res.json();
      const r = data?.chart?.result?.[0];
      if (r && r.meta && r.meta.regularMarketPrice != null) return r;
    } catch {}
  }
  return null;
}

async function verifyStripeSignature(payload, sigHeader, secret) {
  if (!sigHeader || !secret) return false;
  const parts = Object.fromEntries(sigHeader.split(",").map(p => p.split("=")));
  const timestamp = parts["t"];
  const signature = parts["v1"];
  const signed = `${timestamp}.${payload}`;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signed));
  const expected = Array.from(new Uint8Array(mac)).map(b => b.toString(16).padStart(2, "0")).join("");
  return expected === signature;
}

function getTaiwanDate() {
  const now = new Date();
  return new Date(now.getTime() + 8 * 60 * 60 * 1000).toISOString().split("T")[0];
}

// 補寄今日日報給「單一新訂閱者」—— 只寄本人,不碰其他訂閱者。
// 每日全名單廣播由每日 pipeline(main.py)負責,這裡絕不群發。
async function sendTodayDigestToOne(email, apiKey, kv) {
  const today = getTaiwanDate();

  // 同一位用戶當天最多補寄一次
  const sentKey = `digest_sent:${today}:${email}`;
  if (await kv.get(sentKey)) return;

  // 確認今天有 digest（讀 manifest）
  try {
    const manifestRes = await fetch(`https://marketdaily.ai/output/manifest.json?t=${Date.now()}`);
    if (!manifestRes.ok) return;
    const manifest = await manifestRes.json();
    if (!(manifest.dates || []).includes(today)) return; // 今天還沒有日報
  } catch { return; }

  // 抓今天的 digest HTML
  let digestHtml;
  try {
    const res = await fetch(`https://marketdaily.ai/output/digest_${today}.html`);
    if (!res.ok) return;
    digestHtml = await res.text();
    if (!digestHtml.includes('財經日報')) return; // SPA fallback guard
  } catch { return; }

  await kv.put(sentKey, "1", { expirationTtl: 86400 * 3 });

  await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      sender: { name: "MarketDaily 財經日報", email: "hello@marketdaily.ai" },
      to: [{ email }],
      subject: `📈 財經日報 ${today} — 今日市場速覽`,
      htmlContent: digestHtml,
    }),
  });
}

async function addToBrevo(email, apiKey, listId, attributes) {
  const body = { email, listIds: [listId], updateEnabled: true };
  if (attributes) body.attributes = attributes;
  // 限流(429)與伺服器錯誤(5xx)、網路錯誤都重試 —— 暫時性 Brevo 抖動不該害註冊失敗
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch("https://api.brevo.com/v3/contacts", {
        method: "POST",
        headers: { "api-key": apiKey, "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (res.ok || res.status === 400) return true; // 400 = 聯絡人已存在,仍視為成功
      if (res.status === 429 || res.status >= 500) {
        await new Promise(r => setTimeout(r, 600 * (attempt + 1)));
        continue;
      }
      return false; // 401 等其他錯誤 → 不重試
    } catch {
      await new Promise(r => setTimeout(r, 600 * (attempt + 1)));
    }
  }
  return false;
}

// 註冊成功後的背景工作:推薦轉換 + 歡迎信 + 補寄今日日報。
// 每項各自 try/catch —— 任一失敗都不影響「註冊已成功」這個結果。
async function postSignupTasks(email, refCode, env, isPaid = false, tier = "") {
  // signup_ts 是 lifecycle email 系統的時間錨點;只在第一次寫入,避免重訂閱重置 D1/D7/D14。
  try {
    const existing = await env.USER_PREFS.get(`signup:${email}`);
    if (!existing) {
      await env.USER_PREFS.put(`signup:${email}`, JSON.stringify({
        ts: Date.now(),
        iso: new Date().toISOString(),
        is_paid: isPaid,
        tier: tier || "free",
        ref: refCode || null,
      }));
    }
  } catch (e) { console.log("signup ts error:", String(e)); }
  try { await grantReferralReward(env, refCode, email); }
  catch (e) { console.log("postSignup referral error:", String(e)); }
  try {
    await sendWelcomeEmail(email, env.BREVO_API_KEY, isPaid, tier);
  } catch (e) { console.log("postSignup welcome error:", String(e)); }
  try {
    await sendTodayDigestToOne(email, env.BREVO_API_KEY, env.USER_PREFS);
  } catch (e) { console.log("postSignup digest error:", String(e)); }
}

// Meta Conversions API — server-side Purchase fire(配 client-side pixel 雙寫,Meta 用 eventID 自動 dedupe)
// 沒設 META_PIXEL_ID 或 META_CONVERSIONS_API_TOKEN secret 直接 noop,不報錯。
async function sha256Hex(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode((s || "").trim().toLowerCase()));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function sendMetaPurchase(env, opts) {
  if (!env.META_PIXEL_ID || !env.META_CONVERSIONS_API_TOKEN) return;
  try {
    const userData = {};
    if (opts.email) userData.em = [await sha256Hex(opts.email)];
    if (opts.fbp) userData.fbp = opts.fbp;
    if (opts.fbc) userData.fbc = opts.fbc;
    if (opts.clientIp) userData.client_ip_address = opts.clientIp;
    if (opts.clientUA) userData.client_user_agent = opts.clientUA;

    const body = {
      data: [{
        event_name: "Purchase",
        event_time: Math.floor(Date.now() / 1000),
        event_id: opts.eventId,
        action_source: "website",
        event_source_url: "https://marketdaily.ai/dashboard.html",
        user_data: userData,
        custom_data: {
          currency: opts.currency || "TWD",
          value: opts.value || 299,
          content_name: "premium_trial",
        },
      }],
    };
    const r = await fetch(`https://graph.facebook.com/v20.0/${env.META_PIXEL_ID}/events?access_token=${env.META_CONVERSIONS_API_TOKEN}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) console.log("Meta CAPI purchase fail:", r.status, (await r.text()).slice(0, 200));
  } catch (e) { console.log("Meta CAPI error:", String(e)); }
}

// 推薦獎勵兌現:雙方各得 30 天 Premium。防自推(含 Gmail alias)、防重複、月上限。
async function grantReferralReward(env, refCode, newEmail) {
  refCode = (refCode || "").trim().toUpperCase();
  newEmail = (newEmail || "").trim().toLowerCase();
  if (!refCode || !newEmail) return false;

  const referrer = await env.USER_PREFS.get(`referral:code:${refCode}`);
  if (!referrer) return false;

  // 防自推:用 normalizeEmail 比對,bob+a@gmail / bo.b@gmail / bob@gmail 都算同人
  if (normalizeEmail(referrer) === normalizeEmail(newEmail)) return false;

  // 防同一個被推薦人被多次兌現
  const dupKey = `referral:fulfilled:${newEmail}`;
  if (await env.USER_PREFS.get(dupKey)) return false;

  // 防同一個推薦人狂 stack 信用:每月上限 10 人
  const month = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 7);
  const monthKey = `referral:month:${referrer}:${month}`;
  const monthCount = parseInt((await env.USER_PREFS.get(monthKey)) || "0", 10);
  if (monthCount >= 10) return false;

  const ts = new Date().toISOString();
  await env.USER_PREFS.put(dupKey, JSON.stringify({ referrer, code: refCode, ts }));
  await env.USER_PREFS.put(monthKey, String(monthCount + 1), { expirationTtl: 60 * 86400 });

  const raw = await env.USER_PREFS.get(`referral:user:${referrer}`);
  if (raw) {
    const data = JSON.parse(raw);
    data.conversions = (data.conversions || 0) + 1;
    data.total_referrals = (data.total_referrals || 0) + 1;
    data.referrals = Array.isArray(data.referrals) ? data.referrals : [];
    data.referrals.push({ email: newEmail, ts });
    if (data.referrals.length > 50) data.referrals = data.referrals.slice(-50);
    await env.USER_PREFS.put(`referral:user:${referrer}`, JSON.stringify(data));
  }

  await addBonusDays(env, referrer, 30, `referred ${newEmail}`);
  await addBonusDays(env, newEmail, 30, `joined via ${refCode}`);
  return true;
}

async function addBonusDays(env, email, days, reason) {
  const key = `bonus:${email}`;
  const raw = await env.USER_PREFS.get(key);
  const data = raw ? JSON.parse(raw) : { days_credit: 0, history: [] };
  data.days_credit = (data.days_credit || 0) + days;
  data.history = Array.isArray(data.history) ? data.history : [];
  data.history.push({ ts: new Date().toISOString(), days, reason });
  if (data.history.length > 100) data.history = data.history.slice(-100);
  await env.USER_PREFS.put(key, JSON.stringify(data));
}

function maskEmail(e) {
  const [u, d] = (e || "").split("@");
  if (!u || !d) return e || "";
  const head = u.slice(0, 1);
  return `${head}${"*".repeat(Math.max(1, u.length - 1))}@${d}`;
}

async function generateSupportResponse(name, topic, message, apiKey) {
  if (!apiKey) return "感謝您的來信！我們會盡快回覆您。如有緊急問題，請直接聯繫 support@marketdaily.ai";
  try {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 600,
        system: `你是 MarketDaily（財經日報）的 AI 客服助理，服務態度親切專業。

【服務說明】
- 週一到週六早上 7:00 AM（台灣時間）寄送 AI 財經日報;週六是「本週回顧 + 下週重點」特別版,週日不寄信（美股、台股都沒開盤）
- 內容：美股 + 台股新聞、假訊息過濾、30 秒摘要、板塊分析、BTC/ETH
- 來源：Reuters、CNBC、Bloomberg、FT 等可信媒體

【方案】
- 免費方案：留 Email 即可訂閱,完全免費（不需邀請碼）
- Premium 方案：NT$500/月，隨時可取消

【常見問題處理】
- 帳號/訂閱問題：請用戶聯繫 support@marketdaily.ai
- 邀請碼問題：邀請碼由 Delvin 本人發出，數量有限
- 退訂：在 Email 底部點取消訂閱，或聯繫客服

請用繁體中文回覆，語氣友善，回答簡潔（3-5 句話即可）。`,
        messages: [{
          role: "user",
          content: `用戶姓名：${name || "用戶"}\n問題類型：${topic || "一般問題"}\n問題內容：${message}`,
        }],
      }),
    });
    if (!res.ok) throw new Error("API error");
    const data = await res.json();
    return data.content?.[0]?.text || "感謝您的來信！我們會盡快回覆您。";
  } catch {
    return "感謝您的來信！我們收到了您的問題，會盡快為您處理。如有緊急問題，請直接聯繫 support@marketdaily.ai";
  }
}

async function sendSupportReply(email, name, topic, message, aiReply, apiKey) {
  const html = `<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:560px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
  <div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);padding:28px 28px 22px;">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td width="52" valign="middle" style="padding-right:14px;">
          <img src="https://marketdaily.ai/logo-icon.svg" width="46" height="46" alt="MD" style="display:block;border-radius:12px;">
        </td>
        <td valign="middle">
          <div style="font-size:20px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;line-height:1.2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">MarketDaily</div>
          <div style="font-size:10px;color:#a5b4fc;letter-spacing:3px;text-transform:uppercase;margin-top:3px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">客服回覆</div>
        </td>
      </tr>
    </table>
    <h1 style="margin:0 0 6px;font-size:22px;font-weight:800;color:#fde68a;">Hi ${name || "你"} 👋</h1>
    <p style="margin:0;font-size:13px;color:#c4b5fd;">我們收到了你的問題，以下是回覆</p>
  </div>
  <div style="padding:28px;">
    <div style="background:#f8fafc;border-left:4px solid #6366f1;border-radius:0 8px 8px 0;padding:14px 18px;margin-bottom:24px;">
      <div style="font-size:11px;color:#888;font-weight:700;margin-bottom:6px;">你的問題</div>
      <p style="margin:0;font-size:14px;color:#444;line-height:1.6;">${message.replace(/\n/g, "<br>")}</p>
    </div>
    <div style="font-size:14px;color:#222;line-height:1.8;">${aiReply.replace(/\n/g, "<br>")}</div>
    <p style="margin-top:24px;font-size:13px;color:#888;line-height:1.7;">
      如果還有其他問題，隨時回覆這封信或到網站聯絡我們。<br>
      <a href="https://marketdaily.ai" style="color:#6366f1;text-decoration:none;font-weight:700;">marketdaily.ai</a>
    </p>
  </div>
  <div style="background:#1a1a2e;padding:16px 28px;text-align:center;font-size:11px;color:rgba(255,255,255,0.3);">
    財經日報 · AI 精選 · 假訊息過濾<br>
    本回覆由 AI 生成，如有複雜問題請聯繫 support@marketdaily.ai
  </div>
</div>
</body></html>`;

  await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      sender: { name: "財經日報客服", email: "hello@marketdaily.ai" },
      to: [{ email, name: name || "" }],
      subject: `Re: ${topic || "你的問題"} — 財經日報客服`,
      htmlContent: html,
    }),
  });
}

async function notifyAdmin(userEmail, name, topic, message, aiReply, apiKey) {
  const html = `<div style="font-family:sans-serif;max-width:560px;margin:0 auto;">
  <h2 style="color:#6366f1;">📩 新客服來信</h2>
  <p><strong>姓名：</strong>${name || "-"}</p>
  <p><strong>Email：</strong>${userEmail}</p>
  <p><strong>主題：</strong>${topic || "-"}</p>
  <p><strong>問題：</strong><br>${message.replace(/\n/g, "<br>")}</p>
  <hr>
  <p><strong>AI 回覆：</strong><br>${aiReply.replace(/\n/g, "<br>")}</p>
</div>`;

  await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      sender: { name: "財經日報客服系統", email: "hello@marketdaily.ai" },
      to: [{ email: "delvin.12345678@gmail.com" }],
      subject: `[客服] ${name || userEmail}：${topic || "一般問題"}`,
      htmlContent: html,
    }),
  });
}

async function sendWelcomeEmail(email, apiKey, isPaid = false, tier = "") {
  const subject = isPaid ? "✅ 訂閱成功！歡迎加入財經日報 🎉" : "✅ 邀請碼確認！歡迎加入財經日報 🎉";
  const tierLabel = tier && tier !== "付費" ? `${tier} 方案` : "付費方案";
  const planLine = isPaid
    ? `您的 <strong>${tierLabel}</strong>已啟用。`
    : "您的<strong>免費邀請方案</strong>已啟用。";

  const html = `<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:560px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

  <div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);padding:28px 28px 22px;">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td width="52" valign="middle" style="padding-right:14px;">
          <img src="https://marketdaily.ai/logo-icon.svg" width="46" height="46" alt="MD" style="display:block;border-radius:12px;">
        </td>
        <td valign="middle">
          <div style="font-size:20px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;line-height:1.2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">MarketDaily</div>
          <div style="font-size:10px;color:#a5b4fc;letter-spacing:3px;text-transform:uppercase;margin-top:3px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">AI 財經日報</div>
        </td>
      </tr>
    </table>
    <h1 style="margin:0 0 6px;font-size:22px;font-weight:800;color:#fde68a;">✅ 訂閱確認</h1>
    <p style="margin:0;font-size:13px;color:#c4b5fd;font-weight:500;letter-spacing:0.5px;">AI 精選 · 假訊息過濾 · 美股 + 台股</p>
  </div>

  <div style="padding:28px;">
    <p style="font-size:18px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">嗨！歡迎加入 👋</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 22px;">
      ${planLine}<br>
      從明天起，<strong>週一到週六早上 7:00 AM（台灣時間）</strong>，你會收到一封財經日報，30 秒看完市場重點。<br>
      <span style="color:#666;font-size:14px;">📅 <strong>週六</strong>是「本週回顧 + 下週重點」特別版,<strong>週日不寄信</strong>(美股、台股都沒開盤,休息一天)。</span>
    </p>

    <!-- 3 步驟開始 -->
    <div style="background:#f6f7fb;border:1px solid #e2e8f0;border-radius:14px;padding:22px 22px 12px;margin-bottom:20px;">
      <p style="margin:0 0 16px;font-size:16px;font-weight:800;color:#1a1a1a;">🚀 三個步驟，馬上開始</p>
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
          <td width="38" valign="top"><div style="width:28px;height:28px;border-radius:50%;background:#6366f1;color:#fff;font-size:15px;font-weight:800;text-align:center;line-height:28px;">1</div></td>
          <td style="padding-bottom:14px;font-size:15px;color:#333;line-height:1.65;"><strong>設定密碼</strong><br><span style="color:#666;">第一次登入時，系統會請你設定一組密碼（至少 6 位），請寫在紙上收好。</span></td>
        </tr>
        <tr>
          <td width="38" valign="top"><div style="width:28px;height:28px;border-radius:50%;background:#6366f1;color:#fff;font-size:15px;font-weight:800;text-align:center;line-height:28px;">2</div></td>
          <td style="padding-bottom:14px;font-size:15px;color:#333;line-height:1.65;"><strong>登入「我的專區」</strong><br><span style="color:#666;">用 Email 和密碼登入，就能看到你的專屬頁面。</span></td>
        </tr>
        <tr>
          <td width="38" valign="top"><div style="width:28px;height:28px;border-radius:50%;background:#6366f1;color:#fff;font-size:15px;font-weight:800;text-align:center;line-height:28px;">3</div></td>
          <td style="font-size:15px;color:#333;line-height:1.65;"><strong>設定你的股票</strong><br><span style="color:#666;">搜尋你關注的股票加入清單，每日報告就會幫你客製化。</span></td>
        </tr>
      </table>
    </div>

    <!-- 大按鈕 CTA -->
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:12px;">
      <tr>
        <td align="center">
          <a href="https://marketdaily.ai/dashboard.html?email=${encodeURIComponent(email)}" style="display:block;padding:17px 24px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:17px;font-weight:800;text-decoration:none;border-radius:12px;">🔑 設定密碼並登入 →</a>
        </td>
      </tr>
    </table>
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:24px;">
      <tr>
        <td align="center">
          <a href="https://marketdaily.ai/guide.html" style="display:block;padding:15px 24px;background:#ffffff;border:2px solid #6366f1;color:#4f46e5;font-size:16px;font-weight:800;text-decoration:none;border-radius:12px;">📖 看完整圖文教學 →</a>
        </td>
      </tr>
      <tr>
        <td align="center" style="padding-top:8px;">
          <span style="font-size:12px;color:#999;">不知道怎麼操作？點上面看一步步圖文說明</span>
        </td>
      </tr>
    </table>

    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:18px 20px;margin-bottom:20px;">
      <p style="margin:0 0 10px;font-size:14px;font-weight:800;color:#333;letter-spacing:0.5px;">📬 每天報告包含</p>
      <ul style="margin:0;padding-left:18px;font-size:14px;color:#555;line-height:2;">
        <li>☕ 30 秒重點摘要</li>
        <li>📈 美股 + 台股大盤動向</li>
        <li>₿ BTC / ETH 加密貨幣</li>
        <li>🔄 板塊輪動分析</li>
        <li>🔥 今日 5 大重要新聞（假訊息過濾）</li>
        <li>🔗 二階思考：美股如何影響台灣？</li>
        <li>📅 即將公布財報提醒</li>
      </ul>
    </div>

    <!-- 推薦好友區塊 -->
    <div style="background:linear-gradient(135deg,rgba(99,102,241,0.08),rgba(139,92,246,0.08));border:1px solid rgba(99,102,241,0.2);border-radius:12px;padding:18px 20px;margin-bottom:20px;">
      <p style="margin:0 0 8px;font-size:13px;font-weight:800;color:#4f46e5;">🎁 推薦好友，雙方各得 7 天 Pro</p>
      <p style="margin:0 0 12px;font-size:12px;color:#666;line-height:1.6;">你有專屬推薦連結，分享給朋友後，朋友完成訂閱，你們雙方都自動延長 7 天 Pro 方案。</p>
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
          <td align="center">
            <a href="https://marketdaily.ai/dashboard.html" style="display:inline-block;padding:10px 24px;background:#4f46e5;color:#fff;font-size:13px;font-weight:700;text-decoration:none;border-radius:10px;">查看我的推薦連結 →</a>
          </td>
        </tr>
      </table>
    </div>

    <p style="font-size:13px;color:#888;line-height:1.7;margin:0;">
      如果有任何問題，直接回覆這封信即可。<br>
      明天早上 7 點見！💪
    </p>
  </div>

  <div style="background:#1a1a2e;padding:16px 28px;text-align:center;font-size:11px;color:rgba(255,255,255,0.3);line-height:2;">
    財經日報 · AI 精選 · 假訊息過濾<br>
    本報告為 AI 生成，僅供參考，不構成投資建議<br><br>
    <a href="https://marketdaily.ai" style="color:#6366f1;text-decoration:none;font-weight:700;">🌐 marketdaily.ai</a>
    &nbsp;·&nbsp;
    <a href="https://marketdaily.ai/dashboard.html" style="color:#a5b4fc;text-decoration:none;">⚙️ 我的專區</a>
  </div>
</div>
</body>
</html>`;

  await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      sender: { name: "財經日報", email: "hello@marketdaily.ai" },
      to: [{ email }],
      subject,
      htmlContent: html,
    }),
  });
}

// --- Lifecycle Email 共用樣式(對齊 sendWelcomeEmail 玻璃卡風格)---
function lifecycleShell({ badge, headerTitle, headerSub, bodyHtml, footerNote }) {
  return `<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:560px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
  <div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);padding:28px 28px 22px;">
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td width="52" valign="middle" style="padding-right:14px;">
          <img src="https://marketdaily.ai/logo-icon.svg" width="46" height="46" alt="MD" style="display:block;border-radius:12px;">
        </td>
        <td valign="middle">
          <div style="font-size:20px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;line-height:1.2;">MarketDaily</div>
          <div style="font-size:10px;color:#a5b4fc;letter-spacing:3px;text-transform:uppercase;margin-top:3px;">${badge}</div>
        </td>
      </tr>
    </table>
    <h1 style="margin:0 0 6px;font-size:22px;font-weight:800;color:#fde68a;">${headerTitle}</h1>
    <p style="margin:0;font-size:13px;color:#c4b5fd;font-weight:500;letter-spacing:0.5px;">${headerSub}</p>
  </div>
  <div style="padding:28px;">${bodyHtml}</div>
  <div style="background:#1a1a2e;padding:16px 28px;text-align:center;font-size:11px;color:rgba(255,255,255,0.4);line-height:2;">
    ${footerNote || "財經日報 · AI 精選 · 假訊息過濾"}<br>
    <a href="https://marketdaily.ai" style="color:#6366f1;text-decoration:none;font-weight:700;">marketdaily.ai</a>
    &nbsp;·&nbsp;
    <a href="https://marketdaily.ai/dashboard.html" style="color:#a5b4fc;text-decoration:none;">我的專區</a>
  </div>
</div>
</body></html>`;
}

async function sendLifecycleEmail(email, apiKey, subject, html) {
  return fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      sender: { name: "MarketDaily 財經日報", email: "hello@marketdaily.ai" },
      to: [{ email }],
      subject,
      htmlContent: html,
    }),
  });
}

// D1:設股票偏好 —— 沒設就會收到通用版日報,失去個人化價值
async function sendD1Email(email, apiKey, env) {
  const subject = "✋ 把你的持股告訴 MarketDaily,日報才會真的個人化";
  const cta = `https://marketdaily.ai/preferences.html?utm_source=lifecycle&utm_campaign=d1_preferences&email=${encodeURIComponent(email)}`;
  const body = `
    <p style="font-size:17px;font-weight:800;color:#1a1a1a;margin:0 0 14px;">嗨!歡迎來到第二天 👋</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 18px;">
      MarketDaily 的日報是<strong>個人化</strong>的 —— 我們只挑跟「你關心的股票」相關的新聞、財報、技術訊號。<br>
      如果你還沒設定持股,你昨天收到的會是<strong>通用版</strong>,跟你自己的部位無關。
    </p>
    <div style="background:#f6f7fb;border:1px solid #e2e8f0;border-radius:14px;padding:18px 22px;margin-bottom:22px;">
      <p style="margin:0 0 12px;font-size:14px;font-weight:800;color:#1a1a1a;">三種人都適用</p>
      <ul style="margin:0;padding-left:20px;font-size:14px;color:#444;line-height:2;">
        <li>🇺🇸 <strong>美股玩家</strong> — 加 NVDA、TSLA、AAPL 之類,只看你持有的</li>
        <li>🇹🇼 <strong>台股投資人</strong> — 加 2330 台積電、2454 聯發科,自動含中英文名</li>
        <li>🌏 <strong>美台混合</strong> — 同一份日報同時涵蓋,不必分兩個帳號</li>
      </ul>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td align="center">
          <a href="${cta}" style="display:block;padding:17px 24px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:17px;font-weight:800;text-decoration:none;border-radius:12px;">設定我的股票偏好 →</a>
        </td>
      </tr>
    </table>
    <p style="font-size:13px;color:#888;line-height:1.7;margin:0;text-align:center;">
      30 秒設定,從明天起每封日報只給你關心的股票。
    </p>`;
  const html = lifecycleShell({
    badge: "Day 1 · 個人化設定",
    headerTitle: "✋ 還沒設股票?日報會跟你沒關係",
    headerSub: "30 秒搞定,從明天起完全個人化",
    bodyHtml: body,
  });
  return sendLifecycleEmail(email, apiKey, subject, html);
}

// D7:Premium 7 折(只給 free 用戶,由 sweep 控制) —— 一週讀者最容易升級的時機
async function sendD7Email(email, apiKey, env) {
  const subject = "📊 你已讀了 7 封日報 — 解鎖 Premium 三大功能,首月 7 折";
  const cta = `https://buy.stripe.com/cNi3cu74FbI80uSfrG4Ja03?utm_source=lifecycle&utm_campaign=d7_premium&prefilled_email=${encodeURIComponent(email)}`;
  const body = `
    <p style="font-size:17px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">過去 7 天,你省下大概 35 分鐘掃新聞的時間 ☕</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 22px;">
      你已經習慣每天早上 7 點看 MarketDaily,接下來這三個功能會讓你<strong>從「看新聞」進化到「真的能下手」</strong>。
    </p>
    <div style="background:linear-gradient(135deg,rgba(99,102,241,0.08),rgba(139,92,246,0.08));border:1px solid rgba(99,102,241,0.25);border-radius:14px;padding:20px 22px;margin-bottom:22px;">
      <p style="margin:0 0 14px;font-size:15px;font-weight:800;color:#4f46e5;">Premium 三大功能</p>
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
          <td width="38" valign="top"><div style="width:30px;height:30px;border-radius:50%;background:#6366f1;color:#fff;font-size:14px;font-weight:800;text-align:center;line-height:30px;">1</div></td>
          <td style="padding-bottom:14px;font-size:14px;color:#333;line-height:1.7;"><strong>個股深度分析</strong><br><span style="color:#666;">AI 給每支股票的進場 / 停損價位區間,不再只是「漲了 X%」。</span></td>
        </tr>
        <tr>
          <td width="38" valign="top"><div style="width:30px;height:30px;border-radius:50%;background:#6366f1;color:#fff;font-size:14px;font-weight:800;text-align:center;line-height:30px;">2</div></td>
          <td style="padding-bottom:14px;font-size:14px;color:#333;line-height:1.7;"><strong>LINE 即時推播</strong><br><span style="color:#666;">影響你持股的重大新聞,5 分鐘內推到你 LINE。</span></td>
        </tr>
        <tr>
          <td width="38" valign="top"><div style="width:30px;height:30px;border-radius:50%;background:#6366f1;color:#fff;font-size:14px;font-weight:800;text-align:center;line-height:30px;">3</div></td>
          <td style="font-size:14px;color:#333;line-height:1.7;"><strong>月度投資組合健檢</strong><br><span style="color:#666;">每月一份報告,告訴你持股的集中度、產業偏重、漏掉的對沖。</span></td>
        </tr>
      </table>
    </div>
    <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:16px 20px;margin-bottom:20px;text-align:center;">
      <div style="font-size:12px;color:#92400e;font-weight:700;letter-spacing:1px;margin-bottom:6px;">本週限定</div>
      <div style="font-size:15px;color:#1a1a1a;">
        <span style="text-decoration:line-through;color:#999;">NT$299</span>
        &nbsp;→&nbsp;
        <strong style="font-size:22px;color:#d97706;">NT$209</strong>
        <span style="color:#666;font-size:13px;"> / 首月(7 折)</span>
      </div>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td align="center">
          <a href="${cta}" style="display:block;padding:17px 24px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:17px;font-weight:800;text-decoration:none;border-radius:12px;">立即升級 →</a>
        </td>
      </tr>
    </table>
    <p style="font-size:12px;color:#888;line-height:1.7;margin:0;text-align:center;">
      不想升級?完全 OK,繼續用免費版享受日報。<br>這封信不會再寄第二次。
    </p>`;
  const html = lifecycleShell({
    badge: "Day 7 · Premium 7 折",
    headerTitle: "📊 你準備好下一步了嗎?",
    headerSub: "從「看新聞」進化到「真的能下手」",
    bodyHtml: body,
  });
  return sendLifecycleEmail(email, apiKey, subject, html);
}

// D14:推薦計畫 —— 兩週的讀者最有資格幫我們背書
async function sendD14Email(email, apiKey, env) {
  const subject = "🎁 已經發過你 14 封日報了 — 邀請朋友,雙方都得 30 天 Premium";

  // 從既有 referral helper 拿 code;沒有就現場生一個(維持冪等)。
  let refCode = null;
  try {
    const raw = await env.USER_PREFS.get(`referral:user:${email}`);
    if (raw) {
      refCode = JSON.parse(raw).code || null;
    } else {
      let code = generateRefCode(email);
      const existing = await env.USER_PREFS.get(`referral:code:${code}`);
      if (existing) code = generateRefCode(email) + Math.floor(Math.random() * 9);
      const newData = { code, clicks: 0, conversions: 0, created_at: new Date().toISOString() };
      await env.USER_PREFS.put(`referral:user:${email}`, JSON.stringify(newData));
      await env.USER_PREFS.put(`referral:code:${code}`, email);
      refCode = code;
    }
  } catch (e) { console.log("D14 ref code error:", String(e)); }

  const refLink = refCode
    ? `https://marketdaily.ai/?ref=${refCode}&utm_source=lifecycle&utm_campaign=d14_referral`
    : `https://marketdaily.ai/dashboard.html#referral`;
  const dashLink = `https://marketdaily.ai/dashboard.html?email=${encodeURIComponent(email)}#referral`;
  const shareText = `最近發現一個東西不錯 —— marketdaily.ai 每天早上 7 點寄 AI 過濾過的財經日報。我已經用兩週,真的省很多時間。你訂閱我們雙邊都得 30 天 Premium:${refLink}`;

  const body = `
    <p style="font-size:17px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">謝謝你陪 MarketDaily 兩週 🙏</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 22px;">
      如果這 14 封信讓你早晨變更聰明,有件事想拜託你 ——<br>
      <strong>把它分享給一個朋友</strong>,我們的成長 95% 靠口碑。
    </p>
    <div style="background:linear-gradient(135deg,rgba(99,102,241,0.08),rgba(139,92,246,0.08));border:1px solid rgba(99,102,241,0.25);border-radius:14px;padding:20px 22px;margin-bottom:22px;text-align:center;">
      <p style="margin:0 0 8px;font-size:13px;color:#4f46e5;font-weight:800;letter-spacing:1px;">推薦計畫</p>
      <p style="margin:0 0 14px;font-size:20px;font-weight:800;color:#1a1a1a;line-height:1.4;">
        雙方各得 <span style="color:#6366f1;">30 天 Premium</span>
      </p>
      <p style="margin:0;font-size:13px;color:#666;line-height:1.7;">
        朋友點你的連結訂閱後,你和他的帳號都自動延長 30 天 Premium —— 包含 AI 投資助手、LINE 即時推播、深度分析。
      </p>
    </div>
    <div style="background:#f6f7fb;border:1px dashed #cbd5e1;border-radius:12px;padding:14px 18px;margin-bottom:18px;">
      <div style="font-size:11px;color:#888;font-weight:700;letter-spacing:1px;margin-bottom:6px;">你的專屬推薦連結</div>
      <div style="font-size:13px;color:#4f46e5;word-break:break-all;font-family:'SF Mono',Menlo,monospace;">${refLink}</div>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td align="center">
          <a href="${dashLink}" style="display:block;padding:17px 24px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:17px;font-weight:800;text-decoration:none;border-radius:12px;">複製我的推薦連結 →</a>
        </td>
      </tr>
    </table>
    <div style="background:#f8fafc;border-left:4px solid #6366f1;border-radius:0 8px 8px 0;padding:14px 18px;margin-bottom:14px;">
      <div style="font-size:11px;color:#888;font-weight:700;margin-bottom:6px;">分享範例文案(直接複製貼上)</div>
      <p style="margin:0;font-size:13px;color:#444;line-height:1.7;">${shareText}</p>
    </div>
    <p style="font-size:12px;color:#888;line-height:1.7;margin:0;text-align:center;">
      這封信不會再寄第二次。明天早上 7 點見 💪
    </p>`;
  const html = lifecycleShell({
    badge: "Day 14 · 推薦計畫",
    headerTitle: "🎁 邀請朋友,雙方各得 30 天 Premium",
    headerSub: "兩週的讀者,是我們最好的代言人",
    bodyHtml: body,
  });
  return sendLifecycleEmail(email, apiKey, subject, html);
}

async function sendD21Email(email, apiKey, env) {
  const subject = "📊 你已經養成早晨財經習慣了 — 要不要升級 Premium 試讀首月 NT$299?";
  const upgradeLink = `https://marketdaily.ai/pricing?utm_source=lifecycle&utm_campaign=d21_premium&email=${encodeURIComponent(email)}`;
  const body = `
    <p style="font-size:17px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">三週了 ☕</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 22px;">
      你已經連讀 ~18 封 MarketDaily 日報 —— 早晨財經習慣養成了。<br>
      接下來,要不要試試 <strong>Premium 全功能</strong>?
    </p>
    <div style="background:linear-gradient(135deg,rgba(168,85,247,0.10),rgba(99,102,241,0.10));border:1px solid rgba(168,85,247,0.30);border-radius:14px;padding:22px 24px;margin-bottom:22px;">
      <p style="margin:0 0 14px;font-size:14px;color:#7e22ce;font-weight:800;letter-spacing:1px;">PREMIUM 試讀</p>
      <p style="margin:0 0 6px;font-size:26px;font-weight:900;color:#1a1a1a;">
        首月 NT$299 <span style="font-size:18px;color:rgba(0,0,0,0.4);text-decoration:line-through;font-weight:700;margin-left:8px;">NT$499</span>
      </p>
      <p style="margin:0 0 16px;font-size:13px;color:#666;">之後 NT$499/月,隨時取消,30 天無理由退費</p>
      <ul style="margin:0;padding-left:18px;font-size:14px;color:#444;line-height:1.95;">
        <li><strong>個人化日報</strong>(無限持股追蹤,免費版只 5 支)</li>
        <li><strong>個股深度分析</strong>(每支 3-5 段,不只是 1 句 verdict)</li>
        <li><strong>LINE Bot 雙向 AI 對話</strong>(盤中可直接問你的持股)</li>
        <li><strong>重大新聞 LINE 即時推播</strong>(5 分鐘內到)</li>
      </ul>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td align="center">
          <a href="${upgradeLink}" style="display:block;padding:17px 24px;background:linear-gradient(135deg,#a855f7,#6366f1);color:#fff;font-size:17px;font-weight:800;text-decoration:none;border-radius:12px;">試讀首月 NT$299 →</a>
        </td>
      </tr>
    </table>
    <p style="font-size:13px;color:#666;line-height:1.7;margin:0 0 8px;text-align:center;">
      30 天不滿意?寄信給 <a href="mailto:marketdailyhq@gmail.com" style="color:#6366f1;">marketdailyhq@gmail.com</a> 全額退費,不問理由。
    </p>
    <p style="font-size:12px;color:#888;line-height:1.7;margin:0;text-align:center;">
      還沒準備好升級沒關係,免費版會繼續寄。明早 7 點見 ☕
    </p>`;
  const html = lifecycleShell({
    badge: "Day 21 · 習慣養成",
    headerTitle: "📊 你已經是 MarketDaily 老朋友了",
    headerSub: "三週 ~18 封日報 — 該升級了嗎?",
    bodyHtml: body,
  });
  return sendLifecycleEmail(email, apiKey, subject, html);
}

async function sendD45Email(email, apiKey, env) {
  const subject = "⏰ 最後一次提醒:Premium 試讀 NT$299(45 天後就沒有了)";
  const upgradeLink = `https://marketdaily.ai/pricing?utm_source=lifecycle&utm_campaign=d45_final&email=${encodeURIComponent(email)}`;
  const body = `
    <p style="font-size:17px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">45 天了 — 想跟你說一聲</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 22px;">
      你已收 MarketDaily 日報超過 6 週(扣掉週日約 38 封)。<br>
      如果還沒升級 Premium,這封是<strong>最後一次主動推銷</strong>。
      之後我們不會再寄升級信,免費版會繼續陪你。
    </p>
    <div style="background:rgba(251,191,36,0.08);border:1px solid rgba(251,191,36,0.32);border-radius:14px;padding:20px 22px;margin-bottom:22px;">
      <p style="margin:0 0 10px;font-size:13px;color:#b45309;font-weight:800;letter-spacing:1px;">⚡ 為什麼我推薦你升級</p>
      <p style="margin:0 0 14px;font-size:15px;color:#1a1a1a;font-weight:700;line-height:1.6;">
        因為你已經養成讀日報的習慣 —— 表示你真的在意自己的投資組合。
      </p>
      <p style="margin:0;font-size:14px;color:#666;line-height:1.8;">
        Premium 的核心價值是 <strong>盤中即時對話</strong>(LINE Bot)。<br>
        早上 7 點看完 → 白天有突發狀況 → 直接 LINE 問 AI 「我的 NVDA 現在怎樣?」<br>
        5 秒給你答案,不用自己滑 PTT。
      </p>
    </div>
    <div style="background:linear-gradient(135deg,rgba(168,85,247,0.10),rgba(99,102,241,0.10));border:1px solid rgba(168,85,247,0.30);border-radius:14px;padding:22px 24px;margin-bottom:22px;text-align:center;">
      <p style="margin:0 0 6px;font-size:26px;font-weight:900;color:#1a1a1a;">
        首月 NT$299 <span style="font-size:18px;color:rgba(0,0,0,0.4);text-decoration:line-through;font-weight:700;margin-left:8px;">NT$499</span>
      </p>
      <p style="margin:0;font-size:13px;color:#666;">之後 NT$499/月 · 隨時取消 · 30 天無理由退費</p>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td align="center">
          <a href="${upgradeLink}" style="display:block;padding:17px 24px;background:linear-gradient(135deg,#a855f7,#6366f1);color:#fff;font-size:17px;font-weight:800;text-decoration:none;border-radius:12px;">升級 Premium 首月 NT$299 →</a>
        </td>
      </tr>
    </table>
    <p style="font-size:13px;color:#666;line-height:1.7;margin:0;text-align:center;">
      不想升級?完全沒關係。免費版會繼續陪你,週一到週六早上 7 點 ☕
    </p>`;
  const html = lifecycleShell({
    badge: "Day 45 · 最後提醒",
    headerTitle: "⏰ 最後一次主動跟你聊升級",
    headerSub: "45 天了,該決定要不要 Premium",
    bodyHtml: body,
  });
  return sendLifecycleEmail(email, apiKey, subject, html);
}

// === Reactive Content helpers ===

// 命中條件:白名單關鍵字。earnings 必須同時出現大型股票名 — 避免一般 earnings 新聞炸量。
const REACTIVE_KEYWORDS_GENERAL = [
  "fed", "federal reserve", "rate hike", "rate cut", "利率",
  "tariff", "關稅",
  "recession", "inflation", "cpi", "通膨",
  "vix", "crash", "melt-up", "melt up",
];
const REACTIVE_EARNINGS_TICKERS = [
  "nvda", "aapl", "goog", "googl", "meta", "msft", "tsla",
  "tsm", "tsmc", "台積電", "鴻海", "hon hai",
];

function matchReactiveKeywords(title) {
  const t = (title || "").toLowerCase();
  if (!t) return null;
  for (const kw of REACTIVE_KEYWORDS_GENERAL) {
    if (t.includes(kw)) return kw;
  }
  if (t.includes("earnings") || t.includes("財報") || t.includes("法說")) {
    for (const tk of REACTIVE_EARNINGS_TICKERS) {
      if (t.includes(tk)) return `earnings:${tk}`;
    }
  }
  return null;
}

// 不引外部套件 — 用 regex 解 RSS item。穩定度夠 MVP,壞 feed 跳過。
function parseRssItems(xml) {
  if (!xml || typeof xml !== "string") return [];
  const items = [];
  const itemRe = /<item[\s\S]*?<\/item>/gi;
  const matches = xml.match(itemRe) || [];
  for (const block of matches.slice(0, 50)) {
    const title = extractRssField(block, "title");
    const link = extractRssField(block, "link");
    const pub = extractRssField(block, "pubDate");
    const desc = extractRssField(block, "description");
    if (title && link) items.push({ title, link, pubDate: pub, description: desc });
  }
  return items;
}
function extractRssField(block, tag) {
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, "i");
  const m = block.match(re);
  if (!m) return "";
  let v = m[1].trim();
  v = v.replace(/^<!\[CDATA\[/, "").replace(/\]\]>$/, "").trim();
  v = v.replace(/<[^>]+>/g, "").trim();
  return v;
}

// FNV-1a hash → 8 字元 base36,夠用來判重
function hashTitle(s) {
  let h = 0x811c9dc5;
  const str = (s || "").toLowerCase().trim();
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
  }
  return h.toString(36).padStart(7, "0").slice(0, 8);
}

async function fetchRss(url, ua) {
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": ua, "Accept": "application/rss+xml, application/xml, text/xml, */*" },
      cf: { cacheTtl: 60, cacheEverything: true },
    });
    if (!res.ok) return "";
    return await res.text();
  } catch { return ""; }
}

async function runReactiveDetection(env) {
  const ua = "Mozilla/5.0 (compatible; MarketDailyBot/1.0; +https://marketdaily.ai)";
  const sources = [
    { name: "yahoo", url: "https://finance.yahoo.com/rss/topstories" },
    { name: "marketwatch", url: "https://feeds.marketwatch.com/marketwatch/topstories/" },
  ];
  if (env.NEWSAPI_KEY) {
    sources.push({
      name: "newsapi",
      url: `https://newsapi.org/v2/top-headlines?category=business&language=en&apiKey=${env.NEWSAPI_KEY}`,
      isJson: true,
    });
  }

  const candidates = [];
  for (const s of sources) {
    try {
      if (s.isJson) {
        const res = await fetch(s.url, { headers: { "User-Agent": ua } });
        if (!res.ok) continue;
        const data = await res.json();
        for (const a of (data.articles || []).slice(0, 30)) {
          candidates.push({
            source: s.name, title: a.title || "",
            link: a.url || "", pubDate: a.publishedAt || "",
            description: a.description || "",
          });
        }
      } else {
        const xml = await fetchRss(s.url, ua);
        for (const it of parseRssItems(xml)) {
          candidates.push({ source: s.name, ...it });
        }
      }
    } catch (e) {
      console.log("reactive source error", s.name, String(e));
    }
  }

  let processed = 0, hits = 0, dupes = 0, ai_ok = 0, ai_fail = 0;
  const MAX_NEW_PER_SWEEP = 3;
  for (const c of candidates) {
    const kw = matchReactiveKeywords(c.title);
    if (!kw) continue;
    hits++;
    const id = hashTitle(c.title);
    const seenKey = `reactive:seen:${id}`;
    if (await env.USER_PREFS.get(seenKey)) { dupes++; continue; }
    await env.USER_PREFS.put(seenKey, String(Date.now()), { expirationTtl: 86400 });
    if (processed >= MAX_NEW_PER_SWEEP) continue;
    processed++;

    let ai = null;
    try {
      ai = await geminiHotTake(env, c.title, c.description || "");
    } catch (e) { console.log("gemini error", String(e)); }
    if (!ai) { ai_fail++; continue; }
    ai_ok++;

    const item = {
      id,
      ts: Date.now(),
      source: c.source,
      source_url: c.link,
      source_title: c.title,
      matched_keyword: kw,
      ai,
      status: "pending",
    };
    await env.USER_PREFS.put(`reactive:pending:${id}`,
      JSON.stringify(item), { expirationTtl: 86400 * 2 });

    await sendLineAdminPush(env,
      `⚡ Hot take pending\n${ai.headline}\n${(ai.body || "").slice(0, 60)}...\n→ marketdaily.ai/admin-reactive.html`
    );
  }
  console.log("reactive sweep:", JSON.stringify({
    candidates: candidates.length, hits, dupes, processed, ai_ok, ai_fail,
  }));
}

// Gemini Flash:結構化 JSON。失敗回 null,不阻塞。
async function geminiHotTake(env, title, desc) {
  if (!env.GEMINI_API_KEY) return null;
  const prompt =
    `你是一位台灣財經評論員,要為散戶寫一段 80 字繁中 hot take。\n` +
    `來源新聞:\n標題:${title}\n描述:${desc || "(無描述)"}\n\n` +
    `請只回傳純 JSON(無 markdown code fence),格式:\n` +
    `{"headline":"30 字以內繁中標題,有觀點不是描述",` +
    `"body":"80 字繁中分析,告訴讀者為什麼重要與影響哪些族群",` +
    `"bias":"bullish | bearish | neutral",` +
    `"tickers":["相關股票代號,大寫,陣列最多 5 個"],` +
    `"tag":"Fed/個股財報/關稅/通膨/市場情緒 擇一"}`;
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${env.GEMINI_API_KEY}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.7, responseMimeType: "application/json" },
      }),
    }
  );
  if (!res.ok) {
    console.log("gemini status", res.status, (await res.text()).slice(0, 200));
    return null;
  }
  const data = await res.json();
  const text = data?.candidates?.[0]?.content?.parts?.[0]?.text || "";
  if (!text) return null;
  let parsed;
  try { parsed = JSON.parse(text); } catch {
    const m = text.match(/\{[\s\S]*\}/);
    if (!m) return null;
    try { parsed = JSON.parse(m[0]); } catch { return null; }
  }
  if (!parsed.headline || !parsed.body) return null;
  return {
    headline: String(parsed.headline).slice(0, 120),
    body: String(parsed.body).slice(0, 500),
    bias: ["bullish", "bearish", "neutral"].includes(parsed.bias) ? parsed.bias : "neutral",
    tickers: Array.isArray(parsed.tickers)
      ? parsed.tickers.slice(0, 5).map(t => String(t).toUpperCase().slice(0, 10))
      : [],
    tag: String(parsed.tag || "市場情緒").slice(0, 30),
  };
}

// LINE push 給主編個人帳號 — secret 不全就跳過,不阻塞
async function sendLineAdminPush(env, message) {
  const token = env.LINE_CHANNEL_ACCESS_TOKEN;
  const adminId = env.ADMIN_LINE_USER_ID;
  if (!token || !adminId) {
    console.log("LINE admin push skipped (missing LINE_CHANNEL_ACCESS_TOKEN or ADMIN_LINE_USER_ID)");
    return { ok: false, skipped: true };
  }
  try {
    const res = await fetch("https://api.line.me/v2/bot/message/push", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
      body: JSON.stringify({
        to: adminId,
        messages: [{ type: "text", text: message.slice(0, 4900) }],
      }),
    });
    return { ok: res.ok, status: res.status };
  } catch (e) { return { ok: false, error: String(e) }; }
}

// LINE broadcast(全訂戶)— live=false 預設只 log,避免開發階段誤推
async function sendLineBroadcast(env, message, live) {
  if (!live) {
    console.log("[mock] LINE broadcast:", message.slice(0, 100));
    return { ok: true, mocked: true };
  }
  const token = env.LINE_CHANNEL_ACCESS_TOKEN;
  if (!token) return { ok: false, error: "missing_token" };
  const res = await fetch("https://api.line.me/v2/bot/message/broadcast", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
    body: JSON.stringify({ messages: [{ type: "text", text: message.slice(0, 4900) }] }),
  });
  return { ok: res.ok, status: res.status };
}

// Threads:create container → publish。live=false 只 log。
async function sendThreadsPost(env, message, live) {
  if (!live) {
    console.log("[mock] Threads post:", message.slice(0, 100));
    return { ok: true, mocked: true };
  }
  const token = env.THREADS_ACCESS_TOKEN;
  const userId = env.THREADS_USER_ID;
  if (!token || !userId) return { ok: false, error: "missing_threads_secret" };
  const createRes = await fetch(`https://graph.threads.net/v1.0/${userId}/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      media_type: "TEXT",
      text: message.slice(0, 480),
      access_token: token,
    }),
  });
  if (!createRes.ok) return { ok: false, step: "create", status: createRes.status };
  const created = await createRes.json();
  const containerId = created.id;
  if (!containerId) return { ok: false, step: "create", error: "no_container" };
  const pubRes = await fetch(`https://graph.threads.net/v1.0/${userId}/threads_publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ creation_id: containerId, access_token: token }),
  });
  return { ok: pubRes.ok, step: "publish", status: pubRes.status, container_id: containerId };
}

// ─── LINE Bot 雙向 Q&A ──────────────────────────────────────────────

async function verifyLineSignature(bodyText, sigHeader, secret) {
  if (!sigHeader || !secret) return false;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(bodyText));
  let expected = "";
  for (const b of new Uint8Array(mac)) expected += String.fromCharCode(b);
  return btoa(expected) === sigHeader;
}

async function lineReply(env, replyToken, text) {
  const msg = (text || "").slice(0, 4900);
  if (!msg) return;
  return fetch("https://api.line.me/v2/bot/message/reply", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      replyToken,
      messages: [{ type: "text", text: msg }],
    }),
  });
}

async function processLineEvents(events, env) {
  for (const ev of events) {
    try {
      if (ev.type === "follow") {
        await lineReply(env, ev.replyToken,
          "嗨!👋 歡迎加入 MarketDaily 官方 LINE。\n\n" +
          "✅ 已訂閱者:登入 marketdaily.ai/dashboard 綁定 LINE,Premium 戶可在這裡直接問 AI 投資助手。\n\n" +
          "✨ 還沒訂閱:免費版直接加入(週一到週六早上 7 點寄)→ marketdaily.ai");
        continue;
      }
      if (ev.type !== "message") continue;
      const userId = ev.source?.userId;
      const replyToken = ev.replyToken;
      if (!userId || !replyToken) continue;
      if (ev.message?.type !== "text") {
        await lineReply(env, replyToken,
          "我只能讀文字訊息。直接打你想問的吧 👇\n例如:「NVDA 現在能追嗎?」「我手上 TSM 該停損嗎?」");
        continue;
      }
      const text = (ev.message.text || "").trim();
      if (!text) continue;
      await handleLineQuery(env, userId, text, replyToken);
    } catch (e) {
      console.log("line webhook error:", String(e));
    }
  }
}

async function handleLineQuery(env, userId, text, replyToken) {
  const email = await env.USER_PREFS.get(`linemap:${userId}`);
  if (!email) {
    return lineReply(env, replyToken,
      "👋 還沒看到你的 MarketDaily 帳號跟這個 LINE 綁定。\n\n" +
      "請到 marketdaily.ai/dashboard 登入,在「⚡ 即時 LINE 提醒」綁定後,就能在這裡用 AI 投資助手。\n\n" +
      "(綁定是 Premium 專屬功能)");
  }

  const isAdmin = ADMIN_EMAILS.includes(email);
  const plan = await env.USER_PREFS.get(`plan:${email}`);
  if (!isAdmin && plan !== "premium") {
    return lineReply(env, replyToken,
      "嗨!AI 投資助手是 Premium 專屬功能。\n\n" +
      "升級 Premium 解鎖:\n" +
      "• 即時個股 AI 對話(就在這 LINE 對話框)\n" +
      "• 重大新聞 LINE 即時推播\n" +
      "• 個人化深度分析\n\n" +
      "升級 → marketdaily.ai/pricing");
  }

  const day = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
  const countKey = `chatcount:${email}:${day}`;
  const used = parseInt((await env.USER_PREFS.get(countKey)) || "0", 10);
  if (used >= 30) {
    return lineReply(env, replyToken,
      "今天的 AI 對話額度已用完(30 次/天),明天早上 7 點重置。\n\n" +
      "若需要更高額度,可寄信給主編 marketdailyhq@gmail.com");
  }

  // Holdings context
  let holdings = "";
  const prefRaw = await env.USER_PREFS.get(email);
  if (prefRaw) {
    try {
      const p = JSON.parse(prefRaw);
      const us = (p.us_stocks || []).join("、");
      const tw = (p.tw_stocks || []).join("、");
      const parts = [us && `美股:${us}`, tw && `台股:${tw}`].filter(Boolean);
      if (parts.length) holdings = parts.join(";");
    } catch {}
  }
  if (!holdings) holdings = "(尚未設定持股)";

  // Session history(LINE 沒 conversation context,我們自己維護)
  const sessKey = `linechat:${userId}`;
  let history = [];
  const sessRaw = await env.USER_PREFS.get(sessKey);
  if (sessRaw) {
    try { history = JSON.parse(sessRaw); } catch {}
  }
  history.push({ role: "user", content: text.slice(0, 1000) });
  // 只保留最近 10 輪,避免 token 暴漲
  if (history.length > 20) history = history.slice(-20);

  const system = `你是 MarketDaily 的 AI 投資助手,透過 LINE 跟用戶對話。MarketDaily 是給台灣投資人的每日財經 AI 日報平台。

LINE 對話規則:
- **回應要短**,LINE 是手機介面,2-4 段最舒服。盡量 200 字以內,絕對不超過 500 字。
- 一律繁體中文。
- 不用 markdown(LINE 不支援);要分隔用空行或 emoji 開頭。
- 涉及買賣判斷時結尾加「⚠️ 僅供參考,非投資建議」。
- 沒有即時報價時誠實說「我不知道現在的盤中價」,建議用戶看券商 App 確認價位。
- 提到台股一律用公司名稱(可附代號,如「台積電 2330」),不要只報代號。
- 與投資、財經、用戶持股無關的閒聊,簡短禮貌帶過,引導回投資主題。

這位用戶目前在 MarketDaily 追蹤的持股:${holdings}`;

  let aiRes;
  try {
    aiRes = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 700,
        system,
        messages: history,
      }),
    });
  } catch {
    return lineReply(env, replyToken, "⚠️ AI 暫時連不上,稍等 1 分鐘再試。");
  }
  if (!aiRes.ok) {
    return lineReply(env, replyToken, "⚠️ AI 回應失敗,稍等 1 分鐘再試。");
  }
  const data = await aiRes.json();
  const reply = (data.content || []).map(c => c.text || "").join("").trim();
  if (!reply) {
    return lineReply(env, replyToken, "⚠️ AI 沒給回應,換個方式問問看?");
  }

  // 留 session 給下次對話用
  history.push({ role: "assistant", content: reply });
  await env.USER_PREFS.put(sessKey, JSON.stringify(history.slice(-20)),
    { expirationTtl: 24 * 3600 });
  // 計數共用 web /chat 配額(同一用戶 LINE / web 加總 30 次/天)
  await env.USER_PREFS.put(countKey, String(used + 1),
    { expirationTtl: 26 * 3600 });

  return lineReply(env, replyToken, reply);
}
