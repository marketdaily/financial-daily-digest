"""艦隊級 liveness 總表(2026-08-03,升工程部「cron 艦隊健康」+情報部「連接器殭屍」兩格 B→A)。

問題:106+ cron 各自告警,但「誰靜默死了」沒有一張總表——cron 沒跑=沒有告警=沒人知道。
解法:掃兩個 log 家(repo logs/=cron_run_and_alert 逐 job、~/.marketdaily-fallback/logs/=runner 級),
以「檔案含 end rc=0 的最新成功日」為 job 心跳,**自校準**每個 job 的正常間隔
(近 30 天成功日的中位數間隔),超過 max(1.5×中位間隔+1 天, 2 天) 判靜默。
無需手維護 106 條期望表;退役 job 30 天視窗自然老化不誤報。

另掃 intel 引擎傘級健康:briefs/latest.json 年齡 + by_code 訊源數 vs 上輪(掉>25%=連接器群靜默壞)。

⭐ 2026-08-05 補「產出級心跳」(check_outputs):上面兩種心跳都綁「job 有沒有成功執行」,
抓不到**穩定地成功地什麼都沒產出**的 job。實例:券商喊單源(sinopac_line)自 07-31 起斷 5 天
——Windows 的 LINE 登出了,截圖抓到登入頁,解析器正確判定「非聊天室」並 SKIP、exit 0、寫 done,
每一層都「正常」,連 3 個交易日零產出卻零告警;而且它的 log 叫 line_group_cron.log,
不符 <job>_<date>.log 也不在 logs/ 下,根本不在納管範圍。
通則:**liveness != productivity。價值在產出物的來源,心跳要綁產出物年齡,不能綁 exit code。**

失敗 exit 1 → runner cron_run_and_alert 推 admin(指紋去重)。狀態落 state/fleet_liveness.json。
用法: .venv/bin/python scripts/fleet_liveness.py [--quiet]
"""
import datetime
import json
import os
import re
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIRS = [os.path.join(REPO, "logs"),
            os.path.expanduser("~/.marketdaily-fallback/logs")]
STATE = os.path.join(REPO, "state", "fleet_liveness.json")
LOOKBACK_DAYS = 30
FNAME_RE = re.compile(r"^(?P<job>.+)_(?P<date>\d{4}-\d{2}-\d{2})\.log$")
# 內容閘控 job:只在「有新內容」時才被父 runner 呼叫,自身靜默≠死(父 runner 才是心跳)。
# 首跑實證:deploy_docs_tldr 5 天沒跑=傘級 tldr_distribution 連日「無新資產無動作」,是正常。
GATED_PATTERNS = [re.compile(p) for p in (r"^deploy_docs_", r"^fallback$", r"^dryrun$",
                                           r"^lint$", r"^locks$", r"_TEST$")]


def collect_success_dates():
    """{job: sorted set of ISO dates having >=1 成功(end rc=0 或 runner done 行)}"""
    jobs = {}
    cutoff = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    for d in LOG_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            m = FNAME_RE.match(fn)
            if not m or m.group("date") < cutoff:
                continue
            path = os.path.join(d, fn)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except Exception:
                continue
            ok = ("end rc=0" in txt) or re.search(r"=== .* done ===", txt)
            if ok:
                jobs.setdefault(m.group("job"), set()).add(m.group("date"))
    return {j: sorted(ds) for j, ds in jobs.items()}


def classify(jobs, today=None):
    """純函式:成功日史 → (silent紅名單, report)。可測。
    判準:間隔中位數自校準;成功日<2 的新 job 不判(觀察期)。"""
    today = today or datetime.date.today()
    silent, report = [], {}
    for job, dates in sorted(jobs.items()):
        last = datetime.date.fromisoformat(dates[-1])
        age = (today - last).days
        if any(p.search(job) for p in GATED_PATTERNS):
            report[job] = {"last": dates[-1], "age_d": age, "status": "gated"}
            continue
        if len(dates) < 2:
            report[job] = {"last": dates[-1], "age_d": age, "status": "observing"}
            continue
        ds = [datetime.date.fromisoformat(x) for x in dates]
        gaps = [(b - a).days for a, b in zip(ds, ds[1:])] or [1]
        med = statistics.median(gaps)
        thresh = max(med * 1.5 + 1, 2)
        status = "silent" if age > thresh else "ok"
        report[job] = {"last": dates[-1], "age_d": age, "median_gap_d": med,
                       "thresh_d": round(thresh, 1), "status": status}
        if status == "silent":
            silent.append(f"{job}(last={dates[-1]},{age}d>{thresh:.0f}d)")
    return silent, report


# 產出級心跳:(標籤, 產出物 glob, 容忍天數, 診斷提示)
# 容忍天數要蓋過週末+連假;寧可晚一天報,不要每個週一誤報。
OUTPUT_HEARTBEATS = [
    ("券商喊單(sinopac_line)", "~/sinopac_line/*.md", 5,
     "多半是 Windows 的 LINE 登出了(截圖會是登入/QR 頁),需 Delvin 本人在 winrig 重新登入"),
    # 下面兩支 2026-08-05 補:輸出全進 /dev/null 或不符 <job>_<date>.log,原本完全不在納管範圍,
    # 靜默死掉沒人知道。心跳由腳本自己在每輪完成時蓋戳記(Mac 離線的合法跳過也算活著)。
    ("大腦送Mac(brain_deliver_mac)", "~/.marketdaily-fallback/state/brain_deliver_mac.beat", 1,
     "本支 */5,戳記超過 1 天=它沒在跑了(不是 Mac 離線,離線也會蓋戳記)"),
    ("cb_server 守護(keepalive)", "~/.marketdaily-fallback/state/cb_server_keepalive.beat", 1,
     "本支 */5,戳記超過 1 天=守護自己死了,cb_server 掛掉將不再自癒"),
]


def check_outputs(today=None):
    """產出物年齡心跳——專抓「跑得很成功但什麼都沒生出來」的來源。"""
    import glob as _glob
    today = today or datetime.date.today()
    problems, info = [], {}
    for label, pat, max_age, hint in OUTPUT_HEARTBEATS:
        files = _glob.glob(os.path.expanduser(pat))
        if not files:
            problems.append(f"{label}:產出物一個都沒有({pat})")
            info[label] = {"age_days": None, "newest": None}
            continue
        newest = max(files, key=os.path.getmtime)
        age = (today - datetime.date.fromtimestamp(os.path.getmtime(newest))).days
        info[label] = {"age_days": age, "newest": os.path.basename(newest), "max_age": max_age}
        if age > max_age:
            problems.append(f"{label}:最新產出 {os.path.basename(newest)} 已 {age} 天"
                            f"(容忍 {max_age} 天)——{hint}")
    return problems, info


def check_intel():
    """intel 傘級:latest.json 年齡 + 訊源覆蓋數 vs 上輪快照。"""
    problems, info = [], {}
    latest_p = os.path.join(REPO, "intel", "briefs", "latest.json")
    try:
        with open(latest_p, encoding="utf-8") as f:
            latest = json.load(f)
        age = (datetime.date.today() - datetime.date.fromisoformat(latest.get("date", "1970-01-01"))).days
        srcs = {it["source"] for items in (latest.get("by_code") or {}).values() for it in items}
        info = {"latest_age_d": age, "sources_n": len(srcs)}
        if age > 2:
            problems.append(f"intel latest.json 已 {age} 天未更新(patrol 死?)")
        prev_n = None
        try:
            with open(STATE, encoding="utf-8") as f:
                prev_n = ((json.load(f).get("intel") or {}).get("sources_n"))
        except Exception:
            pass
        if prev_n and len(srcs) < prev_n * 0.75:
            problems.append(f"intel 訊源數暴跌 {prev_n}→{len(srcs)}(連接器群靜默壞?)")
    except FileNotFoundError:
        problems.append("intel briefs/latest.json 不存在")
    except Exception as e:
        problems.append(f"intel 檢查失敗: {str(e)[:60]}")
    return problems, info


def _selftest():
    today = datetime.date(2026, 8, 3)
    jobs = {
        "daily_ok": ["2026-07-30", "2026-07-31", "2026-08-01", "2026-08-02", "2026-08-03"],
        "daily_dead": ["2026-07-25", "2026-07-26", "2026-07-27", "2026-07-28"],
        "weekly_ok": ["2026-07-13", "2026-07-20", "2026-07-27"],
        "weekly_dead": ["2026-07-06", "2026-07-13"],
        "brand_new": ["2026-08-03"],
    }
    silent, rep = classify(jobs, today)
    names = [s.split("(")[0] for s in silent]
    assert "daily_dead" in names and "weekly_dead" in names, silent
    assert "daily_ok" not in names and "weekly_ok" not in names
    assert rep["brand_new"]["status"] == "observing"
    g_silent, g_rep = classify({"deploy_docs_tldr": ["2026-07-28", "2026-07-29"]}, today)
    assert g_rep["deploy_docs_tldr"]["status"] == "gated" and not g_silent
    assert rep["weekly_ok"]["status"] == "ok"  # 7天週期 age=7 < 7*1.5+1
    # 產出級心跳:新鮮要放行、過期要抓、完全沒產出也要抓
    import tempfile
    global OUTPUT_HEARTBEATS
    _save = OUTPUT_HEARTBEATS
    try:
        with tempfile.TemporaryDirectory() as td:
            fresh = os.path.join(td, "2026-08-05.md")
            open(fresh, "w").close()
            OUTPUT_HEARTBEATS = [("T", os.path.join(td, "*.md"), 5, "hint")]
            probs, info = check_outputs(today=datetime.date.today())
            assert not probs, f"新鮮產出不該告警: {probs}"
            assert info["T"]["age_days"] == 0
            old = datetime.datetime.now().timestamp() - 9 * 86400
            os.utime(fresh, (old, old))
            probs, _ = check_outputs(today=datetime.date.today())
            assert len(probs) == 1 and "9 天" in probs[0], probs
            OUTPUT_HEARTBEATS = [("T", os.path.join(td, "*.nope"), 5, "hint")]
            probs, _ = check_outputs()
            assert len(probs) == 1 and "一個都沒有" in probs[0], probs
    finally:
        OUTPUT_HEARTBEATS = _save
    print("selftest ok")


def main():
    quiet = "--quiet" in sys.argv
    jobs = collect_success_dates()
    silent, report = classify(jobs)
    intel_problems, intel_info = check_intel()
    out_problems, out_info = check_outputs()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "jobs_n": len(jobs), "silent_n": len(silent),
                   "silent": silent, "intel": intel_info, "intel_problems": intel_problems,
                   "outputs": out_info, "output_problems": out_problems,
                   "jobs": report}, f, ensure_ascii=False, indent=1)
    if not quiet:
        for j, r in sorted(report.items()):
            if r["status"] != "ok":
                print(f"  {'🔴' if r['status'] == 'silent' else '👀'} {j}: {r}")
    problems = silent + intel_problems + out_problems
    if problems:
        print(f"🔴 艦隊 liveness:{len(silent)} 個 job 靜默 / intel {len(intel_problems)} 項"
              f" / 產出斷流 {len(out_problems)} 項")
        for p in problems[:15]:
            print(f"   - {p}")
        sys.exit(1)
    print(f"✅ 艦隊 liveness 全綠:{len(jobs)} jobs 心跳正常,"
          f"intel 訊源 {intel_info.get('sources_n', '?')} 源,產出源 {len(out_info)} 個新鮮")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
