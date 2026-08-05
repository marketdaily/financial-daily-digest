#!/usr/bin/env python3
"""離線 A/B:settlement 位置索引(HEAD)vs 市場共識日曆(working tree)。

同一份凍結 price cache、同一批 keys(帳本 1451 列 ∪ 公開 track-record 87 筆),
兩個模組版本各跑 fetch_prices,逐 key 逐欄位 diff + label 翻轉量化。
零網路(yahoo_chart patch 成從凍結 cache 供資料)、零寫檔(save_cache no-op)。

⚠️ 方法學勘誤(2026-07-13 驗證者 F2,verifier_settlement_calendar_20260713.md):
初版用 `type("M",(),g)` 把 exec globals「複製」進 class dict 再 patch class 屬性——
對 fetch_prices.__globals__ 完全無效(patch 全是 no-op),02:32 的首跑實際走了真網路
(每 ticker 抓兩次)並覆寫 scripts/.price_cache.json(樹裡那份 cache 即該跑的產物)。
0-diff 結論倖存(驗證者以修正 harness 獨立重現全部數字),方法學不倖存。
現版:直接 patch exec namespace(函式 __globals__ 即該 dict,保證生效)+ urlopen
tripwire(任何真網路嘗試當場炸)+ patch 有效性 assert + cache sha256 前後不變守衛。

用法: .venv/bin/python research/ab_settlement_calendar_20260713.py
輸出: stdout 摘要 + research/ab_settlement_calendar_20260713.json 全量結果
"""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import types
import urllib.request
from pathlib import Path


def _no_network(*a, **k):
    raise RuntimeError("A/B harness 網路 tripwire:偵測到真實 urlopen(patch 失效或路徑遺漏)")


urllib.request.urlopen = _no_network  # 兩個 exec 模組 import 的是同一個模組物件,全域生效

ROOT = Path(__file__).resolve().parent.parent
CACHE = json.loads((ROOT / "scripts" / ".price_cache.json").read_text())
LEDGER = ROOT / "scripts" / "personal_ledger.jsonl"
PUBLIC = ROOT / "docs" / "data" / "track-record.json"
OUT_JSON = Path(__file__).with_suffix(".json")


class Mod:
    """exec namespace 的屬性視圖:setattr 直寫底層 dict = 函式的 __globals__,patch 必生效。"""

    def __init__(self, g):
        object.__setattr__(self, "_g", g)

    def __getattr__(self, k):
        return self._g[k]

    def __setattr__(self, k, v):
        self._g[k] = v


def load_module(src: str, name: str):
    mod_globals = {"__file__": str(ROOT / "scripts" / "build_track_record.py"), "__name__": name}
    exec(compile(src, f"<{name}>", "exec"), mod_globals)
    return Mod(mod_globals)


def patch(m):
    m.load_cache = lambda: {}
    m.save_cache = lambda c: None
    m.yahoo_chart = lambda sym, *a, **k: CACHE.get(f"{sym}::history")
    m.time = types.SimpleNamespace(sleep=lambda *a, **k: None)
    # patch 有效性 assert(F2 教訓:no-op patch 曾讓「凍結 A/B」實為 live-vs-live)
    assert m.fetch_prices.__globals__ is m._g, "patch target is not the executed namespace"
    assert m.fetch_prices.__globals__["load_cache"]() == {}, "load_cache patch ineffective"
    assert m.fetch_prices.__globals__["save_cache"]({}) is None
    probe = next(iter(CACHE))
    assert m.fetch_prices.__globals__["yahoo_chart"](probe.split("::")[0]) is CACHE[probe], \
        "yahoo_chart patch ineffective"


def run_fetch(m, keys):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        prices = m.fetch_prices(set(keys))
    return prices, err.getvalue()


def main():
    cache_path = ROOT / "scripts" / ".price_cache.json"
    cache_sha_before = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    old_src = subprocess.check_output(
        ["git", "show", "HEAD:scripts/build_track_record.py"], cwd=ROOT, text=True)
    new_src = (ROOT / "scripts" / "build_track_record.py").read_text()
    OLD = load_module(old_src, "ab_old")
    NEW = load_module(new_src, "ab_new")
    for m in (OLD, NEW):
        patch(m)

    # 判定規則本身必須跨版本一致(A/B 只准量結算價差,不准混入規則差)
    assert OLD.JUDGE_RULE_VERSION == NEW.JUDGE_RULE_VERSION, "rule version drift"
    for fn in ("label_from_chg", "settlement_chg", "judge", "judge_holder"):
        co_o, co_n = getattr(OLD, fn).__code__, getattr(NEW, fn).__code__
        assert (co_o.co_code, co_o.co_names, co_o.co_consts) == \
               (co_n.co_code, co_n.co_names, co_n.co_consts), f"{fn} code drift"

    ledger_rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    public = json.loads(PUBLIC.read_text())
    pub_records = public["records"]

    keys = {(r["ticker"], r["date"]) for r in ledger_rows}
    keys |= {(r["ticker"], r["date"]) for r in pub_records}
    print(f"keys: {len(keys)} (ledger rows {len(ledger_rows)}, public records {len(pub_records)})")

    p_old, err_old = run_fetch(OLD, keys)
    p_new, err_new = run_fetch(NEW, keys)
    print(f"computable: old={len(p_old)} new={len(p_new)}")

    FIELDS = ("close", "next_close", "close_5d", "close_21d", "close_63d")
    result = {"n_keys": len(keys), "n_old": len(p_old), "n_new": len(p_new),
              "coverage_only_old": sorted(map(list, set(p_old) - set(p_new))),
              "coverage_only_new": sorted(map(list, set(p_new) - set(p_old))),
              "field_diffs": [], "path_diffs": 0,
              "stderr_old": err_old.strip().splitlines(),
              "stderr_new": err_new.strip().splitlines()}
    for k in sorted(set(p_old) & set(p_new)):
        o, n = p_old[k], p_new[k]
        diffs = {}
        for f in FIELDS:
            ov, nv = o.get(f), n.get(f)
            same = (ov is None and nv is None) or \
                   (ov is not None and nv is not None and abs(ov - nv) < 1e-12)
            if not same:
                diffs[f] = [ov, nv]
        if o.get("path_dates") != n.get("path_dates"):
            result["path_diffs"] += 1
            diffs.setdefault("_path_dates", [o.get("path_dates"), n.get("path_dates")])
        if diffs:
            result["field_diffs"].append({"key": list(k), "diffs": diffs})

    # ── label 翻轉:公開頁 87 筆(每晚 fresh judge → 這是「今晚上線公開數字會不會動」) ──
    flips_pub = []
    for r in pub_records:
        jfn_o = OLD.judge_holder if r.get("type") == "H" else OLD.judge
        jfn_n = NEW.judge_holder if r.get("type") == "H" else NEW.judge
        for hz, field in (("1d", "outcome_1d"), ("5d", "outcome"),
                          ("21d", "outcome_21d"), ("63d", "outcome_63d")):
            lo, ln = jfn_o(r, p_old, hz), jfn_n(r, p_new, hz)
            if lo != ln:
                flips_pub.append({"key": [r["ticker"], r["date"]], "hz": hz,
                                  "class": r["verdict_class"], "old": lo, "new": ln,
                                  "current_public": r.get(field)})
    result["public_label_flips"] = flips_pub

    # ── 帳本 1451 列:label 已凍結(不會被改),量「兩法 chg vs 存檔事實」的一致性 ──
    led = {"computable": 0, "old_vs_stored_mismatch": [], "new_vs_stored_mismatch": [],
           "old_vs_new_mismatch": [], "unstamped_rows": []}
    for r in ledger_rows:
        k = (r["ticker"], r["date"])
        stored = r.get("chg")
        co = OLD.settlement_chg(r, p_old, "5d") if k in p_old else None
        cn = NEW.settlement_chg(r, p_new, "5d") if k in p_new else None
        if r.get("rule") is None:
            led["unstamped_rows"].append({"key": list(k), "class": r["verdict_class"],
                                          "label": r.get("label"), "stored_chg": stored,
                                          "old_chg": co, "new_chg": cn})
        if stored is None or (co is None and cn is None):
            continue
        led["computable"] += 1
        if co is not None and abs(co - stored) > 1e-9:
            led["old_vs_stored_mismatch"].append({"key": list(k), "stored": stored, "old": co})
        if cn is not None and abs(cn - stored) > 1e-9:
            led["new_vs_stored_mismatch"].append({"key": list(k), "stored": stored, "new": cn})
        if co is not None and cn is not None and abs(co - cn) > 1e-9:
            led["old_vs_new_mismatch"].append({"key": list(k), "old": co, "new": cn})
    result["ledger"] = led

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    print("\n=== A/B 摘要 ===")
    print(f"coverage: only-old {len(result['coverage_only_old'])}, only-new {len(result['coverage_only_new'])}")
    print(f"field diffs (5 價欄): {len(result['field_diffs'])} keys; path_dates diffs: {result['path_diffs']}")
    print(f"公開頁 label 翻轉(今晚上線會動的公開數字): {len(flips_pub)}")
    for f in flips_pub[:20]:
        print("  ", f)
    print(f"帳本 chg 事實對比(computable {led['computable']}): "
          f"old≠stored {len(led['old_vs_stored_mismatch'])}, new≠stored {len(led['new_vs_stored_mismatch'])}, "
          f"old≠new {len(led['old_vs_new_mismatch'])}")
    print(f"帳本未蓋章列(9 筆凍錯案): {len(led['unstamped_rows'])}")
    for u in led["unstamped_rows"]:
        print("  ", u)
    print(f"stderr lines: old={len(result['stderr_old'])} new={len(result['stderr_new'])}")
    for ln in result["stderr_new"][:15]:
        print("   [new]", ln)

    cache_sha_after = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    assert cache_sha_before == cache_sha_after, "凍結 cache 被改寫(F2 事故重演)"
    print(f"cache sha256 前後不變: {cache_sha_after[:16]}… (真凍結)")
    print(f"\n全量結果 → {OUT_JSON}")


if __name__ == "__main__":
    main()
