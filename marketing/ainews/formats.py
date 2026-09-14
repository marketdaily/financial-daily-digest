"""另外兩種版型 —— 新聞解釋文之外,對標帳號真正長粉的東西。

拆解 @getintoai / @aipagedaily 的貼文後,三種版型分工很清楚:
  explainer  單則新聞白話解釋      → 有新聞才有,負責「每天都在」
  roundup    24 小時彙整輪播卡     → 零額外成本(來源層已經聚類好),負責「一次看完」
  listicle   存檔誘餌清單          → 完全不依賴新聞,負責「被收藏、被轉傳」

為什麼 listicle 重要:IG 的排序吃「儲存」與「分享」遠重於「讚」。
兩個對標帳號互動最高的貼文全是清單型(7 prompts / 99 codes),不是新聞。
新聞讓帳號活著,清單讓帳號長大。
"""
import json

ROUNDUP_PROMPT = """You write the daily AI roundup for a large Instagram account.

TODAY'S STORIES (use only these; do not add anything you know from elsewhere):
{stories}

Produce ONLY JSON:
  "headline"  - 6 to 9 words for the cover card, sentence case, no emoji
  "cards"     - an array of {n} objects, one per story, each {{"title": "4 to 7 words",
                "line": "one sentence of at most 22 words explaining it plainly"}}
  "caption"   - Instagram caption: one opening line summarising the day with 1-2 emoji at the end,
                then a blank line, then one short paragraph per story (1 to 2 sentences each),
                then a blank line, then a single question to the reader ending in an emoji.
  "threads_caption" - under 420 characters: the opening line plus the three biggest items as
                short lines, then the question.
  "threads_chain"   - an array of 3 or 4 strings for the native Threads format. First string is a
                hook of at most 200 characters naming the day's biggest item. Each following string
                is at most 380 characters and covers different items. Last one ends with the
                question. No hashtags anywhere.

Rules (each one exists because a fact checker rejected a draft for breaking it):
- Never state a number, name or date that is not in TODAY'S STORIES.
- Do not widen the scope of a claim. If a source says code ran on a build server, do not write
  that it ran on the reader's computer. Keep the blast radius exactly as the source states it.
- Do not turn a headline into an interview. "CNBC reported that X says Y" is allowed;
  "X told CNBC" is not, unless the story says so.
- Do not write "today", "this morning" or "right now". The stories span more than one day.
  Write "this week" or no time word at all.
- Keep the source's tense. If the story says a flaw "was" present, do not write that it "is".
- Do not add motive, intent or emotion that the source did not report. "Critics are suspicious"
  is reportable; "critics question their motives" is your own reading.
- Every product, company or technical term a general reader would not know gets four words of
  explanation the first time it appears, or it gets cut.
- No em dashes. No @handles. No hashtags. No follow line. Those are added by the program.
- No investment advice.
"""

LISTICLE_PROMPT = """You write save-worthy list posts for a large Instagram account about AI.
These posts are what people save and send to friends, so usefulness beats novelty.

TOPIC: {topic}
AUDIENCE: people who use AI chatbots casually and want to get more out of them.

Produce ONLY JSON:
  "headline"  - 5 to 9 words for the cover card, sentence case, no emoji
  "items"     - an array of {n} objects: {{"title": "3 to 6 words",
                "body": "the actual prompt or tip, 12 to 40 words, written so it can be copied
                and used as is"}}
  "caption"   - Instagram caption: one opening line saying what the list gives the reader, with
                1-2 emoji at the end. Blank line. Two or three short paragraphs explaining when
                these help and what they are not. Blank line. A line telling the reader to save
                the post. Blank line. One question to the reader ending in an emoji.
  "threads_caption" - under 420 characters: the hook, three of the items compressed to one line
                each, and the question.
  "threads_chain"   - an array of 3 or 4 strings for the native Threads format. First string is a
                hook of at most 200 characters. Each following string gives one or two of the items
                in full so they are usable on their own. Last one ends with the question.
                No hashtags anywhere.

Rules (each one exists because a fact checker rejected a draft for breaking it):
- Every item must be genuinely usable. No filler, no "be creative", no vague advice.
- Do not claim any tool does something you are not certain it does.
- Do not invent statistics, prices, model names or release dates. If unsure, leave numbers out.
- No em dashes. No @handles. No hashtags. No follow line. Those are added by the program.
- Do not give financial, legal or medical advice.
- Do not write "today" or any date reference. This post should read the same in three months.
- Every product or technical term a general reader would not know gets four words of explanation
  the first time it appears, or it gets cut.
"""

# 清單型題目池:不依賴新聞,可無限輪替。刻意避開會過期的題目(版本號、價格)。
LISTICLE_TOPICS = [
    "prompts that make a chatbot give you a straight answer instead of a hedge",
    "ways to use AI to plan a trip without getting made-up hotel names",
    "prompts for turning a messy pile of notes into something you can act on",
    "prompts that help you study a subject you keep bouncing off",
    "ways to use AI when you are stuck on a decision",
    "prompts for writing an email you have been avoiding for three days",
    "ways to check whether something an AI told you is actually true",
    "prompts that turn a long document into the four things you need",
    "ways to use AI to prepare for a job interview",
    "prompts for getting unstuck at the start of a piece of writing",
    "ways to spot an AI generated image or video",
    "prompts that make an AI argue against your own idea",
    "ways to use AI to learn a language without a tutor",
    "prompts for organising a week that already went wrong",
    "ways to use AI on your phone that most people never try",
]


def roundup_prompt(stories, n):
    lines = [{"title": s["title"], "source": s["src_label"],
              "summary": (s.get("summary") or "")[:300], "url": s["url"]} for s in stories]
    return ROUNDUP_PROMPT.format(stories=json.dumps(lines, ensure_ascii=False, indent=1), n=n)


def roundup_facts(stories):
    return {
        "title": "Daily AI roundup",
        "summary": " | ".join(s["title"] for s in stories),
        "source_url": stories[0]["url"],
        "source_name": ", ".join(sorted({s["src_label"] for s in stories})[:5]),
        "also_reported_by": [], "lane": "frontier", "hours_old": None,
        "article_excerpt": " ".join((s.get("summary") or "")[:300] for s in stories)[:2500],
        "stories": [{"title": s["title"], "url": s["url"], "source": s["src_label"]} for s in stories],
    }


def listicle_prompt(topic, n):
    return LISTICLE_PROMPT.format(topic=topic, n=n)


def listicle_facts(topic):
    return {
        "title": f"List post: {topic}",
        "summary": topic,
        # 清單型沒有外部來源 —— 用官網當出處,閘門仍會比對 source_url 一致性
        "source_url": None, "source_name": None,
        "also_reported_by": [], "lane": "product", "hours_old": None,
        "article_excerpt": "",
    }


def pick_topic(state):
    used = [p.get("topic") for p in state.get("posted", []) if p.get("topic")]
    for t in LISTICLE_TOPICS:
        if t not in used[-len(LISTICLE_TOPICS):]:
            return t
    return LISTICLE_TOPICS[len(used) % len(LISTICLE_TOPICS)]
