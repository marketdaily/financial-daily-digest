"""排序層:AI 相關性閘 → 題材線分類 → 打分 → 輪替。

為什麼要有 is_ai_relevant():通用科技源(Ars/Engadget/HN/CNBC)整個 feed 灌進來時,
麻疹疫情與 MagSafe 線材會跟 OpenAI 併排。相關性閘是「這個帳號在講什麼」的定義本身,
不是效能優化 —— 少了它,帳號會在兩週內退回成一個雜訊科技帳。
"""
import datetime
import json
import pathlib
import re

STATE = pathlib.Path(__file__).resolve().parent / "state" / "rotation.json"

AI_CORE = [
    "ai", "a.i.", "artificial intelligence", "machine learning", "deep learning",
    "neural network", "llm", "large language model", "generative", "genai",
    "chatgpt", "gpt", "claude", "gemini", "llama", "mistral", "deepseek", "qwen",
    "openai", "anthropic", "deepmind", "hugging face", "midjourney", "stable diffusion",
    "copilot", "agentic", "ai agent", "transformer", "inference", "fine-tun",
    "prompt", "chatbot", "diffusion model", "multimodal", "foundation model",
    "humanoid", "robotaxi", "self-driving", "autonomous vehicle", "nvidia", "gpu cluster",
    "data center", "datacenter", "tpu", "superintelligence", "agi", "alignment",
]
# 這些字單獨出現不算(避免 "ai" 命中 "said"/"air" 這類)。用邊界比對處理。
AI_RE = re.compile(r"(?<![a-z])(" + "|".join(re.escape(k) for k in AI_CORE) + r")(?![a-z])", re.I)

LANES = {
    "frontier": (10, ["gpt-", "claude ", "gemini", "new model", "launches", "unveils", "releases",
                      "benchmark", "outperform", "state of the art", "sota", "reasoning model",
                      "context window", "open-source model", "open source model", "weights"]),
    "product":  (8,  ["app", "feature", "rolls out", "available now", "free tier", "plugin",
                      "integration", "api", "tool", "beta", "update", "extension", "browser"]),
    "money":    (8,  ["funding", "raises", "valuation", "ipo", "acquisition", "acquires", "billion",
                      "million", "investment", "revenue", "stock", "shares", "capex", "chip deal"]),
    "policy":   (7,  ["regulation", "regulator", "lawsuit", "sues", "court", "ban", "senate",
                      "congress", "eu ai act", "safety", "slow down", "guardrail", "copyright",
                      "白宮", "executive order", "antitrust", "privacy"]),
    "research": (6,  ["study", "paper", "researchers", "arxiv", "breakthrough", "proof", "discovery",
                      "scientists", "experiment", "dataset", "neuroscience"]),
    "robotics": (9,  ["humanoid", "robot", "robotaxi", "self-driving", "drone", "warehouse",
                      "boston dynamics", "figure ai", "tesla bot", "waymo"]),
    "culture":  (7,  ["viral", "went viral", "artist", "deepfake", "scam", "job", "layoff", "hiring",
                      "students", "teacher", "dating", "music", "hollywood", "film", "meme"]),
}

# 名字本身會帶流量的主體(對標帳號的貼文有八成命中其中之一)
MAGNETS = ["openai", "sam altman", "anthropic", "dario amodei", "claude", "chatgpt", "gpt-",
           "google", "gemini", "deepmind", "elon musk", "tesla", "nvidia", "jensen huang",
           "apple", "meta", "zuckerberg", "microsoft", "deepseek", "grok", "xai", "trump"]


def is_ai_relevant(item):
    """相關性閘對所有源都跑,ai_only 只是把門檻放低。

    ⚠️ 不要改回「ai_only 源直接放行」:MIT News 的 AI 主題 feed 實際會夾帶
    「MIT spinout turns plastic waste into building materials」這種零 AI 內容,
    信任來源標籤等於把別人的分類錯誤原樣播出去。
    """
    title_hit = bool(AI_RE.search(item["title"]))
    body_hit = bool(AI_RE.search(item.get("summary", "") or ""))
    if item.get("ai_only"):
        return title_hit or body_hit
    return title_hit or (body_hit and len(AI_RE.findall(item.get("summary", "") or "")) >= 2)


def classify(item):
    """回 (lane, lane 權重)。多命中取權重最高。"""
    blob = f"{item['title']} {item.get('summary','')}".lower()
    best = ("frontier", 0)
    for lane, (w, kws) in LANES.items():
        if any(k in blob for k in kws) and w > best[1]:
            best = (lane, w)
    return best if best[1] else ("frontier", LANES["frontier"][0])


def magnet_score(item):
    blob = f"{item['title']} {item.get('summary','')}".lower()
    return sum(3 for m in MAGNETS if m in blob)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"posted": []}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    st["posted"] = st["posted"][-400:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1))


def score(item, lanes_today=None, last_lane=None):
    lane, lane_w = classify(item)
    s = 0.0
    s += lane_w
    s += item.get("authority", 3) * 1.5
    s += item.get("confluence", 1) * 6          # 跨源共振是最強的熱度訊號
    s += magnet_score(item)
    s += max(0.0, 12 - item.get("age_h", 99))   # 越新越好,12h 後不再加分
    lanes_today = lanes_today or []
    s -= lanes_today.count(lane) * 4            # 同一條線今天發過就罰,避免一天八篇都是融資
    if lane == last_lane:
        s -= 5
    return round(s, 1), lane


def rank(items, state=None, today=None):
    state = state or load_state()
    today = today or datetime.date.today().isoformat()
    seen = {p["key"] for p in state["posted"]}
    lanes_today = [p["lane"] for p in state["posted"] if p["date"] == today]
    last_lane = lanes_today[-1] if lanes_today else None

    out = []
    for it in items:
        if it["key"] in seen:
            continue
        if not is_ai_relevant(it):
            continue
        sc, lane = score(it, lanes_today, last_lane)
        out.append({**it, "score": sc, "lane": lane})
    out.sort(key=lambda x: -x["score"])
    return _suppress_same_story(out, state, today)


def _story_keys(item):
    from .sources import _keyset
    return _keyset(item["title"]) | _keyset(item.get("summary", "")[:160])


def _suppress_same_story(ranked, state, today):
    """同一則故事的不同角度只留分數最高那個。

    聚類抓的是「標題幾乎一樣」;這一層抓的是「同一件事的第五種寫法」——
    今天的減速辯論在 6 家媒體各有一個角度,不擋就會一天發五篇同一件事。
    今天已發過的故事也一併壓掉。
    """
    chosen_keys = []
    for p in state["posted"]:
        if p["date"] == today and p.get("story_keys"):
            chosen_keys.append(set(p["story_keys"]))
    out = []
    for it in ranked:
        ks = _story_keys(it)
        dup = False
        for prev in chosen_keys:
            inter = len(ks & prev)
            if inter >= 3 and inter / (min(len(ks), len(prev)) or 1) >= 0.35:
                dup = True
                break
        if dup:
            continue
        chosen_keys.append(ks)
        it["story_keys"] = sorted(ks)
        out.append(it)
    return out


if __name__ == "__main__":
    from . import sources
    items, health = sources.fetch()
    print(json.dumps(sources.health_summary(health), ensure_ascii=False))
    ranked = rank(items)
    dropped = len(items) - len(ranked)
    print(f"\n{len(items)} 則 → 過相關性閘 {len(ranked)} 則(濾掉 {dropped})\n")
    for r in ranked[:18]:
        print(f"{r['score']:6.1f} [{r['lane']:8s}] {r['confluence']}源 {r['age_h']:5.1f}h "
              f"{r['src_label']:16s} {r['title'][:80]}")
