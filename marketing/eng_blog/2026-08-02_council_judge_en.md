# I run a 9-model LLM council with a judge to write a daily financial newsletter. Here's what actually breaks.

I run MarketDaily, a daily financial email digest. Subscribers pick their holdings (US + Taiwan stocks), and twice a day the system generates a personalized HTML report for each of them and sends it at a fixed time. First commit was 2026-05-19; as of writing that's 75 days and 1,800+ commits of production history, currently serving 21 subscribers. Small scale, but the failure tolerance is basically zero: this is financial content landing in someone's inbox before market open. A hallucinated price target isn't a bug report, it's a trust funeral.

This post is about the reliability layer that makes it survivable: a multi-model council, a judge, and a 31-check deterministic audit gate. Including the three incidents where it failed.

## The problem with "model + fallback"

The naive architecture is: call your main model, fall back to another on error. That handles the failure mode that almost never matters. The failure mode that actually hurts is **silent degradation**: under quota pressure the model returns something that *looks* like a report — right format, right sections, no exception raised — but the analysis inside is mush. No error code fires. Your user finds out before you do.

So the design principle became: **never trust a single model's output, and never trust any model's self-assessment.** Three separated layers:

```
market data ──► structure prior (price vs MA20/MA50 — direction is
                decided by deterministic code, not by any LLM)
                    │
                    ▼
            COUNCIL: 9 configured free-tier seats across 7 providers
            (Gemini x2, Groq, local GPU via Ollama, Cloudflare
             Workers AI x2, OpenRouter, Cerebras, OpenAI —
             seats with no API key auto-skip; ~5 independent
             voices live on a typical day)
                    │  each seat: {lean, conviction, thesis, key_risk}
                    │  quorum: >= 2 seats or no council verdict
                    ▼
            JUDGE: synthesizes consensus AND disagreement
            (free chain: Gemini lite → Groq → if both die,
             take the highest-conviction seat verbatim)
                    │
                    ▼
            report generation (separate LLM chain)
                    │
                    ▼
            AUDIT: 31 deterministic checks on the final HTML
                    │
          HIGH fail ├──► wait 60s, retry with a stronger model
                    │         │ still HIGH
                    │         ▼
                    │    deterministic fallback (no LLM, no price
                    │    targets — a bad email never leaves the building)
                    ▼
              send at the fixed time, every day, no exceptions
```

## Council: disagreement is a feature, not noise

Every stock gets one council round per run (cached across users). Each seat gets identical real market data plus a hard structural constraint: direction is locked by code (price vs MA20 vs MA50). A seat that says "short" on a bullish structure gets demoted to neutral by a plain `if` statement. **No LLM in this system has the authority to flip a direction.** The council only operates on the layer where models are actually useful: thesis, counter-risk, and lean *within* the structurally allowed range.

Then we measure dissent: 0 if all seats agree, 2 if the council contains both long and short, 1 otherwise. Dissent propagates all the way to the final card — high-dissent stocks get forced-conservative wording downstream, and displayed confidence gets pushed down. Confidence is separately capped at 75% by a historical calibration table; the audit treats any number above that as a broken defense, not an opinion.

**Seat selection is quota engineering, not benchmark chasing.** Full disclosure: the council landed on day 42 (2026-06-30) — before that, the system was exactly the naive model+fallback architecture this post opened by criticizing. The seats deliberately span independent vendors' free tiers, because the thing that kills you at 5am is correlated quota exhaustion, not model quality. Some real constraints that shaped the roster:

- Groq's free tier is limited per-minute (8,000 TPM) *and* per-model per-day (200,000 TPD). The council seat uses a *different* model than the report-generation chain, because one shared bucket meant the council ate 197,364 of the 200,000 daily tokens and 45 report calls fell through to a 144-second-per-call backup model. That evening's digest was 1h35 late.
- One seat (a local 14B model on my own GPU) exists purely because it has zero quota and zero network dependency. It's the only survivor when cloud DNS blips or every vendor's quota dies at once.
- One model rewrote a price from the prompt — 385.25 became 385.00. Fabricated precision. It's permanently banned from anything that touches prices, but it's allowed in the council, because council output is JSON opinions with no numbers in them. Blast-radius design beats model trust.

Seats have circuit breakers: quota-dead / missing key / 3 consecutive failures disables the seat for the round. HTTP 402 (billing wall) kills it on the first strike — retrying a payment error is pure waste.

## Judge: synthesize, with an exit

The judge sees all seat opinions as JSON and is instructed to synthesize consensus *and* disagreement, not to parrot the loudest seat. The judge itself has a fallback chain, and if the whole chain dies, the system takes the highest-conviction seat's thesis verbatim. If fewer than 2 seats respond, there's no council verdict at all and the stock goes down the plain single-model path. The entire council is fail-safe: any failure returns partial results and never blocks the send. "Never miss a send" and "never send garbage" are two different guarantees, enforced by two different mechanisms.

## Audit: 31 checks, each one paid for in blood

`audit_digest()` runs 31 named deterministic checks against the final HTML. Every single one maps to a real way a user was (or would have been) angry: tense discipline (at 7am you cannot write "Taiwan stocks rose today" — the market opens at 9), holdings coverage (every stock the user selected must have an action card), fabrication detection (placeholder `XXX` tokens, fake URLs, earnings estimates that don't exist in the data feed), prompt-instruction leakage (the LLM copying its own instructions into the user-facing output), truncation detection, undefined CSS classes.

HIGH failures trigger: wait a full 60 seconds (free tiers are per-minute limited; retrying after 5s just hits the same 429 window and lands on a *weaker* model), regenerate with a stronger model forced to the front, and if it still fails, ship the deterministic fallback — plain code-assembled report, deliberately containing no price levels.

## Three incidents that built the system

**The 429 incident.** Gemini's daily quota ran out; the retry-with-backoff logic burned ~100 seconds per call across the whole run. The digest went out 5 hours late. Fix: two consecutive 429s on one model = quota is dead for the day, fuse the whole model for the run. Retry logic that's correct for transient errors is actively harmful for quota errors — you have to classify.

**The CSS incident, in two acts.** LLMs asked to "reuse the existing CSS classes" would freestyle near-miss names: `news-title` instead of `news-headline`. No stylesheet rule, whole section renders unstyled. Act one: we added an `undefined_css_class` HIGH check. Act two, one week later: the Monday-edition prompt lacked a verbatim skeleton, so **every model** invented classes, all 12 users hit the check, the retry hit it too (same prompt, same disease), and 9 users got the degraded fallback version. The defense became the incident. The real fix was a deterministic repair layer *before* the check: map known near-miss names back to real classes, strip unknown ones (no CSS rule exists, so stripping is a visual no-op). Two lessons: telling an LLM "use the existing classes" is not a spec — a verbatim skeleton is; and before adding any HIGH check, ask "what happens if everyone fails it at once."

**The depth-collapse incident.** All free quotas fused one morning, generation fell to the weakest models, and per-stock reasoning collapsed from 129–165 characters to 48–64. Format was perfect. Prices were present. **Every check passed.** A human caught it. The fix was a statistical one: calibrate against real production history (normal days: median reason length 107–197 chars; the bad day: median 48) and flag a run whose median drops below 80 as systemic collapse. Checking format is easy; checking *depth* requires a baseline measured from your own good days.

One more horizontal defense from that family: if the same HIGH check fires for 3 users in a single run, page the admin immediately. Per-user retry→fallback chains handle individual failures fine and systemic failures terribly — they degrade everyone quietly, one user at a time.

## Was it worth it?

75 days of the newsletter, 34 days of the council, two sends a day. The point was never "9 models are smarter than one." The point is an architecture where direction is decided by deterministic code, LLMs operate only inside structurally safe boundaries, every output is verified by code that doesn't trust it, and every incident becomes a permanent named check. Reliability in high-stakes LLM systems is not a model property. It's an architecture property.

Next post: a taxonomy of all 31 audit checks and their failure modes — including the full anatomy of the check that caused its own incident.
