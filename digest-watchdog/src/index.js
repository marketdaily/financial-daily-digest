// MarketDaily 日報寄出守望犬(digest-watchdog)
//
// 解決的問題(2026-06-11 事故):日報 workflow 卡死/失敗時,沒人知道、信沒寄、用戶流失。
// 守望邏輯(全自動,不靠人醒著):
//   第一檢(整點+20分):查當班 daily_digest.yml run
//     - success → 安靜(若先前有重派過 → LINE 報「補寄成功」)
//     - failure/cancelled/timed_out → 自動重派一次 + LINE
//     - in_progress → LINE 預警(40 分後第二檢處理)
//     - 完全沒 run(cron 沒觸發) → 代派 + LINE
//   第二檢(整點+60分):還 in_progress = 卡死 → 砍掉 + 重派一次 + LINE;
//     新架構(outbox 整點寄)下,卡在生成 = 一封都沒寄,重派不會重複寄。
//   防重 guard:KV watchdog:* 每班最多自動重派一次,二次失敗 → LINE 報「需人工」。
//   07:50 TW 另派 site_scan.yml 全站掃描(失敗自動修復見該 workflow)。

const REPO = "marketdaily/financial-daily-digest";
const WF_DIGEST = "daily_digest.yml";
const WF_SCAN = "site_scan.yml";
const ALERT_WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev";

const CRON_TW_1 = "20 23 * * *";
const CRON_TW_2 = "0 0 * * *";
const CRON_US_1 = "20 12 * * *";
const CRON_US_2 = "0 13 * * *";
const CRON_SCAN = "50 23 * * *";

function twNow(now = new Date()) { return new Date(now.getTime() + 8 * 3600 * 1000); }
function twDay(now = new Date()) { return twNow(now).getUTCDay(); }
function twDate(now = new Date()) { return twNow(now).toISOString().slice(0, 10); }

// 班次 run 的建立時間窗(UTC):tw 班 22:00 起、us 班 11:00 起(含 watchdog 重派的 run)。
// 第二檢時 now 已跨 UTC 午夜(00:00),窗口起點要回推到前一 UTC 日 22:00。
function shiftWindowStart(shift, now = new Date()) {
  const d = new Date(now);
  if (shift === "tw") {
    if (d.getUTCHours() < 22) d.setUTCDate(d.getUTCDate() - 1);
    d.setUTCHours(22, 0, 0, 0);
  } else {
    d.setUTCHours(11, 0, 0, 0);
  }
  return d;
}

function shiftSkipped(shift, now = new Date()) {
  const d = twDay(now);
  if (shift === "tw") return d === 0;            // 週日台股休市,digest-cron 本來就不派
  return d === 0 || d === 6;                      // 美股晚報:TW 週六/週日晚 skip
}

async function gh(env, path, init = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      "Authorization": "Bearer " + env.GITHUB_TOKEN,
      "Accept": "application/vnd.github+json",
      "User-Agent": "marketdaily-digest-watchdog",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(init.headers || {}),
    },
  });
}

async function latestShiftRun(env, shift, now = new Date()) {
  const since = shiftWindowStart(shift, now).toISOString();
  const r = await gh(env, `/repos/${REPO}/actions/workflows/${WF_DIGEST}/runs?created=%3E%3D${encodeURIComponent(since)}&per_page=10`);
  if (!r.ok) throw new Error(`GitHub runs list ${r.status}`);
  const d = await r.json();
  const runs = (d.workflow_runs || []).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  return runs[0] || null;
}

async function dispatchDigest(env, market) {
  const r = await gh(env, `/repos/${REPO}/actions/workflows/${WF_DIGEST}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: "main", inputs: { market } }),
  });
  return r.ok;
}

async function cancelRun(env, runId) {
  const r = await gh(env, `/repos/${REPO}/actions/runs/${runId}/cancel`, { method: "POST" });
  return r.ok;
}

async function linePush(env, message) {
  // service binding(env.ALERT):workers.dev 同帳號互打會被 1042 擋,必須走 binding
  try {
    const r = await env.ALERT.fetch(`${ALERT_WORKER}/internal/admin-line-push`, {
      method: "POST",
      headers: { "content-type": "application/json", "authorization": "Bearer " + env.ALERT_TOKEN },
      body: JSON.stringify({ message: `🐕 [watchdog] ${message}` }),
    });
    if (!r.ok) console.log("line push non-ok:", r.status, await r.text());
  } catch (e) {
    console.log("line push failed:", e.message);
  }
}

async function kvGet(env, k) { return env.USER_PREFS.get(`watchdog:${k}`); }
async function kvSet(env, k, v) { return env.USER_PREFS.put(`watchdog:${k}`, v, { expirationTtl: 172800 }); }

async function checkShift(env, shift, phase, now = new Date()) {
  if (shiftSkipped(shift, now)) { console.log(`skip ${shift}(weekend)`); return; }
  const date = twDate(now);
  const label = shift === "tw" ? "早報" : "晚報";
  const retryKey = `retry:${date}:${shift}`;
  let run;
  try {
    run = await latestShiftRun(env, shift, now);
  } catch (e) {
    await linePush(env, `${label} ${date}:守望犬查 GitHub 失敗(${e.message}),無法確認日報狀態,請手動看 Actions`);
    return;
  }
  const retried = await kvGet(env, retryKey);

  if (!run) {
    // cron 根本沒觸發 → 代派(防重:每班只代派一次)
    if (await kvGet(env, `nodispatch:${date}:${shift}`)) {
      await linePush(env, `🔴 ${label} ${date}:代派後仍查無 run,需人工處理`);
      return;
    }
    await kvSet(env, `nodispatch:${date}:${shift}`, "1");
    const ok = await dispatchDigest(env, shift);
    await linePush(env, `🟠 ${label} ${date}:排程 cron 沒觸發!守望犬已代派(${ok ? "成功" : "失敗"})`);
    return;
  }

  if (run.status === "completed") {
    if (run.conclusion === "success") {
      if (retried) await linePush(env, `✅ ${label} ${date}:自動重派後補寄成功`);
      else console.log(`${shift} ok`);
      return;
    }
    // failure / cancelled / timed_out
    if (retried) {
      await linePush(env, `🔴 ${label} ${date}:重派後仍 ${run.conclusion},不再自動重試,需人工。run: ${run.html_url}`);
      return;
    }
    await kvSet(env, retryKey, "1");
    const ok = await dispatchDigest(env, shift);
    await linePush(env, `🟠 ${label} ${date}:run ${run.conclusion} → 已自動重派(${ok ? "成功" : "失敗"})。原 run: ${run.html_url}`);
    return;
  }

  // in_progress / queued
  if (phase === 1) {
    await linePush(env, `🟡 ${label} ${date}:整點已過 20 分仍在跑(生成卡慢?)。40 分後第二檢,還卡會自動砍掉重派。${run.html_url}`);
    return;
  }
  // phase 2:卡死 → 砍掉重派(outbox 架構下卡在生成 = 0 封已寄,重派安全)
  if (retried) {
    await linePush(env, `🔴 ${label} ${date}:重派後第二檢仍未完成,不再自動處理,需人工。${run.html_url}`);
    return;
  }
  await kvSet(env, retryKey, "1");
  const cancelled = await cancelRun(env, run.id);
  const ok = await dispatchDigest(env, shift);
  await linePush(env, `🟠 ${label} ${date}:整點+60分仍卡在跑 → 已砍掉(${cancelled ? "成功" : "失敗"})並重派(${ok ? "成功" : "失敗"})。約 35-40 分後寄出`);
}

async function dispatchScan(env, now = new Date()) {
  const r = await gh(env, `/repos/${REPO}/actions/workflows/${WF_SCAN}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: "main" }),
  });
  console.log(`site_scan dispatch: ${r.status}`);
  if (!r.ok) await linePush(env, `全站掃描派發失敗(HTTP ${r.status})`);
}

export default {
  async scheduled(event, env, ctx) {
    const job = {
      [CRON_TW_1]: () => checkShift(env, "tw", 1),
      [CRON_TW_2]: () => checkShift(env, "tw", 2),
      [CRON_US_1]: () => checkShift(env, "us", 1),
      [CRON_US_2]: () => checkShift(env, "us", 2),
      [CRON_SCAN]: () => dispatchScan(env),
    }[event.cron];
    if (job) ctx.waitUntil(job());
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/test-line" && request.method === "POST") {
      // 驗證 worker→alert-worker LINE 通道(需 ALERT_TOKEN bearer;只推固定測試訊息給 admin)
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
      if (!env.ALERT_TOKEN || got !== env.ALERT_TOKEN) return new Response("forbidden", { status: 403 });
      try {
        const r = await env.ALERT.fetch(`${ALERT_WORKER}/internal/admin-line-push`, {
          method: "POST",
          headers: { "content-type": "application/json", "authorization": "Bearer " + env.ALERT_TOKEN },
          body: JSON.stringify({ message: "🐕 [watchdog] LINE 通道測試 OK — 守望犬已上線(07:20/08:00 早報、20:20/21:00 晚報、07:50 全站掃描)" }),
        });
        return new Response(JSON.stringify({ ok: r.ok, status: r.status, body: await r.text() }), { headers: { "content-type": "application/json" } });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: String(e.message || e) }), { status: 500, headers: { "content-type": "application/json" } });
      }
    }
    if (url.pathname === "/status") {
      // 唯讀:回當天兩班 run 狀態,診斷用
      const out = {};
      for (const shift of ["tw", "us"]) {
        try {
          const run = await latestShiftRun(env, shift);
          out[shift] = run ? { status: run.status, conclusion: run.conclusion, created: run.created_at, url: run.html_url } : null;
        } catch (e) { out[shift] = { error: e.message }; }
      }
      return new Response(JSON.stringify(out, null, 2), { headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({
      ok: true, service: "marketdaily-digest-watchdog",
      checks: "07:20/08:00 TW 早報、20:20/21:00 TW 晚報、07:50 TW 全站掃描派發",
    }), { headers: { "content-type": "application/json" } });
  },
};
