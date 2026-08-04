"""法務部生產面合規哨兵(2026-08-04)。

**要解的問題**:公司所有合規防線都在「產出前」(pricing.test.mjs / post_gate.py / 日報 audit)。
線上頁面 deploy 之後沒有任何東西看過——任一視窗或 agent 改了 `docs/` 直接部署就繞過全部閘門,
而罰則是真的錢(公平法 §42:5萬–2500萬;投顧法 §107:橋頭 111 金訴 235 判 2年2月+沒收 802 萬)。
本檔**抓真的線上頁面**,把 `dept_legal` 的四張檢查表變成每晚會自己跑的判準。

三態(抄 intel/doctor.py 的分辨法,同一個致命歧義):
  clean    掃過了、乾淨
  violation掃過了、咬到紅線
  unknown  **沒掃到**(抓不到頁面/解析失敗)——絕不可跟 clean 混為一談

覆蓋率保證(2026-08-04 突變 harness 教訓:「零覆蓋率」與「全數通過」長得一樣的地方必須有計數器):
  1. 每次跑先 `rules.selfcheck()`——規則自己壞掉(regex 打錯)會讓它從此永遠零命中,
     輸出卻長得像全站乾淨。selfcheck 不過 → exit 3,不進掃描。
  2. 統計每條規則被套用幾次;**有規則一次都沒被套用(pack 名打錯)→ exit 3**。
  3. 掃描成功面數 0 → exit 3。
  4. 有 unknown 面 → 至少 exit 2,報告頭一行就寫「本次未涵蓋 N 面」。

用法:
    python3 -m legal.compliance_watch              # 人看的報告
    python3 -m legal.compliance_watch --json       # 機器讀
    python3 -m legal.compliance_watch --offline    # 只跑規則庫自檢(不連網,給 CI/自測用)
    python3 -m legal.compliance_watch --only md_index,ms_pricing_api
"""
import os
import re
import sys
import json
import html
import time
import argparse
import datetime
import urllib.request
import urllib.error
import concurrent.futures

from legal import rules as R

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# 促銷觀測帳本是**每晚會被寫**的狀態,所以放在 repo 外(同其他 runner 的 state):
# cron 每晚在 tracked 路徑生出改動 = 一堆 cron_abort_if_dirty 生態鏈會被餓死
# (見 capability dirty_tree_watch)。舉證表 price_sold_evidence.json 是人工維護的設定,留在 repo。
_STATE_DIR = os.path.join(os.path.expanduser("~"), ".marketdaily-fallback")
PROMO_LEDGER = os.environ.get("COMPLIANCE_PROMO_LEDGER") or (
    os.path.join(_STATE_DIR, ".compliance_promo_ledger.json") if os.path.isdir(_STATE_DIR)
    else os.path.join(HERE, "promo_ledger.json"))
SOLD_EVIDENCE = os.environ.get("COMPLIANCE_SOLD_EVIDENCE") or os.path.join(
    HERE, "price_sold_evidence.json")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 20
RETRIES = 1

# 單檔促銷上限(天)。與 fortune-ai/worker/src/pricing.js 的 PROMO_MAX_DAYS 同值——
# 那邊是「不准部署」的閘,這邊是「線上真的長怎樣」的哨兵,兩者刻意重複。
PROMO_MAX_DAYS = 60
# 兩檔促銷之間必須恢復定價的最短天數。無縫續檔 = 「限時特惠」變常態價 = 定價虛列
# (公平法 §21;pricing.js 法規紅線 5 明文但**原本沒有任何東西會偵測**,open #95)。
PROMO_MIN_GAP_DAYS = 30

CLEAN, VIOLATION, UNKNOWN = "clean", "violation", "unknown"

SURFACES = [
    {"id": "md_index", "label": "MarketDaily 首頁",
     "url": "https://marketdaily.ai/", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing", "marketdaily_disclaimer"]},
    {"id": "md_pricing", "label": "MarketDaily 方案頁",
     "url": "https://marketdaily.ai/pricing.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_testimonials", "label": "MarketDaily 見證頁",
     "url": "https://marketdaily.ai/testimonials.html", "kind": "html",
     "packs": ["marketdaily"]},
    {"id": "md_track_record", "label": "MarketDaily 戰績頁",
     "url": "https://marketdaily.ai/track-record.html", "kind": "html",
     # 戰績頁是勝率數字的合法真源(公版可查證),不列入 marketing pack
     "packs": ["marketdaily"]},
    {"id": "md_vs_chatgpt", "label": "MarketDaily 對比頁",
     "url": "https://marketdaily.ai/vs-chatgpt.html", "kind": "html",
     "packs": ["marketdaily", "marketdaily_marketing"]},
    {"id": "md_guide", "label": "MarketDaily 使用指南",
     "url": "https://marketdaily.ai/guide.html", "kind": "html",
     "packs": ["marketdaily"]},
    {"id": "md_digest_latest", "label": "日報公版存檔(最新)",
     "url": "@latest_digest", "kind": "html",
     "packs": ["marketdaily", "marketdaily_disclaimer"]},
    {"id": "ms_index", "label": "命書首頁",
     "url": "https://mingshu.tw/", "kind": "html",
     "packs": ["mingshu"]},
    {"id": "ms_pricing_api", "label": "命書定價快照(公平法促銷閘)",
     "url": "https://fortune-ai.delvin-12345678.workers.dev/api/pricing", "kind": "promo",
     "packs": []},
]


# ── 抓取 ────────────────────────────────────────────────────────────────
def fetch(url, timeout=TIMEOUT, retries=RETRIES):
    """回傳 (status, body)。網路層例外一律轉成 (0, 錯誤字串),絕不拋出。"""
    last = (0, "unknown")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.getcode(), raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, f"HTTP {e.code}"
        except Exception as e:
            last = (0, f"{type(e).__name__}: {e}")
            if attempt < retries:
                time.sleep(1.5)
    return last


def latest_digest_url(today=None):
    """公版存檔以日期命名;往前找最多 5 天,回傳第一個 200 的 URL(找不到→None)。"""
    d = today or datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    for back in range(5):
        ymd = (d - datetime.timedelta(days=back)).strftime("%Y-%m-%d")
        for suffix in ("", "_us"):
            url = f"https://marketdaily.ai/output/digest_{ymd}{suffix}.html"
            code, _ = fetch(url, timeout=12, retries=0)
            if code == 200:
                return url
    return None


# ── HTML → 使用者看得到的字 ────────────────────────────────────────────
_DROP = re.compile(r"(?is)<(script|style|template|noscript)\b.*?</\1>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_TAG = re.compile(r"(?s)<[^>]+>")
_SCRIPT = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")
# i18n 字典躺在 inline <script> 裡,是**真的會顯示給用戶看的字**——
# 只抽 quoted 字串(不含 URL/純英數 key),漏掉它等於半個站沒掃到。
_LITERAL = re.compile(r'"((?:[^"\\\n]|\\.){4,300})"' r"|'((?:[^'\\\n]|\\.){4,300})'")
_CJK = re.compile(r"[一-龥]")


def visible_text(page):
    body = _COMMENT.sub(" ", page)
    stripped = _DROP.sub(" ", body)
    text = html.unescape(_TAG.sub(" ", stripped))
    parts = [text]
    for m in _SCRIPT.finditer(body):
        for lit in _LITERAL.finditer(m.group(1)):
            s = lit.group(1) or lit.group(2) or ""
            # 只留含中文的字串:JS 的 selector/class/URL 幾乎都是純英數,留著只會製造噪音
            if _CJK.search(s):
                parts.append(html.unescape(s.replace("\\n", " ").replace('\\"', '"')))
    return re.sub(r"[ \t　]+", " ", "\n".join(parts))


# ── 命書促銷閘(公平法) ─────────────────────────────────────────────────
def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def check_promo(snap, ledger, now_ms=None, write_path=None):
    """回傳 (findings, new_ledger)。snap=/api/pricing 的解析結果。

    這裡的每一條都對應 `fortune-ai/worker/src/pricing.js` 檔頭的法規紅線,差別是
    **那邊擋部署、這邊看線上實況**——線上是 worker 的舊版本、或有人手改 KV,那邊測試全綠也沒用。
    """
    out = []
    led = dict(ledger or {})
    # ⚠️ 逐筆深拷貝,不是 list(...)。淺拷貝會讓我們就地改到呼叫端手上那份帳本——
    #    而帳本裡的 ends_at_ms 正是偵測 rolling timer 的唯一基準,被自己改掉=證據銷毀。
    #    (2026-08-04 突變 M7 存活才揭出來:測試比對的兩份其實是同一個物件,永遠相等。)
    hist = [dict(h) for h in led.get("promos", [])]
    promo = snap.get("promo") or {}
    items = snap.get("items") or {}
    now_ms = now_ms or snap.get("now") or int(time.time() * 1000)

    if not items:
        out.append({"rule": "ms_promo_snapshot", "severity": R.CRITICAL,
                    "law": "公平法 §21", "evidence": "定價快照沒有任何品項——前端會拿不到價格"})
        return out, led

    active = bool(promo.get("active"))
    if active:
        sid = promo.get("id") or "(無 id)"
        starts, ends = promo.get("starts_at"), promo.get("ends_at")
        s_ms, e_ms = _parse_iso_ms(starts), _parse_iso_ms(ends)
        if s_ms is None or e_ms is None:
            out.append({"rule": "ms_promo_window", "severity": R.HIGH, "law": "公平法 §21",
                        "evidence": f"促銷 {sid} 的起訖時間無法解析:{starts!r}→{ends!r}"})
        else:
            days = (e_ms - s_ms) / 86400000.0
            if days > PROMO_MAX_DAYS:
                out.append({"rule": "ms_promo_too_long", "severity": R.HIGH, "law": "公平法 §21",
                            "evidence": f"促銷 {sid} 長 {days:.1f} 天 > 上限 {PROMO_MAX_DAYS} 天"
                                        "——「限時特惠」變常態價,定價即屬虛列"})
            prev = [h for h in hist if h.get("id") == sid]
            if prev:
                old_e = prev[-1].get("ends_at_ms")
                if old_e and e_ms > old_e + 60000:
                    out.append({"rule": "ms_promo_rolling", "severity": R.CRITICAL, "law": "公平法 §21/§25",
                                "evidence": f"促銷 {sid} 的截止時刻往後跳了 "
                                            f"{(e_ms - old_e)/3600000:.1f} 小時(上次觀測 "
                                            f"{_ms_ymd(old_e)} → 現在 {_ms_ymd(e_ms)})——假倒數"})
            else:
                others = [h for h in hist if h.get("id") != sid and h.get("ends_at_ms")]
                if others:
                    last_end = max(h["ends_at_ms"] for h in others)
                    gap = (s_ms - last_end) / 86400000.0
                    if gap < PROMO_MIN_GAP_DAYS:
                        out.append({"rule": "ms_promo_backtoback", "severity": R.HIGH,
                                    "law": "公平法 §21(pricing.js 紅線 5)",
                                    "evidence": f"新促銷 {sid} 距上一檔結束僅 {gap:.1f} 天 "
                                                f"< 應恢復定價 {PROMO_MIN_GAP_DAYS} 天——無縫續檔"})
                hist.append({"id": sid, "starts_at_ms": s_ms, "ends_at_ms": e_ms,
                             "first_seen": _ms_ymd(now_ms)})
            # ⚠️ 只更新 last_seen,**絕不覆寫 ends_at_ms**——帳本裡那個值是「第一次看到的
            #    截止時刻」,正是拿來咬 rolling timer 的基準。覆寫掉等於自己把證據銷毀。
            for h in hist:
                if h.get("id") == sid:
                    h["last_seen"] = _ms_ymd(now_ms)
    else:
        # 促銷未啟動時,實收必須等於定價:不等於代表有第二份價格數字在線上活著
        for pid, it in sorted(items.items()):
            if it.get("price") != it.get("list"):
                out.append({"rule": "ms_price_leak", "severity": R.HIGH, "law": "公平法 §21",
                            "evidence": f"{pid} 無促銷但 price={it.get('price')} ≠ list={it.get('list')}"})
            if it.get("promo"):
                out.append({"rule": "ms_price_leak", "severity": R.HIGH, "law": "公平法 §21",
                            "evidence": f"{pid} 無促銷期間卻回報 promo=true"})

    # 劃線價(compare_at)要有「曾以該價格販售相當數量」的舉證(公處字 098101 華碩案)
    evidence = _load_json(SOLD_EVIDENCE, {}).get("sold", {})
    for pid, it in sorted(items.items()):
        if it.get("compare_at") not in (None, 0) and not evidence.get(pid):
            out.append({"rule": "ms_compare_at_unproven", "severity": R.CRITICAL,
                        "law": "公平法 §21;公處字第098101號(華碩)",
                        "evidence": f"{pid} 對外劃線價 {it.get('compare_at')},"
                                    f"但 legal/price_sold_evidence.json 沒有該品項的定價成交舉證"})

    led["promos"] = hist
    led["last_checked"] = _ms_ymd(now_ms)
    if write_path:
        with open(write_path, "w", encoding="utf-8") as f:
            json.dump(led, f, ensure_ascii=False, indent=1)
    return out, led


def _parse_iso_ms(s):
    if not s:
        return None
    try:
        return int(datetime.datetime.fromisoformat(str(s)).timestamp() * 1000)
    except Exception:
        return None


def _ms_ymd(ms):
    return datetime.datetime.fromtimestamp(ms / 1000 + 8 * 3600, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


# ── 掃描 ────────────────────────────────────────────────────────────────
def scan_surface(sf, write_ledger=True):
    res = {"id": sf["id"], "label": sf["label"], "url": sf["url"],
           "status": UNKNOWN, "findings": [], "rules_run": [], "detail": ""}
    url = sf["url"]
    if url == "@latest_digest":
        url = latest_digest_url()
        if not url:
            res["detail"] = "近 5 天的公版存檔都抓不到(digest 交付可能也出事了)"
            return res
        res["url"] = url

    if sf["kind"] == "promo":
        code, body = fetch(url)
        if code != 200:
            res["detail"] = f"定價快照抓不到(HTTP {code}):{body[:120]}"
            return res
        try:
            snap = json.loads(body)
        except Exception as e:
            res["detail"] = f"定價快照不是合法 JSON:{e}"
            return res
        led = _load_json(PROMO_LEDGER, {})
        findings, _ = check_promo(snap, led, write_path=PROMO_LEDGER if write_ledger else None)
        res["rules_run"] = ["ms_promo_too_long", "ms_promo_rolling", "ms_promo_backtoback",
                            "ms_price_leak", "ms_compare_at_unproven"]
        res["findings"] = findings
        res["status"] = VIOLATION if findings else CLEAN
        res["detail"] = (f"促銷{'啟動中' if (snap.get('promo') or {}).get('active') else '未啟動'}"
                         f",{len(snap.get('items') or {})} 品項")
        return res

    code, body = fetch(url)
    if code != 200:
        res["detail"] = f"HTTP {code}:{body[:120]}"
        return res
    text = visible_text(body)
    if len(text) < 200:
        # 抓到了但幾乎沒有字 = 前端整頁 JS 渲染或被擋 → 這不是「乾淨」,是沒看到
        res["detail"] = f"可見文字僅 {len(text)} 字,判定為沒有真的掃到"
        return res
    applicable = R.rules_for(sf["packs"], sf.get("exclude_rules", ()))
    for rule in applicable:
        res["rules_run"].append(rule["id"])
        for hit in R.check_rule(rule, text):
            res["findings"].append({"rule": rule["id"], "title": rule["title"],
                                    "severity": rule["severity"], "law": rule["law"],
                                    "pattern": hit["pattern"], "evidence": hit["evidence"]})
    res["status"] = VIOLATION if res["findings"] else CLEAN
    res["detail"] = f"{len(text)} 字 / {len(applicable)} 條規則"
    return res


def run(only=None, write_ledger=True, workers=5):
    ok, problems = R.selfcheck()
    report = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "rules_total": len(R.RULES), "selfcheck_ok": ok, "selfcheck_problems": problems,
              "surfaces": [], "unapplied_rules": [], "clean": 0, "violation": 0, "unknown": 0,
              "checks_run": 0, "exit": 0}
    if not ok:
        report["exit"] = 3
        return report

    todo = [s for s in SURFACES if not only or s["id"] in only]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_surface, s, write_ledger): s for s in todo}
        results = []
        for f in concurrent.futures.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                s = futs[f]
                results.append({"id": s["id"], "label": s["label"], "url": s["url"],
                                "status": UNKNOWN, "findings": [], "rules_run": [],
                                "detail": f"掃描器自己爆炸:{type(e).__name__}: {e}"})
    order = {s["id"]: i for i, s in enumerate(SURFACES)}
    report["surfaces"] = sorted(results, key=lambda r: order.get(r["id"], 99))

    applied = set()
    for r in report["surfaces"]:
        report[r["status"]] += 1
        report["checks_run"] += len(r["rules_run"])
        applied.update(r["rules_run"])
    # 只在整批掃描(未 --only)時才判「規則從未被套用」——子集掃描本來就不會全套用
    if not only:
        report["unapplied_rules"] = sorted(r["id"] for r in R.RULES if r["id"] not in applied)

    if report["unapplied_rules"] or report["checks_run"] == 0 or report["clean"] + report["violation"] == 0:
        report["exit"] = 3
    elif report["violation"]:
        report["exit"] = 1
    elif report["unknown"]:
        report["exit"] = 2
    return report


# ── 輸出 ────────────────────────────────────────────────────────────────
_ICON = {CLEAN: "✅", VIOLATION: "🔴", UNKNOWN: "⚠️"}


def render(rep):
    L = []
    if not rep["selfcheck_ok"]:
        L.append("🔴 規則庫自檢失敗——掃描沒有跑。規則壞掉時「全站乾淨」是假的:")
        L += [f"   - {p}" for p in rep["selfcheck_problems"]]
        return "\n".join(L)
    L.append(f"法務合規哨兵 {rep['generated']}  規則 {rep['rules_total']} 條 / "
             f"檢查 {rep['checks_run']} 次")
    L.append(f"  ✅ 乾淨 {rep['clean']} 面 · 🔴 違規 {rep['violation']} 面 · ⚠️ 未涵蓋 {rep['unknown']} 面")
    if rep["unapplied_rules"]:
        L.append(f"  🔴 有規則一次都沒被套用(pack 名打錯?):{', '.join(rep['unapplied_rules'])}")
    L.append("")
    for s in rep["surfaces"]:
        L.append(f"{_ICON[s['status']]} {s['id']:<18} {s['label']}  {s['detail']}")
        if s["status"] == UNKNOWN:
            L.append(f"     ↳ {s['url']}")
        for f in s["findings"]:
            L.append(f"     ✗ [{f['severity']}] {f.get('title') or f['rule']} — {f['law']}")
            L.append(f"       證據:{f['evidence'][:160]}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true", help="只跑規則庫自檢,不連網")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-ledger", action="store_true", help="不寫促銷帳本(測試用)")
    a = ap.parse_args(argv)

    if a.offline:
        ok, problems = R.selfcheck()
        rep = {"generated": "offline", "rules_total": len(R.RULES), "selfcheck_ok": ok,
               "selfcheck_problems": problems, "surfaces": [], "unapplied_rules": [],
               "clean": 0, "violation": 0, "unknown": 0, "checks_run": 0, "exit": 0 if ok else 3}
        print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else
              (f"規則庫自檢:{'✅ 全過' if ok else '🔴 失敗'}({len(R.RULES)} 條)" +
               ("" if ok else "\n" + "\n".join("  - " + p for p in problems))))
        return rep["exit"]

    only = [x for x in a.only.split(",") if x] or None
    rep = run(only=only, write_ledger=not a.no_ledger)
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else render(rep))
    return rep["exit"]


if __name__ == "__main__":
    sys.exit(main())
