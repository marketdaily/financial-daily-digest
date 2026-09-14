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
  "threads_caption"   - the Threads version, under 420 characters, same story, no hashtags.

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
    # ⚠️ 這裡曾經寫成 draft["source_url"] = facts["source_url"](直接覆寫)。
    # 那一行讓 gates 的第一道閘(「模型不准自己換來源」)從上線起永遠射不出來 ——
    # 模型掰的網址會被安靜換成正確的,閘門看到的永遠是相符的兩個值,報綠。
    # 用 setdefault:模型沒給才補,模型給錯就留著讓閘門抓。
    draft.setdefault("source_url", facts["source_url"])
    return draft
