"""親手復現驗證者 F1/F3(2026-07-13)。零網路、零寫檔、合成資料。
F1: rec 日=假日(07-03)且髒 feed 恰有當日偽 bar → 基準價是否中毒。
    OLD(HEAD)=正確 128.5;pre-fix NEW=999.0 中毒;post-fix NEW 應回 128.5。
F3: 右緣未來日偽 bar(僅 1 髒檔覆蓋)→ 是否混入日曆。post-fix cover>=2 應擋。
    殘窗:2 髒檔同印 → cover=2 仍混入(已知限制,documented)。
"""
import subprocess, sys, io, contextlib
from datetime import date, timedelta

REPO = "/home/userdelvin/Delvin-agent"
PATH = "scripts/build_track_record.py"

def load(src, tag):
    g = {"__name__": f"<{tag}>", "__file__": f"{REPO}/{PATH}"}
    exec(compile(src, f"<{tag}>", "exec"), g)
    return g

new_src = open(f"{REPO}/{PATH}").read()
old_src = subprocess.run(["git", "-C", REPO, "show", f"HEAD:{PATH}"],
                         capture_output=True, text=True, check=True).stdout
NEW = load(new_src, "new")
OLD = load(old_src, "old")

def weekdays(a, b, skip=()):
    d, out = date.fromisoformat(a), []
    while d <= date.fromisoformat(b):
        if d.weekday() < 5 and d.isoformat() not in skip:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out

def settle_new(g, hbt, ticker, d):
    cals, fr = g["_market_trading_calendar"](hbt)
    mkt = g["_market_of"](ticker)
    cal = cals.get(mkt)
    assert cal, "calendar not built"
    h = hbt[ticker]
    with contextlib.redirect_stderr(io.StringIO()):
        return g["_settle_on_calendar"](h, sorted(h), cal, set(cal), ticker, d)

def settle_old(g, hbt, ticker, d):
    """HEAD 舊法:_filtered_sorted_dates + 位置索引(照 HEAD fetch_prices Pass2 邏輯重演)"""
    h = hbt[ticker]
    with contextlib.redirect_stderr(io.StringIO()):
        sd, _dropped = g["_filtered_sorted_dates"](h, ticker, g["_market_consensus_days"](hbt))
    if d in h and d in sd:
        ref_idx = sd.index(d); close = h[d]
    else:
        later = [dd for dd in sd if dd >= d]
        if not later:
            return None
        ref_idx = sd.index(later[0]); close = h[later[0]]
    def px(n):
        j = ref_idx + n
        return h[sd[j]] if j < len(sd) else None
    return {"close": close, "next_close": px(1)}

fails = []
def check(name, cond, detail=""):
    print(("  ok  " if cond else " FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(name)

# ── F1:假日偽 bar 當基準 ──────────────────────────────
days = weekdays("2026-04-13", "2026-07-10", skip={"2026-05-25", "2026-06-19", "2026-07-03"})
closes = {d: 100 + i * 0.5 for i, d in enumerate(days)}
hbt = {f"AA{i}": dict(closes) for i in range(9)}
dirty = dict(closes); dirty["2026-07-03"] = 999.0
hbt["DIRTY"] = dirty

o = settle_old(OLD, hbt, "DIRTY", "2026-07-03")
n = settle_new(NEW, hbt, "DIRTY", "2026-07-03")
print(f"F1: OLD close={o['close']} next={o['next_close']} | NEW close={n['close']} next={n['next_close']}")
check("F1 OLD(HEAD) 基準=真 07-06 bar 128.5", o["close"] == 128.5)
check("F1 NEW(post-fix) 基準不中毒=128.5", n["close"] == 128.5, f"got {n['close']}")
check("F1 NEW next_close 一致 129.0", n["next_close"] == 129.0)

# 週六變體:rec 07-04(六)+偽週六 bar
dirty2 = dict(closes); dirty2["2026-07-04"] = 555.0
hbt2 = {f"AA{i}": dict(closes) for i in range(9)}; hbt2["DIRTY"] = dirty2
n2 = settle_new(NEW, hbt2, "DIRTY", "2026-07-04")
check("F1 週六偽 bar 亦不中毒(基準=07-06 128.5)", n2["close"] == 128.5, f"got {n2['close']}")

# ── F3:右緣未來日偽 bar ──────────────────────────────
days3 = weekdays("2026-04-13", "2026-07-02", skip={"2026-05-25", "2026-06-19"})
closes3 = {d: 100 + i * 0.5 for i, d in enumerate(days3)}
hbt3 = {f"AA{i}": dict(closes3) for i in range(9)}
dirty3 = dict(closes3); dirty3["2026-07-03"] = 777.0
hbt3["DIRTY"] = dirty3
cals3, _ = NEW["_market_trading_calendar"](hbt3)
in_cal = "2026-07-03" in cals3["US"]
print(f"F3: 07-03(1 髒檔) in calendar = {in_cal}")
check("F3 右緣單檔偽 bar 不進日曆(cover>=2 閘)", not in_cal)
n3 = settle_new(NEW, hbt3, "DIRTY", "2026-07-02")
check("F3 rec 07-02 next_close=None 誠實待結(非 777.0)", n3["next_close"] is None,
      f"got {n3['next_close']}")

# 殘窗:2 髒檔同印 07-03 → cover=2 仍混入(已知限制)
hbt4 = dict(hbt3); hbt4["DIRTY2"] = dict(dirty3)
cals4, _ = NEW["_market_trading_calendar"](hbt4)
in_cal4 = "2026-07-03" in cals4["US"]
print(f"F3 殘窗: 07-03(2 髒檔) in calendar = {in_cal4}")
check("F3 殘窗確認:2 髒檔同印仍混入(需在註解文檔化)", in_cal4)

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
