#!/usr/bin/env python3
"""零邊際成本驗收測試(Delvin 2026-07-30 令:「1 個用戶到 200 個用戶都是免費、品質不變」)。

驗收標準:LLM 呼叫數必須與「用戶數」脫鉤,只與「不重複標的數」有關。
做法:假 _llm_generate(零真實呼叫/零配額),用同一個標的宇宙餵 5→50→200 位模擬用戶,
比較呼叫數成長。用戶數 ×40 而呼叫數幾乎不變 = 通過。

同時驗「難搞標的」不會被每個用戶重燒:把某些標的的回答做成永遠過不了品質閘,
確認它們的重生迴圈全班次只花一次(舊行為=每個用戶各燒 3 輪)。
"""
import os
import random
import sys

os.environ.setdefault("DIGEST_COUNCIL", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyzer as A  # noqa: E402

# 標的宇宙:模擬真實分佈——少數熱門股大家都持有,長尾各自不同
HOT = ["NVDA", "TSLA", "AAPL", "MSFT", "META", "AMD", "TSM", "AMZN", "GOOGL", "MU"]
TAIL = [f"T{i:03d}" for i in range(300)]
# 這些標的的 LLM 回答故意做成過不了品質閘 → 觸發重生迴圈
HARD = {"NVDA", "T007", "T042"}

CALLS = {"n": 0}


def _fake_llm(prompt, prefer_strong=False, prefer_paid=False):
    CALLS["n"] += 1
    # ⚠️ 不可對命中結果做 [:N] 截斷:prompt 裡除了本批標的還會出現別的代號(新聞/規則區塊),
    # 截斷會把本批該回的卡擠掉 → 觸發重生迴圈 → 測出來的呼叫數是測試瑕疵而非程式行為
    # (第一版就這樣誤判預生成「變糟」)。收集端只認 chunk 內的代號,多回無害。
    syms = [s for s in HOT + TAIL if f"- {s}:" in prompt or f"{s} " in prompt or s in prompt]
    out = []
    for s in syms:
        # 合格卡必備(對齊 _card_passes_audit):3 個 battle-row + reason ≥70 字 + 帶價位
        if s in HARD:
            body, rows = "短", ""   # 理由過短 → 過不了閘,觸發重生迴圈
        else:
            body = ("今晚開盤站上月線 $95 且法人連續買超,結構偏多,現有部位可續抱;"
                    "但單日漲幅已大,追高風險升高,建議等回檔到 $98 附近再分批布局,"
                    "跌破 $95 則減碼保護獲利。")
            rows = ('<div class="battle-row">進場 $98</div>'
                    '<div class="battle-row">目標 $110</div>'
                    '<div class="battle-row">停損 $95</div>')
        out.append(f'<div class="signal-card hold"><div class="signal-card-top">'
                   f'<span class="signal-ticker">{s}</span>'
                   f'<span class="signal-day-move up">▲ +1.00%</span></div>'
                   f'<div class="signal-body"><div class="signal-reason">{body}</div>'
                   f'{rows}</div></div>')
    return "\n".join(out)


def _reset_caches():
    A._CARD_XUSER_CACHE.clear()
    A._CARD_XUSER_BEST.clear()
    A._CARD_XUSER_EXHAUSTED.clear()
    CALLS["n"] = 0


def _make_users(n, rng, fixed_universe=None):
    """每位用戶 8 熱門 + 4 長尾(模擬真實重疊度)。
    fixed_universe=K:長尾只從前 K-len(HOT) 檔抽 → 標的宇宙固定,用來測「純加人」的成本。"""
    tail = TAIL[:max(fixed_universe - len(HOT), 1)] if fixed_universe else TAIL
    return [rng.sample(HOT, 8) + rng.sample(tail, min(4, len(tail))) for _ in range(n)]


def _fake_data(symbols):
    mkt = {s: {"price": 100.0, "change_percent": 1.0, "ma5": 98, "ma20": 95,
               "rsi": 55, "high": 101, "low": 99, "volume": 1000} for s in symbols}
    return {"date": "2026-07-30", "us_market": mkt, "tw_market": {},
            "us_news": [], "tw_news": [], "market_summary": ""}


def run(n_users, rng_seed=42, fixed_universe=None, prewarm=False):
    _reset_caches()
    rng = random.Random(rng_seed)
    users = _make_users(n_users, rng, fixed_universe)
    universe = sorted({s for u in users for s in u})
    data = _fake_data(universe)
    mkt_status = {"tw_open": False, "us_open": False, "shift": "us"}
    if prewarm:  # 模擬 main._prewarm_card_pool:先用聯集跑滿批暖快取
        A._render_signal_cards_batched(data, universe, mkt_status, depth="standard")
    for stocks in users:
        A._render_signal_cards_batched(data, stocks, mkt_status, depth="standard")
    return CALLS["n"], len(universe)


def main():
    orig = A._llm_generate
    orig_sleep = A.time.sleep
    A._llm_generate = _fake_llm
    A.time.sleep = lambda *_a, **_k: None  # 生成迴圈的節流 sleep 在測試裡是純等待
    # 重生迴圈預算給足,確保測到的是「該不該重跑」而不是「預算剛好用完」
    os.environ["DIGEST_CARD_REGEN_BUDGET_S"] = "600"
    try:
        # ── 主驗收:標的宇宙固定,只變用戶數 ──
        # 這才是 Delvin 要求的精確形式:「有 200 個使用者不該比 5 個花更多錢」。
        # (前一版把宇宙隨用戶數一起放大,把「人變多」和「標的變多」混在一起,測不出脫鉤。)
        # 用 120 檔的固定宇宙,比較兩個「都已覆蓋完整宇宙」的規模。
        # ⚠️ 不能拿 5 人跟 200 人比:5 人只碰到 29/120 檔,那個差異是「碰到的標的變多」
        # 不是「人變多」——混在一起就測不出脫鉤(第一版就是這個瑕疵)。
        print("── 主驗收:標的宇宙固定且皆已飽和,只變用戶數 ──")
        rows = []
        for n in (100, 200, 400):
            calls, uni = run(n, fixed_universe=120)
            rows.append((n, uni, calls))
            print(f"用戶 {n:>4} 位 | 覆蓋標的 {uni:>3}/120 | LLM 呼叫 {calls:>4} | 每位用戶 {calls / n:>5.2f} 次")
        base, top = rows[0], rows[-1]
        growth = top[2] / max(base[2], 1)
        print(f"\n宇宙飽和後 用戶 {base[0]}→{top[0]} 位(×{top[0] / base[0]:.0f}),"
              f"呼叫數 {base[2]}→{top[2]}(×{growth:.2f})")
        # 驗收①:宇宙飽和後用戶 ×4,呼叫數成長須 <1.3 倍(≈持平=零邊際成本)
        ok_flat = growth < 1.3
        print(f"① 宇宙飽和後用戶 ×4 而呼叫數成長 <1.3×:{'✅' if ok_flat else '❌'}(實測 ×{growth:.2f})")

        # ── 參考情境:宇宙隨用戶成長(真實世界新用戶會帶新標的) ──
        print("\n── 參考:宇宙隨用戶成長(每人 8 熱門+4 長尾) ──")
        gcalls, guni = run(200)
        print(f"用戶 200 位 | 不重複標的 {guni} | LLM 呼叫 {gcalls} | 每位用戶 {gcalls / 200:.2f} 次")
        # 驗收②:呼叫數要與標的數同量級,不得是用戶數的量級
        ok_bound = gcalls <= guni * 1.6
        print(f"② 呼叫數與標的綁定(總呼叫 {gcalls} ≤ 標的 {guni}×1.6={guni * 1.6:.0f}):"
              f"{'✅' if ok_bound else '❌'}")

        # ── 驗收③:main._prewarm_card_pool 的效果(先跑聯集滿批,再走 per-user)──
        # 沒有預生成時,每位用戶把零星缺口湊成小批,每批重付一次規則區塊 → 呼叫數被人數推高。
        pcalls, puni = run(200, prewarm=True)
        theo = -(-puni // 10)  # ceil(標的/批次大小)=理論下限
        print(f"\n── 驗收③:加上聯集預生成 ──")
        print(f"用戶 200 位 | 不重複標的 {puni} | LLM 呼叫 {pcalls}(理論下限 {theo})"
              f" | 比無預生成省 {(1 - pcalls / max(gcalls, 1)) * 100:.0f}%")
        ok_prewarm = pcalls <= theo * 1.5
        print(f"③ 呼叫數逼近理論下限(≤{theo}×1.5={theo * 1.5:.0f}):{'✅' if ok_prewarm else '❌'}")
        ok_bound = ok_bound and ok_prewarm

        if not (ok_flat and ok_bound):
            print("\n❌ 零邊際成本驗收失敗")
            return 1
        print("\n✅ 零邊際成本驗收通過:LLM 呼叫數與用戶數脫鉤,只與不重複標的數有關")
        return 0
    finally:
        A._llm_generate = orig
        A.time.sleep = orig_sleep


if __name__ == "__main__":
    sys.exit(main())
