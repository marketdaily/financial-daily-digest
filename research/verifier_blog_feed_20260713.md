# Independent Verification — MarketDaily Blog RSS Feed Generator

Date: 2026-07-13
Verifier: fresh-context adversarial review (did not trust author claims; reproduced + attacked)
Scope: `scripts/blog_feed.py`, `docs/feed.xml`, `scripts/seo_articles.py` (step ⑥ + `<link rel=alternate>`),
`stripe-webhook/src/index.js` (`ATTR_SOURCES` += `"rss"`), selftest `~/autonomous/capabilities/tests/blog_feed.test.sh`.
Environment: Python 3.14.4, feedparser available (network NOT blocked).

## Verdict

**SOUND-WITH-CORRECTIONS** — The feed ships valid, well-formed, idempotent, correctly escaped,
correctly attributed, and the pipeline integration is fail-safe. All defects found are LOW severity /
latent (not currently triggered). Two one-line hardenings recommended before shipping, but nothing is
broken with the current 43-article corpus. No CRITICAL or HIGH issues.

---

## What was verified to actually hold (design intents CONFIRMED)

1. **RSS 2.0 well-formedness / reader acceptance** — `feedparser.parse(docs/feed.xml)` → `bozo: False`,
   `43 entries`, channel title/link/description present, every `<item>` has title+description+link+guid.
   `xml.dom.minidom.parse` succeeds. A real RSS library accepts it; Feedly/Substack/Beehiiv importers
   (feedparser-class parsers) will not reject it. `0` bare/unescaped `&` in output.

2. **XML escaping / injection resistance** — Fixture titles containing `& < > " '` and a description
   containing `]]>` + `<script>alert(1)</script>` both round-trip EXACTLY through parse:
   - title `A &amp; B &lt;x&gt; ...` → parsed back to `A & B <x> "q" 'apos'`
   - desc `end]]&gt; &lt;script&gt;...` → parsed back to `end]]> <script>alert(1)</script> & more`
   Output stays well-formed; no CDATA break, no markup injection. `xml.sax.saxutils.escape` escapes
   `& < >`; `_attr` additionally escapes `"` for attribute values.

3. **Idempotency / determinism** — Two in-memory builds are byte-identical AND match the committed
   `docs/feed.xml`. `lastBuildDate = items[0].pub` (newest article date, NOT `now()`).
   `email.utils.format_datetime` uses hardcoded English weekday/month tables (NOT locale-sensitive,
   unlike `time.strftime`). `sorted(glob)` fixes filesystem order; sort key `(pub, slug)` reverse makes
   the 43 items / **17 unique timestamps** (i.e. real date ties exist) deterministic. No `now()`, no set
   iteration, no dict-order dependence.

4. **Date parsing / tz handling** — Verified RFC-822 output for every variant:
   | input | pubDate |
   |---|---|
   | `2026-06-01` (date-only) | `Mon, 01 Jun 2026 00:00:00 +0800` |
   | `2026-06-03T09:00:00` (naive) | `Wed, 03 Jun 2026 09:00:00 +0800` |
   | `2026-06-04T00:00:00Z` (Zulu) | `Thu, 04 Jun 2026 00:00:00 +0000` (UTC preserved) |
   | `2026-06-02T15:30:00+08:00` | `Tue, 02 Jun 2026 15:30:00 +0800` |
   | `...T01:02:03.123456+08:00` | seconds-truncated correctly |
   | `not-a-date` / `` (empty) | **SKIPPED** with `[feed] skip ...: no parseable datePublished` on stderr, no crash |

5. **Sort + MAX_ITEMS** — Newest-first confirmed; `MAX_ITEMS=200` truncation path `print`s the count
   dropped (never silent). Currently 43 < 200 so cap not exercised, but the log statement is present and
   correct. Tie-break deterministic (see #3).

6. **Attribution** — `<item><link>` = `<canonical>?utm_source=rss&utm_medium=feed&utm_content=<slug>`;
   `<guid isPermaLink="true">` = CLEAN canonical (no utm) → importers dedup on stable guid.
   Page beacon (`BEACON_JS`) reads `real = searchParams.get("utm_source"); utm_source = real || "blog"`
   → an RSS-referred visit records `utm_source=rss` (NOT "blog"), so the worker change is meaningful.

7. **Pipeline fail-safety** — `seo_articles.py main()` step ⑥ wraps
   `from blog_feed import build_feed; build_feed(args.dry)` in `try/except Exception` that prints
   `[feed] skip(不阻斷管線)` and continues to `✓ done`. Reproduced with a simulated throwing
   `build_feed` → pipeline still completed. `sys` and `Path` are already imported. `--dry` mode does
   **NOT** write feed.xml (verified: file absent after `build_feed(True)`).

8. **Worker change** — `ATTR_SOURCES` now includes `"rss"` (and `"blog"`). `normalizeSource` lowercases,
   trims, alias-maps (instagram→ig etc.), then `ATTR_SOURCES.includes(v) ? v : "other"`. `utm_source=rss`
   → `"rss"` bucket in `by_source`. Consistent; nothing else needs changing for rss to be recognized.

9. **Selftest quality** — Genuinely exercises escape round-trip, date-only tz-fill, ticker-vs-term
   category, utm-on-link / clean-guid, media:content presence, newest-first sort, idempotency (byte
   compare), and skip-on-missing-date (asserts stderr). It is NOT self-certifying. Exit 0.

---

## Defects found (all LOW / latent — reproduced)

### LOW-1 (latent) — Double `?` when a canonical already contains a query string
`_item_xml` builds the link by naive string concat:
```python
link = f"{it['canonical']}?utm_source=rss&utm_medium=feed&utm_content={it['slug']}"
```
If `canonical` already has a query, the result has TWO `?`. Reproduced with fixture
`canonical=https://marketdaily.ai/blog/x.html?a=1&b=2`:
```
link = https://marketdaily.ai/blog/x.html?a=1&b=2?utm_source=rss&utm_medium=feed&utm_content=evil-url
```
That second `?` is malformed — `utm_source` becomes part of the value of param `b`, breaking attribution.
**Not currently triggered:** all 43 real canonicals are `/blog/<slug>.html` (no query). 
Fix: choose separator via `("&" if "?" in canonical else "?")`, or build with `urllib.parse`.
(Minor sub-note: `utm_content=<slug>` injects raw CJK slug into the query unencoded — harmless as a query
value but not percent-canonical.)

### LOW-2 — Raw non-ASCII (CJK) in `<link>` and `<guid isPermaLink="true">`, not percent-encoded
e.g. `https://marketdaily.ai/blog/8299-新手第一次買要注意什麼-202607.html?...`. These are IRIs, not
strict RFC-3986 URIs. **Verdict (concrete, not hand-waving):** ACCEPTABLE / consistent —
feedparser accepted them (`bozo: False`), the live site already serves these exact paths, and
Chinese-language feeds routinely do this. Risk is limited to (a) W3C Feed Validator *warnings*, and
(b) a hypothetical strict importer that refuses non-ASCII URLs. Since guid consistency within the feed
is preserved (all raw, none mixed), dedup is not harmed. Recommend—but do not require—percent-encoding
the path segment for maximum importer compatibility. Not a blocker.

### LOW-3 (negligible, not currently triggered) — Title regex assumes exactly one `|`
`_TITLE_RE = r"<title>(.+?)\s*\|"` non-greedily stops at the first `|`. A title containing its own `|`
before the `| MarketDaily` suffix would truncate early; a title with no `|` at all falls back to the raw
slug as the `<title>`. All 43 current articles use the `... | MarketDaily` template (feed output shows
clean human titles for every item), so this is latent only.

### OBSERVATION (not a blog_feed.py defect) — pubDate = generation timestamp
Real articles carry `datePublished` = pipeline generation time with microseconds
(e.g. `2026-07-13T01:03:17.353136+08:00`); 43 articles collapse to 17 unique timestamps. If the weekly
pipeline ever REWRITES `datePublished` on existing articles, their pubDate churns and RSS readers may
re-surface old items as new. Mitigated by the stable clean `guid` (importers dedup on guid, so no
duplicate posts). This is a property of the upstream `seo_articles.py` data, not the feed generator;
flagged for awareness only.

---

## Reproduction commands (all run, outputs captured above)
- Selftest: `bash ~/autonomous/capabilities/tests/blog_feed.test.sh` → `ALL PASS`, exit 0.
- Well-formedness: `minidom.parse` OK, 43 items, 0 items missing required, 0 bare `&`.
- feedparser: `bozo: False`, 43 entries.
- Escaping/date/idempotency attacks: temp-BLOG_DIR harness overriding `blog_feed.BLOG_DIR`/`FEED_PATH`.
- Real-data determinism: two `build_feed_xml(collect_items())` calls byte-identical + match committed file.

## Bottom line
Ships correct. Recommend applying **LOW-1** (2-line separator fix) as cheap insurance and optionally
**LOW-2** (percent-encode path) for validator cleanliness. Nothing here blocks production.

**VERDICT: SOUND-WITH-CORRECTIONS**
