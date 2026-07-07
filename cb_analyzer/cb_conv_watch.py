"""轉換價格變動偵測 + 人工覆寫管理。

台灣 CB 轉換價會因除權息/現增/重設條款調整;「最新轉換價」沒有穩定免費 API
(FinMind CB dataset 要贊助會員、MOPS 查詢頁 WAF+改版、thefew.tw 要登入)。誠實三層設計:
  1) 基準 = 老闆 Excel(每期更新)或 TPEx 發行時轉換價(cb_existing)
  2) 偵測 = MOPS 即時重訊 JSON API 每日掃「轉換價格」公告,命中我們追蹤的標的 → 記 alert
  3) 修正 = conv_overrides.json 人工覆寫(python3 cb.py --set-conv 代碼 價格),含日期+備註
報告端:有未解決 alert(晚於基準/覆寫日期)→ 顯著警示「轉換價已調整,請核對」。

  python3 cb_conv_watch.py --scan     掃當日 MOPS 重訊(cron 用;冪等,重跑不重複記)
  python3 cb_conv_watch.py --alerts   列出未解決的轉換價調整警示
"""
import os
import re
import sys
import json
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ALERTS_PATH = os.path.join(HERE, ".conv_alerts.json")
OVERRIDES_PATH = os.path.join(HERE, "conv_overrides.json")
MOPS_API = "https://mops.twse.com.tw/mops/api/home_page/t05sr01_1"
KW = re.compile(r"轉換價格|轉\s*換\s*價")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _roc_to_iso(s):
    """民國 115/07/07 → 2026-07-07;解析失敗回原字串。"""
    m = re.match(r"(\d{3})/(\d{2})/(\d{2})", str(s or ""))
    return f"{int(m.group(1)) + 1911}-{m.group(2)}-{m.group(3)}" if m else str(s or "")


def fetch_announcements(market, count=200):
    """MOPS 即時重訊(當日)。market ∈ sii(上市)/otc(上櫃)。失敗回 []。"""
    try:
        req = urllib.request.Request(
            MOPS_API, data=json.dumps({"count": count, "marketKind": market}).encode(),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                     "Content-Type": "application/json",
                     "Referer": "https://mops.twse.com.tw/mops/"})
        j = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
        return (j.get("data") or []) if isinstance(j, dict) else []
    except Exception:
        return []


def watched_codes():
    """要盯的股票代碼集合 = 老闆 Excel 全部 + 現有 CB 全市場(有 CB 就值得記,量不大)。"""
    codes = set()
    db = _load(os.path.join(HERE, "cb_database.json"), {})
    for i in db.get("items", []):
        codes.add(str(i.get("stock_code")))
    try:
        import cb_existing
        for it in cb_existing.all_items():
            codes.add(str(it.get("stock_code")))
    except Exception:
        pass
    codes.discard("None")
    return codes


def scan(verbose=True):
    """掃 sii+otc 當日重訊,主旨含「轉換價格」且公司在追蹤集合 → 記 alert(冪等)。"""
    alerts = _load(ALERTS_PATH, [])
    seen = {(a["companyId"], a["date"], a["subject"]) for a in alerts}
    codes = watched_codes()
    new = []
    for mk in ("sii", "otc"):
        for r in fetch_announcements(mk):
            subj = r.get("subject") or ""
            cid = str(r.get("companyId") or "")
            if not KW.search(subj) or cid not in codes:
                continue
            key = (cid, r.get("date"), subj)
            if key in seen:
                continue
            seen.add(key)
            a = {"companyId": cid, "name": r.get("companyAbbreviation"),
                 "date": r.get("date"), "date_iso": _roc_to_iso(r.get("date")),
                 "time": r.get("time"), "subject": subj, "market": mk,
                 "resolved": False}
            alerts.append(a)
            new.append(a)
    if new:
        _save(ALERTS_PATH, alerts)
    if verbose:
        print(f"轉換價公告掃描:新增 {len(new)} 筆警示(累計 {len(alerts)})")
        for a in new:
            print(f"  ⚠ {a['date_iso']} {a['name']}({a['companyId']}) {a['subject'][:60]}")
    return new


def pending_alerts(stock_code=None):
    """未解決警示;stock_code 有給就過濾單一公司。"""
    alerts = [a for a in _load(ALERTS_PATH, []) if not a.get("resolved")]
    if stock_code:
        alerts = [a for a in alerts if a["companyId"] == str(stock_code)]
    return alerts


def load_overrides():
    return _load(OVERRIDES_PATH, {})


def set_override(code, price, note=""):
    """人工覆寫最新轉換價(key=債券代碼或股票代碼);同時把該公司警示標記已解決。"""
    ov = load_overrides()
    today = datetime.date.today().isoformat()
    ov[str(code)] = {"conv_price": float(price), "date": today, "note": note}
    _save(OVERRIDES_PATH, ov)
    alerts = _load(ALERTS_PATH, [])
    changed = False
    for a in alerts:
        if not a.get("resolved") and (a["companyId"] == str(code) or str(code).startswith(a["companyId"])):
            a["resolved"] = True
            a["resolved_date"] = today
            changed = True
    if changed:
        _save(ALERTS_PATH, alerts)
    return ov[str(code)]


def apply_override(item):
    """套用覆寫到 item(bond_code 優先於 stock_code)。回 (item, override或None)。"""
    ov = load_overrides()
    hit = ov.get(str(item.get("bond_code"))) or ov.get(str(item.get("stock_code")))
    if hit and hit.get("conv_price"):
        item = dict(item)
        item["conv_price_orig"] = item.get("conv_price")
        item["conv_price"] = hit["conv_price"]
        item["conv_override"] = hit
    return item, hit


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--scan":
        scan()
        return
    if args[0] == "--alerts":
        al = pending_alerts()
        if not al:
            print("無未解決的轉換價調整警示")
        for a in al:
            print(f"⚠ {a['date_iso']} {a['name']}({a['companyId']}) {a['subject']}"
                  f"  → 查到新價後:python3 cb.py --set-conv <債券代碼> <新轉換價>")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
