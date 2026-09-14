"""文案層:把一則 AI 新聞寫成 IG / FB / Threads 三平台文案。

版型來自對標帳號實際貼文的拆解(@getintoai 858.6K / @aipagedaily 3.1M,2026-09-14 實抓):
  - 開頭一句把新聞講完,句尾 1–2 個 emoji
  - 之後每段 1–3 句,段間空行;沒有任何一段超過三句
  - 有引述就直接引號原話
  - 倒數第二段給「所以呢/但有個前提」的轉折
  - 最後一行問讀者問題 + Follow CTA + 5 個 hashtag
分工鐵則:模型只供文字,版型/CTA/hashtag/handle 由程式供給。
"""
import json
import pathlib

BRAND = json.loads((pathlib.Path(__file__).resolve().parent / "brand.json").read_text())

LANE_BRIEF = {
    "breaking":  "Something just happened to people. Lead with what happened and to how many. Numbers only from the facts.",
    "conflict":  "A military or armed event. Say who did what to whom, where, and what is confirmed versus claimed.",
    "politics":  "Power changed hands or was contested. Say who now has what they did not have before.",
    "business":  "Money moved or a market reacted. Say how much and who is affected outside finance.",
    "science":   "A finding or a launch. Say what was tested or built and what it changes.",
    "society":   "People, courts, rights, culture. Lead with the human detail.",
    "sport":     "A result. Say who won, against what odds, and why it is a first if it is.",
    "world":     "An international development. Say which countries and what changes between them.",
    "frontier": "A new model or capability shipped. Explain what it can do that the previous one could not, in plain words.",
    "product":  "Something people can actually use. Say who it is for and what it replaces.",
    "money":    "Money moved. Say how much, from whom to whom, and what it buys.",
    "policy":   "Rules, courts or governments. Say what changes for ordinary users, not for lawyers.",
    "research": "A finding. Say what was tested and what surprised the researchers.",
    "robotics": "Something physical moved. Describe what it did, concretely.",
    "culture":  "People reacting to AI. Lead with the human detail, not the technology.",
}

LANE_TAG = {
    "frontier": "#futuretech", "product": "#aitools", "money": "#tech",
    "policy": "#aisafety", "research": "#science", "robotics": "#robotics",
    "culture": "#technology",
}


def build_facts(item, excerpt=""):
    return {
        "title": item["title"],
        "summary": item.get("summary", ""),
        "source_url": item["url"],
        "source_name": item["src_label"],
        "also_reported_by": item.get("also", []),
        "hours_old": item.get("age_h"),
        "lane": item["lane"],
        "article_excerpt": excerpt[:2500],
    }


PROMPT = """You write for an Instagram / Facebook / Threads account that covers AI news for a
general audience. The account's only goal is reach: people who are curious about AI but do not
work in it.

FACTS (this is the only information you may use; inventing anything outside it is a hard failure):
{facts}

WRITE three things and return ONLY a JSON object with these keys:
  "headline"          - 6 to 10 words, for the image card. No emoji. Title case off; sentence case.
  "caption"           - the Instagram/Facebook caption. Rules below.
  "threads_caption"   - the Threads version, IN TRADITIONAL CHINESE, under 300 characters,
                        same story, no hashtags. See CHINESE RULES below.
  "threads_chain"     - an array of 3 or 4 strings, the native Threads format. The first string is
                        a hook of at most 200 characters: the news in one line plus the single most
                        surprising detail. Each following string is at most 380 characters and adds
                        one new thing, not a restatement. The last string ends with the question to
                        the reader. No hashtags anywhere in the chain. Write it so each part still
                        makes sense to someone who scrolls past only the first one.
                        THIS CHAIN IS IN TRADITIONAL CHINESE. See CHINESE RULES below.

CAPTION RULES (these come from the two largest AI news accounts on Instagram; follow them exactly):
1. First line states the news in one plain sentence, then 1 or 2 emoji at the end of that line.
2. Then 3 to 5 paragraphs. Every paragraph is 1 to 3 short sentences. Blank line between paragraphs.
3. If the facts contain a direct quote, put one quote on its own paragraph in quotation marks.
4. Second-to-last paragraph gives the catch, the tension, or what is still unknown. Be honest that
   it is unconfirmed if the facts say so.
5. Last paragraph is a single question to the reader, ending with an emoji.
6. Explain like the reader has never used the product. No jargon. If you must use a technical term,
   define it in the same sentence in four words or less.
7. Do not use em dashes. Do not use the words "delve", "landscape", "testament", "game-changer",
   "revolutionize", "seamless", "unlock", "leverage".
8. NEVER state a number, percentage, price, or date that is not in FACTS. If you are unsure, omit it.
9. Do not write any @handle. Do not add hashtags. Do not add a follow line. Those are added later
   by the program.
10. Do not give investment advice or suggest anyone buy or sell anything.
11. {lane_brief}

CHINESE RULES (apply ONLY to "threads_caption" and "threads_chain"; the Instagram caption, the
headline, and any card or item text stay in English). The reader is in Taiwan.
C1. Write 繁體中文 (Traditional Chinese). Not one Simplified character anywhere.
C2. Taiwanese technical vocabulary, never mainland China vocabulary.
    Correct:  影片 軟體 硬體 網路 資訊 人工智慧 螢幕 晶片 記憶體 演算法 伺服器 預設 程式碼
              專案 資料庫 品質 雲端運算 行動裝置 部落格 網際網路 列印 雷射 快取 除錯 選單
              登入 滑鼠 智慧型手機 影音
    Wrong:    視頻 軟件 硬件 網絡 信息 人工智能 屏幕 芯片 內存 算法 服務器 默認 代碼
              數據庫 質量 雲計算 移動端 博客 互聯網 打印 激光 緩存 調試 菜單 登錄 鼠標
              智能手機
C3. Write the way a Taiwanese person actually writes online. Short sentences. Never use
    「首先」「其次」「綜上所述」「值得注意的是」「隨著…的發展」「不僅…更是」. No 成語 padding.
    No exclamation marks.
C4. The Chinese is NOT a translation of the English caption. Same facts, written natively.
    A sentence that reads like machine translation is a failure.
C5. Keep company and product names in their original English (OpenAI, Anthropic, Claude, Gemini,
    GitHub). Do not invent Chinese names for products that have none.
C6. Use 全形標點 (，。？「」) except inside English names and numbers.
C7. ⭐ If, and only if, the facts support it, add one sentence on what this means for Taiwan or
    for Asia: supply chains, shipping lanes, energy prices, semiconductors, tourism, security,
    people who live there. This is the one thing the big English accounts never do and it is the
    only real reason a Taiwanese reader follows us instead of them. Never invent the link. If the
    facts do not support one, leave it out rather than reaching.

Return only the JSON object.
"""


def build_prompt(facts):
    return PROMPT.format(
        facts=json.dumps(facts, ensure_ascii=False, indent=1),
        lane_brief=LANE_BRIEF.get(facts["lane"], ""),
    )


def decorate(draft, facts, brand=None):
    """程式端貼上 CTA / hashtag / 來源行 —— 這些是常數,不交給模型。"""
    b = brand or BRAND
    cap = (draft.get("caption") or "").rstrip()
    src = facts.get("source_name")
    if src and f"Source: {src}" not in cap:
        cap += f"\n\nSource: {src}"
    cap += "\n\n" + b["cta_follow_en"].format(handle=b["handle"])
    tags = list(b["hashtags"])
    lt = LANE_TAG.get(facts["lane"])
    if lt and lt not in tags:
        tags = tags[:4] + [lt]
    cap += "\n\n" + " ".join(tags)
    draft["caption"] = cap

    th = (draft.get("threads_caption") or "").rstrip()
    if len(th) < 460:
        th += f"\n\n@{b['handle']}"
    draft["threads_caption"] = th

    chain = [c.strip() for c in (draft.get("threads_chain") or []) if c and c.strip()]
    if chain:
        # handle 只掛在最後一則:每一則都掛等於在自己的串裡洗自己的名字
        if f"@{b['handle']}" not in chain[-1] and len(chain[-1]) < 440:
            chain[-1] = chain[-1] + f"\n\n@{b['handle']}"
        draft["threads_chain"] = chain
    # ⚠️ 這裡曾經寫成 draft["source_url"] = facts["source_url"](直接覆寫)。
    # 那一行讓 gates 的第一道閘(「模型不准自己換來源」)從上線起永遠射不出來 ——
    # 模型掰的網址會被安靜換成正確的,閘門看到的永遠是相符的兩個值,報綠。
    # 用 setdefault:模型沒給才補,模型給錯就留著讓閘門抓。
    draft.setdefault("source_url", facts["source_url"])
    return draft
