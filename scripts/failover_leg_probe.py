#!/usr/bin/env python3
"""備援腿活體探針:GitHub Actions 那兩條腿現在真的派得出去嗎?

為什麼要有:
  MarketDaily 有兩條「主路死掉才會用到」的腿,兩條都靠 GitHub Actions workflow_dispatch:
    ① 日報雲端 failover(digest-watchdog → daily_digest.yml)—— winrig 整台離線時唯一的信
    ② 部署備援腿(scripts/deploy_docs_via_actions.sh → pages_deploy.yml)—— 本機 wrangler
       憑證死掉時唯一能發布的路
  2026-09-07 查出:帳號層 Actions 被停("Actions has been disabled for this user"),
  兩條腿【同時】是死的,而 daily_digest.yml 的 run 總數 = 0 —— 從 2026-07-26 建起就沒
  成功派過一次。repo 層 /actions/permissions 還回 enabled:true,所以看起來是活的。
  之所以 42 天零告警:只在主路死掉那天才會用到,用到那天的告警文字寫「需人工補救」,
  讀起來像單次意外,不像「這條腿從來沒通過」。

  → 沉默的守衛 = 沒有守衛。這支主動、定期、非破壞性地實射一次。

怎麼探而不會真的觸發一輪日報:
  故意送一個不存在的 ref。GitHub 的驗證順序是【先擋帳號層 Actions 停用,再驗 ref】,
  所以兩種回應可以乾淨分開,且任一種都**不會建立 run**:
    422 + "Actions has been disabled"  → 腿是死的(帳號層)
    422 + "No ref found"              → 腿是活的(過了授權與 Actions 閘,只卡在假 ref)
  其他狀態一律回 unknown —— 「問不到」不准寫成「沒事」。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH_REPO = "marketdaily/financial-daily-digest"
LEGS = {
    "daily_digest.yml": "日報雲端 failover(winrig 離線時唯一的信)",
    "pages_deploy.yml": "部署備援腿(本機 wrangler 憑證死掉時唯一的發布路)",
}
STATE = os.path.join(REPO_DIR, "state", "failover_leg_probe.json")
REALERT_SEC = 7 * 86400          # 持續壞:每 7 天再提醒一次,不天天洗


def _token():
    """兩條腿實際用的憑證:deploy_docs_via_actions.sh 走 `gh workflow run`(gh 的登入
    token),watchdog worker 走它自己的 GITHUB_TOKEN secret。「Actions has been disabled
    for this user」是**帳號層**判決,同帳號任一把 token 得到的答案相同 ⇒ 這裡用拿得到的那把。
    (限制要講明:這支證明得了「腿死了」,證明不了 worker 那把 token 本身沒過期。)"""
    try:
        for line in open(os.path.join(REPO_DIR, ".env"), encoding="utf-8", errors="ignore"):
            if line.startswith("GITHUB_TOKEN="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    except OSError:
        pass
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    gh = next((p for p in ("/usr/bin/gh", os.path.expanduser("~/.local/bin/gh"), "/usr/local/bin/gh")
               if os.path.exists(p)), None)
    if gh:
        r = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return r.stdout.strip()
    return ""


def probe(workflow, token):
    """回 (verdict, detail)。verdict ∈ alive / dead / unknown"""
    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{workflow}/dispatches"
    body = json.dumps({"ref": "__failover_leg_probe_no_such_ref__"}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "authorization": "Bearer " + token,
        "accept": "application/vnd.github+json",
        "content-type": "application/json",
        "user-agent": "md-failover-leg-probe/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            # 204 = 真的派出去了。假 ref 不該成功;真成功代表 GitHub 換了驗證順序,
            # 這時要大聲說(它可能剛剛跑了一輪日報),不可當成綠燈。
            return "unknown", f"HTTP {r.status}(假 ref 竟被接受,查 GitHub Actions run!)"
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(raw).get("message", raw)
        except Exception:
            msg = raw
        low = msg.lower()
        if e.code == 422 and "disabled" in low:
            return "dead", msg
        if e.code == 422 and ("no ref found" in low or "unexpected input" in low
                              or "does not have" in low or "required input" in low):
            return "alive", msg
        return "unknown", f"HTTP {e.code}: {msg[:160]}"
    except Exception as e:                                   # 連不上 ≠ 腿死
        return "unknown", f"{type(e).__name__}: {e}"


def _push(title, body):
    subprocess.run([os.path.join(REPO_DIR, ".venv", "bin", "python"),
                    os.path.expanduser("~/.marketdaily-fallback/notify_admin.py"), title, body],
                   env={**os.environ, "MD_REPO": REPO_DIR}, timeout=90)


def main():
    token = _token()
    if not token:
        print("🟠 沒有 GITHUB_TOKEN,無法探測(這本身就是備援腿不可用)")
        return 1
    try:
        prev = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        prev = {}

    now, results, worst = time.time(), {}, "alive"
    for wf, desc in LEGS.items():
        v, detail = probe(wf, token)
        results[wf] = {"verdict": v, "detail": detail}
        print(f"{'🔴' if v == 'dead' else '🟠' if v == 'unknown' else '🟢'} {wf}: {v} — {detail[:120]}")
        if v == "dead":
            worst = "dead"
        elif v == "unknown" and worst != "dead":
            worst = "unknown"

    changed = prev.get("worst") != worst
    stale = now - float(prev.get("last_alert") or 0) > REALERT_SEC
    if worst != "alive" and (changed or stale):
        dead = [f"・{w}({LEGS[w]}):{r['detail'][:90]}" for w, r in results.items() if r["verdict"] != "alive"]
        _push("🔴 備援腿實射失敗" if worst == "dead" else "🟠 備援腿探測不確定",
              "主路還活著,但主路一死就沒有第二條路了。\n" + "\n".join(dead) +
              "\n\n處理:GitHub 帳號層 Actions 被停 → 需 Delvin 去 github.com 申訴解封"
              "(repo 層 /actions/permissions 仍回 enabled:true,看不出來)。"
              "\n實測:python3 scripts/failover_leg_probe.py")
        prev["last_alert"] = now
    elif worst == "alive" and prev.get("worst") not in (None, "alive"):
        _push("🟢 備援腿恢復", "GitHub Actions workflow_dispatch 實射已通,兩條備援腿恢復可用。")
        prev["last_alert"] = 0

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"worst": worst, "results": results, "checked": now,
               "last_alert": prev.get("last_alert", 0)},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
