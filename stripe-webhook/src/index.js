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
