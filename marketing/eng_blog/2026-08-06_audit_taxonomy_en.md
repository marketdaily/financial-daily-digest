# The 31st check didn't exist: a failure-mode taxonomy of auditing LLM output in production

We run a daily finance email. Subscribers pick their holdings; an LLM pipeline generates a personalized HTML digest twice a day; a deterministic audit inspects the final HTML before anything gets sent. In the previous post I described the architecture (multi-model council, judge, audit-retry-fallback). This post dissects the audit layer itself: every check, what incident created it, and — the interesting part — two cases where the defense itself became the outage.

## First, a confession

The previous post claimed "31 independently named checks." The fact-check command behind that number was:

```bash
grep -o '"check": "[a-z_0-9]*"' digest_audit.py | sort -u | wc -l   # → 31
```

While building the table for this post, I listed the checks one by one and got 30. The discrepancy: the module docstring contains a usage example with a check name (`tldr_has_tw`) that doesn't exist in the code — the real check is named `tldr_missing_tw`. Counting `fails.append(` call sites gives exactly 30. Our audit system's own audit method produced a false positive, off by one, and it shipped into a published article.

I'm keeping "31" in the title because the phantom check is the best possible opening for a taxonomy of failure modes: even *counting your checks* has a failure mode. The honest number is 30.

## The design contract

The file's docstring states the philosophy: *every check corresponds to one scenario where a user got angry, or predictably will.* Each check has a stable snake_case name, a severity, and — this matters — a comment carrying the date of the incident that created it. The file reads like a fossil record.

Severity is not decoration; it selects a recovery path:

- **HIGH** → sleep 60 seconds (free-tier rate limits are per-minute token windows; retrying after 5s lands in the same window and hits the same 429), regenerate with a stronger model forced, re-audit; still failing → deterministic fallback assembled by pure code, intentionally price-free. Never send a broken email; never fail to send an email. Two separate invariants.
- **MED / LOW** → logged as a quality deduction, email ships anyway.

Of the 30: 20 fixed-HIGH, 6 MED, 2 LOW, and 2 with dynamic severity (an empty TL;DR section escalates to HIGH; four same-direction cards escalate from LOW to MED if the verdict simultaneously preaches caution).

## The full table

| # | check | category | sev | one-line trigger |
|---|---|---|---|---|
| 1 | tw_pre_market_tense | temporal | HIGH | 7 a.m. pre-market email says the TW market "already rose today" (it opens at 9:00) |
| 2 | tw_pre_market_tense_zaoshen | temporal | HIGH | "TW stocks up this morning" — unknowable before the open |
| 3 | us_holiday_tense | temporal | HIGH | US market was closed last night, email says it "closed green/red" |
| 4 | tw_holiday_open_tense | temporal | HIGH | TW holiday, email says "opens at 9:00 this morning" |
| 5 | us_holiday_tonight_tense | temporal | HIGH | US closed tonight, email says "opens tonight" |
| 6 | tw_morning_action_missing | temporal | MED | TW trading day but no card mentions the morning-open action window |
| 7 | us_tonight_action_missing | temporal | MED | US trading night but no card gives a "tonight / after-hours" action |
| 8 | tldr_section_missing | coverage | HIGH | the 30-second summary section is absent entirely |
| 9 | tldr_missing_tw | coverage | HIGH | user holds TW stocks; TL;DR never mentions the TW market |
| 10 | tldr_missing_us | coverage | HIGH | evening US edition; TL;DR never mentions US stocks |
| 11 | tldr_too_short | coverage | HIGH/MED | 0 bullets (empty section) = HIGH; 1–2 bullets = MED |
| 12 | holdings_uncovered | coverage | HIGH | any single holding the user selected lacks an action card |
| 13 | signal_card_missing_battle | coverage | HIGH | an action card lacks the entry/target/stop triple |
| 14 | market_summary_missing_tw | coverage | MED | market-overview section ignores the TW index for a TW holder |
| 15 | fake_urls | fabrication | HIGH | example.com / placeholder.com style URLs in the output |
| 16 | placeholder_prices | fabrication | HIGH | unfilled placeholders: "amounts to XXX billion" |
| 17 | earnings_fabricated_estimates | fabrication | HIGH | "expected EPS" appears when the data layer supplied no verified estimate |
| 18 | confidence_overclaim | fabrication | MED | confidence >75% (historical calibration cap; above it = a defense was bypassed) |
| 19 | speculative_causality | fabrication | LOW | sourceless attribution: "possibly related to…" |
| 20 | prompt_instruction_leak | leakage | HIGH | instructions meant for the LLM copied verbatim into the product |
| 21 | portfolio_lens_foreign_ticker | leakage | HIGH | a "your portfolio" section contains a real listed security the user doesn't hold |
| 22 | ai_output_truncated | structural | HIGH | HTML tail looks cut off (token limit hit) |
| 23 | undefined_css_class | structural | HIGH | body uses a class `<style>` never defines = unstyled block |
| 24 | tw_ticker_bare_code | structural | HIGH | TW cards show bare numeric codes with no company name (name-table wipeout signal) |
| 25 | ticker_no_zh_name | structural | LOW | US ticker with no company name anywhere near it |
| 26 | signal_reason_shallow | depth | HIGH | median reasoning length <80 chars = systemic model-downgrade collapse |
| 27 | signal_reason_vague | depth | HIGH | "next step" contains neither a price nor a time window |
| 28 | isolated_wait_phrase | depth | MED | a bare "wait and see" with no condition (price/event/date) attached |
| 29 | verdict_monoculture | depth | MED/LOW | ≥4 cards all same direction; MED if the verdict simultaneously says "hold off" |
| 30 | news_headline_body_conflict | depth | MED | headline says "rebounded 1.10%", body says "actually fell" |
| 31 | ~~tldr_has_tw~~ | phantom | — | exists only in a docstring example; counted by our fact-check grep; can never fire |

## Six failure modes, and the incidents behind them

**Temporal discipline** is the least obvious category if you've never shipped a pre-market product. The morning email is written before the open, so any completed-tense claim about today's session is a lie by construction, and every holiday combination (our market closed / their market closed / reopening tomorrow) creates a new way to be wrong. Seven of the 30 checks exist because tense errors are the fastest way to make a finance email look like it was written by someone who doesn't trade.

**Coverage contract** encodes the product's founding promise. The comment above `holdings_uncovered` quotes the user verbatim (2026-05-26): every single stock the user selected must get a next-step card. Missing one is HIGH, non-negotiable. The interesting engineering detail: fallback cards (deterministic, intentionally price-free) are exempted from the entry/target/stop requirement — the audit knows which cards chose to omit prices as a safety feature and doesn't punish them for it.

**Fabrication detection** got serious on 2026-06-10, when the digest claimed AAPL's "expected EPS 3.60" while the data source said 1.86 — and added that "the iPhone 15 remains the focus" (it wasn't). The fix is structural, not textual: the pipeline knows whether it fetched a verified estimate today. If it didn't, *any* "expected EPS" phrasing in the earnings section is by definition invented, severity HIGH. Same day produced the self-consistency checks: four cards all screaming "buy in tranches now" under a verdict saying "wait for CPI," and a headline saying oil rebounded above a body saying oil fell.

**Leakage** has two flavors. Prompt leakage (2026-07-22): every card opened with boilerplate like "explain the 'next step' in plain language: for TW stocks say…, for US stocks say…" — instructions for the model, shipped to customers. The check hunts the whole *category* of meta-instruction tells (placeholder brackets, "must include at least N prices", "never write just 'wait'"), not one string. Data leakage (cross-contamination between the default watchlist and a user's personal portfolio view) is check #21 and gets its own post next week.

**Structural integrity** includes my favorite sleeper: `tw_ticker_bare_code`. Ticker-to-company-name expansion is deterministic post-processing — it *cannot* fail under normal conditions. So when an email went out with bare numeric codes (2026-07-09), the check that catches it is really an infrastructure monitor in disguise: an expired CA bundle had silently killed the SSL handshake to the exchange's name API, and the name table was empty. The check inspects content but detects dependency rot.

**Depth** is the category that taught us the most expensive lesson: format checks are cheap, depth checks require a statistical baseline. On 2026-07-23, quota exhaustion cascaded the cards onto weak models. Reasoning collapsed from ~130+ chars to ~48 — with prices present and format perfect, so 29 of 30 checks passed. A human caught it. The fix: calibrate on three normal days (median 107–197, min ≥97, zero cards <80) versus the bad day (median 48, min 46, 5/7 cards <60), then set thresholds in the gap — median <80 or half the cards <60. It detects *fleet-wide collapse* without executing single naturally-terse cards.

## When the defense became the outage

This is the full timeline the previous post only sketched.

**June 29 (a Monday).** LLMs across vendors "creatively" rename CSS classes — `news-title` instead of `news-headline` — and the unstyled blocks ship. Two fixes that day: CSS rules for 16 renamed classes, plus a new HIGH check, `undefined_css_class`: set-difference between classes used in the body and classes defined in `<style>`. Airtight, we thought.

**July 6 (the next Monday — the check's first Monday in production).** The Monday-edition prompt said "reuse the weekday CSS classes" without pasting the literal skeleton; the weekday prompt had full skeleton examples, so weekdays were safe. This landmine was Monday-only. Every model invented near-miss class names. **12 of 12 users hit the HIGH check.** The retry chain did its job faithfully: stronger model, same prompt, same disease. Nine users were downgraded to the deterministic fallback — a deliberately minimal "generation issue" edition. The admin summary alert arrived at 07:24, *after* everything had been sent. Bonus finding: the 05:30 preflight dry-run had died a month earlier during an infrastructure migration, and nobody had noticed, because a dead watchdog is silent in exactly the way a healthy quiet one is.

Ponder what the check accomplished that morning. Without it, 12 users get ugly-but-complete emails. With it, 9 users get gutted ones. The defense converted a cosmetic defect into a content defect.

**The actual fix** went in the same day, and it's the pattern I'd generalize: a deterministic repair layer *before* the check. Twelve known near-miss names map back to the intended class (restoring the intended styling — strictly better than punishing it); unknown classes are stripped (no CSS rule exists, so removal is a visual no-op). The audit check survives as a tripwire of last resort that should never fire again. Plus a lateral circuit breaker: the same HIGH check hitting 3 users within one generation run pushes an operator alert immediately — per-user retry/fallback chains handle individual failures fine and *systemic* failures catastrophically quietly, so you need a cross-user view, and it must fire before the send deadline, not in the postmortem.

## The false-positive massacre

Check #21 was born righteous: on 2026-07-21 a "your portfolio" section had absorbed 10 tickers from the default public watchlist. The first implementation flagged any ticker-shaped token not in the user's holdings.

Then it started shooting civilians. Years (2026), index levels (23150), price levels (1085), acronyms (AI, GDP, ETF) — all ticker-shaped. On 2026-07-24 one user's digest failed the check, the retry regenerated with a stronger model, the new version tripped over a *different* number, and both versions were executed. Full fallback. The victim was the owner of the product, two days running.

The cure: change the predicate from "looks like a ticker" to "**is a real listed security**" — match against the actual TW universe (~12k listed codes) and the US name table. Genuinely leaked tickers are real securities, so they're still caught at full strength; years and prices aren't in any universe, so they pass. Heuristic denylists never enumerate all exceptions; a real-world universe is the correct boundary.

That incident also produced a taxonomy *within* the taxonomy: HIGH checks are now classed as **soft** (content complete and correct, merely shallow — short reasoning, vague phrasing, thin TL;DR) versus **hard** (broken layout, fake numbers, bare codes, truncation, missed holdings, tense errors, leaks). Soft failures arguably shouldn't cost a user the full edition; hard ones must. That distinction now feeds the fallback decision.

## Rules we paid for

1. **One incident = one detector, same day**, with the date fossilized in the check's comment. The audit file doubles as the system's medical chart.
2. **Before adding a HIGH check, ask three questions.** What happens if *everyone* fails it simultaneously? (You need a systemic circuit breaker.) Who absorbs the false positives? (You need a real universe, not a heuristic.) Is failing it worse than the fallback you'll serve instead? (Soft vs. hard.)
3. **MED checks don't trigger retries, so MED checks need repair layers, not regeneration.** Our two action-window checks failed for 11, 7, and 11 users on three consecutive days once quota pressure randomized prompt compliance; the durable fix was a deterministic rewrite layer, with the audit demoted to independent verifier — both sides sharing one regex so the judgment can never diverge.
4. **The checks themselves fail.** A regex that missed "9:00 open" when two extra characters sat in between; a lookbehind that mistook a price for a time-of-day; a fact-check grep that counted a docstring. Audit code needs its own adversarial case set.

The system's default stance is "prefer false positives over misses." After July, the complete sentence is: prefer false positives over misses — **then build a deterministic repair for every false-positive class you discover, and demote the check to a tripwire.**

*Next post: the full data-isolation incident report — how a public watchlist bled into "your portfolio," and why that's the most embarrassing way a personalization system can fail.*
