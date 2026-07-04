"""掃描任務佇列,產生自帶資料的單一 HTML 戰情室 dashboard.html(stdlib only)。"""
import os
import json
import glob
import subprocess
from datetime import datetime, timezone, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "dashboard.html")
OUT_JSON = os.path.join(DIR, "board.json")
TPE = timezone(timedelta(hours=8))

AGENTS = [
    {"type": "營運",   "name": "Ops",    "emoji": "🛰️", "desc": "MarketDaily 營運",   "accent": "#6366f1"},
    {"type": "開發",   "name": "Dev",    "emoji": "🛠️", "desc": "程式開發",            "accent": "#22d3ee"},
    {"type": "投資",   "name": "Quant",  "emoji": "📈", "desc": "投資與股市分析",      "accent": "#34d399"},
    {"type": "行銷",   "name": "Growth", "emoji": "📣", "desc": "內容與成長行銷",      "accent": "#fb923c"},
    {"type": "短影片", "name": "Studio", "emoji": "🎬", "desc": "TikTok AI 短影片",    "accent": "#f472b6"},
]
PRIORITY = {"高": 0, "中": 1, "低": 2}


def parse_task(path):
    text = open(path, encoding="utf-8").read()
    meta, body = {}, text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, body.strip()


def section(body, name):
    out, capture = [], False
    for line in body.splitlines():
        if line.strip().startswith("## "):
            capture = line.strip()[3:].strip() == name
            continue
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def last_lines(txt, n=3):
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    return lines[-n:]


def collect(folder):
    tasks = []
    for p in sorted(glob.glob(os.path.join(DIR, folder, "*.md"))):
        meta, body = parse_task(p)
        tasks.append({
            "id": meta.get("id", os.path.basename(p)[:-3]),
            "title": meta.get("title", "未命名任務"),
            "type": meta.get("type", "營運"),
            "priority": meta.get("priority", "中"),
            "status": meta.get("status", folder),
            "attempts": meta.get("attempts", "0"),
            "created": meta.get("created", ""),
            "lease": meta.get("lease", ""),
            "completed": meta.get("completed", ""),
            "desc": " ".join(last_lines(section(body, "任務描述"), 2)),
            "progress": last_lines(section(body, "進度紀錄"), 3),
            "summary": section(body, "摘要"),
            "file": folder + "/" + os.path.basename(p),
        })
    return tasks


def git_activity():
    try:
        raw = subprocess.run(
            ["git", "log", "-12", "--format=%h\x1f%s\x1f%cI", "--", "agent_team/"],
            cwd=os.path.dirname(DIR), capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    out = []
    for line in raw.strip().splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            out.append({"hash": parts[0], "msg": parts[1], "iso": parts[2]})
    return out


def build():
    inbox = collect("inbox")
    working = collect("working")
    done = collect("done")
    failed = collect("failed")

    inbox.sort(key=lambda t: (PRIORITY.get(t["priority"], 1), t["created"]))
    working.sort(key=lambda t: t["lease"])
    done.sort(key=lambda t: t["completed"], reverse=True)
    failed.sort(key=lambda t: t["completed"], reverse=True)

    agents = []
    for a in AGENTS:
        cur = next((t for t in working if t["type"] == a["type"]), None)
        q = [t for t in inbox if t["type"] == a["type"]]
        agents.append({
            **a,
            "status": "working" if cur else ("queued" if q else "idle"),
            "current": cur,
            "next": q[0] if q else None,
            "queued": len(q),
            "done": sum(1 for t in done if t["type"] == a["type"]),
            "failed": sum(1 for t in failed if t["type"] == a["type"]),
        })

    now = datetime.now(timezone.utc)
    board = {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_display": now.astimezone(TPE).strftime("%Y-%m-%d %H:%M") + " 台北",
        "stats": {"working": len(working), "inbox": len(inbox),
                  "done": len(done), "failed": len(failed)},
        "agents": agents,
        "tasks": {"inbox": inbox, "working": working, "done": done, "failed": failed},
        "activity": git_activity(),
    }

    data = json.dumps(board, ensure_ascii=False)
    open(OUT_JSON, "w", encoding="utf-8").write(data)
    open(OUT, "w", encoding="utf-8").write(TEMPLATE.replace("/*__BOARD__*/null", data))
    print(f"✅ 儀表板已更新 — 進行中 {len(working)} · 待辦 {len(inbox)} · "
          f"完成 {len(done)} · 失敗 {len(failed)}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Agent Team 戰情室</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family:'Inter','Noto Sans TC',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    background:#0a0a1a; color:#e7e5f3; min-height:100vh;
    background-image:radial-gradient(900px 500px at 12% -8%,rgba(99,102,241,.22),transparent 70%),
                     radial-gradient(900px 500px at 100% 0%,rgba(244,114,182,.14),transparent 70%);
  }
  .wrap { max-width:1180px; margin:0 auto; padding:30px 22px 70px; }
  header { display:flex; justify-content:space-between; align-items:flex-end;
           flex-wrap:wrap; gap:14px; margin-bottom:26px; }
  .brand .kicker { font-size:11px; letter-spacing:3.5px; color:#a5b4fc;
                   text-transform:uppercase; }
  .brand h1 { font-size:28px; font-weight:800; color:#fde68a; margin-top:4px; }
  .meta { text-align:right; font-size:12px; color:#8b89a8; line-height:1.8; }
  .live { display:inline-flex; align-items:center; gap:6px; color:#34d399;
          font-weight:600; }
  .dot { width:8px; height:8px; border-radius:50%; background:#34d399;
         box-shadow:0 0 0 0 rgba(52,211,153,.6); animation:pulse 2s infinite; }
  @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(52,211,153,.5);}
                     70%{box-shadow:0 0 0 9px rgba(52,211,153,0);}
                     100%{box-shadow:0 0 0 0 rgba(52,211,153,0);} }

  .stats { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:26px; }
  .stat { background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08);
          border-radius:14px; padding:16px 18px; }
  .stat .n { font-size:30px; font-weight:800; line-height:1; }
  .stat .l { font-size:12px; color:#8b89a8; margin-top:7px; }

  h2.sec { font-size:14px; font-weight:700; color:#c7d2fe; margin:30px 0 13px;
           letter-spacing:.5px; display:flex; align-items:center; gap:8px; }
  h2.sec::before { content:""; width:3px; height:15px; background:#6366f1; border-radius:2px; }

  .agents { display:grid; grid-template-columns:repeat(auto-fill,minmax(212px,1fr)); gap:13px; }
  .agent { background:rgba(255,255,255,.045); border:1px solid rgba(255,255,255,.08);
           border-radius:16px; padding:16px; position:relative; overflow:hidden; }
  .agent::before { content:""; position:absolute; top:0; left:0; right:0; height:3px;
                   background:var(--ac); }
  .agent .top { display:flex; align-items:center; gap:9px; margin-bottom:11px; }
  .agent .emoji { font-size:21px; }
  .agent .nm { font-weight:700; font-size:15px; }
  .agent .ds { font-size:11px; color:#8b89a8; }
  .badge { font-size:10px; font-weight:700; padding:3px 9px; border-radius:20px;
           margin-left:auto; }
  .b-working { background:rgba(251,146,60,.18); color:#fb923c; }
  .b-queued  { background:rgba(99,102,241,.18); color:#a5b4fc; }
  .b-idle    { background:rgba(255,255,255,.07); color:#8b89a8; }
  .agent .doing { font-size:12px; color:#cbd5e1; line-height:1.6;
                  background:rgba(0,0,0,.25); border-radius:9px; padding:9px 10px;
                  min-height:46px; }
  .agent .doing .lbl { color:#fb923c; font-weight:700; font-size:10px;
                       letter-spacing:.5px; }
  .agent .tally { display:flex; gap:14px; margin-top:10px; font-size:11px;
                  color:#8b89a8; }
  .agent .tally b { color:#e7e5f3; }

  .cols { display:grid; grid-template-columns:repeat(4,1fr); gap:13px; }
  @media(max-width:880px){ .cols,.stats{grid-template-columns:repeat(2,1fr);} }
  @media(max-width:520px){ .cols,.stats{grid-template-columns:1fr;} }
  .col h3 { font-size:12px; font-weight:700; margin-bottom:9px; color:#8b89a8;
            display:flex; justify-content:space-between; }
  .col h3 .c { background:rgba(255,255,255,.08); border-radius:10px;
               padding:1px 8px; color:#c7d2fe; }
  .card { background:rgba(255,255,255,.045); border:1px solid rgba(255,255,255,.08);
          border-left:3px solid var(--c,#6366f1); border-radius:11px;
          padding:11px 12px; margin-bottom:9px; }
  .card .t { font-weight:700; font-size:13px; line-height:1.4; }
  .card .tags { display:flex; gap:5px; flex-wrap:wrap; margin:7px 0 0; }
  .tag { font-size:10px; padding:2px 7px; border-radius:6px;
         background:rgba(255,255,255,.08); color:#c7d2fe; }
  .tag.p高 { background:rgba(255,69,58,.2); color:#ff8a80; }
  .tag.p中 { background:rgba(255,159,10,.18); color:#ffcc80; }
  .tag.p低 { background:rgba(255,255,255,.08); color:#9ca3af; }
  .card .note { font-size:11px; color:#9aa0b4; line-height:1.6; margin-top:8px;
                border-top:1px solid rgba(255,255,255,.06); padding-top:7px;
                white-space:pre-wrap; }
  .card .lease { font-size:10px; margin-top:6px; font-weight:600; }
  .empty { font-size:12px; color:#5b596e; padding:14px 4px; text-align:center; }

  .feed { background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.07);
          border-radius:14px; padding:6px 4px; }
  .feed .row { display:flex; gap:11px; align-items:baseline; padding:8px 13px;
               font-size:12px; border-bottom:1px solid rgba(255,255,255,.045); }
  .feed .row:last-child { border-bottom:none; }
  .feed .hash { font-family:ui-monospace,Menlo,monospace; color:#818cf8;
                font-size:11px; flex-shrink:0; }
  .feed .msg { color:#cbd5e1; flex:1; }
  .feed .when { color:#6b6982; flex-shrink:0; font-size:11px; }
  footer { text-align:center; margin-top:34px; font-size:11px; color:#56546a; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="kicker">MarketDaily · Agent Team</div>
      <h1>🛰️ 夜間戰情室</h1>
    </div>
    <div class="meta">
      <div class="live"><span class="dot"></span> LIVE · <span id="reload">60</span>s 後刷新</div>
      <div id="gen"></div>
    </div>
  </header>

  <div class="stats" id="stats"></div>

  <h2 class="sec">值班團隊</h2>
  <div class="agents" id="agents"></div>

  <h2 class="sec">任務看板</h2>
  <div class="cols" id="cols"></div>

  <h2 class="sec">活動軌跡</h2>
  <div class="feed" id="feed"></div>

  <footer>夜間值班系統 · 每輪 Worker 自動重建此頁 · 分頁每 60 秒重載取得最新進度</footer>
</div>

<script>
const BOARD = /*__BOARD__*/null;

const esc = s => (s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function rel(iso){
  if(!iso) return "";
  const d=new Date(iso), s=(Date.now()-d.getTime())/1000;
  if(s<60) return "剛剛";
  if(s<3600) return Math.floor(s/60)+" 分鐘前";
  if(s<86400) return Math.floor(s/3600)+" 小時前";
  return Math.floor(s/86400)+" 天前";
}
function leaseInfo(iso){
  if(!iso) return null;
  const left=(new Date(iso).getTime()-Date.now())/1000;
  if(left>0) return {txt:"🔒 租約剩 "+Math.ceil(left/60)+" 分",col:"#34d399"};
  return {txt:"⚠ 租約已過期 · 下輪接手",col:"#fb923c"};
}

function render(){
  const b=BOARD;
  if(!b){document.getElementById("gen").textContent="尚無資料";return;}
  document.getElementById("gen").textContent="產生於 "+b.generated_display;

  const S=b.stats;
  document.getElementById("stats").innerHTML=[
    ["進行中",S.working,"#fb923c"],["待辦",S.inbox,"#a5b4fc"],
    ["完成",S.done,"#34d399"],["失敗",S.failed,"#ff6b6b"]
  ].map(([l,n,c])=>`<div class="stat"><div class="n" style="color:${c}">${n}</div>
    <div class="l">${l}</div></div>`).join("");

  document.getElementById("agents").innerHTML=b.agents.map(a=>{
    let doing;
    if(a.current){
      const pg=(a.current.progress||[]).slice(-1)[0]||"已認領,執行中…";
      doing=`<div class="doing"><span class="lbl">執行中</span><br>${esc(a.current.title)}
        <div style="color:#8b89a8;margin-top:4px">${esc(pg)}</div></div>`;
    }else if(a.next){
      doing=`<div class="doing"><span class="lbl" style="color:#a5b4fc">下一個</span><br>
        ${esc(a.next.title)}</div>`;
    }else{
      doing=`<div class="doing" style="color:#5b596e">目前待命,無排隊任務</div>`;
    }
    const bcls=a.status==="working"?"b-working":a.status==="queued"?"b-queued":"b-idle";
    const btxt=a.status==="working"?"執行中":a.status==="queued"?a.queued+" 件排隊":"待命";
    return `<div class="agent" style="--ac:${a.accent}">
      <div class="top"><span class="emoji">${a.emoji}</span>
        <div><div class="nm">${a.name}</div><div class="ds">${esc(a.desc)}</div></div>
        <span class="badge ${bcls}">${btxt}</span></div>
      ${doing}
      <div class="tally"><span>排隊 <b>${a.queued}</b></span>
        <span>完成 <b>${a.done}</b></span>
        <span>失敗 <b style="${a.failed?'color:#ff6b6b':''}">${a.failed}</b></span></div>
    </div>`;
  }).join("");

  const cols=[
    ["inbox","📥 待辦","#a5b4fc"],["working","⚙️ 進行中","#fb923c"],
    ["done","✅ 完成","#34d399"],["failed","❌ 失敗","#ff6b6b"]
  ];
  document.getElementById("cols").innerHTML=cols.map(([k,label,c])=>{
    const list=b.tasks[k]||[];
    const body=list.length?list.map(t=>taskCard(t,k,c)).join(""):
      `<div class="empty">— 空 —</div>`;
    return `<div class="col"><h3>${label}<span class="c">${list.length}</span></h3>${body}</div>`;
  }).join("");

  const act=b.activity||[];
  document.getElementById("feed").innerHTML=act.length?act.map(r=>
    `<div class="row"><span class="hash">${r.hash}</span>
      <span class="msg">${esc(r.msg)}</span>
      <span class="when">${rel(r.iso)}</span></div>`).join(""):
    `<div class="empty">尚無 agent_team 提交紀錄</div>`;
}

function taskCard(t,k,c){
  let note="",lease="";
  if(k==="working"){
    note=(t.progress||[]).join("\n");
    const li=leaseInfo(t.lease);
    if(li) lease=`<div class="lease" style="color:${li.col}">${li.txt}</div>`;
  }else if(k==="done"||k==="failed"){
    note=t.summary||(t.progress||[]).slice(-1)[0]||"";
    if(t.completed) note=(note?note+"\n":"")+"完成於 "+t.completed;
  }else{
    note=t.desc||"";
  }
  return `<div class="card" style="--c:${c}">
    <div class="t">${esc(t.title)}</div>
    <div class="tags"><span class="tag">${esc(t.type)}</span>
      <span class="tag p${t.priority}">${esc(t.priority)}</span>
      ${t.attempts&&t.attempts!=="0"?`<span class="tag">嘗試 ${t.attempts}</span>`:""}
      <span class="tag" style="background:none;color:#5b596e">${esc(t.id)}</span></div>
    ${note?`<div class="note">${esc(note)}</div>`:""}${lease}
  </div>`;
}

render();
let n=60;
setInterval(()=>{
  n--; document.getElementById("reload").textContent=n;
  if(n<=0) location.reload();
},1000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
