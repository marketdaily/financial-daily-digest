"""確定性品質修復層迴歸(2026-08-02):
① _pp_anchor_vague_reasons —— 虛詞卡(audit signal_reason_vague 連日系統性命中)補真實價位錨;
   判準與 digest_audit 9b 同一套 regex,健康卡/備援卡零改動。
② _pp_expand_us_tickers —— 知名美股裸代號補中文名(08-01 AMD 實鍋);tag 內部/已具名者不動。
零網路零 LLM。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyzer  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        FAILS.append(name)
        print(f"  ✗ {name} {detail}")


CARD = ('<div class="signal-card buy"><!--h:{sym}-->'
        '<span class="signal-ticker">{tick}</span>'
        '<div class="signal-reason">{reason}</div></div>')
TAIL = '<div class="signal-disclaimer">x</div>'

DATA = {
    "us_market": {"AAOI": {"price": 20.0}},
    "tw_market": {"2330": {"price": 1000.0}},
    "technicals": {
        "AAOI": {"atr14": 1.0, "ma20": 19.5, "lo20": 18.0, "hi20": 22.0},
        "2330": {"atr14": 30.0, "ma20": 980.0, "lo20": 950.0, "hi20": 1080.0},
    },
}

VAGUE_PRICE_RE = r"\$\s*\d|NT\$?\s*\d|\d+\s*(元|美元|塊|點)"

print("── _pp_anchor_vague_reasons ──")
html = CARD.format(sym="AAOI", tick="AAOI", reason="觀察量能,等趨勢明朗再說。") + TAIL
out = analyzer._pp_anchor_vague_reasons(html, DATA)
check("虛詞卡(美股)補上 $ 價位錨", re.search(VAGUE_PRICE_RE, re.search(
    r'signal-reason[^>]*>(.*?)</div>', out, re.S).group(1)) is not None, out[:200])
check("錨點含支撐與壓力", "支撐 $" in out and "壓力 $" in out)

html = CARD.format(sym="2330", tick="2330 台積電", reason="法說會前保持關注。") + TAIL
out = analyzer._pp_anchor_vague_reasons(html, DATA)
check("虛詞卡(台股)補 NT$ 錨", "NT$" in out)

healthy = CARD.format(sym="AAOI", tick="AAOI", reason="回檔 $19.5 支撐可低接,停損 $18。") + TAIL
check("健康卡逐字不動", analyzer._pp_anchor_vague_reasons(healthy, DATA) == healthy)

timed = CARD.format(sym="AAOI", tick="AAOI", reason="財報後再評估,本週先觀望。") + TAIL
check("有時間窗的卡不動", analyzer._pp_anchor_vague_reasons(timed, DATA) == timed)

fb = CARD.format(sym="AAOI", tick="AAOI", reason="個人化生成異常,主編將盡快修復。") + TAIL
check("備援卡不動", analyzer._pp_anchor_vague_reasons(fb, DATA) == fb)

noq = CARD.format(sym="ZZZZ", tick="ZZZZ", reason="等訊號。") + TAIL
check("無報價/技術資料 → 原樣(不掰價位)", analyzer._pp_anchor_vague_reasons(noq, DATA) == noq)

print("── _pp_expand_us_tickers ──")
out = analyzer._pp_expand_us_tickers("<p>Chip stocks rallied as AMD beat estimates</p>")
check("純英文脈絡裸 AMD → 超微(AMD)", "超微(AMD)" in out, out)
keep = "<p>AMD 財報後大漲</p>"   # ±12 字有中文=audit 本來就放行,修復層同判準不動
check("±12 字內有中文(audit 放行)不動", analyzer._pp_expand_us_tickers(keep) == keep)
keep2 = '<div class="x"><!--h:AMD--><span data-v="AMD">超微 AMD</span></div>'
check("tag 屬性/註解內的代號不動", 'data-v="AMD"' in analyzer._pp_expand_us_tickers(keep2)
      and "<!--h:AMD-->" in analyzer._pp_expand_us_tickers(keep2))
keep3 = "<p>Meta（META）續強</p>"
check("英文公司名相鄰(Meta（META))不動", analyzer._pp_expand_us_tickers(keep3) == keep3)
out = analyzer._pp_expand_us_tickers("<p>NVDA extended gains</p><p>TSM rallied overnight</p>")
check("不同段落的裸 NVDA/TSM 各自補名", "(NVDA)" in out and "(TSM)" in out, out)

# audit 端與修復端名單同源
import stock_names  # noqa: E402
check("FAMOUS_US_TICKERS 皆有名字資料",
      all(stock_names.US_NAMES.get(c) for c in stock_names.FAMOUS_US_TICKERS))

if FAILS:
    print(f"\n✗ {len(FAILS)} 失敗:{FAILS}")
    sys.exit(1)
print("\n✅ 全部通過")
