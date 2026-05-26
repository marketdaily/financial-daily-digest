"""產生 v2 organic post 15 張圖卡 → marketing/assets/posts/v2/。

對應 social_posts.json v2 的 15 篇 draft(2026-05-26 Marketing Agents 4 段串聯產出)。
跑法:python make_v2_cards.py [card_id]   # 沒帶 id 就全部跑;帶 id 只跑該張(供 demo)
"""
import sys
from pathlib import Path

from social_cards import make_card

VIOLET = "#a855f7"
SKY = "#38bdf8"
EMERALD = "#10b981"
GOLD = "#f5b942"
ROSE = "#fb7185"

OUT = Path(__file__).parent / "assets" / "posts" / "v2"

CARDS = [
    {
        "file": "explainer_v01_30sec",
        "tag": "30 秒",
        "headline": "30 秒讀完\n你的財經早報",
        "body": "美股 + 台股 · AI 寫成中文\n7AM 寄到你的 inbox",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "explainer_v02_only_yours",
        "tag": "個人化",
        "accent": EMERALD,
        "headline": "1000 條新聞\n只給你那 5 條",
        "body": "你設定持股 · AI 挑出跟你有關的\n中文寫, 30 秒讀完",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "problem_v01_time_steal",
        "tag": "為什麼",
        "accent": GOLD,
        "headline": "你早上的 1 小時\n被多少新聞偷走?",
        "body": "看完還是不知道:\n那, 我的持股呢?\nMarketDaily 壓成 30 秒。",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "problem_v02_fake_news",
        "tag": "訊號 vs 雜訊",
        "accent": SKY,
        "headline": "假新聞\n不是最危險的",
        "body": "看了 30 篇還是不知道\n哪些跟你的股票有關 ——\n這才是。",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "proof_v01_track_record",
        "tag": "公開戰績",
        "accent": EMERALD,
        "headline": "看對的會貼\n看錯的也會",
        "body": "看多 / 看空 / 觀望\n每日紀錄都列在戰績頁",
        "cta": "marketdaily.ai/track-record →",
    },
    {
        "file": "proof_v02_editor_promise",
        "tag": "編輯紀律",
        "accent": GOLD,
        "headline": "MarketDaily\n編輯五條紀律",
        "body": "1. 不收業配\n2. 日報提及個股 · 編輯不持有\n3. 不喊單\n4. 看錯了就列出來\n5. 永遠中文寫",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "founder_v01_why_built",
        "tag": "創辦人",
        "accent": ROSE,
        "headline": "我自己持股\n自己讀早報\n自己寫",
        "body": "後來朋友也在用\n然後就開放讓你訂\n— Delvin",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "founder_v02_not_a_teacher",
        "tag": "不當老師",
        "accent": ROSE,
        "headline": "我不是老師\n我是讀者",
        "body": "你做決定。我給原料。\n戰績公開 · 不收業配 ·\n日報提及個股不持有",
        "cta": "marketdaily.ai/track-record →",
    },
    {
        "file": "edu_v01_signal_noise",
        "tag": "投資思維",
        "accent": SKY,
        "headline": "真功夫不是\n知道更多\n是過濾更少",
        "body": "資訊永遠夠多\n你的注意力才稀缺\nMarketDaily 幫你過濾 80%",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "edu_v02_market_vs_yours",
        "tag": "個人化",
        "accent": EMERALD,
        "headline": "市場分析\n≠\n你的股票分析",
        "body": "大盤漲 1%\n你的持股可能跌 3%\n大部分財經只給左邊\n我們做相反",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "vs_v01_vs_local",
        "tag": "怎麼選",
        "accent": SKY,
        "headline": "早上追財經\n你的選項",
        "body": "鉅亨 / 經濟日報: 廣告滿版\nYahoo 股市: 沒人寫摘要\n滑社群: 自己過濾喊單\nMarketDaily: AI · 個人化",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "vs_v02_vs_chatgpt",
        "tag": "vs ChatGPT",
        "accent": VIOLET,
        "headline": "你不用問\n它自己 7AM 來",
        "body": "ChatGPT 你要去問\n它不知道你持有什麼\nMarketDaily 知道 · 主動寄",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "habit_v01_weekly",
        "tag": "節奏",
        "accent": GOLD,
        "headline": "週一到週六\n早上 7:00\n週日休息",
        "body": "盤前讀完\n開盤前你已經知道故事\n週末不打擾",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "explainer_v03_inbox_friend",
        "tag": "寫法",
        "headline": "朋友傳的早報\n不是新聞稿",
        "body": "中文 · 口語\n你的股票漲跌 + 為什麼\n沒有「應審慎評估」廢話",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "faq_v01_who_for",
        "tag": "適合你嗎",
        "accent": EMERALD,
        "headline": "MarketDaily\n適合你嗎?",
        "body": "✅ 持有美股或台股\n✅ 想知道持股動態\n✅ 不想花 1 小時掃新聞\n❌ 想要喊單老師",
        "cta": "marketdaily.ai →",
    },
]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    OUT.mkdir(parents=True, exist_ok=True)
    targets = [c for c in CARDS if only is None or c["file"] == only]
    if only and not targets:
        sys.exit(f"找不到 card id: {only}")
    for c in targets:
        out = OUT / f"{c['file']}.png"
        make_card(c, out)
        print(f"✅ {out.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()
