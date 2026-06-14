#!/usr/bin/env python3
"""v3 全新貼文批次 —— 磷光終端機品牌 + 雙時段(台股07:00/美股20:00) + 零假數字。

跑法:
    python build_v3_batch.py          產卡 + staging jpg + append 進 social_posts.json
    python build_v3_batch.py --cards  只產卡(assets/posts/v3/),不動 json

每篇:卡片 spec(tag/headline/body/cta/accent) + 完整 caption(已驗事實)。
事實底線:不寫勝率/用戶數等具體數字;方案只提 Premium(NT$499,首月試讀);台股07:00/美股20:00;organic UTM。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from social_cards import make_card

HERE = Path(__file__).parent
ROOT = HERE.parent
V3 = HERE / "assets" / "posts" / "v3"
SOCIAL = ROOT / "docs" / "social"
AMBER, PHOS, LAMBER, ORANGE = "#FFB000", "#4AF626", "#FFC74D", "#FF8A3D"

TAGS = "#美股 #台股 #財經日報 #投資理財 #盤前"


def url(pid, path=""):
    return f"https://marketdaily.ai{path}?utm_source=social&utm_medium=organic&utm_campaign={pid}"


BATCH = [
    {
        "id": "dual_schedule_v01", "tag": "一天兩班", "accent": PHOS,
        "headline": "早上看台股\n晚上看美股",
        "body": "台股 07:00 盤前\n美股 20:00 盤前\n各一封 · 盤前就位",
        "cta": "marketdaily.ai →",
        "caption": "美股開盤你在睡, 台股開盤你在忙。\n\nMarketDaily 一天兩班, 都在盤前:\n— 台股 07:00, 開盤前先讀\n— 美股 20:00, 美股盤前先讀\n\n只給跟你持股有關的, AI 中文寫好。免費讀一份: {u}\n\n" + TAGS,
    },
    {
        "id": "brand_v01_no_noise", "tag": "NO NOISE", "accent": AMBER,
        "headline": "不像其他\n財經內容",
        "body": "沒有喊單\n沒有業配\n沒有 80 則無結論快訊\nNO NOISE · JUST SIGNAL",
        "cta": "marketdaily.ai →",
        "caption": "我們長得不像市面上的財經內容。\n\n沒有喊單老師, 沒有業配, 沒有 80 則沒結論的快訊洗版。\n\nAI 跨多家可信媒體比對, 過濾雜訊, 只留下對你持股可能有影響的 —— 中文寫成 30 秒可讀。\n\nNO NOISE, JUST SIGNAL。試一份: {u}\n\n" + TAGS,
    },
    {
        "id": "pain_v01_overnight", "tag": "為什麼", "accent": ORANGE,
        "headline": "美股在你\n睡覺時發生",
        "body": "早上醒來 帳戶變了\n但你不知道昨晚發生什麼\n晚上 20:00 先講 · 早上 07:00 補台股",
        "cta": "marketdaily.ai →",
        "caption": "美股的大事, 大多在你睡覺的時候發生。\n\n早上醒來帳戶已經變了, 你卻不知道昨晚到底發生什麼。\n\nMarketDaily 晚上 20:00 在美股盤前先幫你講清楚, 早上 07:00 再補台股 —— 兩邊盤前你都先就位。\n\n看一份: {u}\n\n" + TAGS,
    },
    {
        "id": "proof_v01_open_record", "tag": "戰績公開", "accent": PHOS,
        "headline": "看對看錯\n都列出來",
        "body": "公開戰績頁\n看多 / 看空 / 觀望\n後續對錯都記\n100% 才是假的",
        "cta": "看公開戰績 →",
        "caption": "大部分財經頻道只給你「賺到」的案例。\n\n我們做了一個公開的戰績頁:每天的看多 / 看空 / 觀望, 後續對錯都記下來。看對的貼出來, 看錯的也是。\n\n投資不是抽卡, 是看樣本累積夠不夠誠實。聲稱 100% 準的, 那才是假的。\n\n戰績頁長這樣: {u}\n\n#戰績公開 #投資 #財經日報 #美股 #台股",
    },
    {
        "id": "personalization_v01", "tag": "個人化", "accent": LAMBER,
        "headline": "你設定持股\n它只給你\n那幾條",
        "body": "市場每天上千條新聞\n你需要的只有跟你股票有關的\nAI 幫你挑掉其他",
        "cta": "marketdaily.ai →",
        "caption": "市場每天上千條財經新聞。你真正需要的, 大概只有跟你持股有關的那幾條。\n\nMarketDaily 做的就是這件事:你設定持有的美股 + 台股, AI 每天早晚挑出跟你有關的, 中文寫給你。\n\n其他的, 它幫你過濾掉。試一份: {u}\n\n#個人化 #美股 #台股 #投資理財 #財經",
    },
    {
        "id": "premium_v01_line_alert", "tag": "即時推播", "accent": ORANGE,
        "headline": "你的持股\n出大事\n馬上 LINE 你",
        "body": "Premium 重大新聞即時推播\n不用一直刷盤\n影響你部位的 主動通知",
        "cta": "marketdaily.ai →",
        "caption": "不用整天刷盤等消息。\n\nMarketDaily Premium 會在重大新聞影響到你持股時, 即時推播 LINE 給你 —— 還能在 LINE 上雙向問 AI 「這對我的部位代表什麼」。\n\n日報看全局, 推播抓即時。了解 Premium: {u}\n\n#LINE #即時推播 #美股 #台股 #財經日報",
    },
    {
        "id": "ai_human_v01", "tag": "說人話", "accent": AMBER,
        "headline": "AI 寫的\n但說人話",
        "body": "不是「投資人應審慎評估」\n是「你的台積電昨晚怎樣\n今天要注意什麼」",
        "cta": "marketdaily.ai →",
        "caption": "MarketDaily 的寫法不是新聞稿, 是「朋友傳給你的早報」。\n\n不是「投資人應審慎評估」這種廢話, 而是:你的台積電昨晚發生什麼、為什麼、今天可能要注意什麼。\n\n中文、口語、給你思考材料。試一份看對不對你口味: {u}\n\n" + TAGS,
    },
    {
        "id": "weekend_v01_recap", "tag": "週末", "accent": PHOS,
        "headline": "週六一封\n本週回顧",
        "body": "平日盤前 早晚各一\n週六:本週回顧 + 下週重點\n週日休息 · 不打擾",
        "cta": "marketdaily.ai →",
        "caption": "MarketDaily 的節奏:\n\n— 平日盤前, 台股 07:00、美股 20:00 各一封\n— 週六早上是「本週回顧 + 下週重點」特別版\n— 週日休息 (你也該休息)\n\n盤前讀完, 開盤前你已經知道今天的故事。週末不打擾。從下一封開始: {u}\n\n" + TAGS,
    },
    {
        "id": "usecase_v01_busy", "tag": "誰適合", "accent": LAMBER,
        "headline": "沒空看盤\n但有持股",
        "body": "上班族 / 學生 / 創業者\n持有美股或台股\n沒時間每天掃新聞 —— 這封幫你",
        "cta": "marketdaily.ai →",
        "caption": "MarketDaily 適合你嗎?\n\n✅ 持有美股或台股\n✅ 上班 / 上課 / 創業, 很忙\n✅ 想知道自己持股的動態\n✅ 不想每天花一小時掃新聞\n\n中了 2 個以上, 試一份: {u}\n\n" + TAGS,
    },
    {
        "id": "editor_v01_discipline", "tag": "編輯紀律", "accent": AMBER,
        "headline": "提及的股\n編輯不持有",
        "body": "不收業配\n不喊單\n看錯公開列\n永遠中文寫",
        "cta": "marketdaily.ai →",
        "caption": "MarketDaily 的編輯底線:\n\n1. 不收業配\n2. 日報提及的個股, 編輯不持有 (避免利益衝突)\n3. 不喊單 (給你思考材料, 不當你老師)\n4. 看錯了會列出來 (戰績頁公開)\n5. 永遠中文寫 (英文新聞 AI 翻好給你)\n\n我們把這五條當底線。看實際日報: {u}\n\n#編輯紀律 #媒體識讀 #財經 #投資 #台股",
    },
    {
        "id": "vs_chatgpt_v02", "tag": "vs ChatGPT", "accent": PHOS,
        "headline": "ChatGPT 要你問\n我們主動寄",
        "body": "它不知道你持有什麼\n我們知道 (你設定過)\n台股早上 + 美股晚上 · 自己到 inbox",
        "cta": "marketdaily.ai →",
        "caption": "用 ChatGPT 查財經?\n\n— 你要每天記得去問\n— 它可能引用過時資料\n— 它不知道你持有什麼\n\nMarketDaily 是相反設計:不用你問, 台股 07:00、美股 20:00 自己到 inbox, 標明來源, 只給跟你持股有關的。\n\n看一份: {u}\n\n#ChatGPT #AI #美股 #台股 #財經日報",
    },
    {
        "id": "signal_noise_v02", "tag": "投資思維", "accent": LAMBER,
        "headline": "真功夫不是\n知道更多\n是過濾更少",
        "body": "資訊永遠夠多\n你的注意力才稀缺\nAI 幫你做 80% 過濾",
        "cta": "marketdaily.ai →",
        "caption": "投資的真功夫, 不是「知道更多」, 是「過濾更少」。\n\n資訊永遠夠多, 你的注意力才稀缺。\n\nMarketDaily 幫你做掉 80% 的過濾 —— AI 跨多家媒體比對、去掉廣告稿和點擊餌、只留對你持股可能有影響的。剩下 20% 留給你判斷。\n\n試一份: {u}\n\n#投資思維 #媒體識讀 #財經 #理財 #台股",
    },
]


def build(append_json=True):
    V3.mkdir(parents=True, exist_ok=True)
    posts_path = HERE / "social_posts.json"
    data = json.load(open(posts_path, encoding="utf-8"))
    existing = {p["id"] for p in data["posts"]}
    base_day = max((p.get("day", 0) for p in data["posts"]), default=0)
    new_posts = []
    for i, c in enumerate(BATCH):
        pid = c["id"]
        spec = {k: c[k] for k in ("tag", "headline", "body", "cta") if k in c}
        spec["accent"] = c.get("accent", AMBER)
        png = V3 / f"{pid}.png"
        make_card(spec, png)
        jpg = SOCIAL / f"{pid}.jpg"
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        str(png), "--out", str(jpg)], capture_output=True, check=True)
        path = "/track-record" if pid.startswith("proof") else ""
        cap = c["caption"].replace("{u}", url(pid, path))
        print(f"  ✓ {pid}")
        if pid not in existing:
            new_posts.append({"id": pid, "caption": cap, "image": f"{pid}.png",
                              "platforms": ["instagram", "facebook", "threads"],
                              "day": base_day + i + 1})
    if append_json and new_posts:
        data["posts"].extend(new_posts)
        json.dump(data, open(posts_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n已 append {len(new_posts)} 篇進 social_posts.json")


if __name__ == "__main__":
    build(append_json="--cards" not in sys.argv)
