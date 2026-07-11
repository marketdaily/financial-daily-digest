#!/usr/bin/env python3
"""個人語音快報拼裝產線:manifest(每人 token+實收個股)+公版 brief → 每人專屬 mp3。

設計:「分段合成、按人拼裝」——F5 逐句合成本來就是本產線的形狀,句子跨用戶
共用快取(全體持股聯集每句只合成一次),個人化邊際成本≈0。長度隨持股自然伸縮
(2 檔≈1 分鐘,持股多者逐檔上限+其餘壓縮一句,封頂約 4 分鐘)。

內容規則(全確定性,聽者視角):
- 只唸這位訂閱者 email 裡實際收到的個股(來源=寄出前抽的 manifest)
- 市場重點:第一條(避坑/頭條)必唸;其餘 bullets 有提到他的持股才唸
- 新聞:先挑有提到他持股的,否則補一則一般市場新聞;噪音/與重點重複的不唸
- 板塊(XL* 美股 ETF):只在美股晚間班次唸,台股晨間對純台股聽眾是雜訊
- 不唸訂閱 CTA(聽的人就是訂閱者),免責聲明保留
上傳 key = pa_{date}_{ed}_{token}.mp3:media-worker /_list 白名單只放行 audio_,
pa_ 不可列舉,只有 email 連結本人打得開。F5 整體不可用 → 退 edge-tts 逐人合成。
"""
import asyncio
import json
import sys
import urllib.request
import wave
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = HERE / "out"
VB_OUT = REPO / "video_brief" / "out"

sys.path.insert(0, str(HERE))
import tts as ttslib  # noqa: E402
from build_script import MOOD_TEXT, _clean  # noqa: E402
from spoken import (mover_line, grouped_quiet_lines, split_movers,  # noqa: E402
                    stock_name_tokens, news_mentions, is_noise_news,
                    news_duplicates_bullets)

PERSONAL_DUR_LO = 20
PERSONAL_DUR_HI = 330


def build_personal_text(brief, entry):
    d = datetime.strptime(brief["date"], "%Y-%m-%d")
    ed = brief["edition"]
    mood = MOOD_TEXT.get(brief.get("mood"), "")
    mkt_label = "美股" if ed == "us" else "台股"
    shift_label = "美股晚間" if ed == "us" else "台股晨間"
    picks = bool(entry.get("picks"))
    stocks = entry.get("stocks") or []
    lines = []
    who = f"AI 委員會今日精選{mkt_label}語音快報" if picks else f"為你準備的{shift_label}持股快報"
    lines.append(f"歡迎收聽 MarketDaily,這是{who},今天是 {d.year} 年 {d.month} 月 {d.day} 日"
                 + (f",{mood}。" if mood else "。"))

    bullets = brief.get("bullets") or []
    tokens = [t for m in stocks for t in stock_name_tokens(m.get("name", ""), m.get("ticker", ""))]
    if bullets:
        lines.append(_clean(bullets[0], first=True))
        extra = [b for b in bullets[1:] if any(t in b for t in tokens)][:2]
        lines.extend(_clean(b) for b in extra)

    closed = bool(brief.get("tw_market_closed")) and ed == "tw"
    verdict_label = "目前評估" if closed else "今日評估"
    if stocks:
        lines.append("接下來是今日精選標的的表現。" if picks else "接下來看你的持股。")
        detail, quiet = split_movers(stocks)
        lines.extend(mover_line(m, verdict_label) for m in detail)
        if quiet:
            if len(quiet) <= 4:
                lines.extend(grouped_quiet_lines(quiet, verdict_label))
            else:
                lines.append(f"其餘 {len(quiet)} 檔昨日變動不大,評估維持不變,細節都在日報裡。")

    news_all = [n for n in (brief.get("news") or [])
                if not is_noise_news(n.get("headline", ""))
                and not news_duplicates_bullets(n.get("headline", ""), bullets)]
    rel = [n for n in news_all if news_mentions(n, tokens)]
    gen = [n for n in news_all if n not in rel]
    chosen = (rel + gen)[:2] if rel else gen[:1]
    if chosen:
        lines.append("接著是跟你持股相關的市場消息。" if rel else "接著是今天值得知道的市場消息。")
        for n in chosen:
            why = (n.get("why") or "").split("。")[0]
            lines.append(f"{n['headline']}。{why}。" if why else f"{n['headline']}。")

    if ed == "us":
        sectors = brief.get("sectors") or []
        ups = [s for s in sectors if s["move"].startswith("▲")]
        downs = [s for s in sectors if s["move"].startswith("▼")]
        if ups or downs:
            seg = "產業板塊方面,"
            if ups:
                s = ups[0]
                seg += f"{s['name']}最強,上漲{s['move'].lstrip('▲ +')},{s['comment']}"
            if downs:
                s = downs[-1]
                seg += f"最弱的是{s['name']},下跌{s['move'].lstrip('▼ -')},{s['comment']}"
            lines.append(seg)

    when = "今天晚上" if ed == "us" else "今天早上"
    what = "今日精選標的" if picks else "你每一檔持股"
    lines.append(f"以上評估的完整進出場計畫,包含建議買價、目標價與止損價,"
                 f"都在{when}寄給你的日報信裡,{what}都有。")
    lines.append("最後提醒,以上內容為公開資訊整理,不構成投資建議,投資一定有風險,進場前請自行評估。我們下一集見。")
    return "\n".join(lines)


class F5SentenceCache:
    """句級合成快取:同一句(全體用戶持股聯集+共用段落)只打 F5 一次。"""

    def __init__(self):
        self.cache = {}
        self.params = None
        self._n = 0

    def frames_for(self, text):
        chunks = ttslib._split_chunks(text)
        out = []
        for c in chunks:
            if c not in self.cache:
                self.cache[c] = self._synth_one(c)
            out.append(self.cache[c])
        return out

    def _synth_one(self, chunk):
        tmp = OUT / f"_pf5_{self._n:04d}.wav"
        self._n += 1
        req = urllib.request.Request(
            ttslib.F5_URL,
            data=json.dumps({"text": ttslib._tts_normalize(chunk), "out": str(tmp)}).encode(),
            headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=180).read())
        if not r.get("ok") or not tmp.exists():
            raise RuntimeError(f"F5 句合成失敗: {r.get('err')}")
        with wave.open(str(tmp), "rb") as w:
            if self.params is None:
                self.params = w.getparams()
            frames = w.readframes(w.getnframes())
        tmp.unlink()
        return frames

    def gap(self):
        p = self.params
        return b"\x00" * (int(ttslib.F5_GAP_S * p.framerate) * p.sampwidth * p.nchannels)


def synth_user_f5(cache, text, raw_wav):
    seg_lists = [cache.frames_for(line) for line in text.splitlines() if line.strip()]
    frames = []
    gap = cache.gap()
    for segs in seg_lists:
        for s in segs:
            frames.append(s)
            frames.append(gap)
    with wave.open(str(raw_wav), "wb") as w:
        w.setparams(cache.params)
        w.writeframes(b"".join(frames))


def process(date_str, edition):
    mpath = OUT / f"manifest_{date_str}_{edition}.json"
    if not mpath.exists():
        print(f"無 manifest({mpath.name}),個人語音跳過(週末/secret 未設/當日無個人化)")
        return 0
    bpath = VB_OUT / f"brief_{date_str}_{edition}.json"
    if not bpath.exists():
        print(f"✗ 缺公版 brief({bpath.name}),先跑 video_brief/extract.py")
        return 15
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    brief = json.loads(bpath.read_text(encoding="utf-8"))
    entries = manifest.get("entries") or []
    if not entries:
        print("manifest entries 為空,跳過")
        return 0

    cache = F5SentenceCache()
    f5_alive = True
    try:
        cache.frames_for("測試一下。")
    except Exception as e:
        f5_alive = False
        print(f"⚠ F5 不可用({e}),全部退 edge-tts")

    ok, failed = [], []
    for entry in entries:
        token = entry["token"]
        final = OUT / f"pa_{date_str}_{edition}_{token}.mp3"
        text = build_personal_text(brief, entry)
        (OUT / f"pnarr_{date_str}_{edition}_{token}.txt").write_text(text, encoding="utf-8")
        try:
            if f5_alive:
                raw = OUT / f"_praw_{token}.wav"
                synth_user_f5(cache, text, raw)
            else:
                raw = OUT / f"_praw_{token}.mp3"
                asyncio.run(ttslib.synth(text, raw))
            ttslib.normalize(raw, final)
            ttslib.verify(final, lo=PERSONAL_DUR_LO, hi=PERSONAL_DUR_HI)
            ttslib.upload(final, final.name)
            raw.unlink(missing_ok=True)
            ok.append(token)
            print(f"✓ 個人音檔 {token}({'精選' if entry.get('picks') else entry.get('email', '?')}) "
                  f"{len(text)} 字")
        except (Exception, SystemExit) as e:
            failed.append(token)
            print(f"✗ 個人音檔 {token} 失敗: {e}")

    summary = {"date": date_str, "edition": edition, "total": len(entries),
               "ok": ok, "failed": failed,
               "voice": "f5-clone" if f5_alive else "edge",
               "unique_sentences": len(cache.cache)}
    (OUT / f"personal_{date_str}_{edition}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "ok"}, ensure_ascii=False))
    return 15 if failed else 0


def main():
    if len(sys.argv) >= 3:
        date_str, edition = sys.argv[1], sys.argv[2]
    else:
        ms = sorted(OUT.glob("manifest_*.json"))
        if not ms:
            print("找不到任何 manifest,跳過")
            return 0
        parts = ms[-1].stem.split("_")
        date_str, edition = parts[1], parts[2]
    return process(date_str, edition)


if __name__ == "__main__":
    sys.exit(main())
