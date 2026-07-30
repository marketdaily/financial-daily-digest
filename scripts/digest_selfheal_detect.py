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


CF_GATE_MSG = "CF neuron 免費額度將盡"
GEMINI_DEAD_MIN = 10      # 單一 gemini 模型失敗達此次數 = 該模型當輪等同不可用
GEMINI_DEAD_MODELS = 4    # 有這麼多支 gemini 同時不可用 = 兩把 key 都倒了,不是偶發


def _degradation(log_path):
    """這一輪的模型鏈有沒有整體降級 → {degraded: bool, why: str}。純讀 log,零 LLM。

    判準(任一):①CF neuron 額度閘門有觸發(強免費層被自己的預算擋掉)
              ②≥GEMINI_DEAD_MODELS 支 gemini 模型各失敗 ≥GEMINI_DEAD_MIN 次(兩把 key 全滅)
    用「多支模型同時大量失敗」而不是「有沒有失敗過」:單次 429 是常態,不該算降級。
    """
    out = {"degraded": False, "why": ""}
    if not os.path.exists(log_path):
        return out
    txt = open(log_path, encoding="utf-8", errors="replace").read()
    cf_gate = txt.count(CF_GATE_MSG)
    fails = {}
    for m in re.finditer(r"\[LLM\]\s+(gemini:[\w.-]+)\s+失敗", txt):
        fails[m.group(1)] = fails.get(m.group(1), 0) + 1
    dead = sorted(k for k, n in fails.items() if n >= GEMINI_DEAD_MIN)
    why = []
    if cf_gate:
        why.append(f"CF 額度閘門觸發 {cf_gate} 次")
    if len(dead) >= GEMINI_DEAD_MODELS:
        why.append(f"{len(dead)} 支 gemini 模型各失敗 ≥{GEMINI_DEAD_MIN} 次(兩把 key 全滅)")
    if why:
        out["degraded"] = True
        out["why"] = "、".join(why)
    return out


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

    # ── 鏈路降級判定(2026-07-30 晚間加)────────────────────────────────
    # 原本的 infra 排除法只看「這個 email 有沒有 HIGH audit fail 行」,擋不住真正的 infra 事件:
    # 當強模型全倒、只剩弱模型時,弱模型寫出的理由本來就淺/虛,audit 會正確地標 HIGH,於是
    # 每個受害者都「有 HIGH 行」→ 看起來跟 prompt/樣板 bug 一模一樣 → 觸發自動修,去修一個
    # 根本沒壞的樣板(docstring 早就寫「自動修只會空轉燒 token」,但判準抓不到這種形狀)。
    # 當晚實況:6 個 gemini 模型各失敗 62 次(兩把 key 全滅)、groq 56、CF 因額度閘門 55
    # (閘門訊息 111 次)、連 openrouter 都 10 次 —— 整條強鏈全倒。
    deg = _degradation(log_path)
    if deg["degraded"] and not out["owner_hit"]:
        out["reason"] = (f"鏈路降級(非樣板 bug):{deg['why']}。弱模型寫出的理由本來就淺/虛,"
                         f"改碼救不了 → 不自動修,請看模型鏈/配額")
        out["checks"] = systemic
        out["sample_email"] = (sorted(check_victims[systemic[0]])[0] if systemic else "")
        return out

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
