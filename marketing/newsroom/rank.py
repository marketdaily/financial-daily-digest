"""排序層:是不是新聞 → 題材線 → 夠不夠大條 → 輪替。

這個帳號是**世界新聞帳號**。有人追蹤,他就該知道世界上正在發生什麼事。
AI/科技是其中一條線,不是全部;教學型、工具介紹型內容一律不是新聞。

三層過濾,順序不能顛倒:
  ①is_news()  —— 把評論/教學/服務性文章/影評擋掉。通訊社整份 feed 免驗,
                  專業媒體與社群一定要驗(它們的 feed 混雜評論與 how-to)。
  ②classify() —— 分八條題材線,一天不會全是同一種事。
  ③score()    —— 跨源共振是最強的「這件事有多大」訊號,遠勝任何關鍵字。
"""
import datetime
import json
import pathlib
import re

STATE = pathlib.Path(__file__).resolve().parent / "state" / "rotation.json"

# 不是新聞:評論、教學、服務性文章、清單文、影評、播客
_NOT_NEWS = re.compile(
    r"(?i)\b("
    r"opinion|editorial|comment is free|analysis:|explainer:|review:|obituary|"
    r"podcast|newsletter|quiz|recipe|horoscope|crossword|"
    r"how to |here'?s how|here'?s what|what to know|should you |"
    r"best \d|top \d+|\d+ best|\d+ things|\d+ ways|guide to |your guide|"
    r"deals?:|discount|coupon|shopping|gift ideas|"
    r"watch live|live blog"
    r")")
# 標題型態也會洩底:問句開頭的服務文、第二人稱的建議文
_SERVICE = re.compile(r"(?i)^(why|how|what|when|should|can|is it|are you|do you)\b.*\?$")

LANES = {
    # lane: (基礎權重, 關鍵字)
    "breaking": (12, ["dead", "killed", "death toll", "missing", "capsize", "crash", "quake",
                      "earthquake", "tsunami", "explosion", "blast", "wildfire", "flood",
                      "collapse", "evacuat", "storm", "hurricane", "typhoon", "shooting",
                      "derail", "outbreak", "state of emergency"]),
    "conflict": (11, ["war", "strike", "missile", "drone", "troops", "ceasefire", "hostage",
                      "invasion", "offensive", "shelling", "airstrike", "militant", "rebel",
                      "border clash", "peace talks", "prisoner swap"]),
    "politics": (10, ["election", "vote", "president", "prime minister", "parliament", "resign",
                      "coalition", "coup", "impeach", "sanction", "summit", "treaty", "cabinet",
                      "referendum", "protest", "ruling party", "opposition", "tariff"]),
    "business": (8, ["markets", "economy", "inflation", "recession", "central bank", "rate cut",
                     "rate hike", "earnings", "ipo", "merger", "acquisition", "bankrupt",
                     "layoff", "oil price", "shares", "stocks", "trade deal", "supply chain"]),
    "tech": (8, ["ai", "artificial intelligence", "openai", "anthropic", "chip", "semiconductor",
                 "data center", "robot", "satellite", "cyber", "hack", "breach", "app",
                 "social media", "smartphone", "self-driving", "quantum"]),
    "science": (7, ["space", "nasa", "launch", "mars", "climate", "study finds", "researchers",
                    "vaccine", "disease", "virus", "cancer", "discovery", "fossil", "species",
                    "telescope", "experiment"]),
    "society": (7, ["court", "trial", "verdict", "sentenced", "arrest", "police", "investigation",
                    "rights", "migrant", "refugee", "strike action", "union", "school",
                    "hospital", "church", "festival", "museum"]),
    "sport": (5, ["world cup", "olympic", "champions league", "final", "tournament", "record",
                  "gold medal", "wins title", "transfer", "grand slam", "formula 1"]),
}

# 事件量級:這些字出現代表事情本身夠大,不是版面填充
_MAGNITUDE = re.compile(
    r"(?i)\b(dead|killed|death toll|missing|hundreds|thousands|millions|billion|"
    r"first time|record|historic|unprecedented|worst|largest|biggest|"
    r"resign|ousted|overthrow|arrested|charged|convicted|banned|"
    r"emergency|evacuat|collapse|halt|suspend|breakthrough)\b")


def is_news(item):
    """通訊社免驗;其餘一定要驗 —— 它們的 feed 混雜評論與 how-to。

    ⚠️ 不要改成「wire 源直接放行所有東西」以外的相反做法:
    這裡的不對稱是刻意的。通訊社的 feed 本來就是新聞線,
    而 The Verge / TechCrunch / Hacker News 的 feed 有一半是評測與教學。
    """
    title = item.get("title", "")
    if _NOT_NEWS.search(title):
        return False
    if item.get("wire"):
        return True
    if _SERVICE.search(title.strip()):
        return False
    return True


# ⚠️ 短關鍵字一定要字邊界比對。"ai" 用子字串比對會命中 Brit(ai)n / ag(ai)n / s(ai)d,
# 於是英國政治新聞被分到科技線 —— 而且它報綠,因為分類本來就不會報錯。
_LANE_RE = {lane: (w, re.compile(r"(?<![a-z])(" + "|".join(re.escape(k) for k in kws) + r")(?![a-z])", re.I))
            for lane, (w, kws) in LANES.items()}


def classify(item):
    blob = f"{item.get('title','')} {item.get('summary','')}"
    best = (None, 0)
    for lane, (w, rx) in _LANE_RE.items():
        if w > best[1] and rx.search(blob):
            best = (lane, w)
    return best if best[0] else ("world", 6)


def magnitude(item):
    return 4 * len(set(_MAGNITUDE.findall(f"{item.get('title','')} {item.get('summary','')}")))


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"posted": []}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    st["posted"] = st["posted"][-400:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1))


def velocity(item):
    """每小時被幾家媒體接手 —— 這是「還能不能蹭到」的訊號,不是「這件事多大」。

    ⭐ 數量是落後指標:六家都報了、事情過了 22 小時,那波流量已經被別人吃完,
    我們進去只是追尾。五家在 12 分鐘內同時發,那是正在成形的浪。
    同樣的素材,早兩小時發跟晚兩小時發是兩個量級的觸及。
    """
    age = max(item.get("age_h") or 0.0, 0.5)   # 0.5h 下限:剛發布不代表速度無限大
    return item.get("confluence", 1) / age


def score(item, lanes_today=None, last_lane=None):
    lane, lane_w = classify(item)
    s = float(lane_w)
    # 有多大:跨源共振
    s += item.get("confluence", 1) * 7
    # 還能不能蹭:加速度。封頂 40 分,避免單一訊號吃掉整個排序
    s += min(40.0, velocity(item) * 6)
    s += item.get("authority", 3) * 1.5
    s += magnitude(item)
    s += max(0.0, 14 - item.get("age_h", 99))
    lanes_today = lanes_today or []
    s -= lanes_today.count(lane) * 5
    if lane == last_lane:
        s -= 6
    return round(s, 1), lane


def _story_keys(item):
    from .sources import _keyset
    return _keyset(item["title"]) | _keyset((item.get("summary") or "")[:160])


def _suppress_same_story(ranked, state, today):
    """同一件事的不同角度只留分數最高那個(聚類抓標題幾乎一樣的,這層抓同一件事的第五種寫法)。"""
    chosen = [set(p["story_keys"]) for p in state["posted"]
              if p.get("date") == today and p.get("story_keys")]
    out = []
    for it in ranked:
        ks = _story_keys(it)
        if any(len(ks & prev) >= 3 and len(ks & prev) / (min(len(ks), len(prev)) or 1) >= 0.35
               for prev in chosen):
            continue
        chosen.append(ks)
        it["story_keys"] = sorted(ks)
        out.append(it)
    return out


def rank(items, state=None, today=None):
    state = state or load_state()
    today = today or datetime.date.today().isoformat()
    seen = {p["key"] for p in state["posted"]}
    lanes_today = [p["lane"] for p in state["posted"] if p.get("date") == today]
    last_lane = lanes_today[-1] if lanes_today else None
    out = []
    for it in items:
        if it["key"] in seen or not is_news(it):
            continue
        sc, lane = score(it, lanes_today, last_lane)
        out.append({**it, "score": sc, "lane": lane})
    out.sort(key=lambda x: -x["score"])
    return _suppress_same_story(out, state, today)


if __name__ == "__main__":
    from . import sources
    items, health = sources.fetch()
    print(json.dumps(sources.health_summary(health), ensure_ascii=False))
    ranked = rank(items)
    print(f"\n{len(items)} 則 → 過「是不是新聞」閘 {len(ranked)} 則(濾掉 {len(items)-len(ranked)})\n")
    for r in ranked[:18]:
        print(f"{r['score']:6.1f} [{r['lane']:9s}] {r['confluence']}源 {r['age_h']:5.1f}h "
              f"v={velocity(r):5.1f} {r['src_label']:13s} {r['title'][:66]}")
