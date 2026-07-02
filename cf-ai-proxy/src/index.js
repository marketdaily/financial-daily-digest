// md-ai-proxy: 讓 winrig 日報管線用 Bearer token 打 Workers AI(免費層 10k neurons/日)。
// fail-closed:沒帶對 token 一律 403;model 白名單防被當免費算力濫用。
const ALLOWED = [
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/meta/llama-3.1-8b-instruct-fast",
  "@cf/qwen/qwq-32b",
];

function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const ba = enc.encode(a), bb = enc.encode(b);
  if (ba.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < ba.length; i++) diff |= ba[i] ^ bb[i];
  return diff === 0;
}

export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("not found", { status: 404 });
    const auth = req.headers.get("authorization") || "";
    const expect = `Bearer ${env.AI_PROXY_TOKEN}`;
    if (!env.AI_PROXY_TOKEN || !timingSafeEqual(auth, expect))
      return new Response("forbidden", { status: 403 });
    let body;
    try { body = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
    const model = ALLOWED.includes(body.model) ? body.model : ALLOWED[0];
    const out = await env.AI.run(model, {
      messages: body.messages || [],
      max_tokens: Math.min(body.max_tokens || 1000, 8192),
      temperature: body.temperature ?? 0.4,
    });
    const text = typeof out.response === "string" ? out.response : JSON.stringify(out.response);
    return Response.json({ model, response: text });
  },
};
