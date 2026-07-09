const ADMIN_EMAILS = ["delvin.12345678@gmail.com"];

const INVITE_CODES = [
  "DELVIN-FE8FZ1","DELVIN-XKNJ4N","DELVIN-F4ONQQ","DELVIN-RBIG9S",
  "DELVIN-WYW4IP","DELVIN-BE2O13","DELVIN-OVMFHN","DELVIN-AV3VIB",
  "DELVIN-06U59N","DELVIN-CVRBWF",
  "MD-4SJWK4","MD-UN81FB","MD-F3KQ11","MD-3A111V","MD-HZBXA1",
  "MD-O9GFBT","MD-3BVD3O","MD-XTKXU8","MD-XETLNK","MD-OAF39F"
];

const TIER_BY_AMOUNT = { 19900: "Pro", 190800: "Pro", 29900: "Pro", 287000: "Pro", 49900: "Premium", 478800: "Premium" };

// 合規結構(COMPLIANCE_STRUCTURE.md):個股分析內容不得與付費產生對價,
// 持股追蹤數為純技術上限,所有方案一律相同,禁止依 plan 分級。
const UNIFORM_STOCK_CAP = 80;
const PLAN_CAPS = { free: UNIFORM_STOCK_CAP, pro: UNIFORM_STOCK_CAP, premium: UNIFORM_STOCK_CAP };
function planCap(plan) { return PLAN_CAPS[plan] || UNIFORM_STOCK_CAP; }
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

// --- Brute-force lockout (KV-backed) ---
// 同一 (email, IP) 失敗 5 次 → lock 15 分鐘。新失敗會延長視窗。
const AUTH_FAIL_LIMIT = 5;
const AUTH_FAIL_WINDOW_SEC = 900;
function clientIp(request) {
  return request.headers.get("cf-connecting-ip") || request.headers.get("x-real-ip") || "unknown";
}
// 台灣用語修正網:Haiku 偶爾漏字吐中國大陸慣用語,這裡確定性轉回台灣說法(保險層,不靠 prompt 100%)
const _TW_TERMS = [
  ["光刻机", "微影機"], ["光刻機", "微影機"], ["卡脖子", "難以替代"],
  ["芯片", "晶片"], ["激光", "雷射"], ["内存", "記憶體"], ["软件", "軟體"],
  ["硬件", "硬體"], ["顶尖", "頂尖"], ["供应商", "供應商"], ["设备", "設備"],
  ["镜头", "鏡頭"], ["制造商", "製造商"], ["制造", "製造"], ["信息", "資訊"],
  ["网络", "網路"], ["数据", "數據"], ["优势", "優勢"], ["领先", "領先"],
];
function _twFix(s) {
  if (typeof s !== "string" || !s) return s;
  for (const [a, b] of _TW_TERMS) if (s.includes(a)) s = s.split(a).join(b);
  return s;
}
function _scStr(v, max) { return _twFix((typeof v === "string" ? v : "").trim()).slice(0, max || 80); }
function _scNormList(arr) {
  if (!Array.isArray(arr)) return [];
  return arr.slice(0, 10).map(p => (p && typeof p === "object") ? {
    name_zh: _scStr(p.name_zh || p.name_en, 60),
    name_en: _scStr(p.name_en || p.name_zh, 60),
    ticker: (typeof p.ticker === "string" && /^[A-Za-z0-9.\-]{1,12}$/.test(p.ticker.trim())) ? p.ticker.trim().toUpperCase() : null,
    category: _scStr(p.category, 40),
    role: _scStr(p.role, 120),
    criticality: _scStr(p.criticality, 40),
  } : null).filter(p => p && (p.name_zh || p.name_en));
}
function authFailKey(email, request) {
  return `auth_fail:${(email || "anon").toLowerCase()}:${clientIp(request)}`;
}
async function isAuthLocked(env, email, request) {
  if (!email) return false;
  const raw = await env.USER_PREFS.get(authFailKey(email, request));
  if (!raw) return false;
  try {
    const { count, until } = JSON.parse(raw);
    return count >= AUTH_FAIL_LIMIT && Date.now() < until;
  } catch { return false; }
}
async function recordAuthFail(env, email, request) {
  if (!email) return;
  const key = authFailKey(email, request);
  const raw = await env.USER_PREFS.get(key);
  let count = 0;
  try { if (raw) count = (JSON.parse(raw).count || 0); } catch {}
  count += 1;
  await env.USER_PREFS.put(
    key,
    JSON.stringify({ count, until: Date.now() + AUTH_FAIL_WINDOW_SEC * 1000 }),
    { expirationTtl: AUTH_FAIL_WINDOW_SEC }
  );
}
async function clearAuthFail(env, email, request) {
  if (!email) return;
  try { await env.USER_PREFS.delete(authFailKey(email, request)); } catch {}
}

// 統一驗密碼 + rate limit + auto-upgrade。回 {ok, status, error, stored}。
async function gatePassword(env, request, email, password) {
  if (!email || !password) return { ok: false, status: 400, error: "auth" };
  if (await isAuthLocked(env, email, request)) {
    return { ok: false, status: 429, error: "too_many_attempts" };
  }
  const stored = await env.USER_PREFS.get(`pwd:${email}`);
  if (!stored || !(await verifyPwd(password, stored))) {
    await recordAuthFail(env, email, request);
    return { ok: false, status: 403, error: "auth", stored };
  }
  await clearAuthFail(env, email, request);
  await maybeUpgradeHash(env, email, password, stored);
  return { ok: true, stored };
}

// --- 密碼強度檢查(新密碼專用,既有密碼不受影響)---
const WEAK_PASSWORDS = new Set([
  "password","password1","password123","passw0rd","123456","1234567","12345678","123456789","1234567890",
  "qwerty","qwerty123","qwertyuiop","abc123","abcdef","letmein","welcome","welcome1","admin","admin123",
  "iloveyou","monkey","dragon","baseball","football","superman","trustno1","sunshine","princess","login",
  "starwars","master","passw0rd1","00000000","11111111","87654321","aaaaaa","000000","marketdaily","delvin"
]);
function checkPwdStrength(pwd) {
  if (typeof pwd !== "string" || pwd.length < 10) return "too_short";
  if (pwd.length > 200) return "too_long";
  const lc = pwd.toLowerCase();
  if (WEAK_PASSWORDS.has(lc)) return "too_weak";
  let kinds = 0;
  if (/[a-z]/.test(pwd)) kinds++;
  if (/[A-Z]/.test(pwd)) kinds++;
  if (/[0-9]/.test(pwd)) kinds++;
  if (/[^a-zA-Z0-9]/.test(pwd)) kinds++;
  if (kinds < 2) return "too_weak";
  return null;
}

// --- TOTP (RFC 6238) — admin 2FA ---
const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
function base32Encode(bytes) {
  let bits = 0, value = 0, out = "";
  for (const b of bytes) {
    value = (value << 8) | b;
    bits += 8;
    while (bits >= 5) { out += BASE32[(value >> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += BASE32[(value << (5 - bits)) & 31];
  return out;
}
function base32Decode(input) {
  const s = (input || "").toUpperCase().replace(/=+$/, "").replace(/\s/g, "");
  let bits = 0, value = 0;
  const out = [];
  for (const c of s) {
    const i = BASE32.indexOf(c);
    if (i < 0) continue;
    value = (value << 5) | i;
    bits += 5;
    if (bits >= 8) { out.push((value >> (bits - 8)) & 0xff); bits -= 8; }
  }
  return new Uint8Array(out);
}
async function hotp(secretBytes, counter) {
  const key = await crypto.subtle.importKey("raw", secretBytes, { name: "HMAC", hash: "SHA-1" }, false, ["sign"]);
  const buf = new ArrayBuffer(8);
  const dv = new DataView(buf);
  dv.setUint32(0, Math.floor(counter / 0x100000000));
  dv.setUint32(4, counter >>> 0);
  const h = new Uint8Array(await crypto.subtle.sign("HMAC", key, buf));
  const o = h[19] & 0xf;
  const code = ((h[o] & 0x7f) << 24) | (h[o+1] << 16) | (h[o+2] << 8) | h[o+3];
  return (code % 1000000).toString().padStart(6, "0");
}
async function verifyTotp(secretBase32, code, time) {
  if (!/^\d{6}$/.test(code || "")) return false;
  const t = time || Date.now();
  const counter = Math.floor(t / 30000);
  const bytes = base32Decode(secretBase32);
  for (let delta = -1; delta <= 1; delta++) {
    if ((await hotp(bytes, counter + delta)) === code) return true;
  }
  return false;
}
function generateTotpSecret() {
  const buf = new Uint8Array(20);
  crypto.getRandomValues(buf);
  return base32Encode(buf);
}

// --- CORS: 對寫入操作擋掉非允許 origin(防 CSRF/惡意網站盜用 API)---
const ALLOWED_ORIGINS = new Set([
  "https://marketdaily.ai",
  "https://www.marketdaily.ai",
  "https://marketdaily.pages.dev",
]);
function isAllowedOrigin(request) {
  const origin = request.headers.get("origin") || "";
  if (!origin) return true; // 非瀏覽器(curl/server)沒 origin,不是 CSRF 攻擊面
  if (ALLOWED_ORIGINS.has(origin)) return true;
  if (/^https:\/\/[a-z0-9-]+\.marketdaily\.pages\.dev$/i.test(origin)) return true;
  return false;
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

// ZeroBounce email 可投遞性驗證。**fail-open**:只在「確定無效/spamtrap/濫用」時回 false 擋下,
// 其餘(valid/catch-all/unknown/API 掛/沒 key/超額)一律回 true 放行,絕不因驗證服務問題擋住真人註冊。
async function isEmailDeliverable(email, env) {
  const key = env.ZEROBOUNCE_API_KEY;
  if (!key) return true; // 沒設 key = 不驗,放行
  try {
    const u = `https://api.zerobounce.net/v2/validate?api_key=${key}&email=${encodeURIComponent(email)}&ip_address=`;
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 4000);
    const r = await fetch(u, { signal: ctl.signal });
    clearTimeout(to);
    if (!r.ok) return true; // API 非 200(含超額)→ 放行
    const d = await r.json();
    // 只擋這幾種「確定不該收信」的狀態;valid/catch-all/unknown 全放行
    const block = new Set(["invalid", "spamtrap", "abuse", "do_not_mail"]);
    return !block.has((d.status || "").toLowerCase());
  } catch {
    return true; // timeout/網路錯 → 放行
  }
}

// 統一 admin 端點驗證:email 必須在 ADMIN_EMAILS,且 password 必須正確;含 rate limit。
// 若該 admin 已啟用 TOTP(KV totp:${email}):驗證 body.totp;同 IP 通過後 10 分鐘記憶。
// 回傳 email(成功)或 null(失敗/被 lock/缺 TOTP)。
async function requireAdmin(env, body, request) {
  const email = ((body && (body.email || body.admin_email || body.auth_email)) || "").trim().toLowerCase();
  if (!ADMIN_EMAILS.includes(email)) return null;
  const password = (body && body.password) || "";
  if (request && await isAuthLocked(env, email, request)) return null;
  const stored = await env.USER_PREFS.get(`pwd:${email}`);
  if (!stored || !(await verifyPwd(password, stored))) {
    if (request) await recordAuthFail(env, email, request);
    return null;
  }
  const totpSecret = await env.USER_PREFS.get(`totp:${email}`);
  if (totpSecret) {
    const ip = request ? clientIp(request) : "unknown";
    const memKey = `totp_ok:${email}:${ip}`;
    const recent = await env.USER_PREFS.get(memKey);
    if (!recent) {
      const code = (body && body.totp) || "";
      if (!(await verifyTotp(totpSecret, code))) {
        if (request) await recordAuthFail(env, email, request);
        return null;
      }
      await env.USER_PREFS.put(memKey, "1", { expirationTtl: 600 });
    }
  }
  if (request) await clearAuthFail(env, email, request);
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

    // CSRF 防護:POST 必須來自允許的 origin。
    // Stripe/LINE server-to-server webhook 沒 Origin header → isAllowedOrigin 自動放行(且還有 signature 驗證)。
    if (request.method === "POST" && !isAllowedOrigin(request)) {
      return json({ error: "forbidden_origin" }, 403);
    }

    // --- Admin 2FA TOTP setup ---
    // 查詢是否已啟用 TOTP(無需密碼,僅回 boolean)
    if (url.pathname === "/admin/totp-status" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = ((body.email || "") + "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ enabled: false });
      const sec = await env.USER_PREFS.get(`totp:${email}`);
      return json({ enabled: !!sec });
    }

    // 啟用 TOTP:第一步 — 要 password,回 secret + otpauth URL(不寫入 KV)
    if (url.pathname === "/admin/totp-setup" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = ((body.email || "") + "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
      // 暫存草稿 secret(不影響現有 totp:${email}),5 分鐘有效
      const password = body.password || "";
      if (await isAuthLocked(env, email, request)) return json({ error: "too_many_attempts" }, 429);
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash || !(await verifyPwd(password, storedHash))) {
        await recordAuthFail(env, email, request);
        return json({ error: "auth" }, 403);
      }
      await clearAuthFail(env, email, request);
      const secret = generateTotpSecret();
      await env.USER_PREFS.put(`totp_draft:${email}`, secret, { expirationTtl: 600 });
      const label = encodeURIComponent("MarketDaily:" + email);
      const issuer = "MarketDaily";
      const otpauth = `otpauth://totp/${label}?secret=${secret}&issuer=${issuer}&algorithm=SHA1&digits=6&period=30`;
      return json({ secret, otpauth });
    }

    // 啟用 TOTP:第二步 — 用 setup 草稿 + 6 碼 confirm,正確才寫 totp:${email}
    if (url.pathname === "/admin/totp-confirm" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = ((body.email || "") + "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
      const password = body.password || "";
      const code = (body.code || "") + "";
      if (await isAuthLocked(env, email, request)) return json({ error: "too_many_attempts" }, 429);
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash || !(await verifyPwd(password, storedHash))) {
        await recordAuthFail(env, email, request);
        return json({ error: "auth" }, 403);
      }
      const draft = await env.USER_PREFS.get(`totp_draft:${email}`);
      if (!draft) return json({ error: "no_draft" }, 400);
      if (!(await verifyTotp(draft, code))) {
        await recordAuthFail(env, email, request);
        return json({ error: "wrong_code" }, 403);
      }
      await env.USER_PREFS.put(`totp:${email}`, draft);
      await env.USER_PREFS.delete(`totp_draft:${email}`);
      await clearAuthFail(env, email, request);
      return json({ ok: true });
    }

    // 停用 TOTP:要 password + 當前 6 碼
    if (url.pathname === "/admin/totp-disable" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = ((body.email || "") + "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
      const password = body.password || "";
      const code = (body.code || "") + "";
      if (await isAuthLocked(env, email, request)) return json({ error: "too_many_attempts" }, 429);
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash || !(await verifyPwd(password, storedHash))) {
        await recordAuthFail(env, email, request);
        return json({ error: "auth" }, 403);
      }
      const secret = await env.USER_PREFS.get(`totp:${email}`);
      if (!secret) return json({ ok: true }); // 本來就沒啟用
      if (!(await verifyTotp(secret, code))) {
        await recordAuthFail(env, email, request);
        return json({ error: "wrong_code" }, 403);
      }
      await env.USER_PREFS.delete(`totp:${email}`);
      await clearAuthFail(env, email, request);
      return json({ ok: true });
    }

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
      if (await isAuthLocked(env, email, request)) {
        return json({ subscribed: true, error: "too_many_attempts" }, 429);
      }
      if (!(await verifyPwd(password, storedHash))) {
        await recordAuthFail(env, email, request);
        return json({ subscribed: true, error: "wrong_password" });
      }
      await clearAuthFail(env, email, request);
      await maybeUpgradeHash(env, email, password, storedHash);
      return json({ subscribed: true, plan, since, hasKvPlan });
    }

    // Set subscriber password (first-time setup)
    // 新流程:全新 email 也可直接設密碼;若還沒在 Brevo,自動以 free 加入再存密碼
    if (url.pathname === "/set-password" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const password = body.password || "";
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      {
        const weak = checkPwdStrength(password);
        if (weak) return json({ error: weak }, 400);
      }

      const targetList = parseInt(env.BREVO_LIST_ID) || 2;
      let contact = null;
      let inTargetList = false;
      const res = await fetch(`https://api.brevo.com/v3/contacts/${encodeURIComponent(email)}`, {
        headers: { "api-key": env.BREVO_API_KEY }
      });
      if (res.ok) {
        contact = await res.json();
        inTargetList = (contact.listIds || []).includes(targetList);
      }

      let createdNew = false;
      if (!inTargetList) {
        // Anti-spam: 進入觸發 welcome email + Brevo add 的 path 前先 rate limit
        // (避免繞 /subscribe-free-direct 改打 /set-password 達到同樣 spam 效果)
        const ip = request.headers.get("cf-connecting-ip") || "anon";
        const ipKey = `rl:signup-ip:${ip}`;
        const ipCount = parseInt((await env.USER_PREFS.get(ipKey)) || "0", 10);
        if (ipCount >= 10) return json({ error: "too_many_attempts", retry_after: "1h" }, 429);
        if (await env.USER_PREFS.get(`rl:signup-email:${email}`)) return json({ error: "rate_limited" }, 429);
        ctx.waitUntil(env.USER_PREFS.put(ipKey, String(ipCount + 1), { expirationTtl: 3600 }));
        ctx.waitUntil(env.USER_PREFS.put(`rl:signup-email:${email}`, "1", { expirationTtl: 300 }));
        if (!(await isEmailDeliverable(email, env))) return json({ error: "undeliverable_email" }, 400);
        const added = await addToBrevo(email, env.BREVO_API_KEY, targetList);
        if (!added) return json({ error: "brevo_error" }, 502);
        const existingPlan = await env.USER_PREFS.get(`plan:${email}`);
        if (!existingPlan) await env.USER_PREFS.put(`plan:${email}`, "free");
        createdNew = true;
        ctx.waitUntil(postSignupTasks(email, body.ref || "", env));
        ctx.waitUntil(recordConvert(env, {
          email, event: "subscribe_free",
          visit_id: body.visit_id, utm_source: body.utm_source,
          utm_medium: body.utm_medium, utm_campaign: body.utm_campaign,
        }));
      }

      const hash = await makePwdHash(password);
      await env.USER_PREFS.put(`pwd:${email}`, hash);

      const isPaid = !!(contact && (contact.attributes?.PAID === true || contact.attributes?.PLAN === "paid"));
      const plan = (await env.USER_PREFS.get(`plan:${email}`)) || (isPaid ? "premium" : "free");
      return json({ ok: true, plan, since: (contact && contact.createdAt) || null, createdNew });
    }

    // Change password (authenticated users)
    if (url.pathname === "/change-password" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      const oldPassword = body.old_password || "";
      const newPassword = body.new_password || "";
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      const weak = checkPwdStrength(newPassword);
      if (weak) return json({ error: weak }, 400);

      const gate = await gatePassword(env, request, email, oldPassword);
      if (!gate.ok) {
        if (gate.status === 429) return json({ error: "too_many_attempts" }, 429);
        if (gate.status === 403 && !gate.stored) return json({ error: "not_found" }, 404);
        return json({ error: "wrong_password" }, 403);
      }

      const newHash = await makePwdHash(newPassword);
      await env.USER_PREFS.put(`pwd:${email}`, newHash);
      return json({ ok: true });
    }

    // 忘記密碼:寄重設連結(token 30 分鐘一次性;無論帳號存在與否一律回 ok,不洩漏帳號存在性)
    if (url.pathname === "/forgot-password" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);

      const ip = clientIp(request);
      const ipKey = `rl:pwdreset-ip:${ip}`;
      const ipCount = parseInt((await env.USER_PREFS.get(ipKey)) || "0", 10);
      if (ipCount >= 5) return json({ ok: true });
      ctx.waitUntil(env.USER_PREFS.put(ipKey, String(ipCount + 1), { expirationTtl: 3600 }));
      if (await env.USER_PREFS.get(`rl:pwdreset-email:${email}`)) return json({ ok: true });
      ctx.waitUntil(env.USER_PREFS.put(`rl:pwdreset-email:${email}`, "1", { expirationTtl: 300 }));

      const stored = await env.USER_PREFS.get(`pwd:${email}`);
      if (!stored) return json({ ok: true });

      const token = crypto.randomUUID().replace(/-/g, "") + crypto.randomUUID().replace(/-/g, "");
      await env.USER_PREFS.put(`pwdreset:${token}`, email, { expirationTtl: 1800 });
      const link = `https://marketdaily.ai/reset-password.html?token=${token}`;
      ctx.waitUntil(sendPasswordResetEmail(email, env.BREVO_API_KEY, link));
      return json({ ok: true });
    }

    // 忘記密碼:用 token 設新密碼(token 用過即刪)
    if (url.pathname === "/reset-password" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const token = (body.token || "").trim();
      const password = body.password || "";
      if (!/^[a-f0-9]{64}$/.test(token)) return json({ error: "invalid_token" }, 400);

      const ip = clientIp(request);
      const tryKey = `rl:pwdreset-try:${ip}`;
      const tries = parseInt((await env.USER_PREFS.get(tryKey)) || "0", 10);
      if (tries >= 20) return json({ error: "too_many_attempts" }, 429);
      ctx.waitUntil(env.USER_PREFS.put(tryKey, String(tries + 1), { expirationTtl: 3600 }));

      const weak = checkPwdStrength(password);
      if (weak) return json({ error: weak }, 400);

      const email = await env.USER_PREFS.get(`pwdreset:${token}`);
      if (!email) return json({ error: "invalid_token" }, 400);

      const newHash = await makePwdHash(password);
      await env.USER_PREFS.put(`pwd:${email}`, newHash);
      await env.USER_PREFS.delete(`pwdreset:${token}`);
      ctx.waitUntil(clearAuthFail(env, email, request));
      return json({ ok: true });
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
        const g = await gatePassword(env, request, email, password);
        if (!g.ok) return json({ error: g.error }, g.status);
      }
      // 合規結構:AI 投資助手對全體登入用戶開放(涉個股分析,不得付費限定);每日 30 則一體適用。
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
    if (url.pathname === "/chat-status" && (request.method === "GET" || request.method === "POST")) {
      // 安全:要求 password 才回真實 plan/remaining,不然攻擊者能列舉「誰是 premium」。
      // GET 向後相容(舊 client),但只回 generic;POST + password 才回真值。
      let email = "", password = "";
      if (request.method === "POST") {
        try {
          const body = await request.json();
          email = (body.email || "").trim().toLowerCase();
          password = body.password || "";
        } catch {}
      } else {
        email = (url.searchParams.get("email") || "").trim().toLowerCase();
      }
      // 合規結構:chat 對全體用戶開放(available 恆為 true);remaining 屬個人資料仍要 password。
      if (!email) return json({ available: true, premium: false, remaining: 0 });
      const isAdmin = ADMIN_EMAILS.includes(email);
      // password 驗證 — GET (無 pwd) 或 pwd 錯時不洩漏 plan。
      // admin 也必驗,否則攻擊者能透過回應差異(generic vs 真實 plan)列舉 admin 名單。
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (!storedHash || !password || !(await verifyPwd(password, storedHash))) {
        return json({ available: true, premium: false, remaining: 0 });
      }
      const plan = await env.USER_PREFS.get(`plan:${email}`);
      const premium = isAdmin || plan === "premium";
      const day = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
      const used = parseInt((await env.USER_PREFS.get(`chatcount:${email}:${day}`)) || "0", 10);
      return json({ available: true, premium, remaining: Math.max(0, 30 - used) });
    }

    // Admin stats
    if (url.pathname === "/admin-stats" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      try {
        const listId = parseInt(env.BREVO_LIST_ID) || 2;
        // Brevo API 預設 limit=50,最大 500;此處抓全部 contacts 給 admin 面板,不可只回前 50。
        const res = await fetch(`https://api.brevo.com/v3/contacts/lists/${listId}/contacts?limit=500`, {
          headers: { "api-key": env.BREVO_API_KEY }
        });
        const data = await res.json();
        const contacts = data.contacts || [];
        const total = data.count || contacts.length;
        const subscribers = await Promise.all(contacts.slice(0, 500).map(async c => {
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
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const raw = await env.USER_PREFS.get("admin:global-config");
      return json({ config: raw ? JSON.parse(raw) : null });
    }

    // Save admin global config
    if (url.pathname === "/admin/save-config" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const config = body.config;
      if (!config || typeof config !== "object") return json({ error: "no config" }, 400);
      config.updated_at = new Date().toISOString();
      await env.USER_PREFS.put("admin:global-config", JSON.stringify(config));
      ctx.waitUntil(logAudit(env, (body.email || "admin").toLowerCase(), "save-config", {}));
      return json({ ok: true, updated_at: config.updated_at });
    }

    // Admin:設定單一用戶方案(free / pro / premium)
    if (url.pathname === "/admin/set-plan" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
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
      ctx.waitUntil(logAudit(env, (body.email || "admin").toLowerCase(), "set-plan", { target, plan }));
      return json({ ok: true, target, plan });
    }

    // 一次性把所有 KV plan 的真實狀態推到 Brevo 屬性(修補手動改 KV 後 Brevo 沒跟上的情況)
    if (url.pathname === "/admin/sync-brevo-plans" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
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

    // Admin:清除符合 email pattern 的測試 contact(Brevo + KV 全清)。一次性工具,
    // 用於清除 audit 留下的 *@example.com 等垃圾資料。
    if (url.pathname === "/admin/purge-contacts" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const pattern = (body.pattern || "").trim().toLowerCase();
      if (!pattern || pattern.length < 5) return json({ error: "pattern_too_short" }, 400);
      // 安全:不允許 pattern 為單字串如 "gmail.com" 之類,必須夠特殊(防誤刪真實用戶)
      if (["gmail.com", "com", "yahoo.com", "outlook.com"].includes(pattern)) {
        return json({ error: "pattern_too_broad" }, 400);
      }
      const listId = parseInt(env.BREVO_LIST_ID) || 2;
      const res = await fetch(`https://api.brevo.com/v3/contacts/lists/${listId}/contacts?limit=500`, {
        headers: { "api-key": env.BREVO_API_KEY }
      });
      if (!res.ok) return json({ error: "brevo_list_failed", status: res.status }, 502);
      const data = await res.json();
      const contacts = data.contacts || [];
      const targets = contacts.filter(c => (c.email || "").toLowerCase().includes(pattern));
      const result = { matched: targets.length, brevo_deleted: 0, brevo_failed: 0, kv_deleted: 0, emails: [] };
      for (const c of targets) {
        const email = (c.email || "").toLowerCase();
        result.emails.push(email);
        const dr = await fetch(`https://api.brevo.com/v3/contacts/${encodeURIComponent(email)}`, {
          method: "DELETE",
          headers: { "api-key": env.BREVO_API_KEY }
        });
        if (dr.ok || dr.status === 204) result.brevo_deleted++;
        else result.brevo_failed++;
        // 同步清 KV:plan / pwd / linemap(若有 line) / 個人偏好(key = email 本身)
        for (const key of [`plan:${email}`, `pwd:${email}`, email, `line:${email}`]) {
          try { await env.USER_PREFS.delete(key); result.kv_deleted++; } catch {}
        }
      }
      ctx.waitUntil(logAudit(env, (body.email || "admin").toLowerCase(), "purge-contacts", { pattern, matched: result.matched, brevo_deleted: result.brevo_deleted }));
      return json(result);
    }

    // Admin:lifecycle email 手動測試(不檢查 days_since_signup、不寫防呆 flag)
    if (url.pathname === "/admin/lifecycle-test" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const target = (body.target || body.to || "").trim().toLowerCase();
      const type = (body.type || "").trim().toLowerCase();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return json({ error: "invalid_target" }, 400);
      const handlers = { d1: sendD1Email, d7: sendD7Email, d14: sendD14Email, d21: sendD21Email, d45: sendD45Email };
      if (!handlers[type]) return json({ error: "invalid_type" }, 400);
      try {
        await handlers[type](target, env.BREVO_API_KEY, env);
        ctx.waitUntil(logAudit(env, (body.email || "admin").toLowerCase(), "lifecycle-test", { target, type }));
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
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);

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

    // Admin:營運監控 — 今日/昨日已產生的個人化日報數(digest_idx 索引)+ 看盤台註解數
    if (url.pathname === "/admin/ops-status" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const twDay = (off = 0) => new Date(Date.now() + 8 * 3600 * 1000 - off * 86400 * 1000).toISOString().slice(0, 10);
      const countIdx = async (date) => {
        let cursor, n = 0;
        for (let i = 0; i < 10; i++) {
          const r = await env.USER_PREFS.list({ prefix: `digest_idx:${date}:`, cursor });
          n += r.keys.length;
          if (r.list_complete) break;
          cursor = r.cursor;
        }
        return n;
      };
      const today = twDay(0), yest = twDay(1);
      const [todayN, yestN] = await Promise.all([countIdx(today), countIdx(yest)]);
      let annotN = 0;
      try { const a = await env.USER_PREFS.get("annot:latest"); if (a) annotN = Object.keys(JSON.parse(a)).length; } catch {}
      return json({ today, yesterday: yest, digests_today: todayN, digests_yesterday: yestN, annotations: annotN });
    }

    // Admin:寄信成效 — Brevo 近 30 日彙總報告(送達/開信/點擊/退信率)
    if (url.pathname === "/admin/email-stats" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      try {
        const r = await fetch("https://api.brevo.com/v3/smtp/statistics/aggregatedReport?days=30", {
          headers: { "api-key": env.BREVO_API_KEY, "accept": "application/json" }
        });
        const d = await r.json();
        if (!r.ok) return json({ error: "brevo_failed", status: r.status, detail: d }, 502);
        const requests = d.requests || 0, delivered = d.delivered || 0;
        const opens = (d.uniqueOpens != null ? d.uniqueOpens : d.opens) || 0;
        const clicks = (d.uniqueClicks != null ? d.uniqueClicks : d.clicks) || 0;
        const softB = d.softBounces || 0, hardB = d.hardBounces || 0;
        const unsub = d.unsubscribed || 0, blocked = d.blocked || 0, spam = d.spamReports || 0;
        const rate = (n, base) => base > 0 ? +(n / base * 100).toFixed(1) : 0;
        const base = requests || delivered;
        return json({
          days: 30, requests, delivered, opens, clicks,
          softBounces: softB, hardBounces: hardB, unsubscribed: unsub, blocked, spam,
          deliveryRate: rate(delivered, base), openRate: rate(opens, delivered),
          clickRate: rate(clicks, delivered), bounceRate: rate(softB + hardB, base)
        });
      } catch (e) { return json({ error: "exception", detail: String(e) }, 502); }
    }

    // Admin:營收 — Stripe 訂閱聚合 MRR/ARR + 各狀態計數
    if (url.pathname === "/admin/revenue" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      if (!env.STRIPE_SECRET_KEY) return json({ error: "missing_stripe_key" }, 500);
      // Stripe 對非零小數幣別(含 TWD)以「分」計價,主單位需 /100;僅零小數幣別直接用整數。
      const ZERO_DEC = new Set(["bif","clp","djf","gnf","jpy","kmf","krw","mga","pyg","rwf","ugx","vnd","vuv","xaf","xof","xpf"]);
      const toMajor = (amt, cur) => ZERO_DEC.has((cur || "").toLowerCase()) ? amt : amt / 100;
      try {
        const auth = { "Authorization": "Bearer " + env.STRIPE_SECRET_KEY };
        let mrr = 0, active = 0, trialing = 0, pastDue = 0, canceled = 0, currency = null;
        const monthStart = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 7);
        let newThisMonth = 0, starting_after = null;
        for (let page = 0; page < 10; page++) {
          const u = new URL("https://api.stripe.com/v1/subscriptions");
          u.searchParams.set("status", "all");
          u.searchParams.set("limit", "100");
          if (starting_after) u.searchParams.set("starting_after", starting_after);
          const r = await fetch(u.toString(), { headers: auth });
          const d = await r.json();
          if (!r.ok) return json({ error: "stripe_failed", status: r.status, detail: d }, 502);
          for (const s of d.data || []) {
            if (s.created && new Date(s.created * 1000 + 8 * 3600 * 1000).toISOString().slice(0, 7) === monthStart) newThisMonth++;
            if (s.status === "active" || s.status === "trialing") {
              if (s.status === "trialing") trialing++; else active++;
              for (const it of (s.items && s.items.data) || []) {
                const price = it.price || {};
                if (!currency) currency = price.currency || null;
                const amt = (price.unit_amount || 0) * (it.quantity || 1);
                const iv = (price.recurring && price.recurring.interval) || "month";
                const ic = (price.recurring && price.recurring.interval_count) || 1;
                let monthly = amt / ic;
                if (iv === "year") monthly = amt / 12 / ic;
                else if (iv === "week") monthly = amt * 52 / 12 / ic;
                else if (iv === "day") monthly = amt * 365 / 12 / ic;
                mrr += monthly;
              }
            } else if (s.status === "past_due" || s.status === "unpaid") pastDue++;
            else if (s.status === "canceled") canceled++;
          }
          if (!d.has_more) break;
          starting_after = d.data[d.data.length - 1].id;
        }
        const mrrMajor = toMajor(mrr, currency);
        return json({
          currency: (currency || "twd").toUpperCase(),
          mrr: Math.round(mrrMajor), arr: Math.round(mrrMajor * 12),
          active, trialing, pastDue, canceled, newThisMonth
        });
      } catch (e) { return json({ error: "exception", detail: String(e) }, 502); }
    }

    // Admin:單一用戶詳情(方案/密碼/偏好/註冊日/Brevo)
    if (url.pathname === "/admin/user-detail" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const target = (body.target || "").trim().toLowerCase();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return json({ error: "invalid_target" }, 400);
      const [plan, pwd, prefsRaw, pushRaw, signupRaw] = await Promise.all([
        env.USER_PREFS.get(`plan:${target}`),
        env.USER_PREFS.get(`pwd:${target}`),
        env.USER_PREFS.get(target),
        env.USER_PREFS.get(`pushsub:${target}`),   // Web Push 訂閱(LINE 已全退役,通道改自有 Web Push)
        env.USER_PREFS.get(`signup:${target}`),
      ]);
      let prefs = null; try { if (prefsRaw) prefs = JSON.parse(prefsRaw); } catch {}
      let signup = null; try { if (signupRaw) signup = JSON.parse(signupRaw); } catch {}
      let pushCount = 0; try { const l = pushRaw ? JSON.parse(pushRaw) : []; pushCount = Array.isArray(l) ? l.length : 0; } catch {}
      let brevo = null;
      try {
        const r = await fetch(`https://api.brevo.com/v3/contacts/${encodeURIComponent(target)}`, {
          headers: { "api-key": env.BREVO_API_KEY, "accept": "application/json" }
        });
        if (r.ok) { const d = await r.json(); brevo = { createdAt: d.createdAt, attributes: d.attributes || {} }; }
      } catch {}
      return json({
        email: target,
        plan: plan || "free",
        hasPassword: !!pwd,
        pushDevices: pushCount,                    // 已訂閱 Web Push 的裝置數(0 = 未開推播)
        signup,
        prefs: prefs ? { us_stocks: prefs.us_stocks || [], tw_stocks: prefs.tw_stocks || [], digest_depth: prefs.digest_depth || "standard", updated_at: prefs.updated_at || null } : null,
        brevo,
      });
    }

    // Admin:稽核記錄(最新 100 筆管理員異動)
    if (url.pathname === "/admin/audit-log" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const list = await env.USER_PREFS.list({ prefix: "audit:", limit: 1000 });
      const keys = list.keys.map(k => k.name).sort().reverse().slice(0, 100);
      const items = [];
      for (const k of keys) {
        const raw = await env.USER_PREFS.get(k);
        if (raw) { try { items.push(JSON.parse(raw)); } catch {} }
      }
      return json({ items });
    }

    // Admin:即時推播記錄 — alert-worker 與此共用同一 KV,直接讀 alert:recent(免跨 worker 打,避 1042)
    if (url.pathname === "/admin/alerts" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      let recent = [], last = null;
      try { const r = await env.USER_PREFS.get("alert:recent"); if (r) recent = JSON.parse(r); } catch {}
      try { const l = await env.USER_PREFS.get("alert:laststatus"); if (l) last = JSON.parse(l); } catch {}
      // 隱私:對外只回推播對象「數量」,不回訂閱者 email 明細
      const items = recent.slice(0, 40).map(a => ({
        ts: a.ts, title: a.title, url: a.url, source: a.source,
        severity: a.severity, reason: a.reason, tickers: a.tickers || [],
        eventType: a.eventType, recipients: Array.isArray(a.recipients) ? a.recipients.length : 0
      }));
      return json({ items, last });
    }

    // Admin:訂閱者成長 — 依 Brevo createdAt 分日聚合,回近 90 日累計曲線
    if (url.pathname === "/admin/growth" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
      const listId = parseInt(env.BREVO_LIST_ID) || 2;
      const days = [];
      let offset = 0;
      try {
        for (let p = 0; p < 6; p++) {
          const res = await fetch(`https://api.brevo.com/v3/contacts/lists/${listId}/contacts?limit=500&offset=${offset}`, {
            headers: { "api-key": env.BREVO_API_KEY, "accept": "application/json" }
          });
          if (!res.ok) break;
          const data = await res.json();
          const cs = data.contacts || [];
          for (const c of cs) { if (c.createdAt) days.push(String(c.createdAt).slice(0, 10)); }
          if (cs.length < 500) break;
          offset += 500;
        }
      } catch {}
      const total = days.length;
      const byDay = {};
      for (const d of days) byDay[d] = (byDay[d] || 0) + 1;
      const windowDays = 90;
      const today = new Date(Date.now() + 8 * 3600 * 1000);
      const startDate = new Date(today.getTime() - (windowDays - 1) * 86400 * 1000).toISOString().slice(0, 10);
      let cum = days.filter(d => d < startDate).length;   // 視窗前累計
      const series = [];
      for (let i = windowDays - 1; i >= 0; i--) {
        const d = new Date(today.getTime() - i * 86400 * 1000).toISOString().slice(0, 10);
        const n = byDay[d] || 0;
        cum += n;
        series.push({ date: d, added: n, cumulative: cum });
      }
      return json({ total, series });
    }

    // === Reactive Content MVP ===

    // Admin:列出所有 pending hot take(最新在前)
    if (url.pathname === "/admin/reactive-list" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
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

    // Admin:通過 hot take → 發 Threads
    if (url.pathname === "/admin/reactive-approve" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = await requireAdmin(env, body, request);
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

      const results = { threads: null };
      // 開發階段:發送先 mock 成 log,避免誤推訂戶。設 env.REACTIVE_LIVE_SEND="1" 才真寄。
      const live = env.REACTIVE_LIVE_SEND === "1";
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

      const anyFail = (results.threads && results.threads.ok === false);
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
      if (!await requireAdmin(env, body, request)) return json({ error: "Forbidden" }, 403);
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
    // 自有 Web Push 訂閱:存瀏覽器 push subscription,alert-worker 讀 pushsub:${email} 直接發(零成本無上限,不經 LINE)
    if (url.pathname === "/push/subscribe" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      const sub = body.subscription;
      if (!sub || !sub.endpoint || !sub.keys || !sub.keys.p256dh || !sub.keys.auth) {
        return json({ error: "invalid_subscription" }, 400);
      }
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (storedHash) {
        const password = body.password || "";
        if (!password || !(await verifyPwd(password, storedHash))) return json({ error: "auth" }, 403);
      }
      // 多裝置:存成陣列,以 endpoint 去重(手機/Mac/平板各一筆都保留)
      let list = [];
      const existing = await env.USER_PREFS.get(`pushsub:${email}`);
      if (existing) { try { const p = JSON.parse(existing); list = Array.isArray(p) ? p : [p]; } catch {} }
      const entry = { endpoint: sub.endpoint, keys: { p256dh: sub.keys.p256dh, auth: sub.keys.auth }, ts: new Date().toISOString() };
      list = list.filter((s) => s && s.endpoint && s.endpoint !== sub.endpoint);
      list.push(entry);
      if (list.length > 10) list = list.slice(-10); // 上限 10 台
      await env.USER_PREFS.put(`pushsub:${email}`, JSON.stringify(list));
      return json({ ok: true, devices: list.length });
    }
    if (url.pathname === "/push/unsubscribe" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email) return json({ error: "invalid_email" }, 400);
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (storedHash) {
        const password = body.password || "";
        if (!password || !(await verifyPwd(password, storedHash))) return json({ error: "auth" }, 403);
      }
      // 帶 endpoint → 只移除「這台」;不帶 → 全清(關閉所有裝置)
      if (body.endpoint) {
        let list = [];
        const existing = await env.USER_PREFS.get(`pushsub:${email}`);
        if (existing) { try { const p = JSON.parse(existing); list = Array.isArray(p) ? p : [p]; } catch {} }
        list = list.filter((s) => s && s.endpoint && s.endpoint !== body.endpoint);
        if (list.length) await env.USER_PREFS.put(`pushsub:${email}`, JSON.stringify(list));
        else await env.USER_PREFS.delete(`pushsub:${email}`);
        return json({ ok: true, devices: list.length });
      }
      await env.USER_PREFS.delete(`pushsub:${email}`);
      return json({ ok: true, devices: 0 });
    }
    // 查詢已訂閱 web push 的裝置數(前端顯示狀態用,公開唯讀)
    if (url.pathname === "/push/status" && request.method === "GET") {
      const email = (url.searchParams.get("email") || "").trim().toLowerCase();
      if (!email) return json({ subscribed: false, devices: 0 });
      const raw = await env.USER_PREFS.get(`pushsub:${email}`);
      let n = 0;
      if (raw) { try { const p = JSON.parse(raw); n = Array.isArray(p) ? p.length : 1; } catch { n = 1; } }
      return json({ subscribed: n > 0, devices: n });
    }

    // 站內即時提醒收件匣:回傳 alerthist:${email}(alert-worker 推播成功時寫入)。需密碼驗證。
    if (url.pathname === "/alerts/list" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email) return json({ error: "invalid_email" }, 400);
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (storedHash) {
        const password = body.password || "";
        if (!password || !(await verifyPwd(password, storedHash))) return json({ error: "auth" }, 403);
      }
      let list = [];
      const raw = await env.USER_PREFS.get(`alerthist:${email}`);
      if (raw) { try { list = JSON.parse(raw); } catch {} }
      list.sort((a, b) => (b.ts || "").localeCompare(a.ts || "")); // 最新在前
      return json({ ok: true, alerts: list });
    }

    if (url.pathname === "/save-preferences" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch {
        return json({ error: "Invalid request" }, 400);
      }
      const email = (body.email || "").trim().toLowerCase();
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        return json({ error: "invalid_email" }, 400);
      }
      // 身份驗證:若用戶已設密碼,save 必須帶正確密碼,否則任何人能改別人偏好。
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (storedHash) {
        const password = body.password || "";
        if (!password || !(await verifyPwd(password, storedHash))) {
          return json({ error: "auth" }, 403);
        }
      }
      const plan = (await env.USER_PREFS.get(`plan:${email}`)) || "free";
      const cap = planCap(plan);
      let us = Array.isArray(body.us_stocks) ? body.us_stocks : [];
      let tw = Array.isArray(body.tw_stocks) ? body.tw_stocks : [];
      const submitted = us.length + tw.length;
      [us, tw] = applyCap(us, tw, cap);
      const saved = us.length + tw.length;
      // 日報深度:全體用戶皆可選 simple/standard/deep(合規結構:深度屬個股分析內容,不得依付費分級);未帶則沿用既有值
      const existingRaw = await env.USER_PREFS.get(email);
      const existing = existingRaw ? JSON.parse(existingRaw) : {};
      let digest_depth = body.digest_depth || existing.digest_depth || "standard";
      if (!["simple", "standard", "deep"].includes(digest_depth)) digest_depth = "standard";
      // 持倉成本(選填,2026-07-07):{ ticker: { entry_price, entry_date } }。
      // 有帶 positions 就整份取代(空物件=清空),沒帶則沿用既有值;只留仍在追蹤清單內的 ticker。
      let positions = existing.positions || {};
      if (body.positions !== undefined) {
        positions = {};
        if (body.positions && typeof body.positions === "object" && !Array.isArray(body.positions)) {
          for (const [sym, p] of Object.entries(body.positions).slice(0, 200)) {
            if (!p || typeof p !== "object") continue;
            const entry = {};
            const price = Number(p.entry_price);
            if (Number.isFinite(price) && price > 0 && price < 1e7) entry.entry_price = Math.round(price * 10000) / 10000;
            if (typeof p.entry_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(p.entry_date)) entry.entry_date = p.entry_date;
            if (entry.entry_price) positions[sym] = entry;
          }
        }
      }
      const trackedSyms = new Set([...us, ...tw]);
      positions = Object.fromEntries(Object.entries(positions).filter(([s]) => trackedSyms.has(s)));
      const prefs = {
        us_stocks: us,
        tw_stocks: tw,
        digest_depth,
        ...(Object.keys(positions).length ? { positions } : {}),
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

    // 內部 token timing-safe 比對:接受 INTERNAL_TOKEN 或 INTERNAL_TOKEN_2。
    // _2 是 2026-06-12 GitHub Actions 被停用時為本機備援 runner 加的第二把,舊把全 caller 不動。
    const internalBearerOk = (auth) => {
      for (const t of [env.INTERNAL_TOKEN, env.INTERNAL_TOKEN_2].filter(Boolean)) {
        const expected = `Bearer ${t}`;
        if ((auth || "").length !== expected.length) continue;
        let diff = 0;
        for (let i = 0; i < auth.length; i++) diff |= auth.charCodeAt(i) ^ expected.charCodeAt(i);
        if (diff === 0) return true;
      }
      return false;
    };

    // Get user preferences
    if (url.pathname === "/get-preferences" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch {
        return json({ error: "Invalid request" }, 400);
      }
      const email = (body.email || "").trim().toLowerCase();
      if (!email) return json({ error: "invalid_email" }, 400);
      // Server-to-server bypass:daily digest job 帶 Bearer INTERNAL_TOKEN 可跳過 password gate。
      // 不能拿掉 password gate(否則 marketdaily.ai 任何人都能 enum 持股),但 digest job 也不能拿用戶密碼。
      const internalOk = internalBearerOk(request.headers.get("authorization") || "");
      // 身份驗證:若用戶已設密碼,read 必須帶正確密碼,否則任何人能查別人持股。
      if (!internalOk) {
        const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
        if (storedHash) {
          const password = body.password || "";
          if (!password || !(await verifyPwd(password, storedHash))) {
            return json({ error: "auth" }, 403);
          }
        }
      }
      const plan = (await env.USER_PREFS.get(`plan:${email}`)) || "free";
      const cap = planCap(plan);
      const raw = await env.USER_PREFS.get(email);
      const prefs = raw ? JSON.parse(raw) : {};
      return json({
        us_stocks: prefs.us_stocks || [],
        tw_stocks: prefs.tw_stocks || [],
        digest_depth: prefs.digest_depth || "standard",
        positions: prefs.positions || {},
        plan,
        cap: cap === Infinity ? null : cap,
      });
    }

    // Save a personalized digest HTML; returns a shareable web URL.
    // 可選 date 欄位 → 同步寫索引 digest_idx:{date}:{token},供 track-record builder 列舉
    if (url.pathname === "/save-digest" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const incoming = (body.token || "").trim();
      const html = body.html || "";
      const date = (body.date || "").trim();
      if (!/^[A-Za-z0-9_-]{8,64}$/.test(incoming)) return json({ error: "invalid_token" }, 400);
      if (!html || html.length > 5000000) return json({ error: "invalid_html" }, 400);
      // Anti-spam: 每 IP 每小時最多 100 次 (legitimate builder 一天 < 30 次,留充足 buffer)
      // 防止攻擊者 spam 5MB KV entry 爆 quota
      const ip = request.headers.get("cf-connecting-ip") || "anon";
      const rlKey = `rl:save-digest:${ip}`;
      const rlCount = parseInt((await env.USER_PREFS.get(rlKey)) || "0", 10);
      if (rlCount >= 100) return json({ error: "too_many_attempts" }, 429);
      ctx.waitUntil(env.USER_PREFS.put(rlKey, String(rlCount + 1), { expirationTtl: 3600 }));
      // 若 client 仍送短 token(舊 builder),server 升級為 32 字元防爆破。
      const token = incoming.length >= 32 ? incoming : crypto.randomUUID().replace(/-/g, "");
      await env.USER_PREFS.put(`digest:${token}`, html, { expirationTtl: 86400 * 45 });
      if (/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        // 同步寫索引,TTL 同 digest 本體
        await env.USER_PREFS.put(`digest_idx:${date}:${token}`, "1", { expirationTtl: 86400 * 45 });
      }
      return json({ ok: true, url: `${url.origin}/digest/${token}`, token });
    }

    // 內部用:推 LINE 訊息給 admin(供 digest pipeline、audit 失分通知用)
    // 認證:Bearer header 比對 env.INTERNAL_TOKEN
    if (url.pathname === "/internal/admin-line-push" && request.method === "POST") {
      if (!internalBearerOk(request.headers.get("authorization") || "")) return json({ error: "unauthorized" }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ error: "bad_body" }, 400); }
      const message = String(body.message || "").slice(0, 4900);
      if (!message) return json({ error: "empty_message" }, 400);
      const res = await sendLineAdminPush(env, message);
      return json({ ok: !!res.ok, status: res.status, skipped: !!res.skipped });
    }

    // 內部用:列舉某日所有 digest tokens(供 track-record builder)
    // 認證:Bearer header 比對 env.INTERNAL_TOKEN
    if (url.pathname === "/internal/list-digests" && request.method === "GET") {
      if (!internalBearerOk(request.headers.get("authorization") || "")) return json({ error: "unauthorized" }, 401);
      const date = (url.searchParams.get("date") || "").trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return json({ error: "invalid_date" }, 400);
      const tokens = [];
      let cursor = undefined;
      // KV list 一次最多 1000 鍵,需要分頁
      for (let i = 0; i < 10; i++) {
        const res = await env.USER_PREFS.list({ prefix: `digest_idx:${date}:`, cursor });
        for (const k of res.keys) {
          const t = k.name.slice(`digest_idx:${date}:`.length);
          if (t) tokens.push(t);
        }
        if (res.list_complete) break;
        cursor = res.cursor;
      }
      return json({ date, count: tokens.length, tokens });
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
      if (!(await isEmailDeliverable(email, env))) return json({ error: "undeliverable_email" }, 400);
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
      // 邀請碼註冊者 = 免費方案;Premium(支持者方案)需付費升級或管理員手動開通
      await env.USER_PREFS.put(`plan:${email}`, "free");
      // 歡迎信、推薦轉換全部背景化 —— 任一失敗都不影響「註冊成功」的回應
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
          const r = data?.chart?.result?.[0];
          const meta = r?.meta;
          if (!meta) return null;
          // 同 /stock-quotes: 用 close array 最後兩個算「當日漲跌」,
          // chartPreviousClose 是 5 天前的收盤,直接用會變累計漲幅而非當日。
          const closes = (r.indicators?.quote?.[0]?.close || []).filter(c => c !== null && c !== undefined);
          const price = meta.regularMarketPrice ?? (closes.length ? closes[closes.length - 1] : null);
          const prev = closes.length >= 2 ? closes[closes.length - 2] : (meta.chartPreviousClose ?? null);
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
      // 上限 80:曾經 50 把用戶 56 支(34美股+22台股)的最後 6 支靜默砍掉 → 那幾檔永遠「···」
      // (2026-06-10 實鍋,違反「禁止靜默砍資料」)。前端已改 25 支/批,這裡是第二道保險。
      const raw = (url.searchParams.get("tickers") || "").split(",").map(t => t.trim()).filter(Boolean).slice(0, 80);
      if (!raw.length) return json({ quotes: [] });
      const fh = env.FINNHUB_API_KEY;
      const yfHeaders = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://finance.yahoo.com/"
      };
      const fetchOne = async (t) => {
        const isTW = /^\d{4,6}$/.test(t);
        // 前收一律用 Yahoo range=1d(intraday)的 meta.chartPreviousClose:
        //   - 1d range 下它就是「正確的前一交易日收盤」(reference 已驗證:1D range chartPreviousClose=昨收)。
        //   - 不可用 5d 日線 closes[-2]:Yahoo 日線新鮮度不穩(常缺最新一天),closes[-2] 會取到大前天,
        //     配上 Finnhub 即時價 → 漲跌幅錯位(2026-06-05 AAOI:日線缺 6/4 時前收誤取 6/2 202.37 → +0.26%,實際 +10.22%)。
        //   - 也不信 Finnhub 的 dp/pc:盤後它的前收同樣會跳號錯位。
        // 美股額外並行抓 Finnhub last-trade 當盤中即時 price(比 Yahoo 即時),前收與漲跌幅一律以 Yahoo 為準。
        const fhQuote = (fh && !isTW)
          ? fetch(`https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(t)}&token=${fh}`, { cf: { cacheTtl: 15, cacheEverything: true } })
              .then(r => r.ok ? r.json() : null).catch(() => null)
          : Promise.resolve(null);
        // Yahoo:台股(.TW 上市 / .TWO 上櫃 自動切換)
        const [r, fd] = await Promise.all([
          fetchYahooChart(t, isTW, "5m", "1d", yfHeaders, 15),
          fhQuote
        ]);
        let price = null, prev = null, name = t;
        if (r) {
          const meta = r.meta;
          const closes = (r.indicators?.quote?.[0]?.close || []).filter(c => c !== null && c !== undefined);
          price = meta?.regularMarketPrice ?? (closes.length ? closes[closes.length - 1] : null);
          prev = meta?.chartPreviousClose ?? null;
          name = meta?.shortName || meta?.longName || t;
        }
        if (fd && typeof fd.c === "number" && fd.c > 0) price = fd.c;  // Finnhub 即時價覆蓋(前收仍用 Yahoo)
        let change = (price !== null && prev !== null && prev !== 0) ? ((price - prev) / prev * 100) : null;
        // Yahoo 全掛的最終後援:退回 Finnhub 自己的 c/dp(次佳,前收可能錯位但聊勝於無)
        if (price === null && fd && typeof fd.c === "number" && fd.c > 0) {
          price = fd.c; change = typeof fd.dp === "number" ? fd.dp : null;
        }
        return { symbol: t, name, price, change };
      };
      const settleChunk = (arr, syms) => arr.map((r, i) => r.status === "fulfilled" ? r.value : { symbol: syms[i], name: syms[i], price: null, change: null });
      // 持倉多時(10+ 檔)同時開 N 條會觸發 Yahoo burst 限流 → 改 4 檔一批、批間 120ms,
      // 從源頭降低觸發機率(2026-06-10:6/8 的單次補抓在「持續限流窗口」下仍會 6/10 檔卡「···」)。
      const quotes = [];
      for (let i = 0; i < raw.length; i += 4) {
        const chunk = raw.slice(i, i + 4);
        quotes.push(...settleChunk(await Promise.allSettled(chunk.map(fetchOne)), chunk));
        if (i + 4 < raw.length) await new Promise(rz => setTimeout(rz, 120));
      }
      // 仍有 miss → 加抖動後單次補抓,同一個 request 自我修復
      const misses = quotes.map((q, i) => q.price == null ? i : -1).filter(i => i >= 0);
      if (misses.length && misses.length < quotes.length) {
        await new Promise(rz => setTimeout(rz, 350 + Math.random() * 250));
        const syms = misses.map(i => raw[i]);
        const retried = settleChunk(await Promise.allSettled(syms.map(fetchOne)), syms);
        retried.forEach((q, j) => { if (q.price != null) quotes[misses[j]] = q; });
      }
      // 最後防線:Yahoo 持續限流時,用同 PoP 快取的「上一筆好報價」(6h)頂上,
      // 前台不再長時間卡「···」;新的好報價順手寫回快取。
      const qcache = caches.default;
      const qkey = (t) => new Request("https://quote-cache.marketdaily.internal/" + encodeURIComponent(t));
      for (let i = 0; i < quotes.length; i++) {
        if (quotes[i].price != null) continue;
        try {
          const hit = await qcache.match(qkey(quotes[i].symbol));
          if (hit) quotes[i] = await hit.json();
        } catch {}
      }
      ctx.waitUntil(Promise.all(quotes.filter(q => q.price != null).map(q =>
        qcache.put(qkey(q.symbol), new Response(JSON.stringify(q), {
          headers: { "Content-Type": "application/json", "Cache-Control": "max-age=21600" }
        })).catch(() => {})
      )));
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
        // prevClose 語意 = 「昨日收盤」(作為圖表上「前一日收盤水平線」用):
        //   - 1D range (intraday 5m):chartPreviousClose 剛好是昨日 ✓
        //   - 5D / 1M / 3M (daily intervals):chartPreviousClose 是 range 起始前一天,
        //     會變成「5 天前 / 1 個月前 / 3 個月前」的收盤,語意錯誤。
        //     用 close array 倒數第二個才是真昨日。
        let prevClose = r.meta?.chartPreviousClose ?? null;
        if (cfg.range !== "1d") {
          const validCloses = closes.filter(c => c !== null && c !== undefined);
          if (validCloses.length >= 2) prevClose = validCloses[validCloses.length - 2];
          // Yahoo 日線(1d interval)偶發落後 intraday 一天:最新交易日的日 K 還沒補進序列,
          // 1M/3M 圖最後一根會停在前一交易日(2026-06-05 抓到 IONQ/META/PLTR 等約 20 支卡 6/3)。
          // 用 meta 即時報價補上缺的最新一根,並把前收線改成原序列最後一根。
          const mt = r.meta?.regularMarketTime, mp = r.meta?.regularMarketPrice;
          if (mt && mp != null && points.length) {
            const lastDay = new Date(points[points.length - 1].t * 1000).toISOString().slice(0, 10);
            const mtDay = new Date(mt * 1000).toISOString().slice(0, 10);
            if (mtDay > lastDay) {
              prevClose = points[points.length - 1].c;
              points.push({ t: mt, c: mp });
            }
          }
        }
        return new Response(JSON.stringify({
          symbol: t,
          prevClose,
          price: r.meta?.regularMarketPrice ?? null,
          points
        }), {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=300" }
        });
      } catch {
        return json({ error: "error" }, 500);
      }
    }

    // 產業鏈🆕最新動態 — alert-worker /internal/supply-chain-event 寫入的官方公告事件
    // (新合作/新供應關係,MOPS 重訊+8-K 1.01)。免登入,唯讀共用 KV scpend:{ticker}。
    if (url.pathname === "/supply-chain-updates" && request.method === "GET") {
      let t = (url.searchParams.get("ticker") || "").trim().toUpperCase().slice(0, 12);
      t = t.replace(/\.(TW|TWO)$/, "");
      if (!t || !/^[A-Z0-9.\-]+$/.test(t)) return json({ error: "invalid_ticker" }, 400);
      const ip = clientIp(request);
      const rlKey = `rl:scu:${ip}`;
      const rlCount = parseInt((await env.USER_PREFS.get(rlKey)) || "0", 10);
      if (rlCount >= 60) return json({ error: "rate_limited" }, 429);
      ctx.waitUntil(env.USER_PREFS.put(rlKey, String(rlCount + 1), { expirationTtl: 60 }));
      let events = [];
      try {
        const raw = await env.USER_PREFS.get(`scpend:${t}`);
        if (raw) events = JSON.parse(raw);
      } catch {}
      // 只回近 60 天,最多 5 則——「最新動態」區塊不是歷史帳
      const cutoff = Date.now() - 60 * 24 * 3600 * 1000;
      events = (Array.isArray(events) ? events : [])
        .filter((e) => e && (!e.ts || e.ts >= cutoff)).slice(0, 5);
      return json({ ticker: t, events });
    }

    // 產業鏈 / 供應鏈 — DB 未命中的股票走這裡用 AI 生成(前端先查靜態 DB)。
    // 免登入(免費功能),但加 per-IP rate limit 防 LLM 濫用;結果存 KV 30 天。
    if (url.pathname === "/supply-chain" && request.method === "GET") {
      const ticker = (url.searchParams.get("ticker") || "").trim().toUpperCase().slice(0, 12);
      if (!ticker || !/^[A-Z0-9.\-]+$/.test(ticker)) return json({ error: "invalid_ticker" }, 400);
      const givenName = (url.searchParams.get("name") || "").trim().slice(0, 40);

      // cache key 含公司名:台股裸代號 AI 會猜錯公司,帶名才準,故名也納入 key
      const cacheKey = `sc:v5:${ticker}:${givenName}`;
      const cached = await env.USER_PREFS.get(cacheKey);
      if (cached) {
        try { return json(JSON.parse(cached)); } catch {}
      }

      // 輕量 per-IP rate limit:30 次/分
      const ip = clientIp(request);
      const rlKey = `rl:sc:${ip}`;
      const rlCount = parseInt((await env.USER_PREFS.get(rlKey)) || "0", 10);
      if (rlCount >= 30) return json({ error: "rate_limited" }, 429);
      ctx.waitUntil(env.USER_PREFS.put(rlKey, String(rlCount + 1), { expirationTtl: 60 }));

      const isTW = /^\d{4,6}$/.test(ticker);
      const sysPrompt = `你是財經產業鏈分析助手。針對給定的股票,輸出這家公司「詳細」的產業鏈資料。

嚴格規則:
- 語言:所有文字欄位(company_zh / industry / mid.desc / name_zh / category / role / criticality)一律使用「台灣繁體中文」的用字與用語,嚴禁任何簡體字,嚴禁中國大陸慣用語。半導體/科技用語一律用台灣說法:晶片(非「芯片」)、微影機或曝光機(非「光刻机」)、關鍵/命脈/難以替代(非「卡脖子」)、記憶體(非「内存」)、軟體(非「软件」)、頂尖(非「顶尖」)、供應商(非「供应商」)、設備(非「设备」)、鏡頭(非「镜头」)、製造(非「制造」)、矽晶圓、封裝測試。若不確定某詞的台灣寫法,用最通用的繁體中文。
- 若提供了公司名稱,以「公司名稱」為準辨識這家公司,不要從代號數字臆測;若公司名稱與你認知的代號不符,以公司名稱為準。
- 只列「真實、公認」的供應鏈關係。不確定就回空陣列,絕不亂掰、絕不臆測。
- 關聯公司的 ticker 只在你確定它是上市公司時才填,否則填 null。
- mid.desc 用 1~2 句繁體中文說明:這家公司做什麼 + 它在產業鏈的位置與競爭優勢(市佔、技術門檻或護城河)。
- industry 填「大產業 › 細分」格式(如「半導體 › 晶圓代工」),不確定填空字串。
- upstream = 它的上游供應商/原材料/設備;downstream = 它的下游客戶/應用。各盡量列 4~8 個關鍵環節,由最關鍵排到次要,別只給一兩個。
- 每個關聯公司物件:{ "name_zh", "name_en", "ticker"(或 null), "category"(這個環節的類別,如「曝光機」「矽晶圓」「AI 伺服器」,沒有填空字串), "role"(具體說明它供應什麼或被如何使用,要具體,例如「EUV 微影機 全球獨家」而非只寫「設備」), "criticality"(對這家公司的重要程度,只能是 極高/高/中/低 其一,可加極短理由如「極高 — 無替代」) }。

只輸出 JSON,不要任何其他文字,格式:
{"ticker":"${ticker}","source":"ai","company_zh":"","industry":"","mid":{"name":"","desc":""},"upstream":[{"name_zh":"","name_en":"","ticker":null,"category":"","role":"","criticality":""}],"downstream":[{"name_zh":"","name_en":"","ticker":null,"category":"","role":"","criticality":""}]}`;

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
            max_tokens: 2000,
            system: sysPrompt,
            messages: [{ role: "user", content: `${givenName ? `公司名稱:${givenName}、` : ""}股票代號:${ticker}${isTW ? "(台股)" : "(美股)"}。輸出它的產業鏈 JSON。` }],
          }),
        });
      } catch {
        return json({ error: "ai_unreachable" }, 502);
      }
      if (!aiRes.ok) return json({ error: "ai_error" }, 502);

      let parsed;
      try {
        const data = await aiRes.json();
        let txt = (data.content || []).map(c => c.text || "").join("").trim();
        const s = txt.indexOf("{"), e = txt.lastIndexOf("}");
        if (s === -1 || e === -1) throw new Error("no json");
        parsed = JSON.parse(txt.slice(s, e + 1));
      } catch {
        return json({ error: "ai_parse" }, 502);
      }
      // 正規化 + 防呆:結構不對就當失敗,不回半成品
      const out = {
        ticker,
        source: "ai",
        company_zh: _twFix(typeof parsed.company_zh === "string" ? parsed.company_zh : ""),
        industry: _twFix(typeof parsed.industry === "string" ? parsed.industry : ""),
        mid: {
          name: _twFix(parsed.mid?.name || parsed.company_zh || ticker),
          desc: _twFix(parsed.mid?.desc || ""),
        },
        upstream: _scNormList(parsed.upstream),
        downstream: _scNormList(parsed.downstream),
      };
      if (!out.mid.desc && !out.upstream.length && !out.downstream.length) {
        return json({ error: "no_data" }, 404);
      }
      ctx.waitUntil(env.USER_PREFS.put(cacheKey, JSON.stringify(out), { expirationTtl: 30 * 86400 }));
      return json(out);
    }

    // Direct free signup (no invite code required)
    if (url.pathname === "/subscribe-free-direct" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "invalid_email" }, 400);
      if (!(await isEmailDeliverable(email, env))) return json({ error: "undeliverable_email" }, 400);
      // Anti-spam: IP 級每小時 10 次 + 同 email 5 分鐘內 1 次
      const ip = request.headers.get("cf-connecting-ip") || "anon";
      const ipKey = `rl:signup-ip:${ip}`;
      const ipCount = parseInt((await env.USER_PREFS.get(ipKey)) || "0", 10);
      if (ipCount >= 10) return json({ error: "too_many_attempts", retry_after: "1h" }, 429);
      if (await env.USER_PREFS.get(`rl:signup-email:${email}`)) return json({ error: "rate_limited" }, 429);
      ctx.waitUntil(env.USER_PREFS.put(ipKey, String(ipCount + 1), { expirationTtl: 3600 }));
      ctx.waitUntil(env.USER_PREFS.put(`rl:signup-email:${email}`, "1", { expirationTtl: 300 }));
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
      // 2026-07-09 全面免費化:法律風險考量,下架所有付費方案,不再開新結帳。
      return json({ error: "payments_disabled", message: "MarketDaily 現已完全免費,所有功能對全體用戶開放,無需付費。" }, 410);
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
      // 身份驗證:任何人查別人 referral 等同洩漏其 conversions/clicks/bonus 統計
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (storedHash) {
        const password = body.password || "";
        if (!password || !(await verifyPwd(password, storedHash))) return json({ error: "auth" }, 403);
      }

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
      // 身份驗證:同 /get-referral,不可洩漏別人 stats
      const storedHash = await env.USER_PREFS.get(`pwd:${email}`);
      if (storedHash) {
        const password = body.password || "";
        if (!password || !(await verifyPwd(password, storedHash))) return json({ error: "auth" }, 403);
      }

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
        // Pro 改為「Premium 試讀首月」定位 — Pro 購買者立即享 Premium 全功能(即時推播 + AI Q&A 等)
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
        // 歡迎信背景化 —— webhook 快速回 200,避免 Stripe 因逾時重送
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
        }
        // 2026-07-09 全面免費化:D7/D14/D21/D45 皆為 Premium 升級/推薦獎勵信,全數停發。
        // 模板函數保留(admin lifecycle-test 仍可預覽),排程不再觸發。

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
  if (!timestamp || !signature) return false;
  // Replay protection: timestamp 必須在 ±5 分鐘內(Stripe 官方建議閾值,
  // 攔截攻擊者重送舊 webhook 觸發重複付款處理)
  const ts = parseInt(timestamp, 10);
  if (!Number.isFinite(ts)) return false;
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - ts) > 300) return false;
  const signed = `${timestamp}.${payload}`;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signed));
  const expected = Array.from(new Uint8Array(mac)).map(b => b.toString(16).padStart(2, "0")).join("");
  // Timing-safe comparison(避免 timing attack 推斷 secret)
  if (expected.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  return diff === 0;
}

// 稽核記錄:管理員每次異動寫一筆,供 /admin/audit-log 檢視。180 天 TTL。永不因失敗中斷主流程。
async function logAudit(env, actor, action, detail) {
  try {
    const ts = Date.now();
    const rec = { ts, iso: new Date(ts).toISOString(), actor: actor || "admin", action, detail: detail || {} };
    await env.USER_PREFS.put(
      `audit:${ts}_${Math.random().toString(36).slice(2, 8)}`,
      JSON.stringify(rec),
      { expirationTtl: 86400 * 180 }
    );
  } catch {}
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

// 註冊成功後的背景工作:推薦轉換 + 歡迎信。日報不補寄,等隔日排程首發。
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
- MarketDaily 目前全功能限時免費開放：留 Email 即可訂閱（不需邀請碼）,包含全部功能（個人化日報、AI 助手、即時推播）
- 早鳥權益：現在訂閱的用戶,未來恢復收費後仍永久保留免費使用權
- 若用戶問到過去的 Premium 付費方案：已於 2026 年 7 月取消,目前沒有任何付費方案;曾付費的用戶請聯繫 support@marketdaily.ai 處理
- 所有分析內容對全體用戶完全相同

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
  const subject = "✅ 訂閱成功！歡迎加入財經日報 🎉";
  const planLine = "您的訂閱已啟用。MarketDaily 目前<strong>全功能限時免費</strong>,而且你已鎖定<strong>早鳥權益</strong> — 未來恢復收費後,你仍永久免費使用。";

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

async function sendPasswordResetEmail(email, apiKey, link) {
  const body = `
    <p style="font-size:16px;font-weight:800;color:#1a1a1a;margin:0 0 14px;">收到重設密碼的請求</p>
    <p style="font-size:14px;color:#444;line-height:1.8;margin:0 0 22px;">
      有人（希望是你本人）為這個 Email 申請重設 MarketDaily 密碼。<br>
      點下方按鈕設定新密碼，連結 <strong>30 分鐘內有效</strong>，且只能使用一次。
    </p>
    <div style="text-align:center;margin-bottom:24px;">
      <a href="${link}" style="display:inline-block;background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;font-size:15px;font-weight:800;padding:14px 36px;border-radius:12px;text-decoration:none;">重設我的密碼 →</a>
    </div>
    <p style="font-size:12px;color:#888;line-height:1.8;margin:0;">
      如果按鈕無法點擊，複製這個網址到瀏覽器開啟：<br>
      <span style="word-break:break-all;color:#6366f1;">${link}</span>
    </p>
    <p style="font-size:12px;color:#888;line-height:1.8;margin:14px 0 0;">
      如果這不是你本人的操作，直接忽略這封信即可，你的密碼不會被更改。
    </p>`;
  const html = lifecycleShell({
    badge: "PASSWORD RESET",
    headerTitle: "🔐 重設你的密碼",
    headerSub: "MarketDaily 帳號安全",
    bodyHtml: body,
  });
  return sendLifecycleEmail(email, apiKey, "🔐 重設你的 MarketDaily 密碼", html);
}

// D1:設股票偏好 —— 沒設就會收到通用版日報,失去個人化價值
async function sendD1Email(email, apiKey, env) {
  const subject = "✋ 把你的持股告訴 MarketDaily,日報才會真的個人化";
  const cta = `https://marketdaily.ai/dashboard?focus=stocks&utm_source=lifecycle&utm_campaign=d1_preferences&email=${encodeURIComponent(email)}`;
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
  const subject = "☕ 你已經讀了 7 封日報 — 如果對你有幫助,首月 6 折支持我們";
  const upgradeLink = `https://marketdaily.ai/pricing?utm_source=lifecycle&utm_campaign=d7_premium&email=${encodeURIComponent(email)}`;
  const body = `
    <p style="font-size:17px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">過去 7 天,你已經養成看 MarketDaily 的習慣 ☕</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 22px;">
      先說清楚:<strong>日報、AI 投資助手、即時推播等所有分析功能,對免費和付費用戶完全相同</strong>,升不升級都不影響你收到的內容。<br>
      如果這一週對你有幫助,<strong>Premium 支持者方案</strong>是你支持我們繼續獨立營運的方式。
    </p>
    <div style="background:linear-gradient(135deg,rgba(99,102,241,0.08),rgba(139,92,246,0.08));border:1px solid rgba(99,102,241,0.25);border-radius:14px;padding:20px 22px;margin-bottom:22px;">
      <p style="margin:0 0 14px;font-size:15px;font-weight:800;color:#4f46e5;">PREMIUM 支持者方案</p>
      <ul style="margin:0;padding-left:18px;font-size:14px;color:#444;line-height:1.95;">
        <li><strong>支持獨立營運</strong>(不接廣告、不賣明牌、不賣你的資料)</li>
        <li><strong>1-1 優先客服</strong>(來信優先回覆)</li>
        <li><strong>非分析類新功能搶先體驗</strong>(總經數據儀表板等,陸續推出)</li>
      </ul>
      <p style="margin:14px 0 0;font-size:12px;color:#888;line-height:1.7;">Premium 不包含任何額外的個股分析或投資建議內容 —— 所有分析內容全體用戶免費且相同。</p>
    </div>
    <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:16px 20px;margin-bottom:20px;text-align:center;">
      <div style="font-size:15px;color:#1a1a1a;">
        首月 <strong style="font-size:22px;color:#d97706;">NT$299</strong>
        <span style="text-decoration:line-through;color:#999;margin-left:6px;">NT$499</span>
        <span style="color:#666;font-size:13px;"> (6 折)</span>
      </div>
      <div style="font-size:12px;color:#92400e;margin-top:4px;">之後 NT$499/月,隨時取消,30 天無理由退費</div>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-bottom:18px;">
      <tr>
        <td align="center">
          <a href="${upgradeLink}" style="display:block;padding:17px 24px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:17px;font-weight:800;text-decoration:none;border-radius:12px;">了解 Premium 支持者方案 →</a>
        </td>
      </tr>
    </table>
    <p style="font-size:12px;color:#888;line-height:1.7;margin:0;text-align:center;">
      不想升級?完全 OK,繼續用免費版享受完整功能。<br>這封信不會再寄第二次。
    </p>`;
  const html = lifecycleShell({
    badge: "Day 7 · Premium 支持者方案",
    headerTitle: "☕ 讀了一週了,想跟你說聲謝謝",
    headerSub: "如果有幫助,首月 6 折支持我們",
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
        朋友點你的連結訂閱後,你和他的帳號都自動獲得 30 天 Premium 支持者方案(1-1 優先客服+新功能搶先體驗)。
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
  const subject = "☕ 三週了 — 如果日報對你有價值,可以用 Premium 支持我們";
  const upgradeLink = `https://marketdaily.ai/pricing?utm_source=lifecycle&utm_campaign=d21_premium&email=${encodeURIComponent(email)}`;
  const body = `
    <p style="font-size:17px;font-weight:800;color:#1a1a1a;margin:0 0 12px;">三週了 ☕</p>
    <p style="font-size:15px;color:#444;line-height:1.8;margin:0 0 22px;">
      你已經連讀 ~18 封 MarketDaily 日報 —— 早晨財經習慣養成了。<br>
      先說清楚:<strong>日報、AI 助手、即時推播等所有分析功能,對免費和付費用戶完全相同</strong>,升不升級都不影響你收到的內容。<br>
      如果這個產品對你有價值,<strong>Premium 支持者方案</strong>是你支持我們繼續獨立營運的方式。
    </p>
    <div style="background:linear-gradient(135deg,rgba(168,85,247,0.10),rgba(99,102,241,0.10));border:1px solid rgba(168,85,247,0.30);border-radius:14px;padding:22px 24px;margin-bottom:22px;">
      <p style="margin:0 0 14px;font-size:14px;color:#7e22ce;font-weight:800;letter-spacing:1px;">PREMIUM 支持者方案</p>
      <p style="margin:0 0 6px;font-size:26px;font-weight:900;color:#1a1a1a;">
        首月 NT$299 <span style="font-size:18px;color:rgba(0,0,0,0.4);text-decoration:line-through;font-weight:700;margin-left:8px;">NT$499</span>
      </p>
      <p style="margin:0 0 16px;font-size:13px;color:#666;">之後 NT$499/月,隨時取消,30 天無理由退費</p>
      <ul style="margin:0;padding-left:18px;font-size:14px;color:#444;line-height:1.95;">
        <li><strong>支持獨立營運</strong>(不接廣告、不賣明牌、不賣你的資料)</li>
        <li><strong>1-1 優先客服</strong>(來信優先回覆)</li>
        <li><strong>非分析類新功能搶先體驗</strong>(總經數據儀表板等,陸續推出)</li>
      </ul>
      <p style="margin:14px 0 0;font-size:12px;color:#888;line-height:1.7;">Premium 不包含任何額外的個股分析或投資建議內容 —— 所有分析內容全體用戶免費且相同。</p>
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
      <p style="margin:0 0 10px;font-size:13px;color:#b45309;font-weight:800;letter-spacing:1px;">⚡ 為什麼值得考慮 Premium</p>
      <p style="margin:0 0 14px;font-size:15px;color:#1a1a1a;font-weight:700;line-height:1.6;">
        因為你已經養成讀日報的習慣 —— 而這個產品能不能繼續獨立營運,靠的是支持者。
      </p>
      <p style="margin:0;font-size:14px;color:#666;line-height:1.8;">
        Premium 是<strong>支持者方案</strong>:支持我們不接廣告、不賣明牌、不賣資料,<br>
        並獲得 1-1 優先客服與非分析類新功能搶先體驗。<br>
        <strong>所有分析內容(日報/AI 助手/推播)免費與付費完全相同</strong>,這點升級前先讓你知道。
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
  const adminId = env.ADMIN_LINE_USER_ID;
  if (!adminId) {
    console.log("LINE admin push skipped (missing ADMIN_LINE_USER_ID)");
    return { ok: false, skipped: true };
  }
  const body = JSON.stringify({
    to: adminId,
    messages: [{ type: "text", text: message.slice(0, 4900) }],
  });
  const tryOnce = (t) => fetch("https://api.line.me/v2/bot/message/push", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + t },
    body,
  });
  try {
    let token = await lineToken(env);
    if (!token) return { ok: false, error: "no_token" };
    let res = await tryOnce(token);
    if (res.status === 401) {
      await env.USER_PREFS.delete("alert:linetoken");
      const fresh = await lineToken(env, { force: true });
      if (fresh && fresh !== token) res = await tryOnce(fresh);
    }
    return { ok: res.ok, status: res.status };
  } catch (e) { return { ok: false, error: String(e) }; }
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

// LINE Messaging API token:KV cache(alert:linetoken,跟 alert-worker 共用)
// → static env LINE_CHANNEL_ACCESS_TOKEN → 動態 OAuth(client_credentials)。
// force=true 跳過 cache 和 static,admin 告警推 LINE 收 401 時呼叫。
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
