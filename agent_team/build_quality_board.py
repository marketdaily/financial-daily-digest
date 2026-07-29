#!/usr/bin/env python3
"""品質戰情室資料彙整器(品質監察部,2026-07-29 組織化拍板)。
唯讀彙整三條品質防線的本地狀態 → docs/data/quality.json,由 status.html 品質戰情室段渲染。
安全鐵則(同 build_board_public.py):只輸出彙整數字/enum 狀態,訂閱者 email 與任何內部
自由文字(log 原文、audit msg、selfheal 細節)一律不出;docs/=公開 Pages 是硬邊界。
唯讀:不 rotate、不刪任何 log(selfheal_detect / latency monitor 都依賴這些檔)。
寫檔比對排除 generated_utc:內容沒變就不動檔 → runner 不觸發 deploy(省 deploy 面)。
新鮮度交叉:前端用 watchdog /status 的 hb(live)判 winrig 死活,不靠本檔時間戳。
"""
import glob
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "Delvin-agent")
FB = os.path.join(HOME, ".marketdaily-fallback")
OUT = os.path.join(REPO, "docs", "data", "quality.json")
LATENCY_CLI = os.path.join(HOME, "autonomous", "capabilities", "digest_latency_monitor", "cli.py")
TW = timezone(timedelta(hours=8))


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def read_text(path, limit=200_000):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def audit_summary(date):
    p = os.path.join(REPO, "output", f"digest_audit_{date}.json")
    try:
        j = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    per_check = {}
    for issues in (j.get("by_email") or {}).values():
        for it in issues:
            c = str(it.get("check", "unknown"))[:60]
            per_check[c] = per_check.get(c, 0) + 1
    return {
        "date": j.get("date", date),
        "total_subscribers": j.get("total_subscribers", 0),
        "audit_failed": j.get("audit_failed_count", 0),
        "fallback": j.get("deterministic_fallback_count", 0),
        "personalization_failed": j.get("personalization_failed_count", 0),
        "per_check": dict(sorted(per_check.items(), key=lambda kv: -kv[1])[:10]),
    }


def audit_trend(days=7):
    rows = []
    for p in sorted(glob.glob(os.path.join(REPO, "output", "digest_audit_*.json")))[-days:]:
        try:
            j = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({"date": j.get("date", os.path.basename(p)[13:23]),
                     "audit_failed": j.get("audit_failed_count", 0),
                     "fallback": j.get("deterministic_fallback_count", 0),
                     "total": j.get("total_subscribers", 0)})
    return rows


def latency_shifts(n=6):
    if not os.path.exists(LATENCY_CLI):
        return []
    try:
        r = subprocess.run(["python3", LATENCY_CLI, "--dir", os.path.join(REPO, "logs"),
                            "--days", "7", "--json"],
                           capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout or "[]")
    except (subprocess.SubprocessError, ValueError, OSError):
        return []
    shifts = []
    for entry in data:
        for s in entry.get("shifts", []):
            shifts.append({k: s.get(k) for k in
                           ("date", "market", "start", "done", "lateness_min", "verdict")}
                          | {"llm_tiers": s.get("llm_tier_hist") or {}})
    shifts.sort(key=lambda s: (s.get("date") or "", s.get("market") or ""))
    return shifts[-n:]


def sitescan_status():
    logs = sorted(glob.glob(os.path.join(FB, "logs", "sitescan_*.log")))
    if not logs:
        return None
    p = logs[-1]
    date = os.path.basename(p)[9:19]
    text = read_text(p)
    fails = [int(m) for m in re.findall(r"🚨 (\d+) 條 fail", text)]
    if fails:
        return {"date": date, "fails": fails[-1], "first_scan_fails": fails[0],
                "fixed_in_place": len(fails) > 1 and fails[-1] < fails[0]}
    passed = ("✅" in text) or ("全過" in text) or ("0 條 fail" in text)
    return {"date": date, "fails": 0 if passed else None,
            "first_scan_fails": None, "fixed_in_place": False}


def tail_verdicts(date):
    selfheal = {}
    for ed in ("tw", "us"):
        m = re.findall(r"=== done verdict=(\w+)", read_text(os.path.join(FB, "logs", f"selfheal_{date}_{ed}.log")))
        selfheal[ed] = m[-1] if m else None
    selfheal["disabled"] = os.path.exists(os.path.join(FB, "digest_selfheal.DISABLED"))
    postcheck = {}
    for ed in ("tw", "us"):
        m = re.findall(r"=== end rc=(\d+)", read_text(os.path.join(REPO, "logs", f"postcheck_{date}_{ed}.log")))
        postcheck[ed] = int(m[-1]) if m else None
    return selfheal, postcheck


def flag_status(date):
    return {
        "hb_miss_tw": os.path.exists(os.path.join(FB, "hb_state", f"{date}_tw_miss")),
        "hb_miss_us": os.path.exists(os.path.join(FB, "hb_state", f"{date}_us_miss")),
        "guard_alert_tw": os.path.exists(os.path.join(HOME, "autonomous", "state", f"digestguard_{date}_tw")),
        "guard_alert_us": os.path.exists(os.path.join(HOME, "autonomous", "state", f"digestguard_{date}_us")),
    }


def company_kpi(trend):
    """公司 KPI v1(2026-07-29 經營體檢⑤):老闆一眼看公司的最小集合。只出彙整數字。"""
    kpi = {}
    if trend:
        kpi["subscribers"] = trend[-1].get("total", 0)
        n = sum(1 for r in trend if r.get("total"))
        ok = sum(1 for r in trend if r.get("total") and r.get("audit_failed", 0) <= 2)
        kpi["digest_clean_days_7d"] = f"{ok}/{n}"
        kpi["fallback_7d"] = sum(r.get("fallback", 0) for r in trend)
    try:
        cutoff = (datetime.now(TW) - timedelta(days=7)).strftime("%Y-%m-%d")
        posts = 0
        for line in open(os.path.join(REPO, "marketing", "social_out", "post_log.jsonl"),
                         encoding="utf-8", errors="replace"):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = str(rec.get("ts") or rec.get("time") or rec.get("date") or "")
            if ts[:10] >= cutoff:
                posts += 1
        kpi["social_posts_7d"] = posts
    except OSError:
        pass
    return kpi


def main():
    date = tw_today()
    selfheal, postcheck = tail_verdicts(date)
    trend = audit_trend()
    payload = {
        "date": date,
        "kpi": company_kpi(trend),
        "digest": {"audit": audit_summary(date), "trend": trend,
                   "shifts": latency_shifts()},
        "selfheal": selfheal,
        "postcheck": postcheck,
        "sitescan": sitescan_status(),
        "flags": flag_status(date),
    }
    try:
        old = json.load(open(OUT, encoding="utf-8"))
        old.pop("generated_utc", None)
    except (OSError, ValueError):
        old = None
    if old == payload:
        print("quality.json:內容無變化,不動檔")
        return
    payload["generated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dump = json.dumps(payload, ensure_ascii=False)
    assert "@" not in dump, "quality.json 疑似含 email,拒絕輸出(公開頁硬邊界)"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"quality.json 已更新({len(dump)} bytes)")


if __name__ == "__main__":
    main()
