"""政壇市場訊號 —— 用 xAI Grok Live Search 抓會影響股市/金融市場的政治人物 X 貼文,供每日日報使用。

無 XAI_API_KEY 時回 [],完全不影響日報產生(零錯誤防線:這只是加分區塊,缺了不缺信)。
LINE 即時推播版在 alert-worker/src/political_source.js,兩邊追蹤名單一致。
"""
import os
import json
import requests
from datetime import datetime, timedelta

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.3")
XAI_URL = "https://api.x.ai/v1/responses"  # Agent Tools API(舊 Live Search 已棄用)

# 美國核心追蹤名單(與 alert-worker political_source.js 同步)。
WATCH_HANDLES = [
    "realDonaldTrump", "WhiteHouse", "POTUS", "USTreasury", "scottbessent",
    "CommerceGov", "USTradeRep", "federalreserve", "SECGov", "elonmusk",
]


def _extract_output_text(data: dict) -> str:
    """從 /v1/responses 回應抽出文字輸出(優先 output_text,否則挖 output[].content[].text)。"""
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]
    chunks = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                    chunks.append(c.get("text") or "")
    return "".join(chunks)


def fetch_political_signals(window_hours: int = 24, max_items: int = 6) -> list:
    """回傳近 window_hours 內、會影響市場的政治人物 X 貼文訊號。

    每個元素:
      {handle, name_zh, posted_at, post_url, headline_zh, quote,
       impact_zh, affected:[...], direction, severity}
    依 severity 由高到低排序,取前 max_items。
    """
    if not XAI_API_KEY:
        return []

    now = datetime.utcnow()
    from_date = (now - timedelta(hours=window_hours + 12)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")
    handle_list = "、".join("@" + h for h in WATCH_HANDLES)

    sys = ("你是頂尖財經市場分析師,專門盯政治人物的發言對金融市場的衝擊。"
           "只挑出『可能實質牽動』美股、台股、外匯、利率、原物料或加密貨幣的貼文 —— "
           "例如關稅、出口管制、利率/Fed、財政與預算、產業補貼、點名特定公司、地緣政治。"
           "與市場無關的純政治口水、個人攻防、選舉造勢一律忽略。所有文字輸出用繁體中文。")

    user = (
        f"搜尋這些帳號在過去 {window_hours} 小時內發出的 X 貼文:{handle_list}。\n"
        "從中篩出會影響金融市場的貼文,每則整理成一個物件。受影響標的(affected)填股票代碼:"
        "美股填 ticker(如 NVDA、TSM),台股填四位數代碼(如 2330);"
        "若影響大盤/匯率/利率而非單一個股,affected 可留空。\n"
        "只輸出 JSON 物件,格式:\n"
        '{"signals":[{'
        '"handle":"發文帳號(不含@)",'
        '"name_zh":"政治人物中文名(如 川普、Fed、財政部)",'
        '"posted_at":"ISO 8601 發文時間",'
        '"post_url":"該貼文的 X 連結",'
        '"headline_zh":"一句繁中標題:他說了什麼",'
        '"quote":"原文關鍵摘錄(原文語言)",'
        '"impact_zh":"一句繁中:對哪些市場/標的的影響與方向",'
        '"affected":["受影響股票代碼"],'
        '"direction":"bullish|bearish|mixed",'
        '"severity":1到10整數}]}\n'
        '找不到符合的貼文就回 {"signals":[]}。不要杜撰貼文或連結,只用 Live Search 真實找到的內容。'
    )

    try:
        resp = requests.post(
            XAI_URL,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": XAI_MODEL,
                "instructions": sys,
                "input": [{"role": "user", "content": user}],
                "tools": [{
                    "type": "x_search",
                    "allowed_x_handles": WATCH_HANDLES,  # 上限 20 個
                    "from_date": from_date,
                    "to_date": to_date,
                }],
            },
            timeout=120,
        )
        if not resp.ok:
            print(f"   [政壇訊號] xAI {resp.status_code}:{resp.text[:160]}")
            return []
        content = _extract_output_text(resp.json())
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return []
        parsed = json.loads(content[start:end + 1])
    except Exception as e:
        print(f"   [政壇訊號] 略過({e})")
        return []

    signals = parsed.get("signals") if isinstance(parsed, dict) else None
    if not isinstance(signals, list):
        return []

    out = []
    for s in signals:
        if not isinstance(s, dict):
            continue
        headline = str(s.get("headline_zh") or "").strip()
        if not headline:
            continue
        affected = [str(t).strip().upper() for t in (s.get("affected") or []) if str(t).strip()]
        sev = s.get("severity")
        try:
            sev = max(0, min(10, int(round(float(sev)))))
        except (TypeError, ValueError):
            sev = 5
        direction = s.get("direction") if s.get("direction") in ("bullish", "bearish", "mixed") else "mixed"
        handle = str(s.get("handle") or "").lstrip("@").strip()
        out.append({
            "handle": handle,
            "name_zh": str(s.get("name_zh") or handle).strip(),
            "posted_at": str(s.get("posted_at") or "").strip(),
            "post_url": str(s.get("post_url") or (f"https://x.com/{handle}" if handle else "https://x.com")).strip(),
            "headline_zh": headline,
            "quote": str(s.get("quote") or "").strip()[:280],
            "impact_zh": str(s.get("impact_zh") or "").strip()[:200],
            "affected": affected,
            "direction": direction,
            "severity": sev,
        })

    out.sort(key=lambda x: x["severity"], reverse=True)
    return out[:max_items]
