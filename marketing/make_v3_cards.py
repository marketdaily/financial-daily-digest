"""產生 v3 organic post 12 張圖卡 → marketing/assets/posts/v3/。

對應 social_posts_v3_draft.json 的 12 篇(2026-07-01 Marketing Agents 5 段串聯產出)。
跑法:python make_v3_cards.py [card_id]   # 沒帶 id 就全部跑
"""
import sys
from pathlib import Path

from social_cards import make_card

EMERALD = "#4AF626"
SKY = "#FFC74D"
GOLD = "#FFB000"
ROSE = "#FF8A3D"

OUT = Path(__file__).parent / "assets" / "posts" / "v3"

CARDS = [
    {
        "file": "v3_noise_filter_01",
        "tag": "訊號 vs 雜訊",
        "accent": SKY,
        "headline": "別人加更多\n我們刪到\n只剩跟你有關",
        "body": "上千條新聞 → AI 濾假消息\n→ 30 秒中文早報\n美股 + 台股",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_time_30sec_01",
        "tag": "30 秒",
        "accent": GOLD,
        "headline": "通勤那 30 秒\n夠讀完一份\n財經早報",
        "body": "不用滑 20 個新聞 App\n台股 07:00 · 美股 20:00\n準時進 inbox",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_personalized_01",
        "tag": "個人化",
        "accent": EMERALD,
        "headline": "上千條新聞\n跟你有關的\n可能只有 5 條",
        "body": "設定你的持股\nAI 每天只挑那幾條\n中文寫給你看",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_bilingual_niche_01",
        "tag": "美股 + 台股",
        "accent": EMERALD,
        "headline": "人在台灣\n手上有美股\n這封寫給你",
        "body": "美股早報 20:00\n台股早報 07:00\n都用中文, 兩邊不漏",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_conclusion_01",
        "tag": "所以呢?",
        "accent": SKY,
        "headline": "你不缺新聞\n你缺的是\n「所以呢?」",
        "body": "看完 80 則快訊\n還是不知道持股怎麼想\n我們只給消化過的重點",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_track_record_01",
        "tag": "公開戰績",
        "accent": EMERALD,
        "headline": "講得頭頭是道\n不如\n回頭對帳",
        "body": "每日方向判斷留紀錄\n對的錯的都在頁面上\n自己去看",
        "cta": "marketdaily.ai/track-record →",
    },
    {
        "file": "v3_last_to_know_01",
        "tag": "即時",
        "accent": GOLD,
        "headline": "重大新聞\n你通常\n第幾個知道?",
        "body": "AI 過濾雜訊與假消息\n整理成中文早報\nPremium 還有即時警報",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_english_cost_01",
        "tag": "怎麼選",
        "accent": SKY,
        "headline": "太貴又英文\n或\n免費但雜訊爆炸",
        "body": "第三種:中文早報\n美股+台股 · AI 濾假消息\n免費開始 · 首月 NT$299",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_schedule_01",
        "tag": "節奏",
        "accent": GOLD,
        "headline": "台股 07:00\n美股 20:00\n你只要讀",
        "body": "卡在你本來就會\n停下來的時間點\n中文整理好",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_ai_assistant_01",
        "tag": "AI 助手",
        "accent": EMERALD,
        "headline": "讀完早報\n還有問題?\n直接問",
        "body": "「這則對我持股影響大嗎?」\nAI 用你的持股脈絡回答\nPremium 功能",
        "cta": "marketdaily.ai →",
    },
    {
        "file": "v3_premium_value_01",
        "tag": "Premium",
        "accent": GOLD,
        "headline": "一個月 NT$499\n你拿到的\n是這些",
        "body": "無限追蹤美股+台股\n即時警報 · 月度投組健檢\nAI 助手雙向對話",
        "cta": "年繳均 NT$399/月 →",
    },
    {
        "file": "v3_weekend_rest_01",
        "tag": "去雜訊",
        "accent": SKY,
        "headline": "我們的早報\n週末\n不吵你",
        "body": "市場休市\n手機不用再多一則推播\n去雜訊, 也包含不製造雜訊",
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
