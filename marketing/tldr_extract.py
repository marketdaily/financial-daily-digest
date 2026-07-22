"""日報自動裂變(P2.5 打法6)資料層 —— 從已寄出的公版日報存檔抽「市場脈搏」短文候選。

規則(feedback_social_post_verify / feedback_no_fake_numbers 死線):
- 唯讀 docs/output/digest_{date}.html(公版存檔,已寄送+digest_audit 驗證過的真實內容)。
- 只抽取 100% 結構化數字區塊(indicator-bar 恐慌/恐貪/十年債/金油/匯率、sector-bar 板塊輪動),
  不引用 LLM 自由生成的段落(market-summary/mood-text 等),避免把未逐字驗證的散文帶進候選。
- 只產出資料到 tldr_queue.json 供人工/下一輪逐字核對後才接進 daily_run.py 發文流程,
  這支腳本本身不碰 social_posts.json、不觸發任何發文。

跑法:python3 marketing/tldr_extract.py [YYYY-MM-DD]  (預設今天)
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "docs" / "output"
QUEUE_FILE = ROOT / "marketing" / "tldr_queue.json"

INDICATOR_RE = re.compile(
    r'<div class="indicator-item">\s*'
    r'<div class="indicator-label">([^<]+)</div>\s*'
    r'<div class="indicator-value[^"]*">([^<]+)</div>\s*'
    r'<div class="indicator-sub">([^<]*)</div>\s*'
    r'</div>',
    re.S,
)
SECTOR_RE = re.compile(
    r'<div class="sector-item">\s*'
    r'<span class="sector-name">([^<]+)</span>\s*'
    r'<span class="sector-move (up|down)">([^<]+)</span>',
    re.S,
)

VARIANT_LABEL = {"tw": "台股", "us": "美股"}


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def parse_indicators(html: str) -> list[dict]:
    return [{"label": lbl.strip(), "value": val.strip(), "sub": sub.strip()}
            for lbl, val, sub in INDICATOR_RE.findall(html)]


def parse_sectors(html: str) -> list[dict]:
    out = []
    for name, direction, move in SECTOR_RE.findall(html):
        m = re.search(r"[-+]?\d+\.?\d*", move)
        if not m:
            continue
        pct = float(m.group(0))
        if direction == "down" and pct > 0:
            pct = -pct
        out.append({"name": name.strip(), "move": move.strip(), "pct": pct})
    return out


def caption_for(date: str, variant: str, indicators: list[dict], sectors: list[dict]) -> str:
    """純樣板字串,只填入結構化區塊的真實數字,不含 LLM 自由生成散文。"""
    ind = {i["label"]: i for i in indicators}
    parts = [f"📊 {date} {VARIANT_LABEL.get(variant, variant)}盤後市場脈搏"]
    bits = []
    vix = ind.get("VIX 恐慌指數")
    fg = ind.get("恐貪指數")
    y10 = ind.get("美國10年債")
    fx = ind.get("USD/TWD 匯率")
    if vix:
        bits.append(f"VIX {vix['value']}({vix['sub']})")
    if fg:
        bits.append(f"恐貪指數 {fg['value']}({fg['sub']})")
    if y10:
        bits.append(f"美10年債 {y10['value']}")
    if fx:
        bits.append(f"USD/TWD {fx['value']}")
    if bits:
        parts.append(" · ".join(bits))
    if sectors:
        best = max(sectors, key=lambda s: s["pct"])
        worst = min(sectors, key=lambda s: s["pct"])
        verb = "重挫" if worst["pct"] < 0 else "落後"
        parts.append(f"板塊輪動:{best['name']} 領漲 {best['move']}、{worst['name']} {verb} {worst['move']}")
    parts.append("完整日報 → link in bio")
    return "\n".join(parts)


def build_candidate(date: str, variant: str, html: str) -> dict | None:
    indicators = parse_indicators(html)
    sectors = parse_sectors(html)
    if not indicators and not sectors:
        return None
    caption = caption_for(date, variant, indicators, sectors)
    return {
        "date": date,
        "variant": variant,
        "indicators": indicators,
        "sectors": sectors,
        "caption_zh": caption,
        "caption_len": len(caption),
        "source_archive": f"docs/output/digest_{date}{'_us' if variant == 'us' else ''}.html",
    }


def merge_queue(existing: list, fresh: list) -> tuple[list, int]:
    """dedup 用 (date,variant) 當 key,避免重跑同一天同班次重複加入佇列。"""
    seen = {(c["date"], c["variant"]) for c in existing}
    added = 0
    merged = list(existing)
    for c in fresh:
        key = (c["date"], c["variant"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
        added += 1
    merged.sort(key=lambda c: (c["date"], c["variant"]), reverse=True)
    return merged, added


def scan_date(date: str) -> list[dict]:
    fresh = []
    tw_file = OUTPUT_DIR / f"digest_{date}.html"
    us_file = OUTPUT_DIR / f"digest_{date}_us.html"
    for variant, path in (("tw", tw_file), ("us", us_file)):
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        cand = build_candidate(date, variant, html)
        if cand:
            fresh.append(cand)
    return fresh


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    fresh = scan_date(date)
    existing_payload = load_json(QUEUE_FILE, {"candidates": []})
    existing = existing_payload.get("candidates", [])
    merged, added = merge_queue(existing, fresh)
    payload = {
        "_comment": "日報自動裂變候選佇列(P2.5打法6資料層)——只含公版存檔結構化數字區塊萃取的短文,"
                    "發文前仍須逐字核對 caption_zh(feedback_social_post_verify)。本檔不會被自動發文流程讀取。",
        "candidates": merged,
    }
    QUEUE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{date}: 掃到 {len(fresh)} 筆班次候選,新增 {added} 筆進佇列,"
          f"佇列現有 {len(merged)} 筆 → {QUEUE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
