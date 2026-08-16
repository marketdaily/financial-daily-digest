// MarketDaily 日報寄出守望犬(digest-watchdog)v3 — 外部 dead-man 監看(雙層)
//
// 2026-07-20 v2 重寫(Mac 晨間 session):v1 綁死 GitHub Actions(帳號被 flag 後全瞎,
// 6/30 停用 crons)。期間監看由 winrig heartbeat.sh 負責,但 7/18 晚 winrig 整台斷電
// → 監看與日報一起死,7/20 早報沒寄、41 小時零告警(本次事故)。
// v2 = 查「公版日報存檔在 marketdaily.ai 上的新鮮度」,不依賴 GitHub、不依賴 winrig。
// v3 = 同日主視窗 session 合併:再加 winrig 反向心跳層(heartbeat.sh 每 10 分 POST /hb,
// 這裡每 20 分驗新鮮度,>45 分 → 推播),主機一死 45 分內就知道,不用等到下一班日報。
//
// 兩層分工:心跳=「主機還活著嗎」(快,45min);存檔=「日報真的出來了嗎」(準,班次時刻)。
// 與 winrig heartbeat.sh 並存(那邊看 log 細節,這邊看死人開關)。
//
// 檢查點(TW 時間):早報 07:30 + 08:00;晚報 20:25 + 21:00;心跳 */20。
// 存檔缺席 → web push admin(KV 防重:每班每檢最多推一次);第二檢仍缺 → 🔴 判定需人工看主機。
// 無法自動補救(runner 在 winrig,Actions 已死)——這隻只負責「絕不靜默」。

const SITE = "https://marketdaily.ai";
const ALERT_WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev";

const CRON_TW_1 = "30 23 * * *";
const CRON_TW_2 = "0 0 * * *";
const CRON_US_1 = "25 12 * * *";
const CRON_US_2 = "0 13 * * *";
const CRON_HB = "*/20 * * * *";
const HB_STALE_MIN = 45;
const HB_REALERT_MS = 6 * 3600 * 1000; // 持續離線時每 6h 再提醒一次

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

// ── 交付訊號的第二軌:git origin(2026-08-16 補)──
// 權威判準是「網站 OR origin」(main._archive_delivered();公版存檔是**寄完才推**的,
// 所以它出現在 origin 上就證明信已經寄了)。這隻守望犬從 v2 起只查網站那半軌 ⇒
// 「寄出去了、但部署腿壞掉」會被它讀成「日報沒寄」:推 🔴 假警報 + 誤派雲端備援。
// 08-11 wrangler 憑證死、08-13 起 Actions 也被停用 ⇒ 部署腿歸零而寄信仍正常,
// 這個誤判從明天早上開始會天天發生。CLAUDE.md 早就寫了「交付訊號要含 push 即可見的
// origin 軌」,補的是 winrig 與雲端兩側,唯獨守望犬沒補到。
// 三態:true=在 / false=不在 / null=問不到(問不到絕不當成「不在」)。
async function originHasArchive(env, shift, date) {
  const name = shift === "tw" ? `digest_${date}.html` : `digest_${date}_us.html`;
  try {
    const r = await fetch(
      `https://api.github.com/repos/marketdaily/financial-daily-digest/contents/docs/output/${name}?ref=main`,
      {
        headers: {
          "authorization": "Bearer " + env.GITHUB_TOKEN,
          "accept": "application/vnd.github+json",
          "user-agent": "md-digest-watchdog/1.0",
        },
      });
    if (r.status === 200) return true;
    if (r.status === 404) return false;
    return null;                       // 401/403/5xx ⇒ 問不到,不是「不在」
  } catch (e) {
    return null;
  }
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

// timing-safe token 比對(feedback_shared_secret_grep 鐵則)
function tsEqual(a, b) {
  const ea = new TextEncoder().encode(String(a)), eb = new TextEncoder().encode(String(b));
  if (ea.length !== eb.length) return false;
  let d = 0;
  for (let i = 0; i < ea.length; i++) d |= ea[i] ^ eb[i];
  return d === 0;
}

function authed(request, env) {
  const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  return !!env.ALERT_TOKEN && tsEqual(got, env.ALERT_TOKEN);
}

// ── 層1:winrig 反向心跳(2026-07-20 斷電 41h 事故) ──
async function checkHeartbeat(env, now = Date.now()) {
  const raw = await env.USER_PREFS.get("watchdog:hb:winrig");
  const last = Number(raw || 0);
  const ageMin = raw ? Math.round((now - last) / 60000) : null;
  const stale = !raw || ageMin > HB_STALE_MIN;
  const stRaw = await env.USER_PREFS.get("watchdog:hb_state");
  let st = { stale: false, lastAlert: 0 };
  try { if (stRaw) st = JSON.parse(stRaw); } catch (e) { /* 壞狀態當 fresh 起算 */ }
  const putState = (s) => env.USER_PREFS.put("watchdog:hb_state", JSON.stringify(s));
  const twStr = raw ? new Date(last + 8 * 3600 * 1000).toISOString().slice(5, 16).replace("T", " ") : "從未收到";

  if (stale && (!st.stale || now - st.lastAlert > HB_REALERT_MS)) {
    await push(env, `🔴 winrig 離線:心跳${raw ? `已 ${ageMin} 分鐘未更新(最後 ${twStr} TW)` : "從未收到"}。日報與所有 cron 全部停擺——請確認主機電源/網路。恢復後會自動回報。`);
    await putState({ stale: true, lastAlert: now });
    return { stale, ageMin, alerted: true };
  }
  if (!stale && st.stale) {
    await push(env, `🟢 winrig 心跳恢復(最後心跳 ${twStr} TW),cron 已續跑。留意離線期間 missed 的班次。`);
    await putState({ stale: false, lastAlert: 0 });
    return { stale, ageMin, recovered: true };
  }
  return { stale, ageMin };
}

// ── 層2:公版存檔新鮮度(v2 原封語意) ──
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
    // 記下「這班存檔今天確認上線過」→ 讓層3 能偵測它之後中途消失(2026-07-23 事故)
    await kvSet(env, `seen:${date}:${shift}`, "1");
    // 第一檢曾告警、第二檢補上了 → 回報解除
    if (phase === 2 && (await kvGet(env, `miss:${date}:${shift}:1`))) {
      await push(env, `✅ ${label} ${date}:存檔已補上,解除警報`);
    } else {
      console.log(`${shift} ${date} ok`);
    }
    return;
  }

  // 網站上沒有 ≠ 沒寄。先問第二軌:origin 有沒有這份存檔(寄完才推)。
  // 有 ⇒ 信已經送出去了,壞的是**部署**,不是投遞 ⇒ 絕不推「可能沒寄」、更不准派備援
  //      (派了只是白燒一輪雲端生成,而且是在已交付之後)。
  const inOrigin = await originHasArchive(env, shift, date);
  if (inOrigin === true) {
    const deployKey = `deployfail:${date}:${shift}`;
    if (!(await kvGet(env, deployKey))) {
      await kvSet(env, deployKey, "1");
      await push(env, `🟡 ${label} ${date}:信**已經寄出**(存檔已在 git origin),但公版存檔沒上線 → ` +
        `marketdaily.ai 上該日報 404、信裡「網頁版」連結是壞的。壞的是部署腿不是投遞;` +
        `查 credential_watch(wrangler 憑證 / GitHub Actions 備援腿)。不派雲端備援。`);
    }
    return;
  }

  const dedupeKey = `miss:${date}:${shift}:${phase}`;
  if (await kvGet(env, dedupeKey)) return;
  await kvSet(env, dedupeKey, "1");

  // inOrigin === null ⇒ 第二軌問不到(GitHub 掛了/token 壞了)。此時只有網站那半軌,
  // 判斷力比平常弱 ⇒ 照原本流程告警(缺信是死線,寧可吵),但把「我只看得到一半」講出來,
  // 免得收到的人以為兩軌都確認過了。
  const halfBlind = inOrigin === null ? "(⚠️ origin 那半軌問不到,本則只依據網站)" : "";

  if (phase === 1) {
    await push(env, `🟠 ${label} ${date}:公版存檔未出現(${shift === "tw" ? "07:30" : "20:25"} 檢)${halfBlind}。可能生成延遲,${shift === "tw" ? "08:00" : "21:00"} 第二檢確認。若今日休市可忽略`);
    // 2026-07-26 雲端備援:第一檢缺席即派發 GH Actions 接手(failover=1 帶防雙發閘:
    // 雲端起跑前再查一次存檔,winrig 遲交完成就退場)。第一檢就派=給雲端最大 runway
    // (tw 07:30→死線 08:40;us 20:25→21:10)。dedupe 每班每天最多派一次。
    await dispatchFailover(env, shift, date, label);
  } else {
    await push(env, `🔴 ${label} ${date}:第二檢仍無存檔(網站與 git origin 兩軌都沒有)${halfBlind} → 日報極可能沒寄!winrig 可能整台離線,雲端備援已於第一檢派發(這則還在=雲端也沒趕上,查 GitHub Actions run),需人工`);
  }
}

// ── 雲端備援派發(2026-07-26,GitHub 帳號解封後 Actions 復活):winrig 缺席 → 派
// daily_digest.yml(failover=1)。workflow 內建防雙發閘;此處 KV dedupe 防重複派發。──
async function dispatchFailover(env, shift, date, label) {
  const k = `fo:${date}:${shift}`;
  if (await kvGet(env, k)) return;
  await kvSet(env, k, "1");
  try {
    const r = await fetch(
      "https://api.github.com/repos/marketdaily/financial-daily-digest/actions/workflows/daily_digest.yml/dispatches",
      {
        method: "POST",
        headers: {
          "authorization": "Bearer " + env.GITHUB_TOKEN,
          "accept": "application/vnd.github+json",
          "user-agent": "md-digest-watchdog/1.0",
          "content-type": "application/json",
        },
        body: JSON.stringify({ ref: "main", inputs: { market: shift, failover: "1" } }),
      });
    if (r.status === 204) {
      await push(env, `☁️ ${label} ${date}:雲端備援已派發(GitHub Actions 接手生成寄送,防雙發閘已帶)。`);
    } else {
      await push(env, `🔴 ${label} ${date}:雲端備援派發失敗(GitHub API ${r.status}),需人工補救`);
    }
  } catch (e) {
    await push(env, `🔴 ${label} ${date}:雲端備援派發異常(${String(e.message || e).slice(0, 80)}),需人工補救`);
  }
}

// ── 層3:已上線存檔中途消失偵測(2026-07-23 事故:git rebase 卡死→未推的當日存檔 commit
// 被 `git checkout -B main origin/main` 復原時丟掉→存檔在 07:30/08:00 檢查【之後】才 404,
// 落在班次窗外整天零告警,Delvin 親手抓到)。語義:只有「今天這班曾確認上線(seen)」後才管,
// 之後任一 */20 心跳跳發現它不見了 → 告警一次(dedupe 每班每天一次)。查詢失敗不誤報。──
async function checkArchivePersistence(env, now = new Date()) {
  const date = twDate(now);
  for (const shift of ["tw", "us"]) {
    if (shiftSkipped(shift, now)) continue;
    if (!(await kvGet(env, `seen:${date}:${shift}`))) continue;   // 還沒確認上線過→班次檢查在管,這層不插手
    const vanishKey = `vanished:${date}:${shift}`;
    if (await kvGet(env, vanishKey)) continue;                    // 今天這班已告警過
    let stillThere;
    try { stillThere = await archiveExists(shift, date); }
    catch (e) { continue; }                                       // 查詢失敗→不誤報,下一跳再試
    const pendingKey = `vanish_pending:${date}:${shift}`;
    if (stillThere) {                                             // 存檔在→清掛號(單輪抖動自癒)
      await env.USER_PREFS.delete(`watchdog:${pendingKey}`).catch(() => {});
      continue;
    }
    // debounce(2026-07-29 假警報:Pages 全站 deploy 傳播窗口會讓存檔 404 數分鐘):
    // 第一輪先掛號,下一輪 */20 還缺才告警——真事故(git 丟 commit)不會自己回來,只晚 20 分。
    if (!(await kvGet(env, pendingKey))) {
      await kvSet(env, pendingKey, "1");
      continue;
    }
    await kvSet(env, vanishKey, "1");
    const label = shift === "tw" ? "早報" : "晚報";
    await push(env, `🔴 ${label} ${date}:公版存檔【曾上線後又消失】(連兩輪確認,非部署傳播抖動;git 復原丟掉未推的存檔 commit,或誤部署覆蓋)→ marketdaily.ai 上該日報現在 404,信裡網頁版連結壞掉,需人工補存檔+部署`);
  }
}

export default {
  async scheduled(event, env, ctx) {
    const job = {
      [CRON_TW_1]: () => checkShift(env, "tw", 1),
      [CRON_TW_2]: () => checkShift(env, "tw", 2),
      [CRON_US_1]: () => checkShift(env, "us", 1),
      [CRON_US_2]: () => checkShift(env, "us", 2),
      // 心跳跳同時做:①winrig 死人開關 ②已上線存檔中途消失偵測(層3)
      [CRON_HB]: () => Promise.all([checkHeartbeat(env), checkArchivePersistence(env)]),
    }[event.cron];
    if (job) ctx.waitUntil(job());
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    // winrig 反向心跳:heartbeat.sh 每 10 分打一次
    if (url.pathname === "/hb" && request.method === "POST") {
      if (!authed(request, env)) return new Response("forbidden", { status: 403 });
      await env.USER_PREFS.put("watchdog:hb:winrig", String(Date.now()), { expirationTtl: 604800 });
      return new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } });
    }
    // 手動觸發一次心跳檢查(部署驗證/演練用,與 cron 同一條邏輯)
    if (url.pathname === "/check-hb" && request.method === "POST") {
      if (!authed(request, env)) return new Response("forbidden", { status: 403 });
      const r = await checkHeartbeat(env);
      return new Response(JSON.stringify(r), { headers: { "content-type": "application/json" } });
    }

    if (url.pathname === "/test-line" && request.method === "POST") {
      // 驗證 worker→alert-worker push 通道(需 ALERT_TOKEN bearer;只推固定測試訊息給 admin)
      if (!authed(request, env)) return new Response("forbidden", { status: 403 });
      try {
        const r = await env.ALERT.fetch(`${ALERT_WORKER}/internal/admin-line-push`, {
          method: "POST",
          headers: { "content-type": "application/json", "authorization": "Bearer " + env.ALERT_TOKEN },
          body: JSON.stringify({ message: "🐕 [watchdog] push 通道測試 OK — v3 dead-man 監看已上線(心跳 */20 + 早報 07:30/08:00、晚報 20:25/21:00 查公版存檔)" }),
        });
        return new Response(JSON.stringify({ ok: r.ok, status: r.status, body: await r.text() }), { headers: { "content-type": "application/json" } });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: String(e.message || e) }), { status: 500, headers: { "content-type": "application/json" } });
      }
    }
    if (url.pathname === "/status") {
      // 唯讀:回當天兩班存檔新鮮度 + winrig 心跳年齡,診斷用
      // ?date=YYYY-MM-DD:對任一天問兩軌(唯讀診斷)。存在的理由不是方便——
      // 沒有它,「origin 那軌查得到既有存檔」這條路只能等某天早上從告警文字反推,
      // 等於把一條生產判斷路徑長期停在「只驗過失敗那半」。格式不合一律忽略。
      const qd = url.searchParams.get("date");
      const date = /^\d{4}-\d{2}-\d{2}$/.test(qd || "") ? qd : twDate();
      const out = { date };
      for (const shift of ["tw", "us"]) {
        try {
          // 兩軌都揭露:光看 archived 分不出「沒寄」與「寄了但部署腿壞掉」,
          // 而那正是 checkShift 現在用來決定推不推紅、派不派備援的依據。
          // inOrigin=null ⇒ 第二軌問不到(GITHUB_TOKEN 沒權限/GitHub 掛了),
          // 這時守望犬只剩半隻眼睛 —— 要在診斷端看得見,不能等明天早上從告警文字反推。
          // 週末判斷要跟著**被查詢的那一天**走,不是跟著「現在」——查歷史日期時
          // 拿今天的星期幾去判,會對著一個交易日回 skipped:weekend(診斷說謊)。
          out[shift] = shiftSkipped(shift, new Date(`${date}T00:00:00Z`))
            ? { skipped: "weekend" }
            : {
                archived: await archiveExists(shift, date),
                inOrigin: await originHasArchive(env, shift, date),
                url: archiveUrl(shift, date),
              };
        } catch (e) { out[shift] = { error: e.message }; }
      }
      const raw = await env.USER_PREFS.get("watchdog:hb:winrig");
      const ageMin = raw ? Math.round((Date.now() - Number(raw)) / 60000) : null;
      const stRaw = await env.USER_PREFS.get("watchdog:hb_state");
      out.hb = { ageMin, stale: !raw || ageMin > HB_STALE_MIN, state: stRaw ? JSON.parse(stRaw) : null };
      // CORS:status.html(品質戰情室)跨網域直拉;唯讀無敏感資料
      return new Response(JSON.stringify(out, null, 2), { headers: { "content-type": "application/json", "access-control-allow-origin": "https://marketdaily.ai" } });
    }
    return new Response(JSON.stringify({
      ok: true, service: "marketdaily-digest-watchdog", mode: "dead-man v3(心跳+存檔新鮮度)",
      checks: "winrig 心跳 */20(>45分推播);TW 07:30/08:00 早報、20:25/21:00 晚報(查 marketdaily.ai 公版存檔)",
    }), { headers: { "content-type": "application/json" } });
  },
};

// 具名匯出只給自測用(Workers runtime 只讀 default export,多這幾個不影響部署)。
// 沒有這幾行,雙軌交付判斷就只能靠「部署上去等明天早上看」來驗——那不是驗證。
export { checkShift, originHasArchive, archiveExists, shiftSkipped, twDate };
