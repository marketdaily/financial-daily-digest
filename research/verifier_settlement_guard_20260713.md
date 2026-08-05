# Adversarial verification — spurious-bar settlement guard in `scripts/build_track_record.py`

Date: 2026-07-13
Verifier: independent adversarial pass (fresh context)
Target: guard added to `fetch_prices` (`_market_of`, `_market_consensus_days`, `_filtered_sorted_dates`)
Runtime used: `.venv/bin/python` (has bs4). Module loaded by `exec(compile(src, path, "exec"), {"__file__": <path>, "__name__": "mod"})`.

## OVERALL VERDICT: SOUND-WITH-CORRECTIONS

The guard is **behavior-preserving on the current frozen cache (0 bars dropped, independently reproduced)** and is **boundary/index-safe** (no IndexError at first/last element, min-5 fallback correct, rec-date-dropped handled). It does not silently change any public number *today*.

However it introduces one **real, demonstrable failure mode (HIGH)**: under an uncommon-but-genuine Yahoo data condition (a single real trading date returned/null-closed for the *majority* of feeds while a *minority* keeps it), the guard drops that **real** trading day from the clean-minority tickers, shifting their positional settlement window by one → wrong settlement price → wrong win/loss label frozen forever. This is the exact error class the fix targets, now inflicted on the tickers that had *correct* data. Current data already contains a real TW trading day (2026-04-09) sitting at 0.05 market-frequency — i.e. real days genuinely land deep inside the drop-zone band; only the *contiguity* of the ragged history edge (not the threshold design) keeps it alive.

Plus latent MED/LOW soundness issues (over-broad drop band vs the "one dirty feed" claim; ticker misclassification of lettered TW instruments). None fire on current data.

---

## FINDING 1 — HIGH — False-drop of a REAL trading day creates a NEW frozen settlement error

**Defect.** `_filtered_sorted_dates` drops any date whose market-frequency ≤ 0.15 when both neighbors are ≥ 0.60. "Market-frequency ≤ 0.15" is NOT "spurious bar in one dirty feed" — with n=40 tickers it means "present in ≤ 6 of 40 feeds." So a **real** trading day that Yahoo happens to return for only a minority of feeds (single-date null-close glitch / provider correction hitting most symbols on the day their cache was built, a few clean) is dropped **from the clean-minority tickers**. Their `sorted_dates` loses a real day → `sorted_dates[ref_idx+5]` now points one real day too far → wrong settlement price. Because judge labels are idempotent (frozen on first settlement, never recomputed), the wrong win/loss is frozen into the public track record permanently. This corrupts the tickers that had *correct* data (the glitched majority were already missing the day and are unaffected by the guard).

**Runnable repro** (`.venv/bin/python`, module loaded as above):
```python
# 40 US tickers, real consecutive trading days 2026-05-11..05-22.
# 4 tickers ("full") keep the real day D5=2026-05-15; 36 tickers miss it (Yahoo null-close glitch).
days=["2026-05-11","2026-05-12","2026-05-13","2026-05-14","2026-05-15",
      "2026-05-18","2026-05-19","2026-05-20","2026-05-21","2026-05-22"]
closes={d:100.0+i for i,d in enumerate(days)}   # rising price
hist={t:{d:closes[d] for d in days} for t in ["AAAA","BBBB","CCCC","DDDD"]}
for i in range(36): hist[f"T{i:03d}"]={d:closes[d] for d in days if d!="2026-05-15"}
cons=_market_consensus_days(hist)
# freq D4=1.0  D5=0.10  D6=1.0  -> D5 dropped for AAAA
keep,dropped=_filtered_sorted_dates(hist["AAAA"],"AAAA",cons)   # dropped == ['2026-05-15']
# Recommendation on 2026-05-11, N=5 (5th trading day after):
```
**Output:**
```
freq D4 = 1.0   D5 = 0.1   D6 = 1.0
AAAA dropped: ['2026-05-15']
Settlement date+price WITH guard : 2026-05-19 = 106.0
Settlement date+price TRUE (no drop): 2026-05-18 = 105.0
MISMATCH!
```
The guard moved AAAA's 5-day settlement from the correct 2026-05-18 (105.0) to 2026-05-19 (106.0). With a rising price this can flip a loss into a win (or vice-versa) and freeze it.

**Corroboration that real days land in the drop-zone on live data.** Running the guard over the actual frozen cache and listing dates ≤0.15 whose neighbors qualify:
```
TW: dropped-now=[]  one-flip-from-drop=[('2026-04-09', 0.05, 'nextReal')]
  timeline: ...('2026-04-08',0.05),('2026-04-09',0.05),('2026-04-10',1.0)...
```
2026-04-09 is a genuine TW trading day at 0.05 frequency (present in ~2/40 deep-history tickers). It is NOT dropped only because its *previous* neighbor (2026-04-08) is also 0.05, not because the threshold logic recognizes it as real. In the dense region (all neighbors ~1.0) a single-date minority hole would be dropped outright — see repro above.

**Severity rationale.** HIGH not CRITICAL: does not fire on current cache (0 drops verified — Finding 4), and requires the specific split "one real date present in ≤15% of feeds while both neighbors ≥60%." But it (a) is a genuine, demonstrable regression that (b) corrupts the *correct-data* tickers, (c) produces the very frozen-wrong-label the fix exists to prevent, and (d) real days demonstrably sit at 0.05 freq in live data. Recommend: require the dropped date to be absent from a *large majority* AND present in a *tiny* count (e.g. drop only if freq ≤ ~1-2 tickers AND ≥ ~90% of feeds have both neighbors), or cross-check that the date is a genuine non-trading day via at least K independent feeds *missing* it rather than a positional consensus that also catches sparse-history real days.

## FINDING 2 — MED — "Only one dirty feed" assumption is false; over-broad drop band; symmetric under-drop gap

The code comment claims a spurious bar "只在個別髒 feed 冒出" (appears in only one dirty feed) and drops at freq ≤ 0.15. But 0.15 of 40 = 6 feeds: the guard will drop a date present in **up to 6 clean feeds** (feeding Finding 1). Conversely, a *genuinely* spurious bar that Yahoo injects into >15% of feeds (e.g. a holiday/weekend bar propagated to 8/40 = 0.20 of feeds by a provider-wide issue) is **NOT** dropped (> 0.15) → the guard silently fails to fix the case it was written for. And two adjacent spurious bars, or a spurious bar adjacent to a low-liquidity/ragged-edge day, are never dropped because the neighbor-≥0.60 AND-test fails. Net: the drop band is both too wide for real days and too narrow for multi-feed spurious bars. Under-drop is no worse than status quo (guard just doesn't help); over-drop is the HIGH regression. The band (0.15/0.60) leaves a "grey zone" (0.15 < f < 0.60) where a bar is neither dropped nor counts as a "real" neighbor — a bar at f=0.40 can never anchor a neighbor test, so a true spurious bar sandwiched by two 0.40-freq real days is never dropped.

**Repro (under-drop of a multi-feed spurious bar):** in the Finding-1 harness set the "spurious" date present in 8/40 feeds (freq 0.20) instead of 4 → `_filtered_sorted_dates` returns `dropped == []`; the guard does nothing.

## FINDING 3 — MED/LOW (latent) — Market misclassification by `ticker.isdigit()` for lettered TW instruments / pure-digit US

`_market_of` = `"TW" if ticker.strip().isdigit() else "US"`. Verified against the live ledger + cache: **all 73 current tickers classify correctly** — 4-digit TW equities, 5-6 digit TW ETFs (006208/00919/00878, correctly TW), pure-alpha US (43). No BRK.B / BF.B / mixed-alnum US in current data. But the classifier is fragile for:
- **Lettered TW instruments** (warrants e.g. `07286P`, TDRs, some ETNs) → `.isdigit()` False → dumped into the **US** bucket. Since US and TW have different trading calendars, that instrument's TW-only trading days would be measured against US consensus (all US tickers lack them → low freq) and its bars near US holidays could be dropped as "spurious." If ≥5 US tickers exist (normal), this actively mis-filters that instrument.
- **Pure-digit US tickers** → TW bucket (essentially nonexistent on NYSE/NASDAQ, so ~zero real risk).

**Repro:** `_market_of("07286P")` → `'US'` (should be TW). LOW today (no such tickers recommended), but the classifier will silently misroute the day it appears. Recommend suffix/known-market lookup rather than `isdigit()`.

## FINDING 4 — PASS (reproduced) — Behavior preservation on current clean cache: 0 bars dropped

Independently reconstructed `hist_by_ticker` from `scripts/.price_cache.json` (inverting `yf_symbol`: strip `.TW`/`.TWO` to recover the raw ledger ticker the code actually keys on — confirmed raw tickers are un-suffixed via `personal_ledger.jsonl`), ran `_market_consensus_days` + `_filtered_sorted_dates` over **all 83 cached tickers (TW=40, US=43)**:
```
tickers per market: {'TW': 40, 'US': 43}
TOTAL BARS DROPPED on current clean cache: 0
```
The change is genuinely behavior-preserving on today's data — no silent change to the public win-rate. (US market is pristine: every US date at freq 1.0. TW has a ragged deep-history left edge at 0.05 that is not dropped due to contiguity.)

## FINDING 5 — LOW — Boundary/index cases all safe; min-5 gate and run-to-run consistency note

Verified, no defects:
- **First/last element:** a ticker with an isolated extra first day *and* extra last day → `dropped == []` (the `i>0` / `i<len(sd)-1` guards prevent IndexError and correctly refuse to drop unbounded edges).
- **Min-tickers boundary:** 4 tickers → consensus `{}` → no filtering (correct fallback to original behavior). 5 tickers → active; a day present in 1/5 = 0.20 > 0.15 → not dropped (safe). Exactly-5 works.
- **Recommendation date itself dropped:** `_filtered_sorted_dates` can drop the rec date (freq 0.118 case); it then falls into the existing `today is None or d not in sorted_dates` branch → recomputes ref from next trading day. No crash. (Note: this is the *same* Finding-1 window-shift when the dropped rec date is actually real.)
- **Run-to-run inconsistency (informational):** the guard only activates per-market when that market's bucket ≥5 tickers *in that run*. A sparse run (few US recs) silently disables US filtering. Graceful, but the guard's protection is not deterministic across runs.

**Scope note (not a defect):** the background mentions "duplicate bars" as a spurious-bar type, but `hist_dict` is keyed by ISO date, so duplicate dates collapse to one key and cannot be represented — the guard neither can nor needs to address duplicates; only injected *extra dates* (holiday/weekend) are in scope.

---

## Repro index (all runnable with `.venv/bin/python`, module exec'd with `__file__` set)
1. Behavior preservation (Finding 4): reconstruct hist from cache, `_market_consensus_days` + `_filtered_sorted_dates` over all tickers → 0 drops.
2. False-drop (Finding 1): 40 US tickers, real day in 4/40 feeds, neighbors 40/40 → dropped, settlement 2026-05-18→2026-05-19 mismatch.
3. Near-miss on live data (Finding 1): list dates ≤0.15 with qualifying neighbors → TW 2026-04-09 one condition from being dropped.
4. Boundary tests (Finding 5): min-5, edges, rec-date-dropped — all safe.
5. Misclassification (Finding 3): `_market_of("07286P")` → 'US'.
