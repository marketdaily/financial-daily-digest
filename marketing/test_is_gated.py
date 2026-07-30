#!/usr/bin/env python3
"""promote_ad_creatives._is_gated() 的迴歸校準集。

2026-07-30 事故:舊判準是「留言」與閘門關鍵字**全文共現**,與合規口徑直接相撞——
「現在訂閱的早鳥用戶永久保留免費使用權」是全面免費化政策的強制口徑(每則都得寫),
所以任何「邀請留言 + 寫了必寫口徑」的貼文都會被永久誤判成閘門型擋掉。偏偏研究簡報
正因「近 14 天 50 篇留言全為 0」在推互動型內容 → 舊判準會把那條路悄悄掐死。

校準集刻意含**中間帶**(既有「留言」又有口徑但不是閘門的寫法),因為只放極端案例的
校準集會讓「全文共現」這種天真判準也考 100 分,測不出退步。

真實案例取自 07-30 那批的 salvage 檔與已上線草稿,不是我編的字串。
跑法:.venv/bin/python marketing/test_is_gated.py  (exit 0 = 全過)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import promote_ad_creatives as p  # noqa: E402

SALVAGE = os.path.join(REPO, "marketing", "salvage", "wf_2d91553c_20260730.json")
CURRENT = os.path.join(REPO, "marketing", "ad_creative_drafts.json")

LONG_FILLER = "這是一段很長的內容說明。" * 6


def _by_id(path):
    with open(path, encoding="utf-8") as f:
        return {d["id"]: d for d in json.load(f)["drafts"]}


def cases():
    sal, cur = _by_id(SALVAGE), _by_id(CURRENT)

    def s(i):
        return sal[f"adcreative_PENDING_{i}"]["caption_zh"]

    def c(i):
        return cur[f"adcreative_2026-07-30_{i}"]["caption_zh"]

    return [
        # 真閘門(實測:「留言↔關鍵字」最近距離全是 3,即 `留言「早鳥」`)
        ("真閘門 _03", s("03"), True),
        ("真閘門 _05", s("05"), True),
        ("真閘門 _06", s("06"), True),
        ("真閘門 _07", s("07"), True),
        # 舊判準的誤判案例(實測最近距離 46,分屬不同段落)
        ("舊誤判 _02 原文", s("02"), False),
        # 已上線且確定不是閘門型的三則
        ("_02 修正後", c("02"), False),
        ("_01", c("01"), False),
        ("_04", c("04"), False),
        # 同義寫法也要抓到(漏判比誤判嚴重:漏判=承諾兌現不了=對用戶失信)
        ("跨句緊鄰+同義詞", "想收日報的留一句。關鍵字早鳥。", True),
        ("同義詞同句", "想鎖早鳥資格的留個言給我", True),
        # ⭐中間帶:這三個是校準集的重點,天真判準會在這裡全錯
        ("中間帶:純提問+必寫口徑",
         "你是讀派還是聽派?在下面告訴我。\n\n目前限時免費開放;未來恢復收費後,"
         "現在訂閱的早鳥用戶永久保留免費使用權。", False),
        ("中間帶:留言但無關鍵字", "你最常被哪種訊息騙?留言告訴我 👇\n\n目前全功能限時免費開放。", False),
        ("中間帶:留言+口徑相隔一大段",
         "留言告訴我你的看法 👇\n\n" + LONG_FILLER + "\n\n現在訂閱的早鳥用戶永久保留免費使用權。", False),
    ]


def main() -> int:
    bad = []
    for name, caption, want in cases():
        got = p._is_gated(caption)
        if got != want:
            bad.append(f"{name}(期望 {want},實際 {got})")
        print(f"  {'✅' if got == want else '❌'} {name}")
    if bad:
        print(f"\n❌ _is_gated 校準集 {len(bad)} 項不符:")
        for b in bad:
            print(f"  - {b}")
        return 1
    print("\n✅ _is_gated 校準集全過(真閘門/已上線/同義詞/中間帶四類)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
