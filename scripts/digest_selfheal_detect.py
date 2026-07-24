#!/usr/bin/env python3
"""日報自癒偵測器(2026-07-24 Stage 2):判斷「這班日報是否有『檢查造成』的硬錯備援
值得自動根因修」。確定性、唯讀、零 LLM。

觸發條件(任一):
  - 老闆本人(MARKETDAILY_OWNER_EMAIL)掉 deterministic 備援,且成因是 audit HIGH check
  - ≥3 位掉備援且同一 audit HIGH check(系統性 prompt/樣板 bug)

**刻意排除**:LLM provider 429/503/配額耗盡造成的備援 —— 那是基礎設施問題,改碼救不了,
自動修只會空轉燒 token。用 fallback log 的成因行區分(HIGH audit fail vs retry 異常)。

輸出:JSON {trigger: bool, reason, checks:[...], owner_hit: bool, sample_email}。
exit 0 = 該修;exit 1 = 不用修(clean 或純 infra)。給 runner 判斷是否 spawn Claude 修。
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _owner_emails():
    return {e.strip().lower() for e in os.environ.get(
        "MARKETDAILY_OWNER_EMAIL", "delvin.12345678@gmail.com").split(",") if e.strip()}


def detect(date_iso, shift):
    """回傳 dict。shift ∈ {'tw','us'};us 版 log 檔名帶 _us,audit 報告不分班次(同日覆寫)。"""
    audit_path = os.path.join(REPO, "output", f"digest_audit_{date_iso}.json")
    log_path = os.path.join(REPO, "logs", f"fallback_{date_iso}.log")
    out = {"trigger": False, "reason": "", "checks": [], "owner_hit": False, "sample_email": ""}

    fallbacks = []
    if os.path.exists(audit_path):
        try:
            rep = json.load(open(audit_path, encoding="utf-8"))
            fallbacks = list(rep.get("deterministic_fallbacks") or [])
        except Exception as e:
            out["reason"] = f"audit 報告讀取失敗:{e}"
            return out
    if not fallbacks:
        out["reason"] = "無 deterministic 備援(clean)"
        return out

    # 從 fallback log 抽「email → 成因 check」,只認 audit HIGH 造成的(排除 429/503 infra)。
    # 行例:「⚠️ <email> HIGH audit fail(<check>),retry 一次」→ 該 email 因 <check> 掉備援。
    email_check = {}
    if os.path.exists(log_path):
        txt = open(log_path, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"⚠️\s*(\S+@\S+)\s*HIGH audit fail\(([a-z_,]+)\)", txt):
            email_check.setdefault(m.group(1).strip().lower(), set()).update(
                m.group(2).split(","))

    owners = _owner_emails()
    check_victims = {}   # check -> set(emails) 因該 check 掉備援
    owner_checks = set()
    for em in fallbacks:
        eml = str(em).strip().lower()
        checks = email_check.get(eml)
        if not checks:
            continue  # log 沒對應 HIGH check 行 = 多半是 provider 429/503 → 排除
        if eml in owners:
            out["owner_hit"] = True
            owner_checks |= checks
        for c in checks:
            check_victims.setdefault(c, set()).add(eml)

    systemic = sorted(c for c, v in check_victims.items() if len(v) >= 3)

    if out["owner_hit"]:
        out["trigger"] = True
        out["checks"] = sorted(owner_checks)
        out["sample_email"] = next(iter(owners), "")
        out["reason"] = f"老闆本人因 audit HIGH {sorted(owner_checks)} 掉備援"
    elif systemic:
        out["trigger"] = True
        out["checks"] = systemic
        out["sample_email"] = sorted(check_victims[systemic[0]])[0]
        out["reason"] = f"系統性:{systemic} 各 ≥3 位掉備援(疑 prompt/樣板 bug)"
    else:
        infra = len(fallbacks) - sum(len(v) for v in check_victims.values())
        out["reason"] = (f"有 {len(fallbacks)} 位掉備援,但非老闆且無單一 check≥3 位"
                         f"(疑 {infra} 位為 provider 429/503 infra,改碼救不了)")
    return out


def main():
    date_iso = sys.argv[1] if len(sys.argv) > 1 else ""
    shift = sys.argv[2] if len(sys.argv) > 2 else "tw"
    res = detect(date_iso, shift)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res["trigger"] else 1)


if __name__ == "__main__":
    main()
