#!/usr/bin/env python3
"""接 Marketing Agents 5-skill 鏈(spy→extractor→bulk-creative→ads-score→ads-meta)產出的
草稿佇列進實際發文佇列 —— marketing/ad_creative_drafts.json → social_posts.json。

跟 promote_win_cards.py/promote_tldr.py 同一套「generate→promote」慣例,但**這支刻意不同**:
草稿內容來源含「借鏡競品 creative 骨架改寫」這個新風險面(brand voice 是否對味、有沒有語意
上仍貼競品太近),不像 win_card/tldr 是從自家真實數字/歷史結算改寫——所以本腳本**只 promote
`status == "approved"` 的草稿**,且生成者不可核可自己的草稿。approved 唯一合法來源=獨立驗證者
(全新 context 的 headless claude,ma_verify_prompt.md 規範;2026-07-06 前是人工閘門,Delvin
親令改制,見 capabilities/marketing_agents_pipeline/RUNBOOK.md)。

即使已標 approved,promote 前仍會重跑一次 marketing_compliance_lint 逐字合規掃描
(capabilities/marketing_agents_pipeline/compliance_selfcheck.py,同一套產生草稿時用的檢查),
掃到違規一律拒絕 promote 並印出具體原因——不會靜默略過,也不假設「當初產生時過關,現在
一定還過關」(草稿可能被人工編輯過)。

id 用草稿自帶的 id 當去重鍵,已存在 social_posts.json 的一律跳過(可重複執行)。
platforms 用草稿自帶的單一 platform(每則草稿的 caption 是針對該平台調過長度/語氣,
不像 win_card/tldr 用同一份 caption 發三平台)。

圖卡:草稿本身沒有預先渲染好的圖(這批是純文字創意,visual_direction 只是文字建議),
用既有 social_cards.make_card() 通用模板(spec={tag, headline, body, cta})就地產生
一張以 hook 為主標、body 為內文、cta 為按鈕的圖卡,不需要另外接 AI 圖像生成 API。

跑法:
    python3 promote_ad_creatives.py --dry   # 只列出 approved 且合規、尚未 promote 的項目,不寫入
    python3 promote_ad_creatives.py         # 實際 promote(status 須已由獨立驗證者改成 "approved")
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from auto_post import POSTS_FILE, _png_to_jpg_playwright  # noqa: E402
from social_cards import make_card  # noqa: E402
import shutil
import subprocess

AUTO = Path.home() / "autonomous"
sys.path.insert(0, str(AUTO / "capabilities" / "marketing_agents_pipeline"))
import compliance_selfcheck as cc  # noqa: E402

DRAFTS_FILE = HERE / "ad_creative_drafts.json"
PNG_DIR = HERE / "assets" / "posts" / "ad_creative"
JPG_DIR = HERE.parent / "docs" / "social"

PLATFORM_TAG = {
    "instagram": "IG", "facebook": "FB", "threads": "Threads", "x": "X",
}


def spec_for(draft: dict) -> dict:
    return {
        "tag": PLATFORM_TAG.get(draft["platform"], draft["platform"]),
        "headline": draft["hook"] if "hook" in draft else draft["caption_zh"].split("\n", 1)[0],
        "body": draft.get("body", ""),
        "cta": draft.get("cta", ""),
    }


def png_to_jpg(png_path: Path, jpg_path: Path):
    if shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        str(png_path), "--out", str(jpg_path)], capture_output=True, check=True)
    else:
        _png_to_jpg_playwright(png_path, jpg_path)


def load_drafts() -> list:
    if not DRAFTS_FILE.exists():
        return []
    data = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
    return data.get("drafts", [])


def eligible(drafts: list, already: set) -> list:
    """status == approved、未 promote 過、重新掃描仍合規(草稿可能被人工編輯過,不能只信
    生成當下留在檔案裡的 compliance_self_check)。回傳 [(draft, reject_reason_or_None), ...]。
    seen 累積本批次已收錄的 id,防同批次重複 id 被重複 promote(各自產一張圖互相覆蓋)。"""
    out = []
    seen = set(already)
    for d in drafts:
        draft_id = d.get("id")
        if not draft_id or "caption_zh" not in d:
            out.append((d, f"草稿缺少必要欄位(id/caption_zh):{d}"))
            continue
        if draft_id in seen:
            continue
        if d.get("status") != "approved":
            continue
        check = cc.check_caption(d["caption_zh"], draft_id)
        if not cc.all_pass(check):
            failed = [k for k, v in check.items() if not v]
            out.append((d, f"重新掃描仍未過合規檢查:{failed}"))
            seen.add(draft_id)
            continue
        out.append((d, None))
        seen.add(draft_id)
    return out


def main() -> int:
    dry = "--dry" in sys.argv
    drafts = load_drafts()
    if not drafts:
        print("marketing/ad_creative_drafts.json 不存在或沒有草稿。")
        return 0

    posts_payload = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    posts = posts_payload["posts"]
    already = {p["id"] for p in posts}

    candidates = eligible(drafts, already)
    if not candidates:
        approved_count = sum(1 for d in drafts if d.get("status") == "approved" and d.get("id") not in already)
        if approved_count == 0:
            print("沒有 status==approved 的新草稿——需先由獨立驗證者(ma_verify_prompt.md)"
                  "把草稿 status 從 pending_review 改成 approved 才會被 promote。")
        return 0

    ready = [(d, r) for d, r in candidates if r is None]
    rejected = [(d, r) for d, r in candidates if r is not None]

    for d, reason in rejected:
        print(f"⛔ 拒絕 promote {d['id']}:{reason}")

    if not ready:
        return 1 if rejected else 0

    if dry:
        print(f"[dry] {len(ready)} 則 approved 且合規、可 promote:")
        for d, _ in ready:
            print(f"  · {d['id']} ({d['platform']}) score={d['score']}")
        return 0

    PNG_DIR.mkdir(parents=True, exist_ok=True)
    JPG_DIR.mkdir(parents=True, exist_ok=True)
    next_day = max((p.get("day") or 0) for p in posts) + 1
    added = []
    for d, _ in ready:
        png_path = PNG_DIR / f"{d['id']}.png"
        jpg_path = JPG_DIR / f"{d['id']}.jpg"
        make_card(spec_for(d), png_path)
        png_to_jpg(png_path, jpg_path)
        posts.append({
            "id": d["id"],
            "day": next_day,
            "image": f"{d['id']}.png",
            "platforms": [d["platform"]],
            "caption": d["caption_zh"],
        })
        added.append(d["id"])
        next_day += 1

    POSTS_FILE.write_text(json.dumps(posts_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"新增 {len(added)} 篇 ad-creative 貼文進佇列:")
    for slug in added:
        print(f"  · {slug}")
    print(f"\n圖檔已輸出 {PNG_DIR} + {JPG_DIR}(尚未 deploy docs/,需另跑 wrangler pages deploy 才會公開可見)")
    if rejected:
        print(f"\n{len(rejected)} 則已 approved 但重新掃描未過合規,已跳過(見上方 ⛔)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
