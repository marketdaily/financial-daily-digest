#!/usr/bin/env python3
"""日報樣板句(AI 腔)守衛 — open item #660 的迴歸。

為什麼有這支(2026-08-30):
  ai_slop_lint 對 106 份存檔日報實測,「顯示…信心」命中 39 次/31 份、「將是關注焦點」
  23 次/17 份,2026-08-29 那份六則 catalysts 清一色用這兩句收尾。根因在 analyzer.py 三支
  報告 prompt + signal-card 規則裡沒有任何一條擋萬用結論句(修法= `_ANTI_SLOP_BLOCK`)。
  prompt 改完沒有守衛 = 下一次有人重寫 prompt 就會靜默退回去,所以這支存在。

它不是第二個掃描器:判準完全來自 ~/autonomous/capabilities/ai_slop_lint(既有唯一路徑),
本檔只負責「挑哪些檔、用什麼門檻、什麼時候該紅」。

門檻是對著「災難」寫的,不是對著「變化」寫的:
  災難 = 一份日報裡萬用樣板句又變成收尾模板(08-29 那份 = 7 次命中 / density 3.11)。
  MAX_PER_DIGEST=4:單份 ≥4 次命中即紅(08-29 那份會紅;修前 106 份裡只有它會紅)。
  MAX_MEAN=1.2:窗內平均 >1.2 次/份即紅(修前全庫平均 0.72,08-29 前後那批明顯抬高)。
  兩道閘任一觸發即紅——單份爆量與長期慢性回流是兩種不同的退化。

只看 EPOCH 之後產生的日報:EPOCH 之前的存檔是「修法上線前」的產物,拿它們判紅等於
永遠紅(檔案不會消失),那種紅燈只會被消音。EPOCH 之後零日報且已過 STALE_DAYS 天也算紅
(不是「沒事」,是這支守衛瞎了或日報停產)。

用法:
  python3 scripts/digest_slop_watch.py [--window N] [--json] [--epoch YYYY-MM-DD] [--dir PATH]
exit: 0=綠 · 1=紅(超標/瞎了) · 2=前提錯(lint 積木不在)
"""
import argparse
import datetime as _dt
import glob
import json
import os
import re
import sys

LINT_DIR = os.path.expanduser("~/autonomous/capabilities/ai_slop_lint")
DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

EPOCH = "2026-08-30"      # _ANTI_SLOP_BLOCK 上線日;之前的存檔不列入判決
STALE_DAYS = 10           # EPOCH 過了這麼多天還一份都沒掃到 = 紅(瞎了 / 日報停產)
WINDOW = 14               # 只看最近 N 份(滾動,不會讓一次事故永久掛紅)
MAX_PER_DIGEST = 4
MAX_MEAN = 1.2

_DATE_RE = re.compile(r"digest_(\d{4}-\d{2}-\d{2})")


def _load_lint():
    if not os.path.isdir(LINT_DIR):
        return None
    if LINT_DIR not in sys.path:
        sys.path.insert(0, LINT_DIR)
    import logic  # noqa: E402
    return logic


def _file_date(path):
    m = _DATE_RE.search(os.path.basename(path))
    return m.group(1) if m else None


def collect(digest_dir=DEFAULT_DIR, epoch=EPOCH, window=WINDOW):
    """回傳 [(檔名, 日期, 命中次數, density, [pattern...])],依日期排序取最後 window 份。"""
    logic = _load_lint()
    if logic is None:
        raise RuntimeError(f"ai_slop_lint 積木不在 {LINT_DIR}(判準的唯一真源)")
    rows = []
    for p in sorted(glob.glob(os.path.join(digest_dir, "digest_*.html"))):
        d = _file_date(p)
        if not d or d < epoch:
            continue
        raw = open(p, encoding="utf-8", errors="replace").read()
        rep = logic.score(raw, is_html=True)
        offs = rep.get("offenders") or rep.get("top_offenders") or []
        pats, n = [], 0
        for o in offs:
            if isinstance(o, (list, tuple)):
                pat, c = o[0], (o[1] if len(o) > 1 else 1)
            else:
                pat, c = (o.get("pattern") or o.get("pat")), o.get("count", 1)
            pats.append(f"{pat} ×{c}")
            n += c
        rows.append((os.path.basename(p), d, n, rep.get("slop_density", 0.0), pats))
    rows.sort(key=lambda r: (r[1], r[0]))
    return rows[-window:]


def judge(rows, epoch=EPOCH, today=None,
          max_per=MAX_PER_DIGEST, max_mean=MAX_MEAN, stale_days=STALE_DAYS):
    """→ (ok: bool, reasons: list[str], stats: dict)"""
    today = today or _dt.date.today()
    reasons = []
    if not rows:
        age = (today - _dt.date.fromisoformat(epoch)).days
        if age >= stale_days:
            reasons.append(
                f"EPOCH {epoch} 起 {age} 天內一份日報都沒掃到 — 不是「沒事」,"
                f"是日報停產或檔名/路徑變了讓這支守衛瞎掉")
            return False, reasons, {"n": 0, "mean": None, "age_days": age}
        return True, [f"EPOCH {epoch} 起尚無日報({age} 天),還在寬限期"], {"n": 0, "mean": None, "age_days": age}

    mean = sum(r[2] for r in rows) / len(rows)
    for name, _d, n, dens, pats in rows:
        if n >= max_per:
            reasons.append(f"{name}: 樣板句命中 {n} 次(門檻 {max_per})density={dens:.2f} · " + "; ".join(pats[:4]))
    if mean > max_mean:
        reasons.append(f"最近 {len(rows)} 份平均 {mean:.2f} 次/份 > 門檻 {max_mean}(慢性回流)")
    return (not reasons), reasons, {"n": len(rows), "mean": round(mean, 3)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--epoch", default=EPOCH)
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        rows = collect(a.dir, a.epoch, a.window)
    except RuntimeError as e:
        print(f"❌ 前提錯:{e}", file=sys.stderr)
        return 2
    ok, reasons, stats = judge(rows, a.epoch)
    if a.json:
        print(json.dumps({"ok": ok, "reasons": reasons, "stats": stats,
                          "rows": [{"file": r[0], "date": r[1], "hits": r[2],
                                    "density": r[3], "patterns": r[4]} for r in rows]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"{'✅ 綠' if ok else '❌ 紅'} digest_slop_watch — 掃 {stats['n']} 份"
              f"(EPOCH {a.epoch} 起,窗 {a.window}),平均 {stats['mean']} 次/份")
        for r in rows:
            print(f"   {r[1]}  hits={r[2]:2d}  density={r[3]:5.2f}  {r[0]}")
        for x in reasons:
            print("   ⚠️ " + x)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
