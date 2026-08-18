import fs from 'fs';
const src = fs.readFileSync(new URL('../src/index.js', import.meta.url),'utf8');
// 抽出被測函式本人(不重刻一份)
const m = src.match(/const ADMIN_EVENT_KEEP = [\s\S]*?\n}\n/);
if(!m) { console.error('FAIL: 抽不出 pruneAdminEvents'); process.exit(1); }
const { pruneAdminEvents, ADMIN_EVENT_KEEP } = await import('data:text/javascript,'+encodeURIComponent(m[0]+'\nexport {pruneAdminEvents, ADMIN_EVENT_KEEP};'));

let fail=0;
const ok=(c,msg)=>{ console.log((c?'✅':'❌')+' '+msg); if(!c) fail++; };

// [1] 真實 200 筆:全部在預算內 → 一筆都不該掉
const real = JSON.parse(fs.readFileSync(new URL('./fixtures/admin_events_snapshot.json', import.meta.url),'utf8'));
const realOut = pruneAdminEvents(real);
const realAlerts = real.filter(e=>!e.info).length, outAlerts = realOut.filter(e=>!e.info).length;
ok(outAlerts === realAlerts, `真實資料:${realAlerts} 則真告警一則不掉 (得 ${outAlerts})`);
ok(realOut.filter(e=>e.info).length === ADMIN_EVENT_KEEP.info,
   `真實資料:${real.filter(e=>e.info).length} 則資訊型收斂到 ${ADMIN_EVENT_KEEP.info}(首次寫入會丟掉最舊的 ${real.filter(e=>e.info).length-ADMIN_EVENT_KEEP.info} 則自動歸檔通知,刻意)`);
ok(JSON.stringify(realOut) === JSON.stringify(realOut.slice().sort((a,b)=>b.ts-a.ts)), '真實資料:輸出仍為新→舊');

// [2] 依實測流量模擬 30 天 (75 真告警/日 + 60 資訊/日),比較新舊行為
function simulate(days, prune){
  let list=[]; const DAY=86400000; const t0=Date.now()-days*DAY;
  for(let d=0; d<days; d++){
    const evs=[];
    for(let i=0;i<75;i++) evs.push({ts:t0+d*DAY+i*60000, body:'alert', pushed:true});
    for(let i=0;i<60;i++) evs.push({ts:t0+d*DAY+i*60000+30000, body:'info', info:true, resolved:t0+d*DAY});
    evs.sort((a,b)=>a.ts-b.ts);
    for(const e of evs){ list.unshift(e); list=prune(list); }
  }
  return list;
}
const oldPrune = l => l.slice(0,200);
const oldList = simulate(30, oldPrune);
const newList = simulate(30, pruneAdminEvents);
const span = l => { const a=l.filter(e=>!e.info); return a.length? (a[0].ts-a[a.length-1].ts)/3600000 : 0; };
console.log(`   舊行為: 共 ${oldList.length} 則, 真告警 ${oldList.filter(e=>!e.info).length} 則, 回溯 ${span(oldList).toFixed(1)}h`);
console.log(`   新行為: 共 ${newList.length} 則, 真告警 ${newList.filter(e=>!e.info).length} 則, 回溯 ${span(newList).toFixed(1)}h`);
ok(span(newList) > span(oldList)*3, `真告警回溯時距至少變 3 倍 (${span(oldList).toFixed(1)}h → ${span(newList).toFixed(1)}h)`);
ok(newList.filter(e=>!e.info).length === ADMIN_EVENT_KEEP.open, `未解決艙裝滿 ${ADMIN_EVENT_KEEP.open}`);
ok(newList.filter(e=>e.info).length === ADMIN_EVENT_KEEP.info, `資訊艙上限 ${ADMIN_EVENT_KEEP.info}`);

// [3] 反對照(這是重點):資訊型再怎麼灌,都不准擠掉任何一則未解決真告警
const alerts = Array.from({length:10},(_,i)=>({ts:1000-i, body:'真告警'+i}));
let flooded = alerts.slice();
for(let i=0;i<5000;i++){ flooded.unshift({ts:2000+i, body:'洪水', info:true, resolved:1}); flooded=pruneAdminEvents(flooded); }
ok(flooded.filter(e=>!e.info).length === 10, `5000 則資訊洪水後真告警仍全在 (得 ${flooded.filter(e=>!e.info).length}/10)`);
// 同樣的洪水在舊行為下會全滅 —— 證明這個測試不是恆真
let floodedOld = alerts.slice();
for(let i=0;i<5000;i++){ floodedOld.unshift({ts:2000+i, info:true, resolved:1}); floodedOld=oldPrune(floodedOld); }
ok(floodedOld.filter(e=>!e.info).length === 0, `反對照:同一波洪水在舊行為下真告警全滅 (得 ${floodedOld.filter(e=>!e.info).length}/10)`);

// [4] 已解決的告警換艙,不再占未解決預算
const solved = Array.from({length:ADMIN_EVENT_KEEP.open+50},(_,i)=>({ts:9000-i, resolved:1, body:'已解決'}));
const r4 = pruneAdminEvents(solved);
ok(r4.length === ADMIN_EVENT_KEEP.solved, `全已解決時只留 solved 預算 ${ADMIN_EVENT_KEEP.solved} (得 ${r4.length})`);

// [5] 髒資料不炸
let crashed=false;
try { pruneAdminEvents([null, undefined, {}, {info:true}, {resolved:0}]); } catch(e){ crashed=true; }
ok(!crashed, 'null/空物件不拋例外');

// [6] 不改動入參
const inp=[{ts:1},{ts:2}]; const cp=JSON.stringify(inp); pruneAdminEvents(inp);
ok(JSON.stringify(inp)===cp, 'prune 不改動入參');

// [7] 保留順序 = 由新到舊
const ordered=[{ts:3},{ts:2},{ts:1}];
ok(JSON.stringify(pruneAdminEvents(ordered))===JSON.stringify(ordered), '順序不變(新→舊)');

console.log(fail? `\n${fail} 項失敗`:'\n全部通過');
process.exit(fail?1:0);
