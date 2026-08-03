#!/usr/bin/env python3
"""social_post_gate —— 社群品牌貼文「發文當下」的確定性閘門。

背景:`marketing/daily_run.py` 是品牌貼文的唯一發文路徑(winrig cron 週一/三/五 14:00 TW),
原本只做「挑佇列裡第一篇沒發過的 → 直接發」,零檢查。marketing/CLAUDE.md 的鐵則
「發前必逐字驗 caption」(2026-05-26 出包後立的)是寫給人看的,而真正在發文的是 cron。
2026-08-03 實測:下一篇是 `tldr_2026-07-22_us`,會在 08-05 公開發出 14 天前的市場脈搏數據。

本模組純 stdlib、零網路、無 LLM:給一則貼文 + 「現在」,回傳 ok / expired / violation。
`now` 一律由呼叫端注入(測試不可寫死今天,見 lesson harness_golden_live_data_drift)。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime

# ── 內容型別與時效 ────────────────────────────────────────────────────────────
# TTL 的判準是「這則 caption 有沒有斷言一個**當下**的市場狀態」,不是「內容多舊」:
#   tldr  = 當日盤後脈搏(VIX/恐貪/板塊輪動)→ 隔幾天就是錯的市場狀態,最嚴
#   newsr = 新聞快評,同理
#   win   = 戰績卡,caption 自帶日期、講的是「當時建議 X,5 日後 Y」的歷史事實,衰減慢
#   adcreative = 週批次行銷素材;帶新聞 hook 的衰減快(見 news_hook_ttl)
#   其他(explainer / eng_article 等品牌常青文)= 不過期
TTL_DAYS = {
    "tldr": 4,
    "newsr": 3,
    "win": 30,
    "adcreative": 21,
}
NEWS_HOOK_TTL_DAYS = 10  # adcreative 帶 source_url(新聞 hook 型)時改用這個
# 過期後可以「自動退場」的型別:這幾種是機器每天/每週自己生的,會有新的替補,
# 自動標 retired 不會弄丟人做的東西。其他型別過期只 skip + 等人覆核。
AUTO_RETIRE_KINDS = {"tldr", "newsr", "win"}

_ID_KIND = re.compile(r"^([a-z]+)[_-]")
_ID_DATE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
_CAPTION_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def infer_kind(post_id: str) -> str:
    m = _ID_KIND.match(post_id or "")
    return m.group(1) if m else "unknown"


def extract_content_date(post: dict) -> date | None:
    """貼文素材對應的日期。優先 id 內的日期,退回 caption 裡第一個 YYYY-MM-DD。

    只認 id 的第一個日期樣式;抓不到就退 caption(tldr/win 的 caption 都自帶日期)。
    兩邊都沒有 → None = 常青內容,不套 TTL。
    """
    for pat, text in ((_ID_DATE, post.get("id") or ""), (_CAPTION_DATE, post.get("caption") or "")):
        for m in pat.finditer(text):
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue   # 像日期但湊不成日期(例:_20261399)→ 換下一個候選,不可直接當常青內容
    return None


def ttl_for(post: dict) -> int | None:
    kind = infer_kind(post.get("id") or "")
    if kind == "adcreative" and post.get("source_url"):
        return NEWS_HOOK_TTL_DAYS
    return TTL_DAYS.get(kind)


# ── 合規紅線 ─────────────────────────────────────────────────────────────────
# 詞表比對一律用 word-boundary(拉丁字)或明確中文詞,禁裸子字串:
# 「Pro」若裸比對會誤傷 Professional/Product/Pro-forma(見 capability_genai_prompt_lint 教訓)。
_PRO_PLAN = re.compile(r"(?<![A-Za-z])Pro(?![A-Za-z])\s*(?:方案|版|會員|訂閱|計畫)|升級\s*(?<![A-Za-z])Pro(?![A-Za-z])")
_PREMIUM_GIVEAWAY = re.compile(r"(?:免費)?(?:送|贈送|贈)\s*(?:一個月|1\s*個月|三個月)?\s*Premium|Premium\s*(?:免費送|免費贈)")
_REFERRAL_REWARD = re.compile(r"推薦\s*\d+\s*(?:人|位)[^。\n]{0,20}?(?:免費|送|贈|Premium)")
_INVITE_ONLY_FREE = re.compile(r"免費方案[^。\n]{0,12}邀請制|邀請制[^。\n]{0,12}免費方案")
_FUTURE_PAYWALL = re.compile(r"(?:未來|日後|之後|即將|將來)[^。\n]{0,10}(?:收費|付費|漲價)")
_ANALYSIS_WORD = re.compile(
    r"個股分析|個別股票的?分析|深度分析|進場價|出場價|停損|停利|買賣價位|選股建議|投資組合健檢")
_PAID_WORD = re.compile(r"付費|訂閱費|升級|Premium|方案|月費|年費")
_NEGATION = re.compile(
    r"不包含|不因付費|不會因|不能因|不得因|免費且相同|一律免費|永遠免費|全部免費|"
    r"不與付費|無關付費|不需付費|不跟任何方案|不掛鉤|不與方案")
# 句子切割:未來收費的合規判準是**句級共現**,不是整篇共現。
# 「全功能限時免費;未來恢復收費後,早鳥用戶永久保留免費使用權」是老闆核定的唯一對外口徑
# (project_marketdaily_free_earlybird),整篇比對會把這句合規文案判成違規(實測誤判 5 則)。
# 真正的紅線只有一種形狀:**同一句話裡**同時講「未來收費」和「個股分析」。
_SENT_SPLIT = re.compile(r"[。！？!?;；\n]+")

# 我方產品數據硬編(2026-05-25 假數字事件 + 2026-05-26 caption 出包的核心地雷)。
# 只錨在「我方統計名詞」上,個股漲跌 % 是事實不受此規範。
_PRODUCT_STAT = [
    (re.compile(r"(?:勝率|命中率|準確率|正確率)\s*[:：]?\s*\d"), "勝率/命中率類我方統計硬編在 caption"),
    (re.compile(r"\d+\s*(?:位|名|個)?\s*(?:訂閱者|訂戶|用戶|讀者|會員)"), "訂閱者/用戶數硬編在 caption"),
    (re.compile(r"\d+\s*\+?\s*(?:個)?\s*(?:來源|資料源|新聞源|資訊源)"), "來源數硬編在 caption"),
]
_SLANG = re.compile(r"鬼話|唬爛|屁話|廢到|智障")
_PLACEHOLDER = re.compile(r"\{\{|\}\}|\bTODO\b|\bTBD\b|lorem ipsum|XX\s*%|xx\s*%", re.IGNORECASE)
_URL = re.compile(r"https?://([^\s/?#)\]]+)")  # host 到 / ? # 為止(不含 query,否則整串 utm 會被當網域)
_ALLOWED_HOSTS = ("marketdaily.ai",)


def _lines(caption: str) -> list[str]:
    return [ln for ln in (caption or "").splitlines() if ln.strip()]


def _duplicated_phrase(caption: str) -> str | None:
    """相鄰重複片語(真實案例:「完整日報 → link in bio in bio」)。

    以空白切 token,看 2-4 個 token 的序列有沒有緊接著自我重複。中文沒有空白,
    整段會變成單一 token → 天然不會誤判中文句子。
    """
    for line in _lines(caption):
        toks = line.split()
        for size in (4, 3, 2):
            for i in range(len(toks) - 2 * size + 1):
                a = toks[i:i + size]
                if a == toks[i + size:i + 2 * size] and any(len(t) > 1 for t in a):
                    return " ".join(a)
    return None


@dataclass
class Finding:
    rule: str
    detail: str


@dataclass
class Verdict:
    post_id: str
    kind: str
    status: str                      # ok | expired | violation
    age_days: int | None = None
    ttl_days: int | None = None
    stale: bool = False
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.status != "ok"

    @property
    def auto_retire(self) -> bool:
        """過期 + 屬於機器自己會再生的型別 → 可以自動退場,不必等人。

        同時帶合規問題的也照樣退場(它反正已經過期、不會再發),但告警仍會逐條列出
        合規 finding,讓根因有人修——退場只處理佇列,不代表問題被吞掉。
        """
        return self.stale and self.kind in AUTO_RETIRE_KINDS

    def reason_text(self) -> str:
        return "; ".join(f"{f.rule}: {f.detail}" for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "id": self.post_id, "kind": self.kind, "status": self.status,
            "age_days": self.age_days, "ttl_days": self.ttl_days,
            "stale": self.stale, "auto_retire": self.auto_retire,
            "findings": [{"rule": f.rule, "detail": f.detail} for f in self.findings],
        }


def check_compliance(caption: str) -> list[Finding]:
    """caption 的紅線掃描。回傳空 list = 乾淨。"""
    out: list[Finding] = []
    cap = caption or ""
    if m := _PRO_PLAN.search(cap):
        out.append(Finding("plan_pro", f"出現已不存在的「Pro」方案:{m.group(0).strip()}"))
    if m := _PREMIUM_GIVEAWAY.search(cap):
        out.append(Finding("premium_giveaway", f"承諾贈送 Premium:{m.group(0).strip()}"))
    if m := _REFERRAL_REWARD.search(cap):
        out.append(Finding("referral_reward", f"推薦獎勵承諾(從未兌現,禁寫):{m.group(0).strip()}"))
    if m := _INVITE_ONLY_FREE.search(cap):
        out.append(Finding("invite_only_free", f"舊「免費方案邀請制」口徑:{m.group(0).strip()}"))
    for sent in _SENT_SPLIT.split(cap):
        if _FUTURE_PAYWALL.search(sent) and _ANALYSIS_WORD.search(sent) and not _NEGATION.search(sent):
            out.append(Finding("future_paywall_on_analysis",
                               f"同句暗示未來對個股分析收費(依法永遠免費):{sent.strip()[:60]}"))
            break
    for sent in _SENT_SPLIT.split(cap):
        if _ANALYSIS_WORD.search(sent) and _PAID_WORD.search(sent) and not _NEGATION.search(sent):
            out.append(Finding("analysis_paywall", f"個股分析與付費同句且無否定聲明:{sent.strip()[:60]}"))
            break
    for pat, msg in _PRODUCT_STAT:
        if m := pat.search(cap):
            out.append(Finding("hardcoded_product_stat", f"{msg}:{m.group(0).strip()}"))
    if m := _SLANG.search(cap):
        out.append(Finding("slang", f"俚俗詞:{m.group(0)}"))
    if m := _PLACEHOLDER.search(cap):
        out.append(Finding("placeholder", f"樣板/佔位符外洩:{m.group(0).strip()}"))
    if dup := _duplicated_phrase(cap):
        out.append(Finding("duplicated_phrase", f"相鄰重複片語:「{dup}」"))
    for host in _URL.findall(cap):
        h = host.lower().split("@")[-1].split(":")[0]
        if not any(h == a or h.endswith("." + a) for a in _ALLOWED_HOSTS):
            out.append(Finding("foreign_link", f"caption 連到非自家網域:{h}"))
    return out


def evaluate(post: dict, now: date) -> Verdict:
    """單則貼文的閘門判決。now 必須由呼叫端注入(禁在此讀系統時鐘)。"""
    pid = post.get("id") or "?"
    kind = infer_kind(pid)
    v = Verdict(post_id=pid, kind=kind, status="ok")

    cdate = extract_content_date(post)
    ttl = ttl_for(post)
    if cdate is not None:
        v.age_days = (now - cdate).days
        v.ttl_days = ttl
        if v.age_days < 0:
            v.status = "violation"
            v.findings.append(Finding("future_date", f"素材日期 {cdate} 在「現在」{now} 之後(時鐘/翻頁問題)"))
            return v

    # 時效與合規**各自獨立算**,不可短路:早期版本一發現合規問題就 return,結果 9 則
    # tldr 同時「重複片語」又「14 天前的市場脈搏」時只報前者,過期事實被藏起來、
    # 也就永遠不會自動退場(佇列頭永久卡死)。兩邊的 findings 一起帶走。
    stale = (cdate is not None and ttl is not None
             and v.age_days is not None and v.age_days > ttl)
    if stale:
        v.status = "expired"
        v.findings.append(Finding("stale", f"素材日 {cdate} 已 {v.age_days} 天(型別 {kind} 上限 {ttl} 天)"))
    compliance = check_compliance(post.get("caption") or "")
    if compliance:
        v.status = "violation"   # 合規問題比過期更需要有人看到,狀態以它為準
        v.findings.extend(compliance)
    v.stale = stale
    return v


def audit(posts: list[dict], now: date, done_ids: set[str] | None = None) -> list[Verdict]:
    """整個佇列的體檢:只看還沒發、也沒 retired 的。"""
    done = done_ids or set()
    return [evaluate(p, now) for p in posts
            if p.get("id") not in done and not p.get("retired")]


def pick_postable(posts: list[dict], now: date, done_ids: set[str],
                  max_scan: int = 200) -> tuple[dict | None, list[Verdict]]:
    """依佇列順序找出第一則過閘的貼文。

    回傳 (該則貼文 or None, 整條待發佇列裡被擋下來的判決清單)。**不是**「第一則被擋就當天
    不發」——佇列頭若卡一則壞內容,那種設計會讓整條線永久停擺(現況 39 篇待發正是這個形狀);
    但也不是無限跳過:被擋的每一則都會被記錄+告警,不會安靜消失。

    掃描**整條佇列**而不是掃到第一則可發就停:過期存貨若留在佇列裡,
    `content_inventory_watchdog` 會把它算進存貨水位 → runway 看起來比真的長。
    """
    blocked: list[Verdict] = []
    picked: dict | None = None
    scanned = 0
    for p in posts:
        if p.get("id") in done_ids or p.get("retired"):
            continue
        scanned += 1
        if scanned > max_scan:
            # 靜默截斷會讓「全部掃過了」變成謊話(feedback_no_silent_limits)
            print(f"  ⚠️ post_gate 只掃了前 {max_scan} 則待發貼文,其餘未檢查")
            break
        v = evaluate(p, now)
        if not v.blocked:
            if picked is None:
                picked = p
            continue
        blocked.append(v)
    return picked, blocked


# ── 落地層:退場 / 待覆核 / 告警去重 ─────────────────────────────────────────
STATE_VERSION = 1
ALERT_COOLDOWN_DAYS = 7


def load_state(path) -> dict:
    """壞掉的 state 不可以讓發文停擺,但也不可以無聲——回空 dict 並讓呼叫端印出來。"""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return {"version": STATE_VERSION, "items": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            raise ValueError("state 結構不對")
        return data
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ post_gate state 讀取失敗({e}),本次以空狀態續跑(告警去重會失效一次)")
        return {"version": STATE_VERSION, "items": {}}


def _atomic_write_json(path, payload) -> None:
    """先寫暫存再 rename:中途被 kill 時目的地仍是完整的舊版(lesson: 半毀檔比舊檔糟)。"""
    from pathlib import Path
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def apply_verdicts(queue_path, state_path, blocked: list[Verdict], now: date) -> dict:
    """把閘門判決落地。

    - `auto_retire` 的(過期 + 機器會再生的型別)→ 在 social_posts.json 標 `retired`,
      佇列頭不會被同一則永久卡住(這正是目前 39 篇積壓的形狀)。
    - 其餘被擋的 → 只寫進 state 等人覆核,**絕不自動刪人做的東西**。
    - 告警去重:同一則 id 每 ALERT_COOLDOWN_DAYS 天最多吵一次。

    回傳 {"retired": [...], "needs_review": [...], "alert_ids": [...]}。
    """
    state = load_state(state_path)
    items = state["items"]
    retired, needs_review, alert_ids = [], [], []

    payload = json.loads(open(queue_path, encoding="utf-8").read())
    posts = payload["posts"] if isinstance(payload, dict) else payload
    by_id = {p.get("id"): p for p in posts}
    changed = False

    for v in blocked:
        rec = items.setdefault(v.post_id, {"first_seen": now.isoformat()})
        rec["status"] = v.status
        rec["reasons"] = v.reason_text()
        rec["last_seen"] = now.isoformat()
        if v.auto_retire and v.post_id in by_id and not by_id[v.post_id].get("retired"):
            by_id[v.post_id]["retired"] = f"gate:{v.status} {now.isoformat()} — {v.reason_text()}"[:400]
            retired.append(v.post_id)
            changed = True
        elif not v.auto_retire:
            needs_review.append(v.post_id)
        last = rec.get("last_alert")
        due = True
        if last:
            try:
                due = (now - date.fromisoformat(last)).days >= ALERT_COOLDOWN_DAYS
            except ValueError:
                due = True
        if due:
            rec["last_alert"] = now.isoformat()
            alert_ids.append(v.post_id)

    if changed:
        _atomic_write_json(queue_path, payload)
    _atomic_write_json(state_path, state)
    return {"retired": retired, "needs_review": needs_review, "alert_ids": alert_ids}


ALERT_MAX_LINES = 5
# ⚠️ 告警權杖在**repo 根目錄**的 .env,不是 marketing/.env(marketing/.env 只有社群平台
# 的 token)。第一版寫成 auto_post.load_env() 讀 marketing/.env → 永遠拿不到 token →
# 閘門擋了東西卻沒有人會知道。沉默的守衛=沒有守衛,所以這條路徑有自測盯著。
ALERT_TOKEN_KEY = "MARKETDAILY_ALERT_TOKEN"
DEFAULT_ALERT_WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev"
ALERT_PATH = "/internal/admin-line-push"
# 裸 urllib 的 User-Agent 會被 Cloudflare 擋(2026-07-10 實測 403/1010)。UA 跟端點放在
# 同一個地方,呼叫端拿 alert_headers() 就不可能忘記——別讓每個新呼叫端各自記得這件事。
ALERT_UA = "Mozilla/5.0 MarketDailyBot/1.0"


def _root_env(repo_root=None) -> dict:
    import os
    from pathlib import Path
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parent.parent
    kv = {}
    f = root / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip().strip('"').strip("'")
    return {**kv, **{k: v for k, v in os.environ.items() if k.startswith("MARKETDAILY_")}}


def resolve_alert_token(repo_root=None) -> str:
    return _root_env(repo_root).get(ALERT_TOKEN_KEY, "")


def alert_endpoint(repo_root=None) -> str:
    base = _root_env(repo_root).get("MARKETDAILY_ALERT_WORKER_URL") or DEFAULT_ALERT_WORKER
    return f"{base.rstrip('/')}{ALERT_PATH}"


def alert_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "User-Agent": ALERT_UA}


def format_alert(result: dict, blocked: list[Verdict], picked_id: str | None) -> str:
    """推播文案。同一批常常是同一個根因(例:9 則 tldr 全中同一個 caption bug),
    逐則列會把手機推播撐爆 → 超過 ALERT_MAX_LINES 就按規則分組講,不丟資訊也不洗版。"""
    by_id = {v.post_id: v for v in blocked}
    picked = [by_id[p] for p in result["alert_ids"] if p in by_id]
    lines = [f"🚦 社群發文閘門擋下 {len(picked)} 則"
             f"(自動退場 {len(result['retired'])}/待覆核 {len(result['needs_review'])})"]
    if len(picked) <= ALERT_MAX_LINES:
        for v in picked:
            tag = "自動退場" if v.auto_retire else "待覆核"
            lines.append(f"· [{tag}] {v.post_id} — {v.reason_text()[:160]}")
    else:
        groups: dict[str, list[Verdict]] = {}
        for v in picked:
            key = ",".join(sorted({f.rule for f in v.findings})) or "unknown"
            groups.setdefault(key, []).append(v)
        for key, vs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            sample = vs[0]
            more = f" 等 {len(vs)} 則" if len(vs) > 1 else ""
            lines.append(f"· [{key}] {sample.post_id}{more} — {sample.reason_text()[:120]}")
    lines.append(f"本次改發:{picked_id}" if picked_id else "本次無可發內容(存貨真空)")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────
def _load_queue(path: str) -> list[dict]:
    data = json.loads(open(path, encoding="utf-8").read())
    return data["posts"] if isinstance(data, dict) else data


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="社群品牌貼文發文閘門")
    ap.add_argument("queue", nargs="?", help="social_posts.json 路徑")
    ap.add_argument("--now", help="YYYY-MM-DD,覆寫「現在」(測試/回溯用)")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--include-posted", action="store_true",
                    help="連已發過的也掃(用來抓詞表誤判:已發出去的歷史貼文原則上該是乾淨的)")
    a = ap.parse_args(argv)

    from pathlib import Path
    qpath = a.queue or str(Path.home() / "Delvin-agent" / "marketing" / "social_posts.json")
    now = datetime.strptime(a.now, "%Y-%m-%d").date() if a.now else date.today()
    posts = _load_queue(qpath)

    done: set[str] = set()
    if not a.include_posted:
        logp = Path(qpath).parent / "social_out" / "post_log.jsonl"
        if logp.exists():
            for line in logp.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if any(x.get("ok") for x in (rec.get("results") or {}).values()):
                    done.add(rec.get("post"))

    verdicts = audit(posts, now, done)
    if a.json:
        print(json.dumps([v.to_dict() for v in verdicts], ensure_ascii=False, indent=2))
    else:
        ok = [v for v in verdicts if v.status == "ok"]
        exp = [v for v in verdicts if v.status == "expired"]
        vio = [v for v in verdicts if v.status == "violation"]
        print(f"社群發文閘門稽核 @ {now} — 待發 {len(verdicts)}:過閘 {len(ok)} / 過期 {len(exp)} / 違規 {len(vio)}")
        for v in exp + vio:
            tag = "⏳過期" if v.status == "expired" else "🚫違規"
            retire = " (可自動退場)" if v.auto_retire else ""
            print(f"  {tag} {v.post_id}{retire} — {v.reason_text()}")
        if ok:
            print(f"  ✅ 下一則可發:{ok[0].post_id}")
    return 1 if any(v.status == "violation" for v in verdicts) else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
