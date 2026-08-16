// digest-watchdog 自測(2026-08-16 建)。全離線:fetch / KV / push 全部注入假的。
//
// 為什麼現在才有:這隻守望犬是「絕不靜默」的最後一道防線,卻從上線起零測試——
// 驗證方式是「部署上去等明天早上看」。2026-08-16 補雙軌交付判斷時,這種驗法擋不住
// 任何回歸,所以連測試一起補。
//
// 守的行為(不是措辭):
//   ① 網站有存檔 → 安靜
//   ② 網站沒有、但 git origin 有 → 信已寄、壞的是部署 ⇒ 🟡 一則,**絕不派雲端備援**
//   ③ 兩軌都沒有 → 🟠 + 派備援(原本的死線語意不可被這次改動放寬)
//   ④ origin 那軌問不到(null)→ 仍照 ③ 告警,但要說出「只看得到一半」
//   ⑤ ② 的 🟡 每班每天只推一次
//
// 跑:node digest-watchdog/test_watchdog.mjs
import { checkShift, originHasArchive } from "./src/index.js";

let PASS = 0, FAIL = 0;
const chk = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { PASS++; }
  else { FAIL++; console.log(`  ✗ ${name}: 期望 ${w} 得到 ${g}`); }
};

// ── 假環境 ────────────────────────────────────────────────
function makeEnv({ site, origin }) {
  const kv = new Map();
  const pushes = [];
  const dispatched = [];
  const env = {
    ALERT_TOKEN: "t", GITHUB_TOKEN: "g",
    USER_PREFS: {
      get: async (k) => (kv.has(k) ? kv.get(k) : null),
      put: async (k, v) => void kv.set(k, v),
      delete: async (k) => void kv.delete(k),
    },
    // push 走 service binding env.ALERT.fetch
    ALERT: { fetch: async (_u, init) => { pushes.push(JSON.parse(init.body).message); return { ok: true, status: 200, text: async () => "" }; } },
  };
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u.includes("marketdaily.ai/output/")) {
      if (site === "throw") throw new Error("net down");
      return { ok: site === 200, status: site };
    }
    if (u.includes("api.github.com") && u.includes("/contents/")) {
      if (origin === "throw") throw new Error("gh down");
      return { status: origin };
    }
    if (u.includes("/dispatches")) { dispatched.push(u); return { status: 204 }; }
    throw new Error("未預期的 fetch: " + u);
  };
  return { env, pushes, dispatched, kv };
}

// 週一(非週末),避開 shiftSkipped
const MON = new Date("2026-08-17T00:00:00Z");   // TW 08-17 08:00 週一

console.log("== digest-watchdog 雙軌交付判斷 ==");

// ① 網站有 → 安靜、不派
{
  const { env, pushes, dispatched } = makeEnv({ site: 200, origin: 404 });
  await checkShift(env, "tw", 1, MON);
  chk("① 網站有存檔 → 不推播", pushes.length, 0);
  chk("① 網站有存檔 → 不派備援", dispatched.length, 0);
}

// ② 網站沒有、origin 有 → 🟡 一則、**不派**
{
  const { env, pushes, dispatched } = makeEnv({ site: 404, origin: 200 });
  await checkShift(env, "tw", 1, MON);
  chk("② 已寄但沒上線 → 推一則", pushes.length, 1);
  chk("② 訊息說「已經寄出」", /已經寄出/.test(pushes[0] || ""), true);
  chk("② 不推『可能沒寄』", /可能沒寄|極可能沒寄/.test(pushes[0] || ""), false);
  chk("② ⭐ 絕不派雲端備援(已交付後再派=白燒一輪且有雙發風險)", dispatched.length, 0);
}

// ③ 兩軌都沒有 → 🟠 + 派(原本的死線語意不可被放寬)
{
  const { env, pushes, dispatched } = makeEnv({ site: 404, origin: 404 });
  await checkShift(env, "tw", 1, MON);
  chk("③ 兩軌皆無 → 有推播", pushes.length >= 1, true);
  chk("③ ⭐ 兩軌皆無 → 仍要派備援", dispatched.length, 1);
  chk("③ 不誤貼『只看得到一半』", /只依據網站/.test(pushes[0] || ""), false);
}

// ④ origin 問不到(5xx / 例外)→ 仍照 ③ 走,但要自曝半盲
for (const [name, originVal] of [["5xx", 500], ["例外", "throw"]]) {
  const { env, pushes, dispatched } = makeEnv({ site: 404, origin: originVal });
  await checkShift(env, "tw", 1, MON);
  chk(`④ origin ${name} → 仍派備援(不因判不出來而沉默)`, dispatched.length, 1);
  chk(`④ origin ${name} → 訊息自曝只看得到一半`, /只依據網站/.test(pushes[0] || ""), true);
}

// ⑤ ② 的 🟡 每班每天只推一次(同一個 env/KV 連跑兩次)
{
  const { env, pushes } = makeEnv({ site: 404, origin: 200 });
  await checkShift(env, "tw", 1, MON);
  await checkShift(env, "tw", 2, MON);
  chk("⑤ 部署失敗只吵一次", pushes.length, 1);
}

// ⑥ 第二檢:兩軌皆無才可以說「極可能沒寄」
{
  const { env, pushes } = makeEnv({ site: 404, origin: 404 });
  await checkShift(env, "tw", 2, MON);
  chk("⑥ 第二檢兩軌皆無 → 🔴 極可能沒寄", /極可能沒寄/.test(pushes[0] || ""), true);
}

// ⑦ 週末 skip 沒被這次改動弄壞(TW 週日不派早報)
{
  const SUN = new Date("2026-08-16T00:00:00Z");   // TW 08-16 週日
  const { env, pushes, dispatched } = makeEnv({ site: 404, origin: 404 });
  await checkShift(env, "tw", 1, SUN);
  chk("⑦ 週日早報 skip:不推不派", [pushes.length, dispatched.length], [0, 0]);
}

// ⑧ originHasArchive 三態(問不到 ≠ 不在)
{
  const cases = [[200, true], [404, false], [500, null], [403, null], ["throw", null]];
  for (const [code, want] of cases) {
    const { env } = makeEnv({ site: 200, origin: code });
    chk(`⑧ origin ${code} → ${want}`, await originHasArchive(env, "tw", "2026-08-17"), want);
  }
}

// ⑨ 美股班用的是 _us 檔名(抓錯檔名 = 永遠判定沒交付)
{
  let seen = "";
  const { env } = makeEnv({ site: 200, origin: 200 });
  const real = globalThis.fetch;
  globalThis.fetch = async (u, i) => { if (String(u).includes("/contents/")) seen = String(u); return real(u, i); };
  await originHasArchive(env, "us", "2026-08-17");
  chk("⑨ 晚報查的是 _us 存檔", /digest_2026-08-17_us\.html/.test(seen), true);
}

console.log(`── digest-watchdog: ${PASS}✓ ${FAIL}✗`);
process.exit(FAIL ? 1 : 0);
