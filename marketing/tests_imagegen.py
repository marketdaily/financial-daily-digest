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
    # ⚠️ 這三條是**誤告反例**,首版子字串比對全部誤殺:
    #    sur"face" / "man"-made / "human"-scale。守衛咬太寬的傷害是無聲的
    #    ——它不會報錯,只會安靜地退回庫存底圖,花錢做的功能沒在動也沒人知道。
    ("surface（不是 face）", "A shallow stone water basin at dusk, its still surface split by one ripple, wet stone edges catching one lantern glow"),
    ("human-scale（不是 man）", "Human-scale gantry cranes standing over a container yard at night with sea fog drifting between the stacks"),
    ("workmanship（不是 worker）", "A brass compass showing fine workmanship on dark worn wood, engraved rings catching one low warm lamp"),
]:
    ok, why = ig.vet_subject(s)
    check(name, ok, why)

print("\n[主體閘：該擋下的]")
for name, s, want in [
    ("人臉肖像", "A portrait of the chairman speaking at the announcement, his face lit from the side", "portrait"),
    ("交易員", "Traders shouting across a dealing room floor at the opening bell under bright screens", "traders"),
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

print("\n[連續降級告警：安靜退回庫存不等於沒事]")
import json as _json  # noqa: E402
_pushed = []
_orig_push, ig._push_admin = ig._push_admin, lambda m: _pushed.append(m)
_orig_led = ig.LEDGER
with tempfile.TemporaryDirectory() as td:
    ig.LEDGER = Path(td) / "l.json"
    for _ in range(5):
        ig._note(False, "token 死了")
    check("連續降級只推一則（同日防重）", len(_pushed) == 1, str(len(_pushed)))
    check("門檻是第 3 次才響", "連續 3 次" in (_pushed[0] if _pushed else ""))
    ig._note(True)
    check("成功一次就歸零", _json.loads(ig.LEDGER.read_text())["fail_streak"] == 0)
ig.LEDGER, ig._push_admin = _orig_led, _orig_push

print("\n[照片版位要被題材賺到]")
nophoto = sum(1 for i in range(30)
              if styles.render({"id": f"d{i}", "headline": "VIX 恐慌指數 18.2"},
                               "marketdaily")[1]["backdrop"] == "photo")
check("沒有 topic 也沒有現生圖的資料卡，永遠不配照片", nophoto == 0, f"{nophoto}/30 配到照片")
withtopic = sum(1 for i in range(30)
                if styles.render({"id": f"t{i}", "headline": "荷姆茲通行費上路", "topic": "world"},
                                 "marketdaily")[1]["backdrop"] == "photo")
check("有 topic 的卡拿得到照片版位", withtopic > 0, "一次都沒有")

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

# ⭐⭐ 這條才是會出事的那條:貼文**早就被指派過**一個程序化風格,之後才帶著現生底圖回來。
#    指派表若直接回快取而不看 photo_only,圖生了、錢花了、畫面上完全看不到,
#    而且程式一路回報成功。首版就是這樣,而且測試因為只用新 key 而全綠(假綠)。
key = "already_assigned_nonphoto"
first, tries = None, 0
while tries < 80:
    first = styles.assign("marketdaily", key)
    if first["backdrop"] != "photo":
        break
    key = f"already_assigned_nonphoto_{tries}"
    tries += 1
check("前置條件:先拿到一個非 photo 指派", first and first["backdrop"] != "photo", str(first))
again = styles.assign("marketdaily", key, photo_only=True)
check("同一則帶現生底圖回來時改走 photo 版位", again["backdrop"] == "photo", again["id"])
check("原本的非 photo 指派沒有被改掉(重跑一致性還在)",
      styles.assign("marketdaily", key)["id"] == first["id"])
_, st2 = styles.render({"id": key, "headline": "測試", "plate_path": plate}, "marketdaily")
check("render 走完整路徑也拿到 photo 版位", st2["backdrop"] == "photo", st2["id"])
check("命書也有 photo 版位可用", len(styles.photo_styles("mingshu")) >= 3)

print("\n[⭐⭐ 09-17 老闆令 stop entirely:自動產圖必須停用,且不碰 token/網路]")
check("IMAGEGEN_ENABLED 寫死為 False", ig.IMAGEGEN_ENABLED is False)
_orig_token, _touched = ig._token, []
ig._token = lambda: _touched.append(1) or "x"
try:
    _r = ig.generate("marketdaily", "a quiet harbour at dusk with cargo cranes", "t-off", None, log=lambda *a: None)
finally:
    ig._token = _orig_token
check("停用時 generate 回 None", _r is None, _r)
check("停用時完全沒去拿 token(不可能扣點)", not _touched)

print(f"\n{'❌ 失敗 ' + str(len(FAILS)) + ' 項: ' + ', '.join(FAILS) if FAILS else '✅ 全過'}")
sys.exit(1 if FAILS else 0)
