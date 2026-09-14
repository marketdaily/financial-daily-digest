"""蹭流量:在別人已經聚起來的討論底下,用一個查得到出處的事實加入對話。

⛔ **2026-09-14 實測:這條路目前走不通,本模組不要接上線。**
   Threads 的 `keyword_search` 端點會回 200,但**只搜得到自己帳號的貼文**。
   校準方式:拿我們自己發過的字("台股"/"台積電"/"聯準會")去搜 → 各回 25 則;
   拿我們沒發過的字("Trump")去搜 → 回 0 則;把 118 筆結果的 username 全撈出來,
   **100% 是 marketdailyhq**。
   ⭐ 這就是「找不到」與「不存在」分不出來的那種陷阱:沒做這個校準就上線的話,
   這支工具會永遠回報「找到 0 則可回覆的討論」,看起來像「沒人在談這件事」,
   實際上是它根本搜不到別人。報綠的無效工具比壞掉的工具更危險。
   要復活需要:Threads 開放跨帳號搜尋權限,或改用別的探索路徑。
   在那之前,蹭討論串只能由人在 App 裡手動做。
   閘門邏輯(check_reply)先留著 —— 真的拿到權限時,需要的正是這一套判準。

為什麼這是新帳號唯一真的有效的槓桿:
  零追蹤者的帳號自己發文,只有演算法願意給的那點觸及。
  但一則已經在跑的熱門貼文底下,有現成的幾千人在看。
  在那裡留一句別人不知道的事實,是唯一不靠追蹤者就能被大量看到的動作。

**和洗版的界線寫死在程式裡,不是靠自覺:**
  - 回覆必須帶一個**出現在 facts 裡**的事實(數字或具名事實),否則不成立。
    「說得好」「同意」這種沒有資訊量的回覆,就是洗版。
  - 不准放連結、不准叫人追蹤、不准提自己的帳號。
  - 同一個 username 一天只回一次;每天總量設上限。
  - **只產草稿,不自動送出**(對外發布需老闆先看過,08-17 親令)。
自動化的價值密度太低就是垃圾訊息,帳號會被檢舉,那比沒流量更糟。
"""
import datetime
import json
import pathlib
import re
import urllib.parse
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
BRAND = json.loads((ROOT / "brand.json").read_text())
STATE = ROOT / "state" / "reply_radar.json"
API = "https://graph.threads.net/v1.0"

DAILY_CAP = 8              # 一天最多草擬幾則回覆
PER_USER_PER_DAY = 1       # 同一個人一天只回一次
MAX_LEN = 300

# 這些字出現代表這是推銷不是參與討論
_SELF_PROMO = re.compile(
    r"(?i)(follow (me|us)|check out|link in bio|追蹤我|歡迎追蹤|我的帳號|私訊我|"
    r"https?://|www\.)")


def _env():
    env = {}
    for line in (ROOT.parents[1] / "marketing" / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


BLOCKED = ("Threads keyword_search 只搜得到自己的貼文(2026-09-14 實測,118/118 筆都是本帳號)"
           " —— 蹭別人討論串目前做不到,不是今天沒人在談。")


def search(query, env=None, limit=10):
    """Threads 關鍵字搜尋。回 [] 可能是真的沒人在談,也可能是 API 變了 ——
    呼叫端要看得到差別,所以錯誤原樣往上拋而不是吞成空清單。"""
    env = env or _env()
    url = (f"{API}/keyword_search?q={urllib.parse.quote(query)}&search_type=TOP"
           f"&fields=id,text,username,timestamp,permalink&access_token={env['THREADS_ACCESS_TOKEN']}")
    req = urllib.request.Request(url, headers={"User-Agent": "newsroom-radar/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r).get("data", [])[:limit]


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"replied": []}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    st["replied"] = st["replied"][-500:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1))


def _facts_tokens(facts):
    blob = json.dumps(facts, ensure_ascii=False)
    nums = set(re.findall(r"\d[\d,\.]*", blob))
    names = set(re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", blob))
    return nums, names


def check_reply(text, facts, post_text=""):
    """確定性閘。回 reasons[];空的才算過。"""
    reasons = []
    t = (text or "").strip()
    if not t:
        return ["回覆是空的"]
    if len(t) > MAX_LEN:
        reasons.append(f"回覆超長 {len(t)}/{MAX_LEN}")
    if _SELF_PROMO.search(t):
        reasons.append("回覆含推銷字眼或連結(那是洗版不是參與討論)")
    if f"@{BRAND['handle']}" in t:
        reasons.append("回覆不該提自己的帳號")
    if re.search(r"#[^\s#]+", t):
        reasons.append("回覆不該帶主題標籤")
    nums, names = _facts_tokens(facts)
    has_num = any(n in t for n in nums if len(n) >= 2)
    has_name = any(n in t for n in names)
    if not (has_num or has_name):
        reasons.append("回覆沒有帶任何 facts 裡的具體事實 —— 沒有資訊量的回覆就是洗版")
    for n in re.findall(r"\d[\d,\.]*", t):
        if n.strip(".,") not in nums and not re.match(r"^(19|20)\d{2}$", n):
            reasons.append(f"回覆出現 facts 裡沒有的數字:{n}")
    return reasons


def candidates(story, facts, env=None, state=None):
    """回可以參與的討論串(已套每日/每人上限與去重)。"""
    state = state or load_state()
    today = datetime.date.today().isoformat()
    done_today = [r for r in state["replied"] if r["date"] == today]
    if len(done_today) >= DAILY_CAP:
        return [], f"今日已達上限 {DAILY_CAP} 則"
    users_today = [r["username"] for r in done_today]
    seen_ids = {r["post_id"] for r in state["replied"]}

    # 用故事的關鍵字去找,不是用我們自己的標題(標題是我們的寫法,別人不會那樣打)
    terms = [w for w in (story.get("story_keys") or [])[:6] if len(w) > 3]
    query = " ".join(terms[:3]) or story["title"][:60]
    try:
        found = search(query, env)
    except urllib.error.HTTPError as e:
        return [], f"搜尋失敗 http{e.code}(不是沒人在談,是 API 出事)"
    except Exception as e:
        return [], f"搜尋失敗 {type(e).__name__}(不是沒人在談,是連不上)"

    out = []
    for p in found:
        if p.get("id") in seen_ids:
            continue
        if users_today.count(p.get("username", "")) >= PER_USER_PER_DAY:
            continue
        out.append(p)
    return out, f"query={query!r} 找到 {len(found)} 則,可用 {len(out)} 則"


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "Sweden election"
    print("⛔", BLOCKED, "\n")
    try:
        res = search(q)
        users = {p.get("username") for p in res}
        print(f"搜尋 {q!r}:{len(res)} 則,來自帳號 {users or '(無)'}")
        for p in res[:6]:
            print(f"  @{p.get('username')} {p.get('timestamp','')[:16]} | {(p.get('text') or '')[:70]}")
    except Exception as e:
        print(f"搜尋失敗:{type(e).__name__}: {e}")
