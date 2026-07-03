"""渲染日報自動裂變(P2.5 打法6)市場脈搏圖卡 —— tldr_queue.json → PNG。

只做渲染,不寫 social_posts.json、不觸發任何發文(feedback_social_post_verify:
發文前仍須人工逐字核對 caption,本腳本只產出可審核的圖卡資產)。

卡面只放 tldr_extract.py 已驗證過的結構化數字(indicator/sector),不重算、不新增數字。

跑法:python make_tldr_cards.py [限筆數,預設全部]
"""
import json
import sys
from pathlib import Path

from social_cards import make_card

HERE = Path(__file__).parent
QUEUE_FILE = HERE / "tldr_queue.json"
OUT = HERE / "assets" / "posts" / "tldr"

VARIANT_LABEL = {"tw": "台股", "us": "美股"}


def load_candidates() -> list[dict]:
    payload = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    return payload.get("candidates", [])


def slugify(candidate: dict) -> str:
    return f"tldr_{candidate['date']}_{candidate['variant']}"


def spec_for(candidate: dict) -> dict:
    ind = {i["label"]: i for i in candidate["indicators"]}
    label = VARIANT_LABEL.get(candidate["variant"], candidate["variant"])
    body_bits = []
    for key in ("VIX 恐慌指數", "恐貪指數", "美國10年債", "USD/TWD 匯率"):
        row = ind.get(key)
        if row:
            body_bits.append(f"{key}:{row['value']}" + (f"({row['sub']})" if row["sub"] else ""))
    sectors = candidate["sectors"]
    if sectors:
        best = max(sectors, key=lambda s: s["pct"])
        worst = min(sectors, key=lambda s: s["pct"])
        body_bits.append(f"領漲 {best['name']} {best['move']} · 落後 {worst['name']} {worst['move']}")
    return {
        "tag": f"市場脈搏 · {candidate['date']}",
        "headline": f"{label}盤後快照",
        "body": "\n".join(body_bits),
        "cta": "完整日報 marketdaily.ai →",
    }


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    candidates = load_candidates()
    if limit:
        candidates = candidates[:limit]
    OUT.mkdir(parents=True, exist_ok=True)
    made = 0
    for c in candidates:
        out = OUT / f"{slugify(c)}.png"
        make_card(spec_for(c), out)
        made += 1
        print(f"✅ {out.relative_to(HERE)}")
    print(f"\n共渲染 {made} 張 → {OUT}(僅本機資產,未寫入 social_posts.json,發文前仍需人工審核)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
