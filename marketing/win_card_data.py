"""戰績武器化(P2.5 打法3)資料層 —— 只挑「命中(win)」的公版建議,算真實漲跌% 進審核佇列。

規則(feedback_social_post_verify / feedback_no_fake_numbers 死線):
- 唯讀 docs/data/track-record.json(公版、已 git 版控,track-record.html 可查證同一份數字)
  + scripts/.price_cache.json(build_track_record.py 用的同一份價格快取,唯讀不寫)。
- 算不出真實 5 日漲跌% 的紀錄(快取沒有該股或天數不夠)一律跳過,絕不用估計值頂替。
- 只產出資料到 win_cards_queue.json 供人工/下一輪逐字驗證後才接進 daily_run.py 發文流程,
  這支腳本本身不碰 social_posts.json、不觸發任何發文。

跑法:python3 marketing/win_card_data.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TRACK_RECORD_FILE = ROOT / "docs" / "data" / "track-record.json"
CACHE_FILE = ROOT / "scripts" / ".price_cache.json"
QUEUE_FILE = ROOT / "marketing" / "win_cards_queue.json"

HORIZON_DAYS = 5  # 對齊 build_track_record.py judge() 的主指標(5 個交易日後收盤)


def yf_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    if re.fullmatch(r"\d{4}", t):
        return f"{t}.TW"
    return t


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def real_pct_move(history: dict, date_str: str, horizon: int = HORIZON_DAYS):
    """從價格快取算「建議日收盤 → horizon 個交易日後收盤」的真實漲跌%。查不到就回 None,不可估算。"""
    if not history or date_str not in history:
        return None
    dates = sorted(history)
    i = dates.index(date_str)
    j = i + horizon
    if j >= len(dates):
        return None
    today = history[dates[i]]
    ref = history[dates[j]]
    if not today:
        return None
    return round((ref - today) / today * 100, 2)


VERDICT_LABEL = {
    "buy": "買進",
    "sell": "賣出/避開",
    "wait": "觀望",
    "hold": "續抱",
}


def caption_for(rec: dict, pct: float) -> str:
    """純樣板字串,數字全部來自 rec/pct(真實資料),不含 LLM 自由生成的統計數字。"""
    vc = rec["verdict_class"]
    name = rec.get("name") or rec["ticker"]
    date = rec["date"]
    if vc == "buy":
        body = f"當時建議買進,{HORIZON_DAYS}個交易日後上漲 {pct:+.2f}%。"
    elif vc == "sell":
        body = f"當時建議賣出/避開,{HORIZON_DAYS}個交易日後下跌 {pct:+.2f}%,方向判斷正確。"
    elif vc == "hold":
        body = f"當時建議續抱,{HORIZON_DAYS}個交易日後變動 {pct:+.2f}%,維持原判斷正確。"
    else:  # wait
        body = f"當時建議觀望,{HORIZON_DAYS}個交易日後變動 {pct:+.2f}%,避開追高/追空正確。"
    return f"{date} {name}({rec['ticker']}):{body} 完整對帳見 marketdaily.ai/track-record"


def build_candidates(track_record: dict, cache: dict) -> tuple[list, int]:
    records = track_record.get("records") or []
    wins = [r for r in records if r.get("outcome") == "win"]
    candidates = []
    dropped_no_price = 0
    for rec in wins:
        history = cache.get(f"{yf_symbol(rec['ticker'])}::history")
        pct = real_pct_move(history, rec["date"])
        if pct is None:
            dropped_no_price += 1
            continue
        candidates.append({
            "date": rec["date"],
            "ticker": rec["ticker"],
            "name": rec.get("name") or rec["ticker"],
            "market": rec.get("market"),
            "verdict_class": rec["verdict_class"],
            "verdict_label": VERDICT_LABEL.get(rec["verdict_class"], rec["verdict_class"]),
            "verdict_text": rec.get("verdict_text"),
            "pct_move_5d": pct,
            "source_anchor": "marketdaily.ai/track-record",
            "caption_zh": caption_for(rec, pct),
        })
    candidates.sort(key=lambda c: c["date"], reverse=True)
    return candidates, dropped_no_price


def merge_queue(existing: list, fresh: list) -> tuple[list, int]:
    """dedup 用 (date,ticker,verdict_class) 當 key,避免重跑同一批候選重複加入佇列。"""
    seen = {(c["date"], c["ticker"], c["verdict_class"]) for c in existing}
    added = 0
    merged = list(existing)
    for c in fresh:
        key = (c["date"], c["ticker"], c["verdict_class"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
        added += 1
    merged.sort(key=lambda c: c["date"], reverse=True)
    return merged, added


def main() -> int:
    track_record = load_json(TRACK_RECORD_FILE, {})
    cache = load_json(CACHE_FILE, {})
    if not track_record:
        print(f"[warn] 讀不到 {TRACK_RECORD_FILE},略過本次", file=sys.stderr)
        return 1
    fresh, dropped = build_candidates(track_record, cache)
    existing_payload = load_json(QUEUE_FILE, {"candidates": []})
    existing = existing_payload.get("candidates", [])
    merged, added = merge_queue(existing, fresh)
    payload = {
        "_comment": "戰績武器化候選佇列(P2.5打法3資料層)——只含已驗證真實5日漲跌%的命中建議,"
                    "發文前仍須逐字核對 caption_zh(feedback_social_post_verify)。本檔不會被自動發文流程讀取。",
        "candidates": merged,
    }
    QUEUE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"本次掃到 win={len(fresh)}(缺價格快取跳過 {dropped}),新增 {added} 筆進佇列,"
          f"佇列現有 {len(merged)} 筆 → {QUEUE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
