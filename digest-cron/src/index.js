// MarketDaily 日報雲端排程觸發器(雙班次)
//
// Cloudflare Cron Triggers:
//   "55 22 * * *" UTC = 台灣 06:55 → market=tw 台股早報(台股 09:00 開盤前)
//   "0 12 * * *"  UTC = 台灣 20:00 → market=us 美股晚報(美股 21:30-22:30 開盤前)
// 派發 daily_digest.yml workflow(帶 inputs.market),由 GitHub Actions 跑 main.py 寄送。
// 全程在雲端,不依賴本機 Mac。觸發結果見 Cloudflare 的 Worker log(wrangler tail)。
//
// Secret:GITHUB_TOKEN — fine-grained PAT,對本 repo 有 Actions: Read and write。

const REPO = "marketdaily/financial-daily-digest";
const WORKFLOW = "daily_digest.yml";
const BRANCH = "main";

const CRON_TW = "55 22 * * *";  // 台灣 06:55 台股早報
const CRON_US = "0 12 * * *";   // 台灣 20:00 美股晚報

function twDay(now = new Date()) {
  return new Date(now.getTime() + 8 * 3600 * 1000).getUTCDay();  // 0=日 1=一 ... 6=六
}

// 依觸發的 cron 決定班次市場;判斷是否該跳過(週末)。
// 回傳 { market, skip, reason }。
function resolveSchedule(cron, now = new Date()) {
  const d = twDay(now);
  if (cron === CRON_US) {
    // 美股晚報:台灣週六/週日晚上對應美股週末不開盤 → 跳過。US 週一~週五 = TW 週一~週五晚。
    if (d === 0 || d === 6) return { market: "us", skip: true, reason: "US weekend (TW Sat/Sun evening, no US session)" };
    return { market: "us", skip: false };
  }
  // 預設(含 CRON_TW):台股早報。週日台股休市跳過;週六走 weekend recap(照發)。
  if (d === 0) return { market: "tw", skip: true, reason: "Sunday TWT (TW market closed)" };
  return { market: "tw", skip: false };
}

export default {
  async scheduled(event, env, ctx) {
    const { market, skip, reason } = resolveSchedule(event.cron);
    if (skip) {
      console.log(`skip dispatch [cron=${event.cron} market=${market}]: ${reason}`);
      return;
    }
    console.log(`dispatch [cron=${event.cron} market=${market}]`);
    ctx.waitUntil(dispatch(env, market));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/check") {
      // 用儲存的 GITHUB_TOKEN 做一次唯讀呼叫,確認 token 有效且能存取 workflow。
      // 不會派發 workflow、不會寄信。
      if (!env.GITHUB_TOKEN) {
        return json({ token_present: false, token_ok: false, hint: "Worker 還沒設 GITHUB_TOKEN secret" });
      }
      const r = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}`,
        {
          headers: {
            "Authorization": "Bearer " + env.GITHUB_TOKEN,
            "Accept": "application/vnd.github+json",
            "User-Agent": "marketdaily-digest-cron",
          },
        }
      );
      let detail = null;
      try { const d = await r.json(); detail = d.state || d.message; } catch {}
      return json({
        token_present: true,
        github_status: r.status,
        token_ok: r.ok,
        workflow: detail,
      });
    }
    return json({
      ok: true,
      service: "marketdaily-digest-cron",
      crons: { tw: `${CRON_TW} (UTC) = 06:55 TW 台股早報`, us: `${CRON_US} (UTC) = 20:00 TW 美股晚報` },
    });
  },
};

async function dispatch(env, market = "tw") {
  let result;
  try {
    const r = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          "Authorization": "Bearer " + env.GITHUB_TOKEN,
          "Accept": "application/vnd.github+json",
          "User-Agent": "marketdaily-digest-cron",
          "X-GitHub-Api-Version": "2022-11-28",
          "content-type": "application/json",
        },
        body: JSON.stringify({ ref: BRANCH, inputs: { market } }),
      }
    );
    const text = await r.text();
    result = { ok: r.ok, status: r.status, market, error: r.ok ? null : text };
  } catch (e) {
    result = { ok: false, status: 0, market, error: String(e.message || e) };
  }
  console.log("digest dispatch:", JSON.stringify({ ...result, at: new Date().toISOString() }));
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}
