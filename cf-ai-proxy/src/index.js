// md-ai-proxy: 讓 winrig 日報管線用 Bearer token 打 Workers AI(免費層 10k neurons/日)。
// fail-closed:沒帶對 token 一律 403;model 白名單防被當免費算力濫用。
// 2026-07-30 擴充:Google 已封死「新 GCP 專案=新免費 Gemini 桶」(新 key 實測 limit:0、
// 2.5-flash 對新用戶 404)→ 免費產能改從 CF 這桶取。同帳號同免費層,但模型世代整代提升。
const ALLOWED = [
  "@cf/openai/gpt-oss-120b",
  "@cf/moonshotai/kimi-k2.6",
  "@cf/zai-org/glm-4.7-flash",
  "@cf/google/gemma-4-26b-a4b-it",
  "@cf/nvidia/nemotron-3-120b-a12b",
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/meta/llama-3.1-8b-instruct-fast",
  "@cf/qwen/qwq-32b",
];

// Workers AI 各模型世代回傳形狀不同:舊 llama 走 {response},gpt-oss/kimi 走 Responses API
// 的 {output:[{type:"message",content:[{text}]}]},部分走 OpenAI chat 的 {choices}。
// reasoning 型模型的 output 陣列前面幾項是 reasoning,只取 message/output_text 的文字。
function extractText(out) {
  if (typeof out?.response === "string" && out.response.trim()) return out.response;
  const chat = out?.choices?.[0]?.message?.content;
  if (typeof chat === "string" && chat.trim()) return chat;
  if (Array.isArray(out?.output)) {
    const parts = [];
    for (const item of out.output) {
      if (item?.type === "reasoning") continue;
      for (const c of item?.content || []) {
        if (typeof c?.text === "string") parts.push(c.text);
      }
    }
    const joined = parts.join("").trim();
    if (joined) return joined;
  }
  if (typeof out?.result === "string" && out.result.trim()) return out.result;
  return "";
}

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
    const text = extractText(out);
    // 萃取不到文字時附回原始形狀(僅此情形,且已過 token 驗證):新模型上架換形狀時
    // 呼叫端 log 直接看得到,不用再回頭猜(2026-07-30 五模型靜默空字串事故)。
    if (!text) return Response.json({ model, response: "", raw: out });
    return Response.json({ model, response: text });
  },
};
