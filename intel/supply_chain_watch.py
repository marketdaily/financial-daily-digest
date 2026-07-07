"""供應鏈事件守望:偵測「公司宣布新合作/新供應關係」官方事件,推給持股用戶第一時間知道。
信息差引擎(偵測)→ 產品(通知)的第一條即時接線,全免費源:
  台股:MOPS 重大訊息全市場掃描(mops_watch.partnership_news——策略聯盟/合作備忘錄/合資/
       供貨合約/訂單等,澄清/更正類已排除)
  美股:8-K Item 1.01 重大合約(讀 us_8k_signals.jsonl,由 us_8k_poll_runner 每 30 分累積,
       本模組只消費 ledger 不重複打 SEC)
每則新事件 POST alert-worker /internal/supply-chain-event,worker 端負責:
  KV pending(dashboard 產業鏈🆕區塊)+ 比對全體用戶持股發 web push + 站內收件匣 + admin 通知。
紀律:
  只有 worker 回 ack(stored)才落 seen 與本地 ledger——上送失敗下一輪自動重試,
  不會「失敗一次就永遠不再提」(digest_performance_loop cron 同款教訓)。
  seen cache 原子寫入(write-temp-then-replace),防 driver 哨兵砍進程截斷 JSON。
用法:
  python3 -m intel.supply_chain_watch poll          # 正常輪詢(cron 用)
  python3 -m intel.supply_chain_watch poll --dry    # 只列偵測結果,零副作用
  python3 -m intel.supply_chain_watch poll --seed   # 首跑播種:存量全部標記已見,不上送不推播
"""
import os
import sys
import json
import hashlib
import datetime
import urllib.request

from intel import mops_watch

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SEEN_CACHE = os.path.join(HERE, ".sc_watch_seen.json")
LEDGER = os.path.join(HERE, "supply_chain_events.jsonl")
US_8K_LOG = os.path.join(HERE, "us_8k_signals.jsonl")

WORKER_URL = os.environ.get(
    "MARKETDAILY_ALERT_WORKER_URL",
    "https://marketdaily-alert-worker.delvin-12345678.workers.dev")
ENDPOINT = WORKER_URL.rstrip("/") + "/internal/supply-chain-event"

SEEN_KEEP_DAYS = 45
BATCH_CAP = 20


def _load_env_token():
    """從環境或 repo/.env 讀 alert token(stdlib 解析,不引入 dotenv 依賴)。"""
    tok = os.environ.get("MARKETDAILY_ALERT_TOKEN") or os.environ.get("MARKETDAILY_INTERNAL_TOKEN")
    if tok:
        return tok
    try:
        with open(os.path.join(REPO, ".env"), encoding="utf-8") as f:
            kv = {}
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip().strip('"').strip("'")
        return kv.get("MARKETDAILY_ALERT_TOKEN") or kv.get("MARKETDAILY_INTERNAL_TOKEN") or ""
    except OSError:
        return ""


def _eid(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _load_seen():
    try:
        with open(SEEN_CACHE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_seen(seen):
    cutoff = (datetime.date.today() - datetime.timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if str(v) >= cutoff}
    tmp = SEEN_CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)
    os.replace(tmp, SEEN_CACHE)


def collect_events(days=2):
    """彙整台股+美股「新合作/新供應關係」候選事件(未去重)。"""
    events = []
    for e in mops_watch.partnership_news(days=days):
        events.append({
            "id": _eid("tw", e["code"], e["date"], e["subject"]),
            "market": "tw", "code": e["code"], "name": e["name"],
            "date": e["date"], "headline": e["subject"],
            "counterparty": e.get("counterparty"), "url": "",
            "source_type": "mops", "keyword": e["keyword"],
        })
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    # filing 新鮮度閘:回填/補追的舊 8-K(如 watchlist 新增股票首輪抓到數月前 filing)
    # 不是「最新動態」,不推也不上架,讓它隨輪詢日期窗口自然過期
    fresh_cutoff = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    try:
        with open(US_8K_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") != "form_8k" or str(row.get("date", "")) < cutoff:
                    continue
                if not any(i == "1.01" for i in (row.get("items") or [])):
                    continue
                if str(row.get("filing_date") or "") < fresh_cutoff:
                    continue
                sym = str(row.get("symbol") or "").upper()
                if not sym:
                    continue
                events.append({
                    "id": _eid("us", sym, row.get("filing_date"), row.get("source")),
                    "market": "us", "code": sym, "name": sym,
                    "date": str(row.get("filing_date") or row.get("date") or ""),
                    "headline": "8-K Item 1.01 重大合約(Material Definitive Agreement)申報",
                    "counterparty": None, "url": str(row.get("source") or ""),
                    "source_type": "8k", "keyword": "8-K 1.01",
                })
    except OSError:
        pass
    return events


def _post_batch(batch, token):
    payload = {"events": batch}
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode(),
        # 自訂 UA:預設 Python-urllib 會被 Cloudflare WAF 擋 403(notify_admin.py 同款教訓)
        headers={"content-type": "application/json", "authorization": "Bearer " + token,
                 "User-Agent": "md-winrig-scwatch/1.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def poll(dry=False, seed=False):
    seen = _load_seen()
    # code/headline 空值上送必被 worker 退 bad_event,又永不落 seen → 每輪重送+告警迴圈,先擋掉
    new = [e for e in collect_events()
           if e["id"] not in seen and e["code"].strip() and e["headline"].strip()]
    if dry:
        print(f"偵測到 {len(new)} 則新事件(dry,零副作用):")
        for e in new:
            print(f"  [{e['market']}] {e['code']} {e['name']} {e['date']} kw={e['keyword']} "
                  f"cp={e['counterparty'] or '—'}\n     {e['headline'][:80]}")
        return 0
    if seed:
        # 首跑播種:把目前偵測得到的全部標記已見,不上送不推播——
        # pending/推播從「播種之後真正新增的事件」開始,絕不把存量當新聞
        today = datetime.date.today().isoformat()
        for e in new:
            seen[e["id"]] = today
        _save_seen(seen)
        print(f"seed 完成:{len(new)} 則既有事件標記已見,未上送")
        return 0
    if not new:
        print("無新供應鏈事件")
        return 0
    token = _load_env_token()
    if not token:
        print("缺 MARKETDAILY_ALERT_TOKEN,無法上送", file=sys.stderr)
        return 1
    today = datetime.date.today().isoformat()
    acked, failed = 0, 0
    for i in range(0, len(new), BATCH_CAP):
        batch = new[i:i + BATCH_CAP]
        try:
            resp = _post_batch(batch, token)
        except Exception as exc:
            print(f"上送失敗(下一輪重試): {exc}", file=sys.stderr)
            failed += len(batch)
            continue
        ok_ids = {r.get("id") for r in (resp.get("results") or []) if r.get("stored")}
        with open(LEDGER, "a", encoding="utf-8") as f:
            for e in batch:
                if e["id"] in ok_ids:
                    seen[e["id"]] = today
                    f.write(json.dumps({**e, "sent_at": today}, ensure_ascii=False) + "\n")
                    acked += 1
                else:
                    failed += 1
    _save_seen(seen)
    print(f"供應鏈事件:上送成功 {acked} 則,失敗 {failed} 則")
    return 1 if failed else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] != "poll":
        print(__doc__)
        sys.exit(0)
    sys.exit(poll(dry="--dry" in args, seed="--seed" in args))
