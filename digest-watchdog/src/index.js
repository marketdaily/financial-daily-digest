// MarketDaily 日報寄出守望犬(digest-watchdog)v2 — 外部 dead-man 監看
//
// 2026-07-20 重寫:v1 綁死 GitHub Actions(帳號被 flag 後全瞎,6/30 停用 crons)。
// 期間監看由 winrig heartbeat.sh 負責,但 7/19 winrig 整台離線 → 監看與日報一起死,
// 7/20 早報沒寄、零告警(本次事故)。v2 = wrangler.toml 註解預留的修法:
// 只查「公版日報存檔在 marketdaily.ai 上的新鮮度」,不依賴 GitHub、不依賴 winrig,
// 專補 winrig 整台掛掉的盲區。與 winrig heartbeat.sh 並存(那邊看 log 細節,這邊看死人開關)。
//
// 檢查點(TW 時間):早報 07:30 + 08:00;晚報 20:25 + 21:00。
// 存檔缺席 → web push admin(KV 防重:每班每檢最多推一次);第二檢仍缺 → 🔴 判定需人工看主機。
// 無法自動補救(runner 在 winrig,Actions 已死)——這隻只負責「絕不靜默」。

const SITE = "https://marketdaily.ai";
const ALERT_WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev";

const CRON_TW_1 = "30 23 * * *";
const CRON_TW_2 = "0 0 * * *";
const CRON_US_1 = "25 12 * * *";
const CRON_US_2 = "0 13 * * *";

function twNow(now = new Date()) { return new Date(now.getTime() + 8 * 3600 * 1000); }
function twDay(now = new Date()) { return twNow(now).getUTCDay(); }
function twDate(now = new Date()) { return twNow(now).toISOString().slice(0, 10); }

function shiftSkipped(shift, now = new Date()) {
  const d = twDay(now);
  if (shift === "tw") return d === 0;            // 週日台股休市,早報本來就不派
  return d === 0 || d === 6;                      // 美股晚報:TW 週六/週日晚 skip
}

function archiveUrl(shift, date) {
  return shift === "tw"
    ? `${SITE}/output/digest_${date}.html`
    : `${SITE}/output/digest_${date}_us.html`;
}

async function archiveExists(shift, date) {
  // Pages 會 308 去掉 .html,follow 後以最終狀態為準;帶 query 避開 CDN 快取
  const r = await fetch(`${archiveUrl(shift, date)}?wd=${Date.now()}`, {
    method: "GET",
    redirect: "follow",
    headers: { "user-agent": "marketdaily-digest-watchdog" },
  });
  return r.ok;
}

async function push(env, message) {
  // 通道=自有 web push(路徑名沿用 line-push,LINE 已退役);
  // service binding(env.ALERT):workers.dev 同帳號互打會被 1042 擋,必須走 binding
  try {
    const r = await env.ALERT.fetch(`${ALERT_WORKER}/internal/admin-line-push`, {
      method: "POST",
      headers: { "content-type": "application/json", "authorization": "Bearer " + env.ALERT_TOKEN },
      body: JSON.stringify({ message: `🐕 [watchdog] ${message}` }),
    });
    if (!r.ok) console.log("push non-ok:", r.status, await r.text());
  } catch (e) {
    console.log("push failed:", e.message);
  }
}

async function kvGet(env, k) { return env.USER_PREFS.get(`watchdog:${k}`); }
async function kvSet(env, k, v) { return env.USER_PREFS.put(`watchdog:${k}`, v, { expirationTtl: 172800 }); }

async function checkShift(env, shift, phase, now = new Date()) {
  if (shiftSkipped(shift, now)) { console.log(`skip ${shift}(weekend)`); return; }
  const date = twDate(now);
  const label = shift === "tw" ? "早報" : "晚報";

  let exists;
  try {
    exists = await archiveExists(shift, date);
  } catch (e) {
    await push(env, `${label} ${date}:守望犬查存檔失敗(${e.message}),無法確認日報狀態`);
    return;
  }

  if (exists) {
    // 第一檢曾告警、第二檢補上了 → 回報解除
    if (phase === 2 && (await kvGet(env, `miss:${date}:${shift}:1`))) {
      await push(env, `✅ ${label} ${date}:存檔已補上,解除警報`);
    } else {
      console.log(`${shift} ${date} ok`);
    }
    return;
  }

  const dedupeKey = `miss:${date}:${shift}:${phase}`;
  if (await kvGet(env, dedupeKey)) return;
  await kvSet(env, dedupeKey, "1");

  if (phase === 1) {
    await push(env, `🟠 ${label} ${date}:公版存檔未出現(${shift === "tw" ? "07:30" : "20:25"} 檢)。可能生成延遲,${shift === "tw" ? "08:00" : "21:00"} 第二檢確認。若今日休市可忽略`);
  } else {
    await push(env, `🔴 ${label} ${date}:第二檢仍無存檔 → 日報極可能沒寄!winrig 可能整台離線(cron runner 在上面),請檢查主機電源/網路/WSL。守望犬無法代跑,需人工`);
  }
}

export default {
  async scheduled(event, env, ctx) {
    const job = {
      [CRON_TW_1]: () => checkShift(env, "tw", 1),
      [CRON_TW_2]: () => checkShift(env, "tw", 2),
      [CRON_US_1]: () => checkShift(env, "us", 1),
      [CRON_US_2]: () => checkShift(env, "us", 2),
    }[event.cron];
    if (job) ctx.waitUntil(job());
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/test-line" && request.method === "POST") {
      // 驗證 worker→alert-worker push 通道(需 ALERT_TOKEN bearer;只推固定測試訊息給 admin)
      const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
      if (!env.ALERT_TOKEN || got !== env.ALERT_TOKEN) return new Response("forbidden", { status: 403 });
      try {
        const r = await env.ALERT.fetch(`${ALERT_WORKER}/internal/admin-line-push`, {
          method: "POST",
          headers: { "content-type": "application/json", "authorization": "Bearer " + env.ALERT_TOKEN },
          body: JSON.stringify({ message: "🐕 [watchdog] push 通道測試 OK — v2 dead-man 監看已上線(早報 07:30/08:00、晚報 20:25/21:00 查公版存檔新鮮度)" }),
        });
        return new Response(JSON.stringify({ ok: r.ok, status: r.status, body: await r.text() }), { headers: { "content-type": "application/json" } });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: String(e.message || e) }), { status: 500, headers: { "content-type": "application/json" } });
      }
    }
    if (url.pathname === "/status") {
      // 唯讀:回當天兩班存檔新鮮度,診斷用
      const date = twDate();
      const out = { date };
      for (const shift of ["tw", "us"]) {
        try {
          out[shift] = shiftSkipped(shift)
            ? { skipped: "weekend" }
            : { archived: await archiveExists(shift, date), url: archiveUrl(shift, date) };
        } catch (e) { out[shift] = { error: e.message }; }
      }
      return new Response(JSON.stringify(out, null, 2), { headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({
      ok: true, service: "marketdaily-digest-watchdog", mode: "dead-man archive freshness v2",
      checks: "TW 07:30/08:00 早報、20:25/21:00 晚報(查 marketdaily.ai 公版存檔)",
    }), { headers: { "content-type": "application/json" } });
  },
};
