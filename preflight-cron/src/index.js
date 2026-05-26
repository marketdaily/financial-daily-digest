// MarketDaily 日報 Pre-Flight 預檢觸發器
//
// 主寄送 cron 在 22:55 UTC(TW 06:55)觸發 GitHub Actions 寄信。
// 這個 preflight 提前 30 分鐘(22:25 UTC = TW 06:25)派發 digest_preview.yml,
// 跑完整 pipeline 但 --dry-run 不寄信。任何 HIGH audit fail 立刻 LINE 推 admin,
// admin 有 30 分鐘修 prompt + push 再讓主 cron 跑。
// 用戶絕不會看到品質有問題的日報。

const REPO = "marketdaily/financial-daily-digest";
const WORKFLOW = "digest_preview.yml";
const BRANCH = "main";

function isSundayTW(now = new Date()) {
  const twDay = new Date(now.getTime() + 8 * 3600 * 1000).getUTCDay();
  return twDay === 0;
}

export default {
  async scheduled(event, env, ctx) {
    if (isSundayTW()) {
      console.log("skip preflight: Sunday TWT (weekend mode)");
      return;
    }
    ctx.waitUntil(dispatch(env));
  },

  async fetch(request) {
    return json({ ok: true, service: "marketdaily-preflight-cron", cron: "25 22 * * * (UTC)" });
  },
};

async function dispatch(env) {
  let result;
  try {
    const r = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          "Authorization": "Bearer " + env.GITHUB_TOKEN,
          "Accept": "application/vnd.github+json",
          "User-Agent": "marketdaily-preflight-cron",
          "X-GitHub-Api-Version": "2022-11-28",
          "content-type": "application/json",
        },
        body: JSON.stringify({ ref: BRANCH }),
      }
    );
    const text = await r.text();
    result = { ok: r.ok, status: r.status, error: r.ok ? null : text };
  } catch (e) {
    result = { ok: false, status: 0, error: String(e.message || e) };
  }
  console.log("preflight dispatch:", JSON.stringify({ ...result, at: new Date().toISOString() }));
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}
