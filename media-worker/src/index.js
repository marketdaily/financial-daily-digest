const TYPES = { mp4: "video/mp4", jpg: "image/jpeg", png: "image/png", mp3: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav" };

const CORS = { "access-control-allow-origin": "*", "access-control-allow-methods": "GET, HEAD" };

// 允許被列出的 prefix 白名單(fail-closed:不在清單內一律拒絕,防止任意列舉整個 KV namespace)
// 只列進實際有呼叫端在用的 prefix——reel_ 目前沒有任何呼叫端需要列表,不預先開放
const LISTABLE_PREFIXES = ["audio_"];
const LIST_CURSOR_CAP = 20; // 安全上限(每頁最多 1000 筆 × 20 = 2 萬筆,遠超實際量級,防止異常狀態下無限迴圈

async function listAllKeys(env, prefix) {
  let names = [];
  let cursor;
  for (let i = 0; i < LIST_CURSOR_CAP; i++) {
    const page = await env.MEDIA.list({ prefix, cursor });
    names = names.concat(page.keys.map(k => k.name));
    if (page.list_complete) break;
    cursor = page.cursor;
  }
  return names;
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405, headers: CORS });
    }
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/_list") {
      const prefix = url.searchParams.get("prefix") || "";
      if (!LISTABLE_PREFIXES.includes(prefix)) {
        return new Response(JSON.stringify({ error: "invalid prefix" }), {
          status: 400, headers: { "content-type": "application/json", ...CORS },
        });
      }
      const names = await listAllKeys(env, prefix);
      return new Response(JSON.stringify({ keys: names }), {
        headers: { "content-type": "application/json", "cache-control": "public, max-age=60", ...CORS },
      });
    }
    const key = decodeURIComponent(url.pathname.replace(/^\/+/, ""));
    if (!key || key.includes("..")) return new Response("not found", { status: 404, headers: CORS });
    const obj = await env.MEDIA.get(key, { type: "arrayBuffer" });
    if (!obj) return new Response("not found", { status: 404, headers: CORS });
    const ext = key.split(".").pop().toLowerCase();
    return new Response(request.method === "HEAD" ? null : obj, {
      headers: {
        "content-type": TYPES[ext] || "application/octet-stream",
        "content-length": String(obj.byteLength),
        "cache-control": "public, max-age=86400",
        "accept-ranges": "bytes",
        ...CORS,
      },
    });
  },
};
