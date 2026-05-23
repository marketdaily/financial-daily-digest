"""產生信任牆 6 篇貼文的圖卡 → marketing/assets/posts/。"""
from pathlib import Path
from social_cards import make_card

EMERALD = "#10b981"
RED = "#ef4444"
INDIGO = "#6366f1"
VIOLET = "#a855f7"
AMBER = "#f5b942"

CARDS = [
    {
        "file": "trust_record",
        "tag": "公開戰績",
        "accent": EMERALD,
        "headline": "我們不空談\nAI 多強",
        "body": "看多勝率 75.5%\n看空勝率 42.9%\n錯的也列出來,不藏一支",
        "cta": "marketdaily.ai/track-record",
    },
    {
        "file": "trust_bullish_bearish",
        "tag": "看多 vs 看空",
        "accent": EMERALD,
        "headline": "每支個股\n都標好方向",
        "body": "🟢 看多 / 🔴 看空 / ⚪ 觀望\n隔天結果公開核對,輸贏不藏\n這是我們敢被檢驗的底氣",
        "cta": "marketdaily.ai/track-record",
    },
    {
        "file": "trust_vs_competitors",
        "tag": "為什麼不是他們",
        "accent": INDIGO,
        "headline": "為什麼不用\n三竹 / TradingView?",
        "body": "他們給你數據和線圖。\n我們給你判斷和方向。\n主動推送 + 個人化,他們做不到。",
        "cta": "marketdaily.ai/vs",
    },
    {
        "file": "trust_editor_promise",
        "tag": "編輯承諾",
        "accent": VIOLET,
        "headline": "每封信\n主編親自審稿",
        "body": "Delvin 清晨 6:00 起床校對\n品質沒過不發出去\n不收業配 · 不持有提及的個股",
        "cta": "marketdaily.ai/about",
    },
    {
        "file": "trust_refund_guarantee",
        "tag": "30 天保證",
        "accent": AMBER,
        "headline": "30 天\n無理由退費",
        "body": "首月 NT$299 試讀 (4 折)\n30 天內不滿意全額退\n隨時取消,1 鍵搞定",
        "cta": "marketdaily.ai",
    },
    {
        "file": "trust_testimonials_jason",
        "tag": "訂戶見證",
        "accent": INDIGO,
        "headline": "「省了\nNT$6 萬」",
        "body": "「NVDA 法說前一晚,日報就標短期過熱建議觀望,隔天真的回 3%。一個月訂閱費賺回來。」\n— Jason L. 軟體工程師",
        "cta": "marketdaily.ai/testimonials",
    },
]


def main():
    out_dir = Path(__file__).parent / "assets" / "posts"
    for c in CARDS:
        spec = {k: v for k, v in c.items() if k != "file"}
        path = out_dir / f"{c['file']}.png"
        make_card(spec, path)
        print(f"✓ {path.name}")
    print(f"\n完成 {len(CARDS)} 張圖卡 → {out_dir}")


if __name__ == "__main__":
    main()
