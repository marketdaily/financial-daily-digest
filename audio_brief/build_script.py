#!/usr/bin/env python3
"""brief.json → 晨間音頻旁白稿(確定性生成,非 LLM,數字全部來自公版日報)。

輸出 out/narration_{date}_{ed}.txt。目標 2.5-3 分鐘(約 650-800 字)。
合規:公版日報本身免費公開,音頻=同內容之衍生,全員免費相同。
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VB_OUT = REPO / "video_brief" / "out"
OUT = HERE / "out"

sys.path.insert(0, str(HERE))
from spoken import mover_line, grouped_quiet_lines, split_movers, pick_news  # noqa: E402

MOOD_TEXT = {"bearish": "整體氛圍偏空", "bullish": "整體氛圍偏多", "neutral": "整體呈現震盪格局"}
NUM_READ = str.maketrans({"%": " 個百分點"})


_EMOJI_RE = re.compile("[\u2600-\u27bf\ufe0f\u2b00-\u2bff\U0001f000-\U0001faff]")


def _clean(b, first=False):
    b = _EMOJI_RE.sub("", b).strip()
    return b.replace("避坑：", "首先是今天的避坑提醒:" if first else "避坑提醒:").strip()


def build(brief):
    d = datetime.strptime(brief["date"], "%Y-%m-%d")
    label = "美股晚間快報" if brief["edition"] == "us" else "台股晨間快報"
    lines = []
    lines.append(f"歡迎收聽 MarketDaily {label},今天是 {d.year} 年 {d.month} 月 {d.day} 日,{MOOD_TEXT.get(brief['mood'])}。")
    lines.append(_clean(brief["bullets"][0], first=True))
    if len(brief["bullets"]) > 1:
        lines.append("接下來是今天的市場重點。")
        for i, b in enumerate(brief["bullets"][1:4], 1):
            lines.append(f"第{['一','二','三'][i-1]},{_clean(b)}")
    if brief["movers"]:
        closed = bool(brief.get("tw_market_closed")) and brief["edition"] == "tw"
        lines.append("再來快速看一下重點個股的昨日表現。" if closed
                     else "再來快速看一下重點個股的昨日表現與今日方向。")
        verdict_label = "目前評估" if closed else "今日評估"
        # 有波動/評估有變的逐檔唸;安靜的分組壓縮(「續抱持有」連唸五次=機械式聽感)
        detail, quiet = split_movers(brief["movers"])
        for m in detail:
            lines.append(mover_line(m, verdict_label))
        lines.extend(grouped_quiet_lines(quiet, verdict_label))
    news = pick_news(brief.get("news") or [], brief.get("bullets") or [])
    if news:
        lines.append("接著看今天必知的市場新聞。")
        for n in news:
            why = n["why"].split("。")[0]
            lines.append(f"{n['headline']}。{why}。")
    sectors = brief.get("sectors") or []
    if sectors:
        ups = [s for s in sectors if s["move"].startswith("▲")]
        downs = [s for s in sectors if s["move"].startswith("▼")]
        seg = "產業板塊方面,"
        if ups:
            s = ups[0]
            seg += f"{s['name']}最強,上漲{s['move'].lstrip('▲ +')},{s['comment']}"
        if downs:
            s = downs[-1]
            seg += f"最弱的是{s['name']},下跌{s['move'].lstrip('▼ -')},{s['comment']}"
        lines.append(seg)
    when = "今天晚上" if brief["edition"] == "us" else "今天早上"
    next_see = "我們下一集見。"
    lines.append(f"以上個股評估都有完整的進出場計畫,包含建議買價、目標價與止損價,詳細內容在{when}寄出的日報裡。")
    lines.append("MarketDaily 每個交易日早晚,把你自選股票的完整分析寄到你的信箱,完全免費,到 marketdaily 點 ai 就能訂閱。")
    lines.append(f"最後提醒,以上內容為公開資訊整理,不構成投資建議,投資一定有風險,進場前請自行評估。{next_see}")
    return "\n".join(lines)


def main():
    briefs = sorted(VB_OUT.glob("brief_*.json"))
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (briefs[-1] if briefs else None)
    if not src:
        sys.exit("找不到 brief json,先跑 video_brief/extract.py")
    brief = json.loads(src.read_text(encoding="utf-8"))
    text = build(brief)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"narration_{brief['date']}_{brief['edition']}.txt"
    out.write_text(text, encoding="utf-8")
    print(f"✓ {out.name}  {len(text)} 字")
    print(text[:200] + "…")


if __name__ == "__main__":
    main()
