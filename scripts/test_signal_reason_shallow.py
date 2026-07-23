#!/usr/bin/env python3
"""digest_audit check#9b-2(signal_reason_shallow)迴歸測試。

背景(2026-07-23 事故):免費 LLM council 429 → 生卡模型降級 → 每張 signal-reason
從正常 ~130 字塌到 ~48 字。舊 check 全放行:9b(signal_reason_vague)只查有沒有價位/
時間窗,而塌陷後的短理由「仍帶價位」→ 過關;verdict_monoculture 只是 MED 不觸發 retry。
結果是 Delvin 本人先抓到、機器沒抓到。本 check 補上「深度塌陷」偵測。

校準(output/ 實測):07-20~22 正常日 median 107~197、min≥97、零卡 <80;
07-23 壞日 median 48、min 46、5/7 卡 <60。門檻:median<80 或 過半卡 <60 → HIGH。
HIGH 會被 main._audit_with_retry 泛型接住 → retry 換強模型 → 仍塌則 deterministic
fallback + _push_systemic_alert 告警,全部趕在 07:00/20:00 整點寄出前。

本檔凍結:系統性塌陷必抓、正常/單張天生短/小樣本不誤殺(鑑別力不可退化)。
用法: .venv/bin/python scripts/test_signal_reason_shallow.py   (exit 0=全過)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digest_audit


def mk_reason(n):
    """產生長度約 n 字、且含價位(排除 9b vague)的理由文字。"""
    base = "建議 NT$1050 附近進場 目標 NT$1180 跌破 NT$980 停損 "
    filler = "後續觀察量能與法人買賣超動向再決定加減碼耐心等待財報不追高殺低嚴控部位風險"
    s = base
    while len(s) < n:
        s += filler
    return s[:n]


def build_html(lengths):
    cards = []
    for i, n in enumerate(lengths):
        cards.append(
            f'<div class="signal-card">'
            f'<span class="signal-ticker">T{i:02d}</span>'
            f'<div class="signal-reason">{mk_reason(n)}</div>'
            f'<div class="battle-row">進場</div>'
            f'<div class="battle-row">目標</div>'
            f'<div class="battle-row">停損</div>'
            f'</div>'
        )
    return "<html><body>" + "".join(cards) + "</body></html>"


def fires(lengths):
    html = build_html(lengths)
    fails = digest_audit.audit_digest(html, "2026-07-23", [], [], {}, market="tw")
    hits = [f for f in fails if f.get("check") == "signal_reason_shallow"]
    return bool(hits), (hits[0]["msg"] if hits else "")


# (名稱, 每張理由字數, 預期是否 FAIL)
CASES = [
    ("正常日 7 張深理由(~120字)= 不塌陷", [120] * 7, False),
    ("事故重現:7 張淺理由(~48字,仍帶價位)= 系統性塌陷", [48] * 7, True),
    ("容錯:6 深 + 1 張天生短(45)= 不誤殺", [120] * 6 + [45], False),
    ("小樣本:2 張淺卡(<3 張不判)= 不假陽性", [48, 48], False),
    ("門檻上緣:7 張 ~92字(>80)= 不誤殺", [92] * 7, False),
    ("門檻下緣:7 張 ~68字(<80)= 必抓", [68] * 7, True),
    ("過半塌陷:4 短(50)+ 3 深(120)= 必抓", [50] * 4 + [120] * 3, True),
]


def main():
    ok = True
    for name, lengths, want_fail in CASES:
        got, msg = fires(lengths)
        status = "✅" if got == want_fail else "❌"
        if got != want_fail:
            ok = False
        print(f"{status} {name}: got={'FAIL' if got else 'PASS'} "
              f"預期={'FAIL' if want_fail else 'PASS'}" + (f" | {msg}" if msg else ""))
    print("\n=== ALL PASS ===" if ok else "\n=== SOME FAILED ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
