#!/usr/bin/env python3
"""RULE_LAYERS.md 對帳:宣稱的守衛真的存在嗎?真的還在跑嗎?

三個問題,對應三個我們真的踩過的坑:
  1. 機制欄的路徑存在嗎?      ← `我引用的告警腳本不存在`、`官網宣稱的機制實際不存在`
  2. 戳記還新鮮嗎?            ← `守衛沒在跑卻報綠`、`沉默的守衛=沒有守衛`
  3. 哪些規則還停在 L4/L5?     ← Lauren 的五層防線:3-5 是軟的,agent 會忘

刻意不做的事:不去驗「規則本身有沒有被遵守」(那是各守衛自己的職責)。
這支只驗**登記簿說的話是不是真的**——宣稱有守衛卻沒有,比誠實承認沒有更危險。

用法: python3 scripts/rule_layer_audit.py [--max-age-days N]
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
REG = ROOT / "RULE_LAYERS.md"
SOFT = {"L3", "L4", "L5"}


def resolve(p):
    p = p.strip()
    if p.startswith("~/"):
        return HOME / p[2:]
    return ROOT / p


def parse():
    rows = []
    for line in REG.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| R-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        rid, rule, layer, mech, stamp, note = cells[:6]
        rows.append({
            "id": rid, "rule": rule, "layer": layer,
            "mech": [] if mech == "—" else mech.split(),
            "stamp": None if stamp == "—" else stamp,
            "note": note,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=float, default=7.0,
                    help="戳記超過幾天算過期(預設 7)")
    a = ap.parse_args()

    if not REG.exists():
        print("RULE_LAYERS.md 不存在"); return 2
    rows = parse()
    if not rows:
        print("RULE_LAYERS.md 解析不到任何 R- 列 —— 表格格式壞了"); return 2

    fails, stale, soft = [], [], []
    for r in rows:
        for m in r["mech"]:
            if not resolve(m).exists():
                fails.append(f"{r['id']} 宣稱的機制不存在: {m}　（{r['rule']}）")
        if r["layer"] in SOFT and not r["mech"]:
            soft.append(r)
        elif r["layer"] in SOFT:
            soft.append(r)
        if r["stamp"]:
            ok = ROOT / "logs" / "ok" / f"{r['stamp']}.ok"
            if not ok.exists():
                fails.append(f"{r['id']} 宣稱有戳記 {r['stamp']} 但 logs/ok/ 裡沒有 —— "
                             f"這條規則的守衛從來沒成功跑過")
            else:
                age = (time.time() - ok.stat().st_mtime) / 86400
                if age > a.max_age_days:
                    stale.append(f"{r['id']} 戳記 {r['stamp']} 已 {age:.1f} 天沒更新　（{r['rule']}）")

    hard = [r for r in rows if r["layer"] not in SOFT]
    print(f"鐵則登記簿 — {len(rows)} 條規則：硬閘 {len(hard)} 條 / 軟層 {len(soft)} 條")

    if soft:
        print(f"\n📋 還停在軟層、待硬化（{len(soft)} 條）：")
        for r in soft:
            why = r["note"] if r["note"] and r["note"] != "—" else "（沒寫為什麼不能硬化）"
            print(f"  {r['layer']} {r['id']} {r['rule']}\n       → {why}")

    if stale:
        print(f"\n⏳ 戳記過期（{len(stale)} 條）：")
        for s in stale:
            print(f"  - {s}")

    if fails:
        print(f"\n❌ 假宣稱（{len(fails)} 條）—— 宣稱有守衛卻沒有，比誠實承認沒有更危險：")
        for f in fails:
            print(f"  - {f}")
        return 1

    print("\n✅ 所有宣稱的機制都存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
