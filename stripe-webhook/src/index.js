const ADMIN_EMAILS = ["delvin.12345678@gmail.com"];

const INVITE_CODES = [
  "DELVIN-FE8FZ1","DELVIN-XKNJ4N","DELVIN-F4ONQQ","DELVIN-RBIG9S",
  "DELVIN-WYW4IP","DELVIN-BE2O13","DELVIN-OVMFHN","DELVIN-AV3VIB",
  "DELVIN-06U59N","DELVIN-CVRBWF"
];

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request, env) {
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
      const isPaid = (contact.attributes?.PAID === true || contact.attributes?.PLAN === "paid");
      return json({
        subscribed: listIds.includes(targetList),
        plan: isPaid ? "paid" : "free",
        since: contact.createdAt || null,
      });
    }

    // Admin stats
    if (url.pathname === "/admin-stats" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "Invalid" }, 400); }
      const email = (body.email || "").trim().toLowerCase();
      if (!ADMIN_EMAILS.includes(email)) return json({ error: "Forbidden" }, 403);
      try {
        const listId = parseInt(env.BREVO_LIST_ID) || 2;
        const res = await fetch(`https://api.brevo.com/v3/contacts/lists/${listId}`, {
          headers: { "api-key": env.BREVO_API_KEY }
        });
        const data = await res.json();
        const total = data.uniqueSubscribers || 0;
        return json({ total, free: total, paid: 0 });
      } catch { return json({ total: 0, free: 0, paid: 0 }); }
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
      const prefs = {
        us_stocks: Array.isArray(body.us_stocks) ? body.us_stocks : [],
        tw_stocks: Array.isArray(body.tw_stocks) ? body.tw_stocks : [],
        updated_at: new Date().toISOString(),
      };
      await env.USER_PREFS.put(email, JSON.stringify(prefs));
      return json({ ok: true });
    }

    // Get user preferences
    if (url.pathname === "/get-preferences" && request.method === "POST") {
      let body;
      try { body = await request.json(); } catch {
        return json({ error: "Invalid request" }, 400);
      }
      const email = (body.email || "").trim().toLowerCase();
      if (!email) return json({ error: "invalid_email" }, 400);
      const raw = await env.USER_PREFS.get(email);
      if (!raw) return json({ us_stocks: [], tw_stocks: [] });
      return json(JSON.parse(raw));
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
      const ok = await addToBrevo(email, env.BREVO_API_KEY, listId);
      if (!ok) return json({ error: "brevo_error" }, 500);

      await sendWelcomeEmail(email, env.BREVO_API_KEY, false);
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

    if (event.type === "checkout.session.completed") {
      const email = event.data.object?.customer_details?.email;
      if (email) {
        await addToBrevo(email, env.BREVO_API_KEY, parseInt(env.BREVO_LIST_ID));
        await sendWelcomeEmail(email, env.BREVO_API_KEY, true);
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

async function addToBrevo(email, apiKey, listId) {
  const res = await fetch("https://api.brevo.com/v3/contacts", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({ email, listIds: [listId], updateEnabled: true })
  });
  return res.ok || res.status === 400; // 400 = contact already exists, still OK
}

async function sendWelcomeEmail(email, apiKey, isPaid = false) {
  const subject = isPaid ? "✅ 訂閱成功！歡迎加入財經日報 🎉" : "✅ 邀請碼確認！歡迎加入財經日報 🎉";
  const planLine = isPaid
    ? "您的 <strong>NT$500/月付費方案</strong>已啟用。"
    : "您的<strong>免費邀請方案</strong>已啟用。";

  const html = `<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:560px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

  <div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);padding:32px 28px 24px;">
    <div style="font-size:11px;color:#a5b4fc;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;font-weight:700;">財經日報</div>
    <h1 style="margin:0;font-size:24px;font-weight:800;color:#fde68a;">📊 訂閱確認</h1>
    <p style="margin:10px 0 0;font-size:14px;color:#c4b5fd;font-weight:600;letter-spacing:0.5px;">AI 精選 · 假訊息過濾 · 美股 + 台股</p>
  </div>

  <div style="padding:28px;">
    <p style="font-size:16px;font-weight:700;color:#1a1a1a;margin:0 0 12px;">嗨！歡迎加入 👋</p>
    <p style="font-size:14px;color:#444;line-height:1.7;margin:0 0 20px;">
      ${planLine}<br>
      從明天起，每天早上 <strong>7:00 AM（台灣時間）</strong>，你會收到一封財經日報，30 秒看完今天所有重要的市場動態。
    </p>

    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:18px 20px;margin-bottom:20px;">
      <p style="margin:0 0 10px;font-size:13px;font-weight:800;color:#333;letter-spacing:0.5px;">📬 每天報告包含</p>
      <ul style="margin:0;padding-left:18px;font-size:13px;color:#555;line-height:2;">
        <li>☕ 30 秒重點摘要</li>
        <li>📈 美股 + 台股大盤動向</li>
        <li>₿ BTC / ETH 加密貨幣</li>
        <li>🔄 板塊輪動分析</li>
        <li>🔥 今日 5 大重要新聞（假訊息過濾）</li>
        <li>🔗 二階思考：美股如何影響台灣？</li>
        <li>📅 即將公布財報提醒</li>
      </ul>
    </div>

    <p style="font-size:13px;color:#888;line-height:1.7;margin:0;">
      如果有任何問題，直接回覆這封信即可。<br>
      明天早上 7 點見！💪
    </p>
  </div>

  <div style="background:#1a1a2e;padding:16px 28px;text-align:center;font-size:11px;color:rgba(255,255,255,0.3);line-height:2;">
    財經日報 · AI 精選 · 假訊息過濾<br>
    本報告為 AI 生成，僅供參考，不構成投資建議
  </div>
</div>
</body>
</html>`;

  await fetch("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      sender: { name: "財經日報", email: "delvin.12345678@gmail.com" },
      to: [{ email }],
      subject,
      htmlContent: html,
    }),
  });
}
