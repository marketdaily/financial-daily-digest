const TYPES = { mp4: "video/mp4", jpg: "image/jpeg", png: "image/png", mp3: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav" };

const CORS = { "access-control-allow-origin": "*", "access-control-allow-methods": "GET, HEAD" };

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405, headers: CORS });
    }
    const key = decodeURIComponent(new URL(request.url).pathname.replace(/^\/+/, ""));
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
