#!/usr/bin/env python3
"""寄出後獨立複檢(雙閘系統的第二道閘,2026-07-10 颱風休市事故後建立)。

第一道閘=寄前:main.py 生成時 digest_audit + _fix_closed_market_wording 確定性修復層。
第二道閘=本腳本:寄出後對「實際落地發布」的產物再驗一次——公版 archive、語音稿、
reel post json、CDN 檔案完整性。生成端修好但發布端漏掉的洞,靠這層抓。

檢查項:
  1. 公版 archive 存在(美股休市夜整輪不發=合法缺席,自動跳過)
  2. 市場時序/休市措辭(重用 digest_audit 同一套檢查器,單一事實來源)
  3. 語音稿:休市時序字眼/emoji 殘留(F5 唸不出)/「上漲0.00%」/休市日「今日評估」
     3b. 平日該有語音卻連旁白稿都沒有=產線沒跑,直接失分(2026-07-11 前是靜默跳過)
  4. reel post json(早場):caption 時序字眼、「++」雙符號
     → 任一不過即把 verified 翻 false(post_daily_reel 只發 verified=true,攔下 14:00 社群發文)
  5. 語音 mp3 / reel mp4 CDN HEAD 大小 == 本地檔(上傳假成功偵測)
  6. 訂閱者視角 e2e(2026-07-11 語音頁卡「生成中」事故後建):headless 瀏覽器打開
     email 裡實際的語音連結,必須有可播集數,不准停在「生成中」;守衛本身掛掉也算失分(不靜默)

用法: post_send_check.py tw|us [--date YYYY-MM-DD] [--dry]
exit: 0=全過 / 1=內容或完整性失分(呼叫端推 admin) / 3=該存在的 archive 不存在
--dry 只印不寫(不隔離 post json)。
"""
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TENSE_CHECKS = {"tw_pre_market_tense", "tw_pre_market_tense_zaoshen",
                "us_holiday_tense", "tw_holiday_open_tense", "us_holiday_tonight_tense"}
EMOJI_RE = re.compile("[☀-➿️⬀-⯿\U0001f000-\U0001faff]")


def audio_expected(date, edition):
    """平日班次語音必須存在;週六早報=週末回顧(產線僅產 reel 不產語音)、週日無班次。
    與 video_brief 產線的單一事實源(archive 存在+週末規則)對齊。"""
    wd = datetime.strptime(date, "%Y-%m-%d").weekday()  # Mon=0 .. Sun=6
    return wd < 5


def audio_page_user_view(archive_html, url=None):
    """訂閱者視角 e2e:從已寄出的 archive 抽出 email 裡實際的語音連結,headless 打開,
    要求 #list 內出現可播 <audio>;卡「生成中」或空清單=失分。守衛失效(playwright 掛)
    也回報失分——守衛死掉必須看得見,不准靜默(feedback_zero_error_no_miss)。"""
    import html as _html
    if url is None:
        m = re.search(r'href="(https://marketdaily\.ai/audio\.html[^"]*)"', archive_html)
        url = _html.unescape(m.group(1)) if m else "https://marketdaily.ai/audio.html"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                pg = b.new_page()
                pg.goto(url, wait_until="networkidle", timeout=30000)
                pg.wait_for_timeout(3000)
                list_text = pg.inner_text("#list", timeout=10000)
                n_audio = pg.locator("#list audio").count()
            finally:
                b.close()
    except Exception as e:
        return [f"[語音頁e2e] 守衛本身跑不動({type(e).__name__}: {e}),用戶視角無人看守"]
    if n_audio == 0:
        stuck = "生成中" in list_text or "being generated" in list_text
        state = "卡在「生成中」" if stuck else "無可播集數"
        return [f"[語音頁e2e] 訂閱者點 email 語音連結{state}:{url} → 頁面:{list_text[:80]!r}"]
    return []


def head_size(url):
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "MarketDailyBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("content-length", 0))
    except Exception:
        return -1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    edition = args[0] if args else "tw"
    dry = "--dry" in sys.argv
    date = None
    for i, a in enumerate(sys.argv):
        if a == "--date":
            date = sys.argv[i + 1]
    if not date:
        date = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")

    from analyzer import _market_status
    from digest_audit import audit_digest
    mkt = _market_status(date)
    tw_closed = mkt.get("tw_will_open_today") is False
    problems = []

    # ── 1. 公版 archive ──
    suffix = "_us" if edition == "us" else ""
    archive = REPO / "docs" / "output" / f"digest_{date}{suffix}.html"
    if not archive.exists():
        if edition == "us" and mkt.get("us_will_open_tonight") is False:
            print(f"今晚美股休市,晚報整輪不發是預期行為,跳過複檢")
            return 0
        print(f"✗ 公版 archive 不存在:{archive.name}")
        return 3
    html = archive.read_text(encoding="utf-8")

    # ── 2. 市場時序/休市措辭(digest_audit 單一事實來源) ──
    fails = audit_digest(html, date, mkt_status=mkt, market=edition)
    for f in fails:
        if f["check"] in TENSE_CHECKS:
            problems.append(f"[archive] {f['check']}: {f['msg']}")

    # ── 3b. 平日該有語音卻沒有=產線沒跑,不准靜默(2026-07-11 事故) ──
    narration = REPO / "audio_brief" / "out" / f"narration_{date}_{edition}.txt"
    if not narration.exists() and audio_expected(date, edition):
        problems.append(f"[語音] 平日日報已寄出但旁白稿不存在(產線沒跑或掛在 extract):narration_{date}_{edition}.txt")

    # ── 3. 語音稿 ──
    if narration.exists():
        text = narration.read_text(encoding="utf-8")
        if edition == "tw" and tw_closed:
            m = re.search(r"今早.{0,6}開盤|今日早盤|今日評估", text)
            if m:
                problems.append(f"[語音稿] 台股休市日含「{m.group(0)}」")
        m = EMOJI_RE.search(text)
        if m:
            problems.append(f"[語音稿] 殘留 emoji「{m.group(0)}」(F5 唸不出)")
        if re.search(r"(上漲|下跌)0(\.0+)?%", text):
            problems.append("[語音稿] 「上漲/下跌0.00%」— 平盤應唸持平")

        # ── 5a. 語音 CDN 完整性 ──
        meta_p = REPO / "audio_brief" / "out" / f"audio_{date}_{edition}.json"
        mp3_p = REPO / "audio_brief" / "out" / f"audio_{date}_{edition}.mp3"
        if meta_p.exists() and mp3_p.exists():
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            local, remote = mp3_p.stat().st_size, head_size(meta["url"])
            if remote != local:
                problems.append(f"[語音] CDN 大小不符 local={local} remote={remote} {meta['url']}")
        else:
            problems.append(f"[語音] 有旁白稿但 mp3/meta 未落地(TTS 或上傳掛了)")

    # ── 4 + 5b. reel post json(僅早場) ──
    if edition == "tw":
        post_p = REPO / "video_brief" / "out" / f"post_{date}_tw.json"
        if post_p.exists():
            post = json.loads(post_p.read_text(encoding="utf-8"))
            cap = post.get("caption", "")
            cap_problems = []
            if tw_closed and re.search(r"今早.{0,6}開盤|今日早盤", cap):
                cap_problems.append("[reel] 台股休市日 caption 含開盤時序字眼")
            if re.search(r"\+\+|--(?=\d)", cap):
                cap_problems.append("[reel] caption 含 ++/-- 雙符號")
            remote = head_size(post.get("video_url", ""))
            if remote <= 0:
                cap_problems.append(f"[reel] 影片 CDN 驗不到 {post.get('video_url')}")
            if cap_problems and post.get("verified") and not dry:
                post["verified"] = False
                post["blocked_reason"] = "; ".join(cap_problems) + f" (post_send_check {datetime.now(ZoneInfo('Asia/Taipei')).isoformat(timespec='seconds')})"
                post_p.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
                cap_problems.append("→ 已把 post json verified 翻 false,今天 14:00 不會發這支 reel")
            problems.extend(cap_problems)

    # ── 6. 訂閱者視角 e2e:email 裡的語音連結實際打開看 ──
    problems.extend(audio_page_user_view(html))

    if problems:
        print(f"✗ 寄後複檢 {date} {edition}:{len(problems)} 個問題")
        for p in problems:
            print("  -", p)
        return 1
    print(f"✓ 寄後複檢 {date} {edition} 全過(archive/時序/語音/reel/CDN/用戶視角e2e)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
