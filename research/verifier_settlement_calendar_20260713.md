# Adversarial verification — market-consensus settlement calendar in `scripts/build_track_record.py`

Date: 2026-07-13
Verifier: independent adversarial pass (fresh context)
Target: uncommitted working-tree change replacing spurious-bar consensus filter + per-ticker positional settlement with `_market_trading_calendar` / `_settle_on_calendar`.
Runtime: `.venv/bin/python`; modules loaded via `exec(compile(src, path, "exec"), {...})`; zero network (urlopen monkeypatched to raise in ALL my runs); working tree / cache / ledger / track-record untouched.

## OVERALL VERDICT: SOUND-WITH-CORRECTIONS

The core mechanism is real and validated: on clean uniform data the new method is a byte-exact drop-in (exhaustive synthetic sweep, 0 diffs); the grey-band failure (Finding 2 of the previous verifier) is genuinely fixed; span-aware denominators genuinely rescue ragged left edges; missing-day semantics (carry-back / honest None) behave as claimed; and my independent frozen-cache A/B rerun reproduces **0 field diffs / 0 label flips / 0 coverage diffs** with *exact* float equality — the change does not move any public number today.

But two findings must be addressed before commit:
- **F1 (HIGH, code)**: the base price (`close`) is NOT calendar-protected — a spurious bar landing exactly on the rec date (rec dated on a holiday/Saturday, both live in the ledger: 36 keys on 2026-07-03, 7 keys on 2026-07-11) is used as the base, a **regression vs HEAD**, which dropped it. chg flips from +0.4% to −87% in repro.
- **F2 (HIGH, harness)**: the A/B harness's monkeypatch is a **no-op on the executed code path** (`type("M",(),g)` copies the dict). Its "零網路、零寫檔、凍結 cache" claims are all false: it did live network fetches through the real `yahoo_chart` and **overwrote the frozen cache mid-run** (cache mtime 02:32:35.573 vs result JSON 02:32:35.581). The 0-diff *conclusion* survives (I reproduced it with a corrected harness), the *methodology* does not.

---

## Independent A/B rerun (corrected harness, /tmp/ab_fixed.py)

Globals-level patching (`g["yahoo_chart"]=...` on the exec namespace, verified effective), `urllib.request.urlopen` raises, `save_cache` no-op, exact `!=` comparison (no float tolerance), same keys universe (ledger 1451 rows ∪ public 87 → 1104 unique keys), current `scripts/.price_cache.json` as frozen source:

```
keys: 1104   computable old: 1097  new: 1097
only-old: []  only-new: []
field diffs: 0   path_dates diffs: 0   path diffs: 0
public label flips: 0
ledger computable 1451: old!=stored 0, new!=stored 0, old!=new 0
unstamped (rule=None) rows: 9   stderr old/new: 0/0
```

Matches `research/ab_settlement_calendar_20260713.json` on every number. The 9 unstamped rows are presented faithfully (all 9 `rule=None` rows listed with frozen label + stored/old/new chg; all three chg values agree on today's data — the frozen-wrong labels themselves remain, honestly, untouched pending human decision).

Caveat: the "frozen cache" both runs used is itself the artifact the buggy harness wrote at 02:32 (see F2) — its content (bars through 2026-07-10) is nonetheless a coherent snapshot, and all 1104 keys fall inside every ticker's window, so the equivalence conclusion stands.

---

## FINDING 1 — HIGH — Off-calendar spurious bar on the rec date becomes the settlement BASE (regression vs HEAD)

**Defect.** `_settle_on_calendar` layer-1 base selection runs **before any calendar check**:
```python
if d in hist_dict:
    base_date, close = d, hist_dict[d]
```
If the rec is dated on a non-trading day (US holiday, Saturday) and that ticker's dirty feed carries a spurious bar exactly at `d`, the spurious price becomes `close` — the denominator of `settlement_chg = (ref - close)/close` — and poisons every horizon's chg and label. The stderr `off-calendar bar` warning fires *and then the bar is used anyway*. The old HEAD code **handled this correctly**: `_filtered_sorted_dates` dropped the sandwiched spurious bar, `d not in sorted_dates` routed to the next-real-day branch (the old comment even called this case out explicitly). The layer-3 fallback (`later = [dd for dd in sd if dd >= d]`) is likewise unfiltered and can pick an off-calendar bar as base.

**Liveness.** Rec-dated-on-non-trading-day keys exist in production: 36 keys dated 2026-07-03 (US holiday — the exact date class of the July incident's spurious bar, incl. MSFT/AAPL/NVDA/TSLA) and 7 Saturday keys dated 2026-07-11 (週六版). One future Yahoo holiday/weekend filler bar on such a date re-creates the frozen-wrong-label incident *through the base* instead of the window.

**Repro** (zero network; load OLD=`git show HEAD:...`, NEW=working tree via exec, patch globals):
```python
days = <weekdays 2026-04-13..07-10 minus 05-25,06-19,07-03>; closes = {d: 100+i*0.5}
serve = {f"AA{i}": dict(closes) for i in range(9)}
dirty = dict(closes); dirty["2026-07-03"] = 999.0        # spurious holiday bar
serve["DIRTY"] = dirty
keys = {("DIRTY","2026-07-03")} | {(t,"2026-06-01") for t in serve}
# OLD: close=128.5 (real 07-06), chg_1d=+0.0039
# NEW: close=999.0 (spurious),  chg_1d=-0.8709   ← label flips
```
Observed: `old {'close': 128.5, 'next_close': 129.0}` vs `new {'close': 999.0, 'next_close': 129.0}`; Saturday variant (2026-07-04 bar 555.0) identical failure.

**Fix.** Require the layer-1 base to be on-calendar, and filter layer-3 to calendar days:
```python
if d in hist_dict and (not cal_set or d in cal_set):
    base_date, close = d, hist_dict[d]
elif ref_date in hist_dict: ...
else:
    later = [dd for dd in sd if dd >= d and dd in cal_set]
```
(This restores the old guard's semantic "建議日本身被判偽 → 走下一交易日分支", now on the strictly stronger calendar signal. Re-run the A/B after — on today's clean cache it stays 0-diff since no off-calendar bars exist.)

## FINDING 2 — HIGH (harness validity; conclusion survives) — A/B monkeypatch is a no-op; harness did live network I/O and overwrote the frozen cache

**Defect.** `research/ab_settlement_calendar_20260713.py` does `ns = type("M", (), mod_globals)` then patches `m.load_cache / m.save_cache / m.yahoo_chart` as **class attributes**. `type()` *copies* the dict into the class `__dict__`; `fetch_prices.__globals__` remains the original `mod_globals`, so the executed code kept the **real** `load_cache`, `save_cache`, `yahoo_chart`. (Only `m.time.sleep` worked, by accident — the module object is shared by reference.) Empirically proven:
```python
exec(compile(src,"<ab_new>","exec"), g); M = type("M",(),g)
M.yahoo_chart = staticmethod(lambda *a: None)
M.fetch_prices.__globals__["yahoo_chart"].__code__.co_filename  # '<ab_new>' — original, unpatched
```
Consequences at the 02:32 run: cache freshness (`latest 2026-07-10 < yesterday 2026-07-12`) forced a **real network refetch of every key ticker, twice** (OLD sweep then NEW sweep — the re-saved data still failed `< yesterday`), and the real `save_cache` **rewrote `scripts/.price_cache.json`** (mtime 02:32:35.573, 8 ms before the result JSON at .581). So the published A/B was live-vs-live seconds apart, not frozen-cache; a transient fetch discrepancy between sweeps would have appeared as a false diff (didn't happen here).

**Why the conclusion still stands.** My corrected harness (patches the exec namespace itself, urlopen blocked) reproduces every published number exactly on the current cache. The `assert ... __code__` judge-drift checks read class attributes (never patched) and were valid.

**Fix.** Patch the exec namespace directly (`g["yahoo_chart"] = ...`) or use `types.ModuleType`; add a tripwire (`urllib.request.urlopen = raise`) and an effectiveness assert (`m.fetch_prices.__globals__["load_cache"]() == {}`); correct the docstring in the harness and the "零網路" line echoed in `settlement_spurious_bar_guard.test.sh` header.

## FINDING 3 — MED — Right-edge spurious bar ENTERS the calendar (span-denominator collapse); 1d-freeze incident class remains open; comment ① overclaims

**Defect.** For a spurious bar dated **beyond every clean ticker's last bar** (exactly how holiday/weekend filler bars appear in real time: clean US feeds end 07-02 while the dirty feed prints 07-03), the span-aware denominator collapses to the dirty feeds themselves: `n_cover = cnt` → `fr = 1.0` → the fake day **becomes a consensus trading day**. A rec dated 07-02 on the dirty ticker then settles `next_close` on the spurious bar; if a run happens in that window (weekend runs exist), judge freezes the wrong 1d label. Once clean feeds print 07-06+ the calendar self-corrects (fr drops to ~0.14) — but frozen labels don't. The code comment "①偽 bar 不論出現在幾檔…都進不了日曆" is **false at the right edge**; only interior spurious bars are excluded.

**Repro:** 9 clean feeds through 07-02 + 1 dirty feed with 07-03=777.0 → `"2026-07-03" in cals["US"]` is True (freq 1.0); rec ("DIRTY","2026-07-02") `next_close = 777.0` (truth: None).

**Not a regression** — HEAD fails identically (trailing bar has no next-real neighbor, filter keeps it; repro shows old `next_close = 777.0` too). But "真根治" is overstated: this is precisely the timing profile of the 2026-07 incident's bar, and the fix only closes the *retrospective* window-shift (settlements computed after clean feeds catch up), not same-run right-edge settlements. Suggest: require a calendar day's date to be ≤ the market's consensus max-date (e.g. covered by ≥60% of ALL market spans, or ≥ MIN_TICKERS covering spans) before admitting fr≥0.6, and document the residual window.

## FINDING 4 — MED-LOW (pathological) — Span inflation: one out-of-band spurious bar per dirty feed can knock REAL deep-history days off the calendar (regression in that configuration)

**Defect.** `spans = [(min(h), max(h))]` trusts raw bars. A single ancient spurious bar stretches a feed's span across the whole deep region **without contributing bars there**, inflating `n_cover` and deflating fr for genuine deep days. With 2 genuine deep feeds + 2 dirty feeds carrying one ancient bar each: real deep days drop to fr=0.5 (<0.6, off-calendar) while the ancient fake bar itself gets fr=1.0 (in-calendar).

**Repro:** DEEP0/DEEP1 with bars 04-13.., 36 shallow feeds from 05-11, 2 feeds + spurious "2026-03-02" bar → rec ("DEEP0","2026-04-14"): OLD (correct) `next=52.0, 5d=56.0, 21d=72.0`; NEW `next=61.0, 5d=65.0, 21d=81.0` (settles on shallow-market days ~3 weeks late). `2026-03-02` in calendar: True.

**Liveness:** requires spurious bars *outside* the 3M response window plus deep-history recs pending — implausible with current range-limited fetches; genuine variant (≥40% of deep-covering feeds suspended) is the documented known-limit. Cheap hardening: ignore isolated bars > K days away from a feed's next bar when computing spans, or clamp spans to each feed's contiguous core.

## FINDING 5 — LOW/INFO — "Market consensus" is actually "tickers-with-pending-keys consensus"; silent method flapping at the min-5 gate

`hist_by_ticker` is built only from tickers present in `keys`. A run whose US (or TW) pending-settlement set has <5 tickers silently reverts that market to positional indexing (my first battery run demonstrated this accidentally: 2-ticker keys → no calendar → old behavior, spurious base included, zero warning that the guard is off). Run-to-run the same key can be settled by different methods as the market's key count crosses 5. Same structural property as the old filter (verified equivalent), and today's key universe has 40+ per market — but the protection is weaker than the comment's "市場共識" phrasing implies. Suggest a one-line stderr note when a ≥1-ticker market runs without a calendar.

## FINDING 6 — LOW/INFO — Undisclosed divergence class: rec dates older than a ticker's fetch window (will go live when 63d settlements meet the hardcoded 3M range)

`yahoo_chart` ignores its start/end args (`range=3M` hardcoded). When a rec's 63d settlement matures (~3 months), `d` sits at/off the left edge of that ticker's window. With staggered per-ticker windows (they are staggered — cache entries fetched on different days), old and new then diverge: old counts positions from the ticker's first bar (windows drift late); new anchors to the market calendar at `d` (more correct dates) but `next_close` can degenerate to the base bar itself (chg_1d = 0) when `d` predates the first bar. Repro: staggered-start clean feeds, rec dates inside the market but before a feed's start → 54 field diffs old-vs-new (e.g. RG06 2026-05-06: old next=109.5 (wrong day), new next=109.0 = base bar, chg 0). Zero such keys today (min ledger date 2026-06-01 ≥ all window starts — verified), consistent with the 0-diff A/B. Not a bug introduced by this change, but the "behavior-preserving" guarantee has a known expiry; flag it in the comment and/or make `yahoo_chart` honor its start arg.

---

## Claims scorecard

| # | Claim | Verdict |
|---|-------|---------|
| 1 | A/B behavior-preserving today (0 diff, 0 flips) | **Result TRUE — independently reproduced with exact equality; harness itself broken (F2: patch no-op, live network, cache overwritten)** |
| 2 | Grey-band (>15%) spurious blocked | **TRUE for interior bars** (repro: 3/10=30% spurious excluded, dirty ticker settles at truth 129.0 where old settled wrong at 128.5); **FALSE at the right edge** (F3) |
| 3 | Span-aware ragged left edge | **TRUE** (deep real days fr=1.0 → in calendar, principled not coincidental; test §4 + my 4a) — with the F4 span-inflation caveat |
| 4 | Missing-day semantics (window aligned to market / carry-back+stderr / honest None) | **TRUE** (tests §6–9 + battery case 5: old silently used the day-after-next bar as next_close, new returns None) — except the **base** is not covered (F1) |
| 5 | Known-limit: minority real day → uniform one-day-late, no per-ticker asymmetry | **TRUE** as stated (test §5: full=glitch=107.0); the mirror case (majority-coverage fake day at the right edge, F3) is not stated |
| — | Removed `_filtered_sorted_dates`/`_market_consensus_days`: no remaining callers | **TRUE** (both repos: only .md docs/reports mention them; test suite rewritten against new functions, ALL PASS, and its monkeypatching is correct module-attribute patching) |
| — | 9 unstamped ledger rows presented honestly | **TRUE** (9 = exact `rule=None` count; labels + stored/old/new chg listed as-is) |

## Required corrections before commit
1. **F1**: calendar-gate the base price (layer-1 `d in cal_set`, layer-3 `later` filtered to `cal_set`), then re-run the A/B (expect still 0-diff today).
2. **F2**: fix or annotate the A/B harness (globals-level patching + network tripwire); correct its docstring and the test header's "零網路" echo; note the cache file now in the tree is the harness's own artifact.
3. Soften comment ① (right-edge residual, F3) so the next incident isn't mis-triaged as "already cured".
