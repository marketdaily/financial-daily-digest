import fs from 'fs';
const src = fs.readFileSync(new URL('../src/index.js', import.meta.url),'utf8');
function grab(re,name){ const m=src.match(re); if(!m){ console.error('抽不出 '+name); process.exit(1);} return m[0]; }
const parts = [
  grab(/const ADMIN_INFO_KEYWORDS = \[[\s\S]*?\n\];/,'ADMIN_INFO_KEYWORDS'),
  grab(/function isInfoAdminEvent\([\s\S]*?\n}\n/,'isInfoAdminEvent'),
  grab(/const ADMIN_EVENT_KEEP = [\s\S]*?\nfunction pruneAdminEvents\([\s\S]*?\n}\n/,'prune'),
  grab(/async function recordAdminEvent\([\s\S]*?\n}\n/,'recordAdminEvent'),
].join('\n');
const mod = await import('data:text/javascript,'+encodeURIComponent(parts+'\nexport {recordAdminEvent, ADMIN_EVENT_INFO_BODY_MAX, ADMIN_EVENT_KEEP};'));
const { recordAdminEvent, ADMIN_EVENT_INFO_BODY_MAX, ADMIN_EVENT_KEEP } = mod;

let fail=0; const ok=(c,m)=>{ console.log((c?'✅':'❌')+' '+m); if(!c) fail++; };
function fakeEnv(){ let store=null, ttl=null;
  return { USER_PREFS:{ async get(){return store;}, async put(k,v,o){store=v; ttl=o&&o.expirationTtl;} },
           read(){return store?JSON.parse(store):[];}, ttl(){return ttl;} }; }

// [A] 資訊型:body 被截到 400,且標成自動歸檔
let env = fakeEnv();
const longInfo = '還沒收乾 '.repeat(500);
await recordAdminEvent(env,'{"title":"🔔 MarketDaily"}',true,longInfo,1000);
let rec = env.read()[0];
ok(rec.info===true && !!rec.resolved, '資訊型自動標已解決');
ok(rec.body.length === ADMIN_EVENT_INFO_BODY_MAX, `資訊型 body 截到 ${ADMIN_EVENT_INFO_BODY_MAX} (得 ${rec.body.length})`);

// [B] 反對照:真告警的 body 不被截到 400(仍可到 2000)
env = fakeEnv();
const longAlert = 'x'.repeat(5000);
await recordAdminEvent(env,'{"title":"🔴 出事了"}',true,longAlert,1000);
rec = env.read()[0];
ok(!rec.info, '真告警不被誤判為資訊型');
ok(rec.body.length === 2000, `真告警 body 保留到 2000 (得 ${rec.body.length})`);

// [C] 端到端:資訊洪水灌爆,先寫進去的真告警還在(這是本次修的正題)
env = fakeEnv();
await recordAdminEvent(env,'{"title":"🔴 早該被看到的告警"}',true,'council 出事:掉備援 2',1);
for(let i=0;i<300;i++) await recordAdminEvent(env,'{"title":"🔔"}',true,'還沒收乾 的 N 項 '+i, 100+i);
const list = env.read();
ok(list.some(e=>!e.info && e.body.includes('掉備援')), '300 則資訊洪水後,那則真告警仍在後台看得到');
ok(list.filter(e=>e.info).length === ADMIN_EVENT_KEEP.info, `資訊型收斂在 ${ADMIN_EVENT_KEEP.info}`);
ok(env.ttl() === 90*24*3600, 'TTL 仍為 90 天');

// [D] 壞掉的既有 KV 值不炸(拿不到 list 也要能寫)
env = { USER_PREFS:{ async get(){return '{壞掉的 json';}, async put(k,v){this._v=v;} } };
await recordAdminEvent(env,'{"title":"t"}',true,'body',1);
ok(Array.isArray(JSON.parse(env.USER_PREFS._v)) && JSON.parse(env.USER_PREFS._v).length===1, '既有 KV 值壞掉時仍寫得進去');

console.log(fail?`\n${fail} 項失敗`:'\n全部通過'); process.exit(fail?1:0);
