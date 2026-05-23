const ADMIN_EMAILS = ["delvin.12345678@gmail.com"];

const INVITE_CODES = [
  "DELVIN-FE8FZ1","DELVIN-XKNJ4N","DELVIN-F4ONQQ","DELVIN-RBIG9S",
  "DELVIN-WYW4IP","DELVIN-BE2O13","DELVIN-OVMFHN","DELVIN-AV3VIB",
  "DELVIN-06U59N","DELVIN-CVRBWF",
  "MD-4SJWK4","MD-UN81FB","MD-F3KQ11","MD-3A111V","MD-HZBXA1",
  "MD-O9GFBT","MD-3BVD3O","MD-XTKXU8","MD-XETLNK","MD-OAF39F"
];

const TIER_BY_AMOUNT = { 19900: "Pro", 190800: "Pro", 29900: "Pro", 287000: "Pro", 49900: "Premium", 478800: "Premium" };

const PLAN_CAPS = { free: 3, pro: 15, premium: Infinity };
function planCap(plan) { return PLAN_CAPS[plan] || PLAN_CAPS.free; }
function applyCap(us, tw, cap) {
  if (cap === Infinity || us.length + tw.length <= cap) return [us, tw];
  if (us.length >= cap) return [us.slice(0, cap), []];
  return [us, tw.slice(0, cap - us.length)];
}

async function hashPassword(password) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(password));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
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
      const plan = (await env.USER_PREFS.get(`plan:${email}`)) || (isPaid ? "premium" : "free");
      const since = contact.createdAt || null;

      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash) {
        return json({ subscribed: true, plan, since, needsPasswordSetup: true });
      }
      if (!password) {
        return json({ subscribed: true, needsPasswordEntry: true });
      }
      const inputHash = await hashPassword(password);
      if (inputHash !== storedHash) {
        return json({ subscribed: true, error: "wrong_password" });
      }
      return json({ subscribed: true, plan, since });
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

      const hash = await hashPassword(password);
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

      const oldHash = await hashPassword(oldPassword);
      if (oldHash !== storedHash) return json({ error: "wrong_password" }, 403);

      const newHash = await hashPassword(newPassword);
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
      if (!storedHash || (await hashPassword(password)) !== storedHash) {
        return json({ error: "auth" }, 403);
      }
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
      if (!storedHash || (await hashPassword(body.password || "")) !== storedHash) {
        return json({ error: "auth" }, 403);
      }
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

    // AI 投資助手:聊天(Premium 專屬)
    if (url.pathname === "/chat" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const password = body.password || "";
      const msgs = Array.isArray(body.messages) ? body.messages : [];
      if (!email) return json({ error: "invalid_email" }, 400);

      const isAdmin = ADMIN_EMAILS.includes(email);
      if (!isAdmin) {
        const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
        if (!storedHash || (await hashPassword(password)) !== storedHash) {
          return json({ error: "auth" }, 403);
        }
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
      const email = (body.email || "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
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
      const email = (body.email || "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
      const raw = await env.USER_PREFS.get("admin:global-config");
      return json({ config: raw ? JSON.parse(raw) : null });
    }

    // Save admin global config
    if (url.pathname === "/admin/save-config" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
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
      const email = (body.email || "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
      const target = (body.target || "").trim().toLowerCase();
      const plan = (body.plan || "").trim().toLowerCase();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return json({ error: "invalid_target" }, 400);
      if (!["free", "pro", "premium"].includes(plan)) return json({ error: "invalid_plan" }, 400);
      await env.USER_PREFS.put(`plan:${target}`, plan);
      return json({ ok: true, target, plan });
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
      const email = (body.email || "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);

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

      const listId = parseInt(env.BREVO_LIST_ID) || 2;
      const added = await addToBrevo(email, env.BREVO_API_KEY, listId);
      if (!added) return json({ error: "brevo_error" }, 502);

      // 邀請碼註冊者 = 免費方案(3 檔上限);Premium 需付費升級或管理員手動開通
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
      ctx.waitUntil(postSignupTasks(email, body.ref, env));
      ctx.waitUntil(recordConvert(env, {
        email, event: "subscribe_free",
        visit_id: body.visit_id, utm_source: body.utm_source,
        utm_medium: body.utm_medium, utm_campaign: body.utm_campaign,
      }));
      return json({ ok: true });
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
        await env.USER_PREFS.put(`plan:${email}`, tier === "Premium" ? "premium" : "pro");
        if (session.customer) await env.USER_PREFS.put(`stripe-cust:${session.customer}`, email);
        // 歡迎信與補寄日報背景化 —— webhook 快速回 200,避免 Stripe 因逾時重送
        ctx.waitUntil((async () => {
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
  }
};

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
  try { await grantReferralReward(env, refCode, email); }
  catch (e) { console.log("postSignup referral error:", String(e)); }
  try {
    await sendWelcomeEmail(email, env.BREVO_API_KEY, isPaid, tier);
  } catch (e) { console.log("postSignup welcome error:", String(e)); }
  try {
    await sendTodayDigestToOne(email, env.BREVO_API_KEY, env.USER_PREFS);
  } catch (e) { console.log("postSignup digest error:", String(e)); }
}

// 推薦獎勵兌現:雙方各得 30 天 Premium。防自推、防重複。
async function grantReferralReward(env, refCode, newEmail) {
  refCode = (refCode || "").trim().toUpperCase();
  newEmail = (newEmail || "").trim().toLowerCase();
  if (!refCode || !newEmail) return false;

  const referrer = await env.USER_PREFS.get(`referral:code:${refCode}`);
  if (!referrer || referrer === newEmail) return false;

  const dupKey = `referral:fulfilled:${newEmail}`;
  if (await env.USER_PREFS.get(dupKey)) return false;

  const ts = new Date().toISOString();
  await env.USER_PREFS.put(dupKey, JSON.stringify({ referrer, code: refCode, ts }));

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
- 每天早上 7:00 AM（台灣時間）寄送 AI 財經日報
- 內容：美股 + 台股新聞、假訊息過濾、30 秒摘要、板塊分析、BTC/ETH
- 來源：Reuters、CNBC、Bloomberg、FT 等可信媒體

【方案】
- 免費方案：需邀請碼（親友邀請制）
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
      從明天起，每天早上 <strong>7:00 AM（台灣時間）</strong>，你會收到一封財經日報，30 秒看完今天的市場重點。
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
