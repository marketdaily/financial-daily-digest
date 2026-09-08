#!/usr/bin/env python3
"""Meta Marketing API insights → 每日 campaign/adset/ad 表現 JSONL 帳本。

用法:
  python -m marketing.adops.insights_pull --date 2026-09-08            # 真帳戶(需 META_ADS_TOKEN + META_AD_ACCOUNT_ID)
  python -m marketing.adops.insights_pull --date 2026-09-08 --dry-run  # 用 fixtures/insights_sample.json,每列標 source=fixture
  python -m marketing.adops.insights_pull --since 2026-09-01 --until 2026-09-07

沒有憑證時自動退到 dry-run 並在 stdout 與帳本列明「fixture」;真 API 列標 source=meta_api。
帳本:marketing/adops/ledger/insights_<account>.jsonl,鍵=(date,level,id) 重跑冪等。
本檔只 GET insights,沒有任何會改帳戶的呼叫。
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKETING = HERE.parent
LEDGER_DIR = HERE / "ledger"
FIXTURE = HERE / "fixtures" / "insights_sample.json"
GRAPH = "https://graph.facebook.com/v21.0"

FIELDS = [
    "date_start", "date_stop", "account_currency",
    "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name",
    "objective", "spend", "impressions", "reach", "frequency", "clicks",
    "inline_link_clicks", "ctr", "cpc", "cpm", "actions", "cost_per_action_type",
]
LEVELS = ("campaign", "adset", "ad")
CONVERSION_ACTION_PRIORITY = (
    "offsite_conversion.fb_pixel_lead", "lead", "offsite_conversion.fb_pixel_purchase",
    "purchase", "offsite_conversion.fb_pixel_complete_registration", "complete_registration",
    "onsite_conversion.messaging_conversation_started_7d", "landing_page_view",
)


def load_env():
    env = {}
    for p in (MARKETING / ".env", MARKETING.parent / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    for k in ("META_ADS_TOKEN", "META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def credentials(env):
    """回 (token, account_id, reason)。token 優先用 META_ADS_TOKEN(user/system-user token);
    META_ACCESS_TOKEN 是粉專 token,打 act_ 會 400,所以不拿它充數。"""
    tok = env.get("META_ADS_TOKEN")
    acct = env.get("META_AD_ACCOUNT_ID")
    if not tok and not acct:
        return None, None, "缺 META_ADS_TOKEN 與 META_AD_ACCOUNT_ID(marketing/.env)"
    if not tok:
        return None, acct, "缺 META_ADS_TOKEN(需 user/system-user token 含 ads_read)"
    if not acct:
        return tok, None, "缺 META_AD_ACCOUNT_ID(act_xxxxxxxx)"
    if not acct.startswith("act_"):
        acct = "act_" + acct
    return tok, acct, None


def _get(url, retries=3):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(body).get("error", {})
            except Exception:
                err = {"message": body[:300]}
            last = f"HTTP {e.code} code={err.get('code')} sub={err.get('error_subcode')} {err.get('message')}"
            if e.code in (429, 500, 502, 503) or err.get("code") in (4, 17, 32, 613):
                time.sleep(2 ** i * 5)
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError) as e:
            last = str(e)
            time.sleep(2 ** i * 3)
    raise RuntimeError(f"insights 讀取失敗(重試 {retries} 次):{last}")


def fetch_insights(token, account, since, until, level):
    params = {
        "level": level,
        "fields": ",".join(FIELDS),
        "time_range": json.dumps({"since": since, "until": until}),
        "time_increment": 1,
        "limit": 500,
        "access_token": token,
    }
    url = f"{GRAPH}/{account}/insights?" + urllib.parse.urlencode(params)
    rows = []
    while url:
        data = _get(url)
        rows.extend(data.get("data", []))
        url = (data.get("paging") or {}).get("next")
    return rows


def _actions_map(lst):
    out = {}
    for a in lst or []:
        try:
            out[a["action_type"]] = float(a.get("value", 0))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def normalize(raw, level, source, account):
    actions = _actions_map(raw.get("actions"))
    cpa_map = _actions_map(raw.get("cost_per_action_type"))
    conv_type = next((t for t in CONVERSION_ACTION_PRIORITY if t in actions), None)
    conversions = actions.get(conv_type, 0.0) if conv_type else 0.0
    spend = _f(raw.get("spend"))
    impressions = int(_f(raw.get("impressions")))
    clicks = int(_f(raw.get("clicks")))
    link_clicks = int(_f(raw.get("inline_link_clicks")))
    ids = {"campaign": raw.get("campaign_id"), "adset": raw.get("adset_id"), "ad": raw.get("ad_id")}
    names = {"campaign": raw.get("campaign_name"), "adset": raw.get("adset_name"), "ad": raw.get("ad_name")}
    row = {
        "date": raw.get("date_start"),
        "level": level,
        "id": ids[level],
        "name": names[level],
        "account": account,
        "currency": raw.get("account_currency"),
        "campaign_id": ids["campaign"], "campaign_name": names["campaign"],
        "adset_id": ids["adset"], "adset_name": names["adset"],
        "ad_id": ids["ad"], "ad_name": names["ad"],
        "objective": raw.get("objective"),
        "spend": round(spend, 4),
        "impressions": impressions,
        "reach": int(_f(raw.get("reach"))),
        "frequency": round(_f(raw.get("frequency")), 3),
        "clicks": clicks,
        "link_clicks": link_clicks,
        "ctr": round(_f(raw.get("ctr")) if raw.get("ctr") is not None else (100.0 * clicks / impressions if impressions else 0.0), 4),
        "cpc": round(_f(raw.get("cpc")) if raw.get("cpc") is not None else (spend / clicks if clicks else 0.0), 4),
        "cpm": round(_f(raw.get("cpm")) if raw.get("cpm") is not None else (1000.0 * spend / impressions if impressions else 0.0), 4),
        "conversion_type": conv_type,
        "conversions": conversions,
        "cpa": round(cpa_map.get(conv_type, (spend / conversions if conversions else 0.0)), 4) if conv_type else None,
        "actions": actions,
        "source": source,
        "pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return row


def ledger_path(account):
    return LEDGER_DIR / f"insights_{account or 'fixture'}.jsonl"


def load_ledger(path):
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def upsert(path, new_rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_ledger(path)
    by_key = {(r["date"], r["level"], r["id"]): r for r in existing}
    added = updated = 0
    for r in new_rows:
        k = (r["date"], r["level"], r["id"])
        if k in by_key:
            updated += 1
        else:
            added += 1
        by_key[k] = r
    ordered = sorted(by_key.values(), key=lambda r: (r["date"], r["level"], str(r["id"])))
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered), encoding="utf-8")
    tmp.replace(path)
    return added, updated, len(ordered)


def data_hash(rows):
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda r: (r["date"], r["level"], str(r["id"]))):
        h.update(json.dumps({k: r[k] for k in ("date", "level", "id", "spend", "impressions", "clicks", "conversions")},
                            sort_keys=True).encode())
    return h.hexdigest()[:16]


def pull(since, until, dry_run=False, fixture=FIXTURE, env=None):
    env = env if env is not None else load_env()
    token, account, reason = credentials(env)
    if dry_run or reason:
        fx = json.loads(Path(fixture).read_text(encoding="utf-8"))
        raw_rows = [r for r in fx["rows"] if since <= r["date_start"] <= until]
        source = "fixture"
        account = fx.get("account", "act_FIXTURE")
        note = f"dry-run(fixture={Path(fixture).name}):{reason or '手動指定 --dry-run'}"
        rows = []
        for r in raw_rows:
            rows.append(normalize(r, r["level"], source, account))
    else:
        note = f"meta_api {account}"
        rows = []
        for level in LEVELS:
            for r in fetch_insights(token, account, since, until, level):
                rows.append(normalize(r, level, "meta_api", account))
    path = ledger_path(account)
    added, updated, total = upsert(path, rows)
    summary = {
        "since": since, "until": until, "source": rows[0]["source"] if rows else ("fixture" if (dry_run or reason) else "meta_api"),
        "account": account, "note": note, "rows": len(rows), "added": added, "updated": updated,
        "ledger_total": total, "ledger": (str(path.relative_to(MARKETING.parent)) if path.is_relative_to(MARKETING.parent) else str(path)), "data_hash": data_hash(rows),
    }
    return summary, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="單日(YYYY-MM-DD)")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--dry-run", action="store_true", help="強制用 fixture,不打 API")
    ap.add_argument("--fixture", default=str(FIXTURE))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.date:
        since = until = a.date
    else:
        until = a.until or (date.today() - timedelta(days=1)).isoformat()
        since = a.since or (datetime.fromisoformat(until) - timedelta(days=6)).date().isoformat()
    summary, _ = pull(since, until, dry_run=a.dry_run, fixture=a.fixture)
    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        tag = "🧪 FIXTURE(合成資料,非真實帳戶)" if summary["source"] == "fixture" else "✅ Meta Marketing API"
        print(f"{tag}  {summary['since']}→{summary['until']}  帳戶 {summary['account']}")
        print(f"  {summary['note']}")
        print(f"  列數 {summary['rows']}(新增 {summary['added']} / 更新 {summary['updated']}),帳本共 {summary['ledger_total']} 列 → {summary['ledger']}")
        print(f"  data_hash {summary['data_hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
