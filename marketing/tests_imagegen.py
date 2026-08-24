#!/usr/bin/env python3
"""imagegen 四道防線的自測（不打 API、不花 credit）—— python3 tests_imagegen.py

⚠️ 這裡最重要的是**第 4 條**:「有現生底圖時風格一定落在 photo 版位」。
   少了那道限制,錢照花、圖照產,但畫面上一點都看不到,而且程式一路回報成功 ——
   跟 08-24 早上 cardkit 接線時「fallback 安靜接住」是同一種說謊法。
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from cardkit import imagegen as ig  # noqa: E402
from cardkit import styles  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


GOOD = ("A crude-oil tanker moving through a narrow strait at night, seen from far across "
        "black water, a searchlight beam raking the haze behind it")

print("[主體閘：該放行的]")
for name, s in [
    ("實景描述", GOOD),
    ("機房", "A service aisle inside a hyperscale data hall at night, cabinets receding to a vanishing point, cooling vapour low across the floor"),
    ("節氣", "Dew beads on grass blades before sunrise with cold mist lying across the field behind them"),
]:
    ok, why = ig.vet_subject(s)
    check(name, ok, why)

print("\n[主體閘：該擋下的]")
for name, s, want in [
    ("人臉肖像", "A portrait of the chairman speaking at the announcement, his face lit from the side", "portrait"),
    ("商標", "The Nvidia logo glowing on the wall of its headquarters at dusk", "logo"),
    ("招牌文字", "A newspaper headline about the tariff deal lying on a desk", "headline"),
    ("中文主體", "夜裡的油輪通過海峽，探照燈掃過霧氣，畫面壓在下三分之一", "ascii"),
    ("太短", "a ship", "長度"),
]:
    ok, why = ig.vet_subject(s)
    check(name, not ok, f"竟然放行了：{s[:40]}")

print("\n[prompt 組裝]")
p = ig.build_prompt("marketdaily", GOOD)
check("含 MarketDaily rig（機身）", "Sony Venice 2" in p)
check("含交付約束（上緣暗場）", "upper 45 percent" in p)
check("零否定句（prose 模型沒有 negative 欄位）",
      not any(w in p.lower().split() for w in ("no", "not", "without")), p[:0])
p2 = ig.build_prompt("mingshu", GOOD)
check("命書用的是另一組 rig", "Hasselblad" in p2 and "Sony Venice" not in p2)

print("\n[額度上限]")
old = ig.DAILY_CREDIT_CAP
with tempfile.TemporaryDirectory() as td:
    ig.LEDGER = Path(td) / "led.json"
    ig.DAILY_CREDIT_CAP = 4
    ig._charge(4)
    check("超過上限就回 None（不是報錯）",
          ig.generate("marketdaily", GOOD, "k", None, log=lambda *_: None) is None)
    ig.DAILY_CREDIT_CAP = old

print("\n[kill switch]")
os.environ["CARDKIT_IMAGEGEN_OFF"] = "1"
check("CARDKIT_IMAGEGEN_OFF=1 一律不產圖",
      ig.generate("marketdaily", GOOD, "k", None, log=lambda *_: None) is None)
del os.environ["CARDKIT_IMAGEGEN_OFF"]

print("\n[⭐ 有現生底圖 → 風格必須落在 photo 版位]")
plate = styles.plate_path("marketdaily", "world_strait")
bad = []
for i in range(40):
    st = styles.pick("marketdaily", f"pk{i}", photo_only=True)
    if st["backdrop"] != "photo":
        bad.append(st["id"])
check("photo_only 挑出來的一律是 photo 版位", not bad, str(bad[:3]))
img, st = styles.render({"id": "photoroute", "headline": "測試", "plate_path": plate},
                        "marketdaily")
check("render 帶 plate_path 時自動走 photo 版位", st["backdrop"] == "photo", st["id"])
check("命書也有 photo 版位可用", len(styles.photo_styles("mingshu")) >= 3)

print(f"\n{'❌ 失敗 ' + str(len(FAILS)) + ' 項: ' + ', '.join(FAILS) if FAILS else '✅ 全過'}")
sys.exit(1 if FAILS else 0)
