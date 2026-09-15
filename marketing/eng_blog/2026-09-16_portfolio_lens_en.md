# The data isolation incident where our own default watchlist leaked into “your holdings”

> The first two posts covered the council + judge multi-model arbitration layer and the taxonomy of the 30 deterministic audit checks. This one dissects a single check, `portfolio_lens_foreign_ticker`, because it is three things at once: a real data isolation incident, an incident caused by the defence itself, and a design lesson that was still live enough to produce a fix while I was writing this.

## First, a correction: the allowlist is 27% larger than the comment says

Rule one of this series is that every number gets re-verified before I write it down. The first number failed. The comment in the code says:

```python
# 改成「必須是真實上市證券」才算外來:台股比對 .tw_names_cache.json(12k 代號)
# ("must be a real listed security" to count as foreign: Taiwan side checks against
#  .tw_names_cache.json, ~12k tickers)
```

The actual count:

```bash
python3 -c "import json;print(len(json.load(open('scripts/.tw_names_cache.json'))))"
# → 15273
```

The engineering log from the day that line was written records 12,019, so the comment was correct when written. The table grew 27% in two months.

My first draft turned that into a tidy conclusion: "an allowlist-based defence has a shelf life." Then I went to verify it and found it was **wrong** — that table re-fetches itself from TWSE and TPEx every hour. I nearly shipped a nice-sounding claim I hadn't checked, in a post whose first red line is that numbers get verified.

The version that survives verification is smaller and more interesting. It's the last section. Everything below is measured today.

## Act one: the most embarrassing way a personalization system can fail

On 2026-07-21 a section of the daily digest called "Portfolio Lens" broke.

The section header says "your" — its content is supposed to be an allocation and valuation view of the holdings *this subscriber picked*. That day it contained ten US tickers from the public default watchlist:

```python
# analyzer.py
default_us = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "TSM", "JPM"]
watchlist_us = user_us_stocks if user_us_stocks else default_us
```

The visible symptoms: the allocation breakdown gained ten US positions out of nowhere, and the "expensive on DCF" row named **not a single ticker the reader actually owned**.

The direction of this leak is worth a pause. When a personalization system has an isolation bug, the failure you imagine is "user A's data appeared in user B's email" — severe, but easy to explain. This was the opposite: **public data leaked into a private view**. No subscriber's privacy was touched. Not one byte crossed between users. But the reader opened "your portfolio" and saw ten stocks they had never bought.

The technical loss was zero. The trust loss was total. A personalization product sells exactly one thing — *this email knows me* — and that section proved on the spot that it didn't. It's worse than an obvious bug, because the reader now has no way to tell which of the other sections are also fake personalization.

### The fix, in three layers

1. **Spec layer.** Any section whose header says "your" must draw its tickers **entirely** from the real holdings passed in. In the curated-picks scenario (the subscriber picked no stocks in that market, so the system sends an AI-committee selection instead) holdings *are* the picks list, and the same constraint applies. A pure public report with no holdings is not checked — it never claimed to be personalized.
2. **Check layer.** `digest_audit.py` gained `portfolio_lens_foreign_ticker` at severity HIGH. HIGH carries weight in this system: it triggers the full retry chain — wait 60s, regenerate the whole email with a stronger model, and if that still fails, fall back to a purely deterministic version.
3. **Fallback layer.** The fallback version is not allowed to pass generic content off as personalized. Degrading is fine; hiding the degradation is not.

Layer 3 reads like boilerplate. It is the setup for act two.

## Act two: the defence turned a subscriber's email into the stripped-down version

Three days later, in the 2026-07-24 Taiwan morning digest, this is what landed in my own inbox:

> ⚠️ AI personalization failed today; this is the fallback version.

And that day's audit JSON said `personalization_failed_count: 0`. The report was green. The email was the stripped-down one.

**Root cause A: the token extraction was too coarse.** The first version found "tickers mentioned in the text" like this:

```python
found  = set(re.findall(r"\b[A-Z]{2,5}\b", lens_text))
found |= set(re.findall(r"\b\d{4,6}\b", lens_text))
```

Consider what those two regexes catch in a page of financial prose: years (`2026`), index levels (`23150`), price targets (`1085`), ordinary acronyms (`AI`, `GDP`, `CPI`, `ETF`). Every one of them was classified as "a security you don't hold" → HIGH → retry. The stronger model regenerated perfectly reasonable prose, which contained **different** numbers, which tripped the same HIGH → fallback.

The misfire had a cruel distribution: **the richer the narrative, the likelier the hit**. Experienced-tier personalization carries the most numbers, and Taiwan sessions quote index levels daily, so nearly every Taiwan session hit it. The defence punished hardest exactly the readers the system worked hardest for.

**Root cause B: the report structurally could not show this.** The audit JSON of the time wrote three kinds of fields — `personalization_failed`, `audit_failed`, `by_email` — and **nothing for deterministic fallbacks**. The fallback version is generated by plain code, so re-auditing it scores zero, it never enters `by_email`, and the file-write condition didn't mention fallbacks either. The result was an airtight blind spot: **"we shipped a fallback" had no field to live in**. Only the person opening the email could see it.

This is the second instance of "the check caused the incident" in this series, and harder to catch than the first — that one (`undefined_css_class` degrading everyone) at least showed up red in the report.

## The real fix: replace the heuristic with a real universe

The tempting fix is to subtract the false positives one at a time: years don't count, four-digit numbers starting with 20 don't count, keep a denylist of common three-letter acronyms. That road never ends, and every gap is another subscriber receiving the stripped-down email.

The actual fix inverts the question. Instead of "does this token *look like* a ticker", ask "**is this token a real listed security**":

```python
def _is_real_ticker(tok):
    t = (tok or "").strip().upper()
    if not t:
        return False
    if t.isdigit():
        return t in _tw_ticker_universe() or t in stock_names.TW_NAMES
    return stock_names.is_known(t)
```

Taiwan tickers check against the local ticker table (15,273 entries today); US tickers check against the name library. The effect:

- `2026`, `23150`, `1085`, `AI`, `GDP` → in no table → passed through, no longer killed.
- `AAPL`, `2330` — tickers that **actually leaked in** → in the table → still caught. **The defence did not get weaker.** That is the part that matters: after fixing a false positive, the thing it was built to catch must still be caught, otherwise you only turned the alarm off.

Root cause B was closed in the same change: the audit JSON gained `deterministic_fallback_count` plus the list, and the write condition now covers all three failure kinds (fallback shipped / personalization threw / audit lost points). Shipping a fallback stopped being invisible.

Five frozen cases pin the behaviour: the false-positive samples are no longer killed, real `AAPL`/`6488` leaks are still caught, clean content produces nothing, plus a unit test on `_is_real_ticker`.

## The design rules this produced

**1. Isolate personalized sections with an allowlist contract, not with detection.** "Find everything that shouldn't be here" requires enumerating every bad case; "confirm everything here is on the permitted list" requires one list. A gap in the former is silent. A gap in the latter goes red immediately.

**2. Make the allowlist's membership test a real universe, not a heuristic.** "Looks like a ticker" is a heuristic and produces both false positives and false negatives. "Is in a table of 15,273 listed tickers" is a factual lookup and produces neither. The cost is that you now have to maintain that table — which is rule three.

**3. There is a supply line between a defence and its allowlist, and nobody was watching ours.** This rule came out of the verification pass; it wasn't in the outline.

The table itself is alive: `data_fetcher.tw_name_map()` re-fetches TWSE + TPEx hourly, overwrites the disk copy on success, and on failure keeps the last good one ("names never go to zero when the upstream is down" is a deliberate choice, so the digest never prints bare ticker codes).

But the audit side **does not go through that function**. `digest_audit._tw_ticker_universe()` opens the json on disk directly:

```python
with open(p, encoding="utf-8") as f:
    uni = set(json.load(f).keys())
```

So the freshness of the universe the auditor uses depends entirely on whether *somebody else* — the digest generation pipeline — ran, and succeeded. It never refreshes anything itself, and nothing anywhere measured how old that file was. I checked: not one mtime check in the repo.

On a normal day this is invisible; both sides run in the same pipeline. But follow the failure mode through. The upstream fails repeatedly (this happened on 2026-07-09 — an expired `certifi` bundle on the host killed TPEx over SSL) and the disk table freezes at that moment. The digest side has explicit degradation semantics: keep the old names, never go to zero. The audit side had none — it would quietly take a stale universe and answer "is this a real security?", and **a newly listed ticker isn't in the stale table ⇒ judged not-a-security ⇒ passed through**. The defence goes blind precisely where it matters most: on the newest tickers, the ones most likely to be dragged in from a public watchlist. Silently.

That wasn't an incident. It was a fuse that hadn't been lit.

So this post doesn't stop at "worth noting" — the fuse got pulled while writing it. New check, `ticker_universe_stale`, severity MED:

```python
age = _tw_universe_age_days()
if age is None:
    ...  # file gone = the Taiwan half of the defence is effectively off
elif age > TICKER_UNIVERSE_STALE_DAYS:      # 7
    ...  # "newly listed tickers will be judged non-securities and passed through;
         #  this defence is going half-blind"
```

Some deliberate choices in there. It **measures file age, not row count** — a count going up or down says nothing about freshness. It is **MED, not HIGH**: a stale allowlist must not send anyone the stripped-down email, which is exactly the mistake of act two. It only runs on personalized reports that actually consult the allowlist, so public reports get no noise. And the message states the **consequence** ("will be judged non-securities and passed through") rather than the symptom ("file is old"), because whoever sees this alert six months from now needs to know what is being lost, not which file has the older mtime.

Seven regression assertions, the last of which is a mutation control: set the threshold to an absurd number and the preceding assertion must go green. A test that doesn't go green under mutation isn't measuring the threshold at all.

Verifying your own numbers is itself an audit. This is the second time in this series that the verification pass has caught something in our own code.

## Verification commands

```bash
# actual allowlist size
python3 -c "import json;print(len(json.load(open('scripts/.tw_names_cache.json'))))"

# the check and its severity
grep -n "portfolio_lens_foreign_ticker" digest_audit.py

# the public default watchlist (the leak source)
grep -n "default_us = " analyzer.py

# the post-fix membership test
sed -n '/def _is_real_ticker/,/is_known/p' digest_audit.py

# how old the allowlist is (nothing measured this before 2026-09-16)
stat -c '%y  %n' scripts/.tw_names_cache.json
```
