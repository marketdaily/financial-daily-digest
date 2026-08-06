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
  7. 個人語音快報(2026-07-11 上線):manifest 每人一支 pa mp3 都要在 CDN,
     並抽一個 token 用訂閱者視角開個人頁驗 #personal 有播放器

用法: post_send_check.py tw|us [--date YYYY-MM-DD] [--dry]
exit: 0=全過 / 1=內容或完整性失分(呼叫端推 admin) / 3=該存在的 archive 不存在
      4=本班還沒交付,判決延後(呼叫端應放掉每日鎖,下一個 tick 重跑;不推播)
--dry 只印不寫(不隔離 post json、不記 LLM 帳本)。

2026-08-02 警報疲勞根治(open #23 + 連 5 班每班推播):
  ① 交付閘:守衛跑在「本班寄出前」時,archive 缺席/語音 manifest 未生成全是時序假陽性
     (07-30 晚報 21:35 才寄,複檢 21:10 就判了)。改成先查交付訊號,沒交付就 DEFER 重試,
     直到硬死線(tw 09:00 / us 23:00 TW)才算真的失分。
  ② LLM 慢路徑分流:那條「整批掉慢路徑」的領先指標在免費化後變成常態(07-30 起 5/5 班觸發),
     每班推一則 = 訓練 Delvin 忽略這個守衛,07-31 真正的「個人語音 15/15 掛掉」就被埋在同一則裡。
     改成 append-only 帳本比對:常態化後降級成 log 註記,只有顯著惡化或每 7 天一次的週期提醒
     才升級推播;帳本讀寫壞掉一律 fail-closed(記帳壞掉不准靜音)。
"""
import json
import os
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
# 內容深度類 HIGH:寄後也要抓(2026-07-23 免費 council 429 降級致 signal-reason 從 ~130 字
# 塌到 ~48 字、寄前 9b vague 放行、Delvin 本人先抓到)。寄前偵測器已補(digest_audit#9b-2),
# 這裡是第二道閘——對「實際落地的公版 archive」再驗一次,漏了就 exit 1 → 呼叫端推 admin。
CONTENT_HIGH_CHECKS = {"signal_reason_shallow"}
EMOJI_RE = re.compile("[☀-➿️⬀-⯿\U0001f000-\U0001faff]")

DEFER_RC = 4
# 本班「還沒交付就不判決」的寬限到幾點(台北時間,分鐘)。過了這條線還查不到交付訊號=真的出事,
# 才失分推播(watchdog 也會從另一邊叫)。寄出時刻:早報 07:00 / 晚報 20:00。
HARD_DEADLINE_HM = {"tw": 9 * 60, "us": 23 * 60}
SLOW_CALLS_THRESHOLD = 15          # 幾次 openrouter 慢路徑算「整批掉下去」
LLM_LEDGER = REPO / "state" / "postcheck_llm_ledger.jsonl"
REASON_MEDIAN_LEDGER = REPO / "state" / "signal_reason_median_history.jsonl"
CHRONIC_WINDOW = 5                 # 看前幾班決定「這是不是常態」
CHRONIC_MIN_HITS = 3               # 前 5 班有 3 班以上觸發 = 常態,降級成註記
CHRONIC_WORSE_RATIO = 1.5          # 常態下還要比近期最糟再糟 50% 才算顯著惡化
CHRONIC_REMIND_DAYS = 7            # 常態持續時每 7 天仍推一次(不讓它永久靜音)


def _now_tw():
    """台北時間的現在。`MD_POSTCHECK_NOW`(ISO 字串)可覆寫,給迴歸測試造時序情境用——
    測試絕不可依賴「跑的當下剛好幾點」(harness_golden_live_data_drift 六度復發的同款坑)。"""
    override = os.environ.get("MD_POSTCHECK_NOW")
    if override:
        return datetime.fromisoformat(override).replace(tzinfo=ZoneInfo("Asia/Taipei"))
    return datetime.now(ZoneInfo("Asia/Taipei"))


def runner_done_for_shift(log_text, edition):
    """本機 run.sh 是否已經跑完這一班(收尾行 `winrig runner done`)。

    run.sh 的收尾行在寄信之後才印,所以它出現=這一班已經交付。log 檔一天一支、早晚兩班接在
    一起,所以要從「本班起跑行」切到「下一班起跑行」之間找,不能整檔 grep(早報跑完會讓晚報
    誤判成已交付)。"""
    starts = [m.start() for m in re.finditer(
        r"^=== .*winrig runner start \(market=" + re.escape(edition) + r"[) ]",
        log_text, re.M)]
    if not starts:
        return False
    seg = log_text[starts[-1]:]
    nxt = re.search(r"^=== .*winrig runner start \(", seg[1:], re.M)
    if nxt:
        seg = seg[:1 + nxt.start()]
    return "winrig runner done" in seg


def shift_delivered(date, edition, log_text=None, origin_fn=None):
    """這一班到底寄出去了沒有。兩個訊號都是【寄完才寫】的,任一為真即已交付:
      ① 本機 runner 收尾行(winrig 自己寄的)
      ② origin 有本班公版存檔(winrig 寄完立刻 push;雲端備援也是寄完才 persist)
    刻意不看本機 docs/output/ 的檔案——那是【生成當下】就寫的(save_local),寄之前就存在,
    拿它當交付訊號正是 open #23 假陽性的來源。"""
    if log_text is None:
        p = REPO / "logs" / f"fallback_{date}.log"
        log_text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    if runner_done_for_shift(log_text, edition):
        return True
    if origin_fn is None:
        try:
            from main import _archive_in_origin as origin_fn   # 單一事實來源(main.py 雙寄防線同款判準)
        except Exception:
            return False
    # ⚠️ `_archive_in_origin` 內部跑的是相對 cwd 的 git;本腳本由 cron 啟動時 cwd=$HOME(非 repo),
    # git 全失敗 → 這條腿在生產【永遠回 False】,雙訊號實際只剩 runner 收尾行(驗證者 F1,已重現)。
    # 通則:從 cron 被呼叫、內部會跑 git/相對路徑的函式,要自己保證 cwd,不能靠呼叫端。
    cwd = os.getcwd()
    try:
        os.chdir(REPO)
        return bool(origin_fn(edition, date))
    except Exception:
        return False
    finally:
        try:
            os.chdir(cwd)
        except Exception:
            pass


def delivery_verdict(date, edition, archive_exists, us_holiday, delivered, now):
    """交付閘的判決(純函式,好測):
      skip            = 美股休市夜,整輪不發是預期行為
      defer           = 還沒交付、也還沒到硬死線 → 不判決,等下一個 tick
      missing_archive = 該有的公版存檔不存在(rc=3)
      undelivered     = 過了硬死線仍查不到交付訊號 → 真失分(存檔在,但可能沒寄出)
      ok              = 已交付,照常往下驗
    """
    if delivered:
        if us_holiday and not archive_exists:
            return "skip"
        return "ok" if archive_exists else "missing_archive"
    if us_holiday and not archive_exists:
        return "skip"
    deadline_passed = (date < now.strftime("%Y-%m-%d")
                       or now.hour * 60 + now.minute >= HARD_DEADLINE_HM.get(edition, 9 * 60))
    if not deadline_passed:
        return "defer"
    return "undelivered" if archive_exists else "missing_archive"


def llm_shift_counts(log_text, edition):
    """本班掉到 openrouter 慢路徑 / 本地模型的次數。

    ⚠️ 起點之後**必須截到下一個 `^=== ` 表頭為止**:同一個 log 檔早晚兩班接在一起,
    只取 marks[-1]: 會讓早報那段一路吃進晚報的呼叫 → 早報天天被誤報成「強模全滅」。
    邊界錨 `[) ]`:起跑行的欄位以後可能再增加,不可錨死右括號(digest_guard 2026-07-20 同坑)。"""
    marks = [m.start() for m in re.finditer(
        r"^=== .*winrig runner start \(market=" + re.escape(edition) + r"[) ]", log_text, re.M)]
    if not marks:
        return 0, 0
    nxt = re.search(r"^=== ", log_text[marks[-1] + 1:], re.M)
    seg = log_text[marks[-1]:marks[-1] + 1 + nxt.start()] if nxt else log_text[marks[-1]:]
    return (len(re.findall(r"\[LLM\] 使用 openrouter:", seg)),
            len(re.findall(r"\[LLM\] 使用 local:", seg)))


def _ledger_path():
    return Path(os.environ.get("MD_POSTCHECK_LLM_LEDGER") or LLM_LEDGER)


def _days_between(d1, d2):
    return abs((datetime.strptime(d1, "%Y-%m-%d") - datetime.strptime(d2, "%Y-%m-%d")).days)


def record_reason_median(date, edition, html, dry=False):
    """把 signal-reason 長度統計 append 進趨勢帳本(2026-08-06,backlog P1 缺口:median 字數
    以前只在觸發 signal_reason_shallow 失分時才會出現在 log 裡,平常完全沒記帳,沒人看得出
    「哪幾天的日報比較薄」。append-only,同 (date,edition) 補跑會留多列——讀取端(kpi_pull.py)
    比照 read_llm_ledger 用 dict 依 date 去重取最後一筆,不在寫入端擋,維持這支腳本一路 append-only
    的既有慣例(同檔案的 LLM_LEDGER 也是這樣)。純觀測記帳,不影響任何 pass/fail 判準。
    最少 3 張卡才記(與 digest_audit 9b-2 的最小樣本門檻一致,單一事實來源):1-2 張卡的
    median 雜訊太大,記進趨勢帳本只會污染 KPI 的 7 日均線,不是真的品質訊號。"""
    from digest_audit import signal_reason_stats
    stats = signal_reason_stats(html)
    if stats.get("n", 0) < 3 or dry:
        return
    try:
        REASON_MEDIAN_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with REASON_MEDIAN_LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"date": date, "edition": edition, **stats},
                                ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"   ⚠️ signal-reason 趨勢帳本寫入失敗(不影響本班判決): {e}")


def read_llm_ledger(path, edition, date):
    """讀出「本班之前」的同班別歷史,回傳 (rows, broken_reason)。

    ⚠️ 三個都是驗證者(2026-08-02)抓到的真缺陷,不要簡化回去:
      · **(date,edition) 去重**:帳本是 append-only,同一班補跑會留多列;不去重的話
        人工 `--date` 補跑三次就能把某一天灌成視窗全部,永久靜音守衛。
      · **依日期排序取尾 5**,不是取檔案末 5 列——視窗語義是「最近 5 個班次」。
      · **只取 date < 本班**:補跑舊日期時不可以拿它「未來」的班次當歷史。
    任何型別漂移(slow 不是數字、缺 date)一律當壞帳本回報,由呼叫端 fail-closed 升級;
    這些計算全部在同一個 try 內,不可以有半個算式漏在外面(F2 就是這樣被打穿的)。"""
    rows, broken = {}, None
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if not isinstance(r, dict):
                    raise TypeError(f"帳本列不是物件:{line[:60]!r}")
                d, ed = r.get("date"), r.get("edition")
                if not isinstance(d, str) or not isinstance(ed, str):
                    raise TypeError(f"帳本列缺 date/edition:{line[:60]!r}")
                datetime.strptime(d, "%Y-%m-%d")
                if not isinstance(r.get("slow"), (int, float)) or isinstance(r.get("slow"), bool):
                    raise TypeError(f"slow 欄型別漂移:{line[:60]!r}")
                if ed != edition or d >= date:
                    continue
                rows[d] = {"date": d, "slow": int(r["slow"]), "escalated": bool(r.get("escalated"))}
    except Exception as e:
        broken = f"讀取失敗({type(e).__name__}: {e})"
    return [rows[k] for k in sorted(rows)], broken


def llm_chain_triage(slow, local_n, date, edition, dry=False):
    """「整批掉 openrouter 慢路徑」訊號的嚴重度分流(2026-08-02)。

    回傳 (problems, notices):problems 會計入 rc→推播;notices 只印在 log。
    規則(照 capability_selftest_flake_quarantine 的分流四要件:看得見/雙窗升級/不清歷史/
    記帳失敗 fail-closed):
      · 沒觸發門檻 → 什麼都不報,但仍記帳(帳本要有完整歷史才判得出常態)。
      · 觸發但不是常態(最近 5 班同班別 <3 班觸發)→ 升級推播:這是新發生的事。
      · 已是常態 → 降級成註記;例外兩扇窗:①比近期最糟再糟 50% 以上 ②距上次推播 ≥7 天。
      · 帳本讀不到/型別漂移/寫不進 → 一律升級推播(記帳壞掉不准靜音)。

    ⚠️ 誠實記錄(驗證者 F5):用截至 2026-08-02 的真實帳本(69 班)模擬,slow≥15 的班次
    總共只有 3 個(07-30 us=45、07-31 us=26、08-01 tw=20),**常態降級路徑目前不可達**,
    每一種情境都還是會升級。所以這條分流現在是「未來的保險」,不是「已經解掉的警報疲勞」;
    真正讓 07-30~08-01 每班推播的是 signal_reason_shallow 與個人語音,不是這條(它 21 支
    postcheck log 裡只出現 2 次)。要宣稱降噪成效必須等真實分布變成常態後再看帳本。"""
    path = _ledger_path()
    prior, ledger_broken = read_llm_ledger(path, edition, date)

    hit = slow >= SLOW_CALLS_THRESHOLD
    window = prior[-CHRONIC_WINDOW:]
    hits_in_window = sum(1 for r in window if r["slow"] >= SLOW_CALLS_THRESHOLD)
    chronic = hits_in_window >= CHRONIC_MIN_HITS
    worst = max([r["slow"] for r in window], default=0)
    last_esc = next((r for r in reversed(prior) if r["escalated"]), None)

    escalate, why = False, ""
    if hit:
        if ledger_broken:
            escalate, why = True, f"帳本{ledger_broken},無法判斷是否常態→保守推播"
        elif not chronic:
            escalate, why = True, "近 5 班內首見/非常態"
        elif slow >= worst * CHRONIC_WORSE_RATIO:
            escalate, why = True, f"顯著惡化(近期最糟 {worst} → {slow})"
        elif last_esc is None or _days_between(date, last_esc["date"]) >= CHRONIC_REMIND_DAYS:
            escalate, why = True, f"常態持續 ≥{CHRONIC_REMIND_DAYS} 天的週期提醒"

    # 文案只講**能證明的事**:openrouter 次數與耗時。原本寫「強模層幾乎全滅」是過度宣稱——
    # 真正的降級主力其實是本地 qwen(07-31 tw:openrouter 0 次、local 129 次卻準時收尾),
    # local 是不是遲到的領先指標樣本只有 n=2,未證實(驗證者 F9,已排進 backlog 校準)。
    msg = (f"本班 {slow} 次呼叫落到 openrouter 慢路徑(~144s/次≈{slow * 144 // 60} 分鐘)"
           f"+本地模型 {local_n} 次 —— 下一班可能遲到。"
           f"查 429 內文分辨 TPM(等一分鐘)/TPD(今天沒救,要換桶)/RPD")

    if not dry:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"date": date, "edition": edition, "slow": slow,
                                    "local": local_n, "escalated": escalate,
                                    "chronic": chronic}, ensure_ascii=False) + "\n")
        except Exception as e:
            if hit and not escalate:
                escalate, why = True, f"帳本寫入失敗({type(e).__name__}),不敢靜音"

    if not hit:
        return [], []
    if escalate:
        return [f"[LLM鏈] {msg}(升級原因:{why})"], []
    return [], [f"[LLM鏈·常態] {msg}(近 5 班有 {hits_in_window} 班同樣掉慢路徑,"
                f"已是常態→只記帳不推播)"]


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


def personal_page_user_view(url):
    """個人語音頁訂閱者視角:#personal 區塊必須有可播 <audio>(不是卡「生成中」)。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                pg = b.new_page()
                pg.goto(url, wait_until="networkidle", timeout=30000)
                pg.wait_for_timeout(3000)
                n_audio = pg.locator("#personal audio").count()
                txt = pg.inner_text("#personal", timeout=10000)
            finally:
                b.close()
    except Exception as e:
        return [f"[個人語音e2e] 守衛本身跑不動({type(e).__name__}: {e}),用戶視角無人看守"]
    if n_audio == 0:
        stuck = "生成中" in txt or "being generated" in txt
        state = "卡在「生成中」" if stuck else "沒有渲染出播放器"
        return [f"[個人語音e2e] 訂閱者點自己的專屬語音連結{state}:{url} → {txt[:80]!r}"]
    return []


def personal_audio_check(date, edition):
    """個人語音防線(2026-07-11 上線):寄信時 main.py 寫的 manifest 每人一支
    pa_{date}_{ed}_{token}.mp3 都要在 CDN,再抽第一個 token 用訂閱者視角開個人頁。
    平日 manifest 不存在 = main.py 掛鉤沒跑或 secret 未設,失分不靜默。"""
    if not audio_expected(date, edition):
        return []
    mpath = REPO / "audio_brief" / "out" / f"manifest_{date}_{edition}.json"
    if not mpath.exists():
        return [f"[個人語音] manifest 不存在(main.py 掛鉤沒跑或 MD_AUDIO_TOKEN_SECRET 未設):manifest_{date}_{edition}.json"]
    try:
        entries = json.loads(mpath.read_text(encoding="utf-8")).get("entries") or []
    except Exception as e:
        return [f"[個人語音] manifest 壞檔({e})"]
    if not entries:
        return []
    missing = [e["token"] for e in entries
               if head_size(f"https://media.marketdaily.ai/pa_{date}_{edition}_{e['token']}.mp3") <= 0]
    if missing:
        return [f"[個人語音] {len(missing)}/{len(entries)} 支個人音檔 CDN 驗不到"
                f"(personal.py 沒跑完或上傳掛了):{missing[:3]}"]
    tok = entries[0]["token"]
    return personal_page_user_view(
        f"https://marketdaily.ai/audio.html?date={date}&ed={edition}&u={tok}")


def head_size(url):
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "MarketDailyBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("content-length", 0))
    except Exception:
        return -1


def parse_args(argv):
    """→ (edition, date, dry)。`--date` 的**值**不以 -- 開頭,舊版會把它當成班別
    (`digest_postcheck.py --date 2026-08-01` → edition="2026-08-01",帳本寫進髒班別,
    log 切段全找不到;驗證者 F8)。班別只認 tw/us,認不得就報錯退出。"""
    edition, date, dry, skip = None, None, False, False
    for i, a in enumerate(argv):
        if skip:
            skip = False
            continue
        if a == "--date":
            date = argv[i + 1] if i + 1 < len(argv) else None
            skip = True
        elif a == "--dry":
            dry = True
        elif not a.startswith("--") and edition is None:
            edition = a
    if edition is None:
        edition = "tw"
    if edition not in ("tw", "us"):
        raise SystemExit(f"用法錯誤:班別只能是 tw|us,收到 {edition!r}")
    if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise SystemExit(f"用法錯誤:--date 需 YYYY-MM-DD,收到 {date!r}")
    return edition, date, dry


def format_report(date, edition, problems, notices):
    """本班判決的**唯一**輸出格式。抽成函式不是為了好看:`digest_chronic_triage` 靠解析這段
    文字判斷慢性失分,格式一改它就會安靜地少算(lesson `producer_format_drift_kills_consumers`)。
    抽出來之後,消費端的測試可以直接 import 這個函式產生 fixture,契約才咬得住真實生產格式。"""
    out = [f"  ℹ️ {n}" for n in notices]
    if problems:
        out.append(f"✗ 寄後複檢 {date} {edition}:{len(problems)} 個問題")
        out += [f"  - {p}" for p in problems]
    else:
        out.append(f"✓ 寄後複檢 {date} {edition} 全過(archive/時序/語音/reel/CDN/用戶視角e2e)"
                   + (f";另有 {len(notices)} 則趨勢註記(常態,不推播)" if notices else ""))
    return "\n".join(out)


def main():
    edition, date, dry = parse_args(sys.argv[1:])
    now = _now_tw()
    if not date:
        date = now.strftime("%Y-%m-%d")

    from analyzer import _market_status
    from digest_audit import audit_digest
    mkt = _market_status(date)
    tw_closed = mkt.get("tw_will_open_today") is False
    problems, notices = [], []

    # ── 1. 公版 archive ──
    suffix = "_us" if edition == "us" else ""
    archive = REPO / "docs" / "output" / f"digest_{date}{suffix}.html"
    us_holiday = edition == "us" and mkt.get("us_will_open_tonight") is False
    log_p = REPO / "logs" / f"fallback_{date}.log"
    log_text = log_p.read_text(encoding="utf-8", errors="replace") if log_p.exists() else ""

    # ── 0. 交付閘(2026-08-02,open #23):本班還沒寄出就判決 = 時序假陽性 ──
    # 本機 docs/output/ 的 archive 是【生成當下】就寫的,它存在不代表已經寄;語音 manifest 更是
    # 寄的過程中才寫。所以先問「這一班交付了沒」,沒交付就延後重試,別把「還在跑」報成失分。
    verdict = delivery_verdict(date, edition, archive.exists(), us_holiday,
                               shift_delivered(date, edition, log_text=log_text), now)
    if verdict == "skip":
        print("今晚美股休市,晚報整輪不發是預期行為,跳過複檢")
        return 0
    if verdict == "defer":
        print(f"⏳ {date} {edition}:查不到本班交付訊號(runner 未收尾且 origin 無公版存檔),"
              f"archive_local={archive.exists()} —— 判決延後,下一個 tick 重跑")
        return DEFER_RC
    if verdict == "missing_archive":
        print(f"✗ 公版 archive 不存在:{archive.name}")
        return 3
    if verdict == "undelivered":
        problems.append("[交付] 到硬死線仍查不到本班交付訊號(runner 未收尾且 origin 無公版存檔)"
                        " —— 日報可能沒寄出,或 run.sh 中途死掉")
    html = archive.read_text(encoding="utf-8")

    # ── 2. 市場時序/休市措辭(digest_audit 單一事實來源) ──
    fails = audit_digest(html, date, mkt_status=mkt, market=edition)
    for f in fails:
        if f["check"] in TENSE_CHECKS or f["check"] in CONTENT_HIGH_CHECKS:
            problems.append(f"[archive] {f['check']}: {f['msg']}")
    record_reason_median(date, edition, html, dry=dry)

    # ── 2b. 本班到底掉到哪一層 LLM(2026-07-30 晚報遲到 1h35 事故) ──
    # 那天 45 次呼叫落在 openrouter nemotron-550b(144s/次)=108 分鐘,而**當下沒有任何
    # 偵測器在看這件事**:日報照樣寄出、audit 全過,只有 Delvin 自己發現信來得太晚。
    # 「強模全滅、整批掉慢路徑」是遲到的**領先指標**,要在它變成遲到之前就看得見。
    # 2026-08-02:訊號本身留著(它真的預測遲到),但嚴重度交給 llm_chain_triage 分流——
    # 免費化後「強模全滅」已是常態,每班推一則只會把守衛推播訓練成雜訊(07-30 起 5/5 班觸發,
    # 07-31 真正的個人語音 15/15 掛掉就被埋在同一則推播裡)。
    chain_problems = []
    if log_text:
        try:
            slow, local_n = llm_shift_counts(log_text, edition)
            chain_problems, chain_notices = llm_chain_triage(slow, local_n, date, edition, dry=dry)
            notices.extend(chain_notices)
        except Exception as e:
            # 舊版這裡是 `pass`——分流器一炸就【完全靜音】,連帳本都不寫,正好把 fail-closed
            # 保證打穿(驗證者 F2)。守衛掛掉必須看得見(feedback_zero_error_no_miss),
            # 但仍不擋下面的既有複檢項。
            chain_problems = [f"[LLM鏈] 分流器本身炸了({type(e).__name__}: {e}),本班沒有慢路徑判斷"]

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

    # ── 7. 個人語音快報:manifest 每人一支 pa mp3 都要上線+個人頁可播 ──
    problems.extend(personal_audio_check(date, edition))

    # 用戶看得到的失分排前面,LLM 鏈這種「內部領先指標」排最後——一則推播裡真問題不准被埋
    # (2026-07-31:個人語音 15/15 掛掉跟慢路徑常態訊號混在同一則,人眼只會看到第一行)。
    problems.extend(chain_problems)

    print(format_report(date, edition, problems, notices))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
