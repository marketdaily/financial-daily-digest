"""Vendored copy of ~/autonomous/capabilities/web_design_quality_lint/lint.py.

Source of truth is the capabilities/ copy (built 2026-07-13, hardened by
verifier-separation review). This file is a snapshot so scripts/site_scan.py
does not depend on a path outside this git repo. If the capability gets fixed
or extended upstream, re-copy it here (zero deps, pure functions, no local
edits made in this copy — diff against upstream before touching).

Deterministic web-design-quality linter.

Catches the mechanical "amateur / AI-generated" tells that make a page read as
cheap, BEFORE a human sees it. It is a FLOOR, not a beauty judge: passing does
NOT mean the page is good; failing means it definitely carries a cheap tell.

Zero LLM, zero third-party deps. Calibrated so a genuinely polished, dense real
page (MarketDaily docs/index.html: 38 font-sizes, dozens of hex colors) passes
with no HIGH findings — raw-count checks (type-scale/color-count) are omitted on
purpose because rich real designs legitimately use many sizes and many tints.

lint_html(html, source=None) -> dict:
  {source, has_css, has_body_text, findings:[...], score(0-100), verdict}
verdict: 'fail' (>=1 HIGH) | 'warn' (>=1 MED) | 'ok'
"""
import re

SEV_WEIGHT = {"HIGH": 25, "MED": 10, "LOW": 3}

# generic / OS-default families — a font-family built only from these shows no
# typographic intent. Anything else in the FIRST slot signals a chosen typeface.
SYSTEM_FAMILIES = {
    "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded",
    "-apple-system", "blinkmacsystemfont", "segoe ui", "segoe", "helvetica",
    "helvetica neue", "arial", "roboto", "noto sans", "noto serif", "ubuntu",
    "cantarell", "fira sans", "droid sans", "oxygen", "liberation sans",
    "sans-serif", "serif", "monospace", "georgia", "times new roman", "times",
    "courier", "courier new", "tahoma", "verdana", "trebuchet ms", "cursive",
    "fantasy", "emoji", "math", "fangsong", "inherit", "initial", "unset",
    "menlo", "consolas", "monaco", "apple color emoji", "segoe ui emoji",
    "segoe ui symbol", "noto color emoji", "sf mono", "sf pro", "-apple-system-body",
}

FONT_SERVICES = ("fonts.googleapis.com", "fonts.gstatic.com", "fonts.bunny.net",
                 "use.typekit.net", "fontshare.com", "rsms.me", "fonts.cdnfonts.com")

_STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.I | re.S)
_INLINE_RE = re.compile(r'style\s*=\s*"([^"]*)"', re.I)
_INLINE_RE2 = re.compile(r"style\s*=\s*'([^']*)'", re.I)
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _css_text(html):
    parts = _STYLE_RE.findall(html)
    parts += _INLINE_RE.findall(html)
    parts += _INLINE_RE2.findall(html)
    css = "\n".join(parts)
    return _COMMENT_RE.sub(" ", css)


def _has_body_text(html):
    stripped = _SCRIPT_RE.sub(" ", html)
    stripped = _STYLE_RE.sub(" ", stripped)
    p_count = len(re.findall(r"<p[\s>]", stripped, re.I)) + len(re.findall(r"<li[\s>]", stripped, re.I))
    text = _TAG_RE.sub(" ", stripped)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text) > 400 or p_count >= 3


# ---- checks -----------------------------------------------------------------
# Keyword scans run over CSS with string LITERALS blanked, so a magic word inside
# content:'...' can't suppress (or trigger) a check. Font-service / @import scans
# are scoped to <link> tags + @import rules, never raw <script>/comment/body text.

# escape-aware: `'it\'s'` is ONE string, not `'it\'` + dangling `s'`. A naive
# `.*?` leaves an unbalanced quote that then makes the calc scanner swallow to EOF.
_CSS_STR_RE = re.compile(r"(['\"])(?:\\.|(?!\1).)*\1", re.S)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_IMPORT_RE = re.compile(r"@import\b[^;{]*;", re.I)
_VAR_DEF_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+)")


def _no_strings(css):
    return _CSS_STR_RE.sub("''", css)


def _font_service_linked(html, css):
    scope = (" ".join(_LINK_RE.findall(html)) + " " + " ".join(_IMPORT_RE.findall(css))).lower()
    return any(s in scope for s in FONT_SERVICES)


def _first_family(fam, varmap):
    first = fam.split(",")[0].strip().strip("'\"").lower()
    m = re.match(r"var\(\s*(--[\w-]+)", first)
    if m:
        resolved = varmap.get(m.group(1))
        if resolved is None:
            return None  # unresolvable indirection -> can't judge
        first = resolved.split(",")[0].strip().strip("'\"").lower()
    return first or None


def _c1_typography(html, css):
    if _font_service_linked(html, css):
        return None
    if re.search(r"@font-face\s*\{", _no_strings(css), re.I):
        return None
    fams = re.findall(r"font-family\s*:\s*([^;{}]+)", css, re.I)
    if not fams:
        return None  # nothing declared here (may be external/inherited) -> abstain
    varmap = {k.lower(): v for k, v in _VAR_DEF_RE.findall(css)}
    saw_system = unknown = False
    ev = fams[0].strip()
    for fam in fams:
        first = _first_family(fam, varmap)
        if first is None:
            unknown = True
            continue
        if first not in SYSTEM_FAMILIES:
            return None  # a real chosen typeface exists
        saw_system = True
        ev = first
    if not saw_system or unknown:
        return None  # abstain unless every resolvable family is a system font
    return dict(
        code="typography_intent", severity="HIGH",
        title="No intentional typeface — page uses only system/default fonts",
        detail="No @font-face, no web-font service, and every declared font-family "
               "is a generic/OS family. Default-font pages read as unfinished.",
        fix="Choose and load one display + one text typeface (e.g. a Google/Fontshare "
            "pairing) and set it as the first font-family.",
        evidence="system font: " + ev)


_BLACK_TEXT = re.compile(r"color\s*:\s*(?:#000(?:000)?\b|black\b|rgb\(\s*0\s*,\s*0\s*,\s*0\s*\))", re.I)
# white must be the WHOLE background value (not one stop inside a gradient), and the
# value may end with ; } !important or line-end (inline styles have no terminator).
_WHITE_BG = re.compile(
    r"background(?:-color)?\s*:\s*(?:#fff(?:fff)?|white|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))"
    r"\s*(?:!important\s*)?(?:[;}\n]|$)", re.I | re.M)
_BLOCK_RE = re.compile(r"\{([^{}]*)\}", re.S)


def _c2_pure_contrast(html, css):
    # require black text and a solid white background in the SAME rule / inline block,
    # so black-text-here + white-card-there on different elements does not co-fire.
    blocks = _BLOCK_RE.findall(css)
    blocks += _INLINE_RE.findall(html) + _INLINE_RE2.findall(html)
    if any(_BLACK_TEXT.search(b) and _WHITE_BG.search(b) for b in blocks):
        return dict(
            code="harsh_pure_contrast", severity="MED",
            title="Pure #000 text and a pure #fff background present",
            detail="Pure-black text with a solid pure-white surface is the classic "
                   "unpolished light theme. Refined UIs soften both ends.",
            fix="Use off-black text (#111–#1a1a1a) on off-white (#fafafa–#f7f7f8).",
            evidence="pure #000 text + solid #fff background both present")
    return None


def _c3_line_height(html, css):
    if not _has_body_text(html):
        return None
    ratio = []
    for v in re.findall(r"line-height\s*:\s*([0-9.]+)\b(?!\s*(?:px|%|em|rem|vh|vw))", css, re.I):
        try:
            ratio.append(float(v))
        except ValueError:
            pass
    for v in re.findall(r"line-height\s*:\s*([0-9.]+)\s*(?:em|rem)\b", css, re.I):
        try:
            ratio.append(float(v))
        except ValueError:
            pass
    if any(x >= 1.4 for x in ratio):
        return None
    # px leading: ratio is font-size-dependent and unknown statically. Treat any
    # >= 22px as plausibly comfortable and abstain (avoid flagging polished pages).
    px = []
    for v in re.findall(r"line-height\s*:\s*([0-9.]+)\s*px\b", css, re.I):
        try:
            px.append(float(v))
        except ValueError:
            pass
    if any(x >= 22 for x in px):
        return None
    return dict(
        code="body_line_height", severity="MED",
        title="Body text has no comfortable line-height",
        detail=("No line-height >= 1.4 anywhere; cramped leading hurts readability."
                if (ratio or px) else "No line-height declared for body text."),
        fix="Set body/paragraph line-height to ~1.5–1.7.",
        evidence=("max unitless line-height %.2f" % max(ratio)) if ratio else
                 ("px line-heights only (< 22px)" if px else "none"))


def _c4_line_measure(html, css):
    if not _has_body_text(html):
        return None
    # functional / variable measures are valid content constraints
    if re.search(r"max-(?:width|inline-size)\s*:\s*(?:clamp|min|max|calc|var)\s*\(", css, re.I):
        return None
    for m in re.finditer(r"max-(?:width|inline-size)\s*:\s*[0-9.]+\s*(?:px|rem|em|ch|vw|vh|%)", css, re.I):
        if re.match(r"\s*\)", css[m.end():]):
            continue  # inside @media (max-width: ...)
        return None  # a real content max-width
    if re.search(r"\bwidth\s*:\s*[0-9.]+\s*ch\b", css, re.I):
        return None
    return dict(
        code="line_measure", severity="MED",
        title="Body text has no max line length (measure)",
        detail="No content max-width found; full-viewport-wide paragraphs are hard "
               "to read and look template-y.",
        fix="Constrain prose containers to ~60–75ch (e.g. max-width: 68ch or ~720px).",
        evidence="no content max-width / measure constraint")


_INTERACTIVE_RE = re.compile(r"<button[\s>]|<a\s[^>]*href|<input[\s>]|<select[\s>]|"
                             r"role\s*=\s*[\"']button[\"']|onclick\s*=|class\s*=\s*[\"'][^\"']*\bbtn\b", re.I)
_MOTION_PROP_RE = re.compile(r"(?m)(?:^|[{;])\s*(?:transition|animation)(?:-[a-z]+)?\s*:", re.I)


def _c5_interaction(html, css):
    if not _INTERACTIVE_RE.search(html):
        return None
    scan = _no_strings(css)
    if re.search(r":hover\b", scan, re.I) or _MOTION_PROP_RE.search(scan) \
            or re.search(r"@keyframes\b", scan, re.I):
        return None
    return dict(
        code="interaction_polish", severity="MED",
        title="Interactive elements but no hover/transition — page feels static",
        detail="Buttons/links exist yet there is no :hover state and no transition or "
               "animation anywhere. Zero motion feedback reads as an unfinished mockup.",
        fix="Add :hover states and short transitions (~120–200ms) on interactive "
            "elements; consider subtle reveal/scroll motion.",
        evidence="interactive elements present, no :hover/transition/animation")


# All CSS math functions (Values 3+4). Every one takes calc-sum arguments where a
# binary + / - REQUIRES surrounding whitespace. `minmax()` is NOT here — it's a grid
# function, not a math context (and `min`/`max` won't match it: the ident before `(`
# in `minmax(` is "minmax"). `rem`/`mod` are the math functions, distinct from the
# `rem` unit (a unit is never immediately followed by `(`).
_MATH_FN = frozenset((
    "calc", "clamp", "min", "max",
    "round", "mod", "rem", "abs", "sign",
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "pow", "sqrt", "hypot", "log", "exp",
))
_WS = " \t\r\n\f"   # CSS whitespace (U+000C form-feed is normalized to whitespace)


def _find_css_math_errors(css):
    """Return [(index, snippet)] for binary + / - that lack the whitespace CSS
    REQUIRES on both sides inside calc()/clamp()/min()/max().

    Why this matters: CSS mandates whitespace around + and - inside math functions
    (because `5vw+1rem` / `100%-20px` tokenize as two adjacent values with no
    operator between them). A single missing space makes the WHOLE declaration
    invalid, and the browser silently drops it — a fluid `clamp()` font-size then
    collapses to the UA default, quietly destroying a big-type hero. Every other
    gate passes because the file still parses as text (2026-07-14 Mingxin big-type
    collapse; caught only by rendering + a sharp eye). * and / need no spaces.

    Precision-first (matches this linter's floor philosophy): only a + / - whose
    preceding value token proves it is a *binary* operator is judged; unary signs
    (after `(` `,` or another operator) and scientific-notation exponents (`1e-3`)
    are skipped, and we do NOT descend into non-math nested functions' arguments
    (var()/env()/rgb()…), where a bare +/- is not a math operator. Known blind
    spots (both vanishingly rare in authored pages): a calc() nested inside a
    non-math function's argument (e.g. a var() fallback) is not scanned; and a CSS
    comment used *as* an operator separator (`calc(1px/**/+/**/2px)`) reads as
    spaced here because `_css_text` already replaced the comment with a space,
    though strict CSS treats comments as no-whitespace token boundaries."""
    s = css
    n = len(s)
    errors = []
    i = 0
    math_depth = 0          # how many calc-family functions we are directly inside
    paren_stack = []        # True if the paren opened a math fn (drives math_depth)
    while i < n:
        c = s[i]
        if c in "'\"":                       # skip string literal (escape-aware)
            q = c
            i += 1
            while i < n and s[i] != q:
                if s[i] == "\\":             # `\'` inside a string is not the closer
                    i += 1
                i += 1
            i += 1
            continue
        if c == "(":
            k = i - 1
            while k >= 0 and (s[k].isalnum() or s[k] in "-_"):
                k -= 1
            ident = s[k + 1:i].lower()
            is_math = ident in _MATH_FN
            if math_depth >= 1 and not is_math and ident:
                # non-math function inside math context: skip its whole arg list so
                # a bare +/- in var()/rgb()/env() args can't false-flag.
                depth = 1
                i += 1
                while i < n and depth:
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                    i += 1
                continue
            paren_stack.append(is_math)
            if is_math:
                math_depth += 1
            i += 1
            continue
        if c == ")":
            if paren_stack and paren_stack.pop() and math_depth:
                math_depth -= 1
            i += 1
            continue
        if c in "+-" and math_depth >= 1:
            p = i - 1
            while p >= 0 and s[p] in _WS:
                p -= 1
            prev = s[p] if p >= 0 else ""
            if prev in "eE" and p - 1 >= 0 and (s[p - 1].isdigit() or s[p - 1] == "."):
                i += 1                       # scientific-notation exponent (1e-3)
                continue
            if prev == "" or prev in "(,+-*/":
                i += 1                       # unary sign at the start of a term
                continue
            before_ok = i - 1 >= 0 and s[i - 1] in _WS
            after_ok = i + 1 < n and s[i + 1] in _WS
            if not (before_ok and after_ok):
                errors.append((i, s[max(0, i - 12):min(n, i + 12)].strip()))
            i += 1
            continue
        i += 1
    return errors


def _c6_invalid_css_math(html, css):
    errs = _find_css_math_errors(_no_strings(css))
    if not errs:
        return None
    ev = "; ".join(sorted({snip for _, snip in errs})[:4])
    return dict(
        code="invalid_css_math", severity="HIGH",
        title="Invalid calc()/clamp() math — missing space around + or -",
        detail="CSS requires whitespace on BOTH sides of + and - inside "
               "calc()/clamp()/min()/max(). Without it the whole declaration is "
               "invalid and silently dropped: a fluid clamp() font-size collapses to "
               "the UA default, quietly destroying big-type heroes. Every other gate "
               "passes because the file still parses as text.",
        fix="Space each side of + and - (e.g. clamp(2rem, 5vw + 1rem, 6rem), not "
            "5vw+1rem). * and / do not need spaces.",
        evidence="%d bad operator(s): %s" % (len(errs), ev))


CHECKS = [_c1_typography, _c2_pure_contrast, _c3_line_height, _c4_line_measure,
          _c5_interaction, _c6_invalid_css_math]


def lint_html(html, source=None):
    css = _css_text(html)
    has_css = bool(css.strip())
    findings = []
    if not has_css:
        # No visible styles -> every CSS-dependent check would draw an unreliable
        # negative conclusion. Emit one honest note and judge nothing else.
        findings.append(dict(
            code="no_analyzable_css", severity="LOW",
            title="No embedded/inline CSS found — analysis skipped",
            detail="Styles appear to live only in external stylesheets or are injected "
                   "at runtime, which this offline linter cannot see. Run against the "
                   "fully-rendered HTML or paste the stylesheet inline for a real check.",
            fix="Render the page and lint the resulting HTML, or inline the styles.",
            evidence="no <style>/style= content"))
        return dict(source=source, has_css=False, has_body_text=_has_body_text(html),
                    findings=findings, score=100 - SEV_WEIGHT["LOW"], verdict="ok")
    for chk in CHECKS:
        try:
            f = chk(html, css)
        except Exception as e:  # a linter must never crash the caller
            f = dict(code=chk.__name__, severity="LOW",
                     title="check errored", detail=str(e), fix="", evidence="")
        if f:
            findings.append(f)
    score = 100
    for f in findings:
        score -= SEV_WEIGHT.get(f["severity"], 0)
    score = max(0, score)
    sevs = {f["severity"] for f in findings}
    verdict = "fail" if "HIGH" in sevs else ("warn" if "MED" in sevs else "ok")
    return dict(source=source, has_css=has_css, has_body_text=_has_body_text(html),
                findings=findings, score=score, verdict=verdict)
