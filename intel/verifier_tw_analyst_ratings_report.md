TASK: tw-analyst-ratings-connector
DATE: 2026-07-17
VERDICT: SOUND-WITH-CORRECTIONS
FINDINGS: 4

Independent verification of intel/tw_analyst_ratings.py + patrol.py wiring + offline test suite.
Method: ran the offline test suite, hit the real cnyes API (pages 1-2, all 60 retained titles),
ran the live CLI scan (read-only), fed 9 hostile/malformed payload shapes, and ran an independent
stubbed e2e of patrol.run() in a sandbox with signal_ledger.record monkeypatched to a no-op
(intel/signal_ledger.jsonl and scripts/buy_signal_log.json were never written; their working-tree
diffs pre-date this session per the opening git snapshot).

Author claims reproduced (evidence in Notes): API structure/pagination ✓, live 7/7 unparsed=0 with
2 UMC hits ✓, offline 8 segments pass ✓, patrol 4-point wiring ✓ (git diff shows exactly
import/scan+try-except/_emit/md-stats), thresholds mirror us_analyst (us_analyst.py:101-103:
<4 discard, >=8 red else yellow) ✓, sandbox e2e puts tw_analyst into by_code + md + latest.json
and into the by_code passed to signal_ledger.record ✓.

## F1 [MEDIUM] Single malformed item silently kills the whole scan (fail-soft granularity gap; docstring claim inaccurate)
Symptom: any item-level malformation inside an otherwise-fetched page raises inside
fetch_events' item loop, escaping the per-page try/except (intel/tw_analyst_ratings.py:100-103
only wraps `fetch_fn(page)`). The exception propagates out of fetch_events; scan() (line 134-137)
swallows it and returns [] — including events already parsed from earlier good pages. patrol
prints nothing (its except at patrol.py:186-189 never fires because scan doesn't raise), and no
unparsed stat records the loss. Net effect: one bad item = zero signals for the night, fully silent.
Evidence (commands run in this session):
- `{'items':{'data':[..., None]}}` on page 2 while page 1 was good:
  `fetch_events RAISED, page-1 good events LOST: AttributeError` / `scan result: []`
- Also raise-and-lose: item `None` in list (AttributeError), `publishAt` as string
  (`TypeError: argument must be int or float`), non-string title (AttributeError on .strip),
  pct text "9.9.9%" (regex `[\d.]+` matches it, `_num` raises
  `ValueError: could not convert string to float: '9.9.9'`), top-level JSON being a string/list.
- Docstring at tw_analyst_ratings.py:93 claims "單頁失敗只跳過該頁(fail-soft)" — true only for
  fetch/JSON-decode failures, not for in-page malformation. Test ⑤ only exercises fetch_fn raising.
Fix: wrap the per-item body (lines 105-127) in try/except Exception → count as `unparsed` and
continue; this makes the fail-soft claim true at item granularity and preserves good pages.

## F2 [MINOR] newsId-missing items after the first are silently dropped by None-dedup
Symptom: the first item lacking `newsId` inserts None into seen_ids
(tw_analyst_ratings.py:105-108); every subsequent id-less item is then treated as a duplicate and
skipped before being counted in stats.
Evidence: fixture with two valid titles both missing newsId →
`missing-newsId x2 -> events: ['2330'] {'fetched': 1, 'parsed': 1, 'unparsed': 0}` — the 2303
event vanished without touching any counter. (Test ⑤'s own fixture relies on a missing-newsId
item being included, which only works for the first one.)
Fix: only dedup when news_id is truthy: `if news_id and news_id in seen_ids: continue` /
`if news_id: seen_ids.add(news_id)`.

## F3 [MINOR] Parse-coverage stats are invisible on the patrol path — title-format drift = permanent silent signal loss
Symptom: fetch_events' stats exist "供 CLI/巡檢誠實回報解析覆蓋率" (tw_analyst_ratings.py:94), but
patrol calls scan() which discards stats (line 135: `events, _ = ...`). If cnyes ever tweaks the
fixed title format (e.g. fullwidth parens `（2330-TW）` — the regex only accepts half-width `\(` —
or wording changes), parsing drops to zero forever with no alarm anywhere: scan returns [],
patrol shows "台股共識評等 0 則", indistinguishable from a genuinely quiet day. House rule
「出事1次=當場建偵測器」/zero-silent-loss makes this worth closing at build time since the whole
connector depends on one third-party title template.
Evidence: code path scan()→fetch_events stats dropped; patrol.py:186-189 catches only exceptions,
which scan never raises (verified in hostile-input runs above — every failure mode surfaced as
an empty list, never an exception at patrol level).
Fix: cheapest deterministic detector — in scan(), when `stats["fetched"] >= N` (e.g. 5) and
`stats["parsed"] == 0`, print/log a warning line patrol's stdout captures, or return stats to
patrol and append `|解析 {parsed}/{fetched}` to the md stats segment.

## F4 [MINOR] CLI `scan` double-fetches the feed (stats and hits from different snapshots; unprotected first fetch)
Symptom: main() calls `fetch_events()` (line 157) then `scan(wl)` (line 160) which re-runs
fetch_events — 4 HTTP requests instead of 2, and the printed parse stats can describe a different
snapshot than the hits if a new bulletin lands between calls. Additionally the line-157 call is
outside any try, so a network failure makes the CLI die with a traceback instead of the module's
own "請求全失敗回空 list" posture (scan-path is protected; CLI-path is not).
Evidence: code reading confirmed by live run behavior (two full fetch rounds observed; live run
output: `tw_forecast 近48h:抓到 7 則... 命中且達門檻:2 則`).
Fix: fetch once, derive both stats printout and watchlist filtering from the same events list
(watchlist/level filtering is already pure via level_for).

## Notes
- External claim ① verified live: `news/category/tw_forecast?limit=30&page=N` returns
  items.data with newsId/publishAt(epoch sec)/title; per_page=30, last_page=2, total=60;
  page-2 pagination works. All 60 retained titles matched the two fixed forms
  (17 target_price + 43 eps_estimate, unparsed=0), supporting "FactSet 共識速報專屬分類" for the
  current retention window; historical/future exclusivity is UNVERIFIED (unverifiable here) and
  is exactly the exposure F3 addresses.
- Claim ② reproduced exactly: live CLI `python3 -m intel.tw_analyst_ratings scan` → 7/7 parsed,
  unparsed=0, watchlist(60 檔) hits = 2 (聯電 EPS上修 + 目標價調升+5.11%, both yellow).
- Claim ③ reproduced: offline test suite exits 0 ("OK units / OK tw_analyst_ratings 自測全過").
  Test stats assertion matches code semantics (empty title excluded before `fetched` increments).
- Claim ④ independently re-verified in this session's own sandbox (not trusting the author's):
  stubbed patrol.run() with BRIEFS redirected to /tmp and record() replaced — by_code got
  `{'source':'tw_analyst','level':'red',...}`, md contained "台股共識評等 1 則" and the red line,
  latest.json red[] contained the FactSet line, and record() received the tw_analyst entries.
  Forbidden files intel/signal_ledger.jsonl and scripts/buy_signal_log.json: not written by any
  verification step (CLI scan is read-only; record patched; both files' M status pre-dates this
  session).
- Claim ⑤ threshold parity verified: us_analyst.py:101-103 uses <4 discard / >=8 red / else
  yellow, identical to RED_PCT=8.0 / YELLOW_PCT=4.0.
- Stateless-design margin is better than documented: docstring says "約 10 則/日、單頁 30 則≈3 天";
  measured 60 items over 233.9h ≈ 6.2/day, single page ≈ 4.8 days — conservative in the safe
  direction. Residual risk: an earnings-season spike >30 bulletins/day sustained would compress
  pages=2 (60 items) below the 48h window; no evidence of that rate in current data.
- signal_ledger dedup is all-time (code,source,level) with no expiry (signal_ledger.py:48-64,
  84-86): once (code,'tw_analyst',level) is recorded, later distinct FactSet revisions for the
  same code/level never add ledger rows. This is a pre-existing platform semantic shared by all
  sources (deliberate per the docstring), not introduced by this work — noted, not a finding.
- Missing publishAt is fail-open (item treated as in-window, dated today,
  tw_analyst_ratings.py:112-115,123) — matches test ⑤ fixture; acceptable for a 48h news window.
- ev["date"] is the UTC date; a TW-evening publication gets the prior UTC day. The field is unused
  on the patrol path (format_line carries no date), so cosmetic/CLI-only.
- Regex robustness spot-checks beyond live data: negative pct "幅度約-3%" → abs() ok (tested);
  thousands separators ok; negative EPS ok; near-miss titles (評等維持買進 / 缺數值段 / 裸提及 /
  ""/None) correctly return None (test ③ re-run confirmed).
