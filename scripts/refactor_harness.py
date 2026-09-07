#!/usr/bin/env python3
"""Clean-code 抽離工程的行為凍結 harness(characterization tests)。

用法(一律用 repo 的 venv python 跑):
  python scripts/refactor_harness.py golden          # 產黃金基線 → scripts/fixtures/golden/
  python scripts/refactor_harness.py diff            # 重新生成並比對黃金基線,任何差異 exit 1
  python scripts/refactor_harness.py provider golden # 8 個 LLM provider 的 payload/解析/鏈序快照
  python scripts/refactor_harness.py provider diff

原則:
- 零真實 LLM 呼叫、零寄信、零配額消耗;市場資料吃 scripts/fixtures/refactor_fixture.pkl。
- _llm_generate 換成回傳「prompt 雜湊樁」的假函式 → prompt 內容改變也會反映在 golden diff。
- datetime 凍結在固定時刻(sys.modules 假模組,函式內 late import 也吃得到)。
- golden 檔寫入前掃描 .env 所有值,任何真實 secret 出現即 abort(防洩漏進 git)。
"""
import difflib
import hashlib
import inspect
import json
import os
import pathlib
import pickle
import re
import sys
import tempfile
import types
import datetime as _real_dt
import os as _os_bsl, tempfile as _tf_bsl
# buy_signal_log 隔離:golden/diff 全程指向臨時檔,活資料不弄髒 golden、golden 不污染真檔
_os_bsl.environ["MD_BUY_SIGNAL_LOG"] = _os_bsl.path.join(_tf_bsl.mkdtemp(prefix="md_harness_"), "buy_signal_log.json")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX_DIR = os.path.join(ROOT, "scripts", "fixtures")
GOLD_DIR = os.path.join(FIX_DIR, "golden")
os.environ.setdefault("MD_SKIP_ADHOC_FETCH", "1")  # 臨時休市偵測活資料隔離(全部入口)
FROZEN = _real_dt.datetime(2026, 7, 2, 11, 30, tzinfo=_real_dt.timezone.utc)  # 週四 19:30 TW
SUBSCRIBERS = ("tw-user@test.local", "us-user@test.local", "nohold-user@test.local",
               "nohold2-user@test.local")  # 末位與 nohold 同(depth,tier)→覆蓋精選版快取命中路徑
US_H = ["AAPL", "NVDA", "TSLA"]
TW_H = ["2330", "2317", "2454"]
# 樁版訊號卡:2026-08-18 r2 驗證者 F1[HIGH] —— 樁的回傳不含 `<div class="signal-card`,
# analyzer._collect() 切段時整段丟棄 ⇒ `_card_passes_audit` 從未被呼叫、17 張卡全部落到
# `_deterministic_signal_card` 模板。也就是說日報「內容量最大的一段」自 harness 誕生起
# 就沒被凍結過,連 `_strip_reason_leak` / `_augment_shallow_reason` / `_CARD_XUSER_CACHE`
# / `_CARD_XUSER_BEST`(08-17 holdings_uncovered 擴散的載體)全是零覆蓋。
# 樁卡必須真的過得了 _card_passes_audit:3 個 battle-row + reason 純文字 ≥70 字 + 帶價位
# + 帶時間窗 + div 配對;signal-ticker 要填 prompt 指定的代號,否則 _collect 的 match 對不上。
_CARD_TARGETS_RE = re.compile(r"標的\([^)]*\)[:：]\s*([^\n]+)")
# 樁**故意**不生這一支的卡:讓 `cards_by_sym.get(s) or _deterministic_signal_card(...)`
# 那條備援線與 card-regen 重生迴圈也留在凍結範圍內。否則「全部卡都過閘」會把備援路徑
# 從 golden 裡整個抹掉 —— 那是拿一個盲區換另一個盲區(08-18 r2 F1 的教訓的反面)。
# 判準因此不是「零張備援卡」,而是「備援卡只出現在我故意戳的那一支」。
_CARD_STUB_SKIP = ("TSLA",)


_STUB_HASH_RE = re.compile(r"固定樁卡 [0-9a-f]{8}")


def _diff_kind(gold, now):
    """差異的種類:prompt-only(只有樁卡雜湊變)還是 render(渲染/流程真的變了)。

    樁卡的雜湊吃 (代號, len(prompt)) —— 那是 harness 刻意設計的「prompt 改動可見」訊號。
    把雜湊遮掉後兩邊逐字相同 ⇒ 這次差異只證明 prompt 文字被改過,不是行為回歸。
    行數不等一律算 render(寧可保守:多說一次「去查」不會有人受傷,說錯成 prompt-only
    會讓真的回歸被當成例行祝福蓋過去)。
    """
    g = [_STUB_HASH_RE.sub("固定樁卡 X", x) for x in gold.splitlines()]
    n = [_STUB_HASH_RE.sub("固定樁卡 X", x) for x in now.splitlines()]
    return "prompt-only" if g == n else "render"


def _card_stub(prompt):
    """卡片批次 prompt → 每支一張合格樁卡;不是卡片 prompt 回 None。"""
    m = _CARD_TARGETS_RE.search(prompt)
    if not m or 'signal-card' not in prompt:
        return None
    syms = [s.strip() for s in m.group(1).split(",") if s.strip()]
    syms = [s for s in syms if s not in _CARD_STUB_SKIP]
    if not syms:
        return None
    out = []
    for s in syms:
        h = hashlib.sha256(f"{s}|{len(prompt)}".encode("utf-8")).hexdigest()[:8]
        out.append(
            "<!--CARD-->\n"
            '<div class="signal-card hold">'
            '<div class="signal-card-top">'
            f'<span class="signal-ticker">{s}</span>'
            '<span class="signal-day-move up">▲ +1.23%</span>'
            '<div class="signal-score-block"><span class="signal-score">6</span>'
            '<span class="signal-score-label">/ 10</span></div>'
            '<span class="signal-bias neutral">📈 NEUTRAL</span>'
            '</div>'
            '<div class="signal-body">'
            f'<div class="signal-reason">固定樁卡 {h}:{s} 昨日收在 100 元附近、量能持續萎縮,'
            '短線仍在區間整理。本週若回測 95 元不破且收盤站回 102 元可分批接回;'
            '跌破 92 元先停損控制風險,上方目標看 115 元。(harness 樁文字,無真實市場判斷)</div>'
            '<div class="signal-battle-plan">'
            '<div class="battle-row"><span class="battle-label">建議買價</span>'
            '<span class="battle-val">95–102 元</span></div>'
            '<div class="battle-row"><span class="battle-label">賺錢目標</span>'
            '<span class="battle-val up">115 元</span></div>'
            '<div class="battle-row"><span class="battle-label">止損賣價</span>'
            '<span class="battle-val down">92 元</span></div>'
            '</div>'
            '<div class="signal-watch">👀 盯 95 元支撐能不能守住</div>'
            '<div class="signal-meta">'
            '<span class="signal-badge hold">🟡 續抱持有</span>'
            '<span class="signal-confidence">信心 60%</span>'
            '<span class="signal-horizon">⏱ 本週視角</span>'
            '</div></div></div>')
    return "\n".join(out)


# 樁版 TLDR:結構照 analyzer._tldr_skeleton 的逐字骨架(div.tldr > div.tldr-title + ul>li),
# 內容同時帶台股與美股關鍵字,讓 tldr_missing_tw / tldr_missing_us 都成立。
TLDR_STUB = (
    '<div class="tldr">\n'
    '<div class="tldr-title">⚡ 30 秒重點</div>\n'
    '<ul>\n'
    '  <li>台股:台積電(2330)昨日收平,加權指數量縮整理。</li>\n'
    '  <li>美股:AAPL 與 NVDA 昨夜小幅震盪,費半收在均線之上。</li>\n'
    '  <li>你的持股今日沒有需要立刻動作的事件,維持原本計畫。</li>\n'
    '  <li>今日觀察:留意開盤量能是否跟上,量縮則不追高。</li>\n'
    '</ul>\n'
    '</div>')

# 2026-07-04 修:_track_stats() 讀活資料 docs/data/track-record.json(08:00 TW cron 每天更新),
# 之前沒凍結 → 每次 08:00 之後跑 diff 都會因信心/避坑數字漂移而假 DIFF(9 個變體全紅),
# 跟任何程式改動無關,逼每次改 analyzer.py 都要順手 reseal 才看得出真假。固定樁值,不再吃活資料。
FIXED_TRACK_STATS = {
    "era": {
        "a_count": 60, "a_wins": 33, "a_rate": 55.0,
        "c_count": 40, "c_wins": 24, "c_rate": 60.0,
        "by_regime": {
            "up": {"a_wins": 20, "a_count": 35},
            "down": {"a_wins": 10, "a_count": 20},
        },
    },
    "a_count": 60, "a_wins": 33, "a_rate": 55.0,
    "c_count": 40, "c_wins": 24, "c_rate": 60.0,
}


def _frozen_classes():
    real = _real_dt

    class FrozenDateTime(real.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return FROZEN.replace(tzinfo=None)
            return FROZEN.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return FROZEN.replace(tzinfo=None)

        @classmethod
        def today(cls):
            return FROZEN.replace(tzinfo=None)

    class FrozenDate(real.date):
        @classmethod
        def today(cls):
            return FROZEN.date()

    return FrozenDateTime, FrozenDate


def _install_frozen_datetime():
    """換掉 sys.modules['datetime'] 讓函式內 late import 吃到凍結時鐘。
    ⚠️ 必須在 pandas/premailer/pickle 等 C 擴充相關載入【之後】才呼叫:
    pandas nattype 在假模組下 C-level 初始化會無限遞迴 segfault(2026-07-03 實測)。"""
    FrozenDateTime, FrozenDate = _frozen_classes()
    fake = types.ModuleType("datetime")
    for k in dir(_real_dt):
        if not k.startswith("_"):
            setattr(fake, k, getattr(_real_dt, k))
    fake.datetime = FrozenDateTime
    fake.date = FrozenDate
    sys.modules["datetime"] = fake
    return FrozenDateTime


def _install_net_tripwire():
    """把檔頭寫的「零真實 LLM 呼叫」從宣稱變成機器強制的不變量。

    2026-08-18:provider 樁是**手寫名單**,analyzer 08-03 新增 _call_mistral 沒補進去,
    harness 就安靜地對 api.mistral.ai 真發了兩週認證請求(429 才露餡)——名單型防線只擋
    得住「我記得的那些」。這道 tripwire 反過來守出口:任何 HTTP 出去就當場炸,漏掉的樁
    會在第一次跑就變成紅字,而不是變成一張帳單或一次擲骰子的 golden。
    要臨時放行(例如手動 debug)設 MD_HARNESS_ALLOW_NET=1。
    """
    if os.environ.get("MD_HARNESS_ALLOW_NET") == "1":
        return
    import requests.sessions as _rs
    import urllib.request as _ur

    def _blocked(where, url):
        raise RuntimeError(
            f"harness 網路出口未封:{where} → {url}\n"
            "  golden 必須零外部呼叫。請把對應的 provider/fetch 打樁,"
            "或確認 analyzer 是否新增了沒被 _call_* 蓋到的呼叫路徑。")

    _orig_req = _rs.Session.request

    def _guard(self, method, url, *a, **kw):
        _blocked(f"requests {method}", str(url)[:120])
        return _orig_req(self, method, url, *a, **kw)  # pragma: no cover

    _rs.Session.request = _guard
    _ur.urlopen = lambda url, *a, **kw: _blocked(
        "urlopen", str(getattr(url, "full_url", url))[:120])


def _load_modules():
    import time as _t
    _t.sleep = lambda *a, **k: None
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    # 臨時休市偵測走網路(TWSE 公告)+當日快取,活資料會弄髒 golden → 隔離掉,
    # harness 內只吃 override 檔(repo 內容,確定性)。
    os.environ["MD_SKIP_ADHOC_FETCH"] = "1"
    import analyzer
    import main
    import premailer  # noqa: F401  真 datetime 下先載完(lxml/cssutils C 擴充)
    FrozenDateTime = _install_frozen_datetime()
    main.datetime = FrozenDateTime  # main 頂層 from datetime import datetime 的補丁

    def fake_llm(prompt: str, prefer_strong: bool = False, **_kw) -> str:
        h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        body = (
            '<div class="section-label">AI 觀點(樁)</div>'
            f"<p>LLM固定樁 {h} len={len(prompt)} strong={int(bool(prefer_strong))}。"
            "台積電(2330)昨日走勢平穩,AAPL 亦無重大波動,信心 65%。</p>"
        )
        # prompt 要求 .tldr 骨架時,樁也要吐出**合格**的 tldr,否則 digest_audit 直接 HIGH
        # (tldr_section_missing / tldr_too_short / tldr_missing_tw)→ 每位用戶都掉
        # deterministic fallback,characterization 就只凍結得到備援路徑,AI 個人化編排
        # (本 harness 存在的唯一理由)一行都沒被覆蓋到。2026-08-18 F1 的第二層。
        if 'class="tldr"' in prompt:
            body = TLDR_STUB + body
        card_batch = _card_stub(prompt)
        if card_batch:
            return card_batch
        return body

    analyzer._llm_generate = fake_llm

    # council 席次不走 _llm_generate 而是直呼各 _call_*(2026-07-03 首跑實測打到真 Gemini
    # 還吃了 429)——provider caller 全打樁,保證整個 golden 流程零 LLM 網路呼叫。
    # 2026-08-18 修:原本是**手寫的 8 個名字**,而 analyzer 08-03 新增的 _call_mistral 沒人
    # 補進來 ⇒ harness 自 08-03 起每跑一次就對 api.mistral.ai 真發一次認證請求(實測回 429),
    # 檔頭寫的「零真實 LLM 呼叫、零配額消耗」有兩週是假的;更糟的是 mistral 哪天回 200,
    # council 就吃到真 LLM 文字 ⇒ golden 變成擲骰子。改成從 analyzer 自己列舉,新增 provider
    # 自動被蓋住,不必記得回來改這行。
    def _stub_provider(tag):
        def _stub(prompt, *a, **kw):
            h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:10]
            return f"看多|信心65|{tag}樁{h}|MA20支撐,量縮整理,逢低分批。"
        _stub._harness_stub = True
        return _stub

    _providers = sorted(n for n in dir(analyzer)
                        if n.startswith("_call_") and callable(getattr(analyzer, n, None)))
    if not _providers:
        raise SystemExit("harness: analyzer 找不到任何 _call_* provider,樁失效")
    for _name in _providers:
        setattr(analyzer, _name, _stub_provider(_name.replace("_call_", "")))
    _leaked = [n for n in _providers
               if not getattr(getattr(analyzer, n), "_harness_stub", False)]
    if _leaked:
        raise SystemExit(f"harness: provider 未打樁 {_leaked}")

    _install_net_tripwire()

    analyzer._track_stats = lambda: FIXED_TRACK_STATS

    main._inject_ai_banner = lambda html, date: html
    return analyzer, main


def _fixture():
    with open(os.path.join(FIX_DIR, "refactor_fixture.pkl"), "rb") as f:
        return pickle.load(f)


def _many_holdings(data):
    us = [s for s in sorted((data.get("us_market") or {}).keys()) if s.isalpha()][:20]
    tw = [s for s in sorted((data.get("tw_market") or {}).keys()) if s.isdigit()][:15]
    return us, tw


def _augmented(data):
    aug = dict(data)
    aug["political_signals"] = [{
        "direction": "bearish", "name_zh": "測試議員", "handle": "@test",
        "headline_zh": "測試:關稅將調整", "impact_zh": "測試影響半導體",
        "affected": ["2330", "AAPL"], "post_url": "https://x.com/test/1",
    }]
    aug["intel_signals"] = {
        "2330": [
            {"level": "red", "source": "margin", "signal": "融資5日+12%(測試樁)"},
            {"level": "yellow", "source": "sbl", "signal": "借券賣出5日+8%(測試樁)"},
        ],
        "2317": [{"level": "plain", "source": "inst", "signal": "不該出現(plain 級)"}],
    }
    aug.setdefault("tw_names_all", {})
    aug["tw_names_all"] = dict(aug["tw_names_all"] or {})
    aug["tw_names_all"].setdefault("2330", "台積電")
    return aug


class _Chdir:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.old = os.getcwd()
        os.chdir(self.path)

    def __exit__(self, *a):
        os.chdir(self.old)


def _variants():
    data = _fixture()  # 在換假 datetime 模組前先 unpickle(內含真 datetime 物件)
    analyzer, main = _load_modules()
    date = data.get("date") or "2026-07-02"
    us_many, tw_many = _many_holdings(data)
    v = {}
    v["report_both_std_email"] = analyzer.generate_report(data, US_H, TW_H, email_safe=True)
    v["report_tw_deep_premium"] = analyzer.generate_report(
        data, US_H, TW_H, depth="deep", market="tw", is_premium=True)
    v["report_us_simple"] = analyzer.generate_report(data, US_H, TW_H, depth="simple", market="us")
    v["report_picks"] = analyzer.generate_report(data, US_H, TW_H, picks_mode=True)
    v["report_trim35"] = analyzer.generate_report(data, us_many, tw_many, email_safe=True)
    v["weekend"] = analyzer.generate_weekend_report(data, US_H, TW_H)
    v["monday"] = analyzer.generate_monday_report(data, US_H, TW_H)
    mkt = analyzer._market_status(date)
    v["market_status"] = json.dumps(mkt, ensure_ascii=False, sort_keys=True, indent=1)
    v["fallback"] = analyzer.generate_deterministic_fallback(data, US_H, TW_H, mkt)
    v["subject"] = analyzer.get_personalized_subject(data, US_H, TW_H, date)
    v["email_shell"] = main.build_email_html(date, v["report_us_simple"])
    aug = _augmented(data)
    v["inject_political"] = main._inject_political_signals(v["report_us_simple"], aug, TW_H)
    v["inject_intel"] = main._inject_intel_signals(v["report_us_simple"], aug, TW_H + US_H)
    with tempfile.TemporaryDirectory() as td:
        with _Chdir(td):
            p = main.save_local(date, v["report_us_simple"])
            with open(p, encoding="utf-8") as f:
                v["save_local"] = f.read()
    return v


def _norm(s: str) -> str:
    s = re.sub(r"\d{4}-\d{2}-\d{2}", "YYYY-MM-DD", s)
    s = re.sub(r"(?<!\w)\d{1,2}:\d{2}(?::\d{2})?(?!\w)", "HH:MM", s)
    # 每輪隨機的臨時目錄(語音 manifest 隔離後會被印進 stdout)→ 固定字樣,否則 golden 每跑必變
    s = re.sub(r"/tmp/[A-Za-z0-9_]*tmp[A-Za-z0-9_]+", "/tmp/TMPDIR", s)
    return s


def _env_values():
    vals = []
    envp = os.path.join(ROOT, ".env")
    if os.path.exists(envp):
        for line in open(envp, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if len(val) >= 8:
                    vals.append(val)
    return vals


def _leak_guard(text: str, label: str):
    for val in _env_values():
        if val in text:
            print(f"🔴 {label} 內含 .env 真實 secret 片段,拒絕寫入 golden!")
            sys.exit(2)


def cmd_golden():
    os.makedirs(GOLD_DIR, exist_ok=True)
    v = _variants()
    for name, content in v.items():
        out = _norm(content)
        _leak_guard(out, name)
        with open(os.path.join(GOLD_DIR, f"{name}.golden"), "w", encoding="utf-8") as f:
            f.write(out)
        print(f"  golden: {name} ({len(out)} chars)")
    print(f"✅ 黃金基線 {len(v)} 個變體 → {GOLD_DIR}")


def cmd_diff():
    v = _variants()
    bad = 0
    prompt_only = 0
    for name, content in v.items():
        gp = os.path.join(GOLD_DIR, f"{name}.golden")
        if not os.path.exists(gp):
            print(f"🔴 {name}: 缺 golden 檔")
            bad += 1
            continue
        with open(gp, encoding="utf-8") as f:
            gold = f.read()
        now = _norm(content)
        if now != gold:
            bad += 1
            kind = _diff_kind(gold, now)
            if kind == "prompt-only":
                prompt_only += 1
            print(f"🔴 {name}: DIFF({'只有 prompt 文字改了' if kind == 'prompt-only' else '渲染/流程改了'})")
            diff = list(difflib.unified_diff(
                gold.splitlines(), now.splitlines(),
                fromfile=f"golden/{name}", tofile="current", lineterm=""))[:40]
            print("\n".join(diff))
        else:
            print(f"  ✅ {name}")
    if bad:
        print(f"🔴 {bad} 個變體與黃金基線不符")
        # 2026-09-07:這支從 08-30(反 AI 腔改卡片 prompt)起連紅 11 天沒人動。
        # 原因不是沒人看告警,是告警只說「不符」——讀的人分不出「prompt 改了該重新祝福」
        # 與「渲染真的回歸了」,於是每天都留給下一個人。差異的【種類】必須寫在告警裡。
        if prompt_only == bad:
            print("ℹ️ 全部差異只在樁卡的 prompt 雜湊 ⇒ 渲染與流程逐字未變,這是【prompt 內容被改過】"
                  "(harness 刻意讓 prompt 改動可見,見檔頭)。確認那次改動是有意的之後,"
                  "重新祝福基線:.venv/bin/python scripts/refactor_harness.py golden")
        else:
            print("⚠️ 有差異落在 prompt 雜湊【以外】的地方 ⇒ 渲染或流程真的變了,先查回歸再談祝福。")
        sys.exit(1)
    print("✅ 全部變體與黃金基線一致(行為凍結成立)")


def _provider_snaps():
    for k, dummy in {
        "ANTHROPIC_API_KEY": "TESTKEY-ANT", "OPENAI_API_KEY": "TESTKEY-OAI",
        "GROQ_API_KEY": "TESTKEY-GROQ", "CF_AI_PROXY_TOKEN": "TESTKEY-CF",
        "CF_AI_PROXY_URL": "https://cf-proxy.test/ai",
        "OPENROUTER_API_KEY": "TESTKEY-OR", "CEREBRAS_API_KEY": "TESTKEY-CER",
        "MISTRAL_API_KEY": "TESTKEY-MIS",
    }.items():
        os.environ[k] = dummy
    import time as _t
    _t.sleep = lambda *a, **k: None
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import analyzer  # provider 快照不需要凍時鐘,不動 sys.modules(防 pandas segfault)
    analyzer.GEMINI_API_KEY = "TESTKEY-GEM"
    # CF neuron 預算閘門吃**當日活用量**(cf_neuron_budget.budget_ok 讀 UTC 日的帳本):
    # 額度用得多的那天 _call_cf_ai 會在發請求前先 raise ⇒ provider 快照跟任何程式改動無關
    # 地變紅(2026-08-18 實遇:9876/6500)。與 7bef298c 凍結 _track_stats 同一個道理——
    # 行為凍結 harness 不准把活資料當輸入。record 一併打樁,確保快照永遠不寫真帳本。
    analyzer._cf_budget.budget_ok = lambda: True
    analyzer._cf_budget.record = lambda *a, **k: 0.0

    calls = []

    class FakeResp:
        def __init__(self, url):
            self.url = url
            self.status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            u = self.url
            if "generativelanguage" in u:
                return {"candidates": [{"content": {"parts": [{"text": "PONG"}]}}]}
            if "anthropic" in u:
                return {"content": [{"type": "text", "text": "PONG"}]}
            if "cf-proxy.test" in u:
                return {"response": "PONG"}
            if "11434" in u:
                return {"message": {"content": "PONG"}}
            return {"choices": [{"message": {"content": "PONG"}}]}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResp(url)

    analyzer.requests.post = fake_post
    snaps = {}

    def snap(name, fn):
        calls.clear()
        parsed = fn()
        snaps[name] = {"calls": [dict(c) for c in calls], "parsed": parsed}

    m0 = analyzer.GEMINI_MODELS[0]
    snap("gemini_default", lambda: analyzer._call_gemini("PING", m0))
    snap("gemini_sys", lambda: analyzer._call_gemini("PING", m0, system="SYS-TEST"))
    snap("claude_default", lambda: analyzer._call_claude("PING"))
    snap("claude_custom", lambda: analyzer._call_claude("PING", system="SYS-TEST", model="claude-test-1"))
    snap("openai_default", lambda: analyzer._call_openai("PING"))
    snap("openai_sys", lambda: analyzer._call_openai("PING", system="SYS-TEST"))
    snap("groq_default", lambda: analyzer._call_groq("PING"))
    snap("groq_custom", lambda: analyzer._call_groq("PING", system="SYS-TEST", model="m-test", max_tokens=1234))
    snap("cf_ai_default", lambda: analyzer._call_cf_ai("PING"))
    snap("cf_ai_custom", lambda: analyzer._call_cf_ai("PING", system="SYS-TEST", max_tokens=1234))
    snap("openrouter_default", lambda: analyzer._call_openrouter("PING"))
    snap("openrouter_custom", lambda: analyzer._call_openrouter("PING", system="SYS-TEST", max_tokens=1234))
    snap("cerebras_default", lambda: analyzer._call_cerebras("PING"))
    snap("cerebras_custom", lambda: analyzer._call_cerebras("PING", system="SYS-TEST", max_tokens=1234))
    snap("ollama_default", lambda: analyzer._call_ollama("PING"))
    snap("ollama_custom", lambda: analyzer._call_ollama("PING", system="SYS-TEST", model="m-test", max_tokens=1234))
    snap("mistral_default", lambda: analyzer._call_mistral("PING"))
    snap("mistral_custom", lambda: analyzer._call_mistral("PING", system="SYS-TEST", max_tokens=1234))

    # 快照名單是手寫的 ⇒ 會漏。mistral 08-03 入鏈後 payload 形狀就一直沒被凍過(這次補上)。
    # 這道斷言把「我記得列了誰」換成「analyzer 有誰就必須有誰」,下次再新增 provider 時
    # 是這裡當場紅,而不是又過了兩週才被別的症狀撞出來。
    _expected = {n[len("_call_"):] for n in dir(analyzer)
                 if n.startswith("_call_") and callable(getattr(analyzer, n, None))} - {"openai_style"}
    _missing = sorted(p for p in _expected
                      if not any(k == p or k.startswith(p + "_") for k in snaps))
    if _missing:
        raise SystemExit(f"provider 快照漏了 {_missing}(analyzer 新增 provider 要補 snap)")

    def chain(prefer_strong):
        calls.clear()

        def post_probe(url, headers=None, json=None, timeout=None, **kw):
            calls.append({"url": url})
            raise RuntimeError("chain-probe")

        analyzer.requests.post = post_probe
        try:
            analyzer._llm_generate("PING", prefer_strong=prefer_strong)
        except RuntimeError:
            pass
        analyzer.requests.post = fake_post
        return [c["url"].split("?")[0] for c in calls]

    snaps["_chain_order_default"] = chain(False)
    snaps["_chain_order_strong"] = chain(True)
    return snaps


def cmd_provider(mode):
    os.makedirs(GOLD_DIR, exist_ok=True)
    snaps = _provider_snaps()
    text = json.dumps(snaps, ensure_ascii=False, sort_keys=True, indent=1)
    _leak_guard(text, "provider_snap")
    gp = os.path.join(GOLD_DIR, "provider_snap.json")
    if mode == "golden":
        with open(gp, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"✅ provider 快照 {len(snaps)} 項 → {gp}")
        return
    with open(gp, encoding="utf-8") as f:
        gold = f.read()
    if text != gold:
        diff = list(difflib.unified_diff(
            gold.splitlines(), text.splitlines(),
            fromfile="golden/provider_snap", tofile="current", lineterm=""))[:60]
        print("\n".join(diff))
        print("🔴 provider 快照與黃金基線不符")
        sys.exit(1)
    print("✅ provider 快照一致(payload/解析/鏈序凍結成立)")


def _stub_unsub_list():
    """退訂名單(main._drop_unsubscribed)的網路出口打樁。

    2026-08-18 tripwire 抓到:run_smoke 的檔頭寫「mock 全部網路出口」,實際上 08-17 上線的
    退訂第一層每跑一次就打一次**正式站 Worker** `/internal/unsub-list` —— 等於 golden 的
    內容綁在線上 KV 的活狀態上(今天有人退訂,明天這支 characterization 就會無故變紅),
    而且測試在對生產環境發帶 token 的請求。這裡改成固定樁:token 也給固定假值,讓
    `_drop_unsubscribed` 的真邏輯(HTTP→json→norm_email→比對)整條跑完且完全確定性。
    名單刻意放一個**不在訂閱者裡**的地址 —— 保留原本 4 位訂閱者的覆蓋形狀(第 4 位是
    b67be887 為了打到精選版快取命中路徑才加的),不因為打樁而少測一條路。
    """
    import requests as _rq
    os.environ["MARKETDAILY_INTERNAL_TOKEN"] = "harness-fixed-internal-token"

    class _Resp:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"emails": ["already-gone@test.local"], "truncated": False}

    def _get(url, *a, **kw):
        if "/internal/unsub-list" in str(url):
            return _Resp()
        raise RuntimeError(f"harness run_smoke 未預期的 HTTP GET → {str(url)[:120]}")

    _rq.get = _get


def _stub_live_intel_notes(analyzer):
    """把兩個「讀活檔」的 prompt 補充段打樁(2026-08-20)。

    `_social_buzz_note` 讀 intel/social_buzz 的 latest.json、`_leadflow_note` 讀
    leadflow_latest.json —— 兩份都是 cron 每天重寫的活檔。它們只進 **prompt**,而 LLM 是
    樁,所以 golden 的 HTML 內容不受影響……除了 `_card_stub` 的卡片編號綁在 len(prompt) 上:
    於是「今天的社群聲量變了」會讓 golden 每天無故變紅(08-19、08-20 連兩天,診斷訊息只有
    一串看不懂的 8 碼 hash)。這跟 `_stub_unsub_list` 修的是同一種病:
    **characterization 基線不可以綁在會自己變動的活狀態上**。
    樁值刻意非空,讓注入點的字串拼接與長度效應仍在凍結範圍內(給空字串等於連注入都不測)。
    """
    calls = {"_social_buzz_note": 0, "_leadflow_note": 0}

    def _mk(name, text):
        def _f(data):
            calls[name] += 1
            return text
        return _f

    _stub(analyzer, "_social_buzz_note",
          _mk("_social_buzz_note",
              "\n【社群聲量觀察(harness 固定樁)】2330 討論度連兩日居前,純觀察不改方向。\n"))
    _stub(analyzer, "_leadflow_note",
          _mk("_leadflow_note",
              "\n【先行異動雷達(harness 固定樁)】2317 量價先行,尚無公開消息,只作觀察。\n"))
    return calls


def _stub(obj, name, fn):
    """裝樁,並強制「生產端的呼叫吃得下這個樁」:binding 失敗當場炸開,
    不准被生產碼的 try/except 吞掉、悄悄退化成備援路徑。

    2026-08-18 事故:main.save_hosted_digest 在 07-09(775aedea)多了 email= 參數,
    harness 的樁沒跟上 → 四位用戶每個都 TypeError → 全員掉 deterministic fallback,
    run_smoke.golden 從此凍結的是「備援路徑」而不是 AI 個人化路徑,40 天沒人發現,
    08-18 的 reseal 還差點把這個退化蓋章成正解。"""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None
    where = f"{getattr(obj, '__name__', obj)}.{name}"

    def _wrapped(*a, **kw):
        if sig is not None:
            try:
                sig.bind(*a, **kw)
            except TypeError as e:
                raise SystemExit(
                    f"🔴 harness 樁與生產簽章漂移:{where} 吃不下生產呼叫({e})。\n"
                    f"   → 把樁改成符合生產簽章,**不要** reseal golden——"
                    f"golden 會把「呼叫失敗後的備援路徑」凍結成正解。")
        return fn(*a, **kw)

    setattr(obj, name, _wrapped)


# 生產端會印的退化訊息(main.py/analyzer.py 逐字抄來,r2 驗證者 F2:原本只認三種措辭,
# 「🛡️ 預設版 AI 生成全失敗,改用 deterministic 備援版」這條——四封信內容全爛——直接漏網)。
_DEGRADE_MARKS = (
    "個人化失敗", "deterministic fallback", "掉備援",
    "deterministic 備援版",      # main.py 預設版全失敗
    "剩餘走 deterministic",       # analyzer 卡片時間預算用盡
    "其餘改 deterministic",       # analyzer 單支重試也失敗
)


def _assert_not_degraded(stdout_text, sent, det_cards=(), expect_sent=None):
    """run_smoke 一旦退化成備援/預設版就直接紅(而不是靠人肉看 diff)。
    characterization 的價值全在「真的走過 AI 個人化編排」,走備援等於什麼都沒凍結。

    2026-08-18 r2 驗證者 F1/F2:只比對 stdout 措辭是「守措辭不守行為」——生產端改一次
    文案守衛就靜默。所以主判準改成**狀態**:deterministic 模板卡張數、寄出封數;
    字串比對只留當第二層。"""
    marks = [m for m in _DEGRADE_MARKS if m in stdout_text]
    no_subject = [s.get("email") for s in sent if not s.get("subject")]
    short_sent = expect_sent is not None and len(sent) != expect_sent
    det_syms = set(det_cards)
    # 備援卡只准出現在故意戳的那一支;多一支 = AI 卡路徑正在靜默退化(F1 的偵測器)。
    unexpected_det = sorted(det_syms - set(_CARD_STUB_SKIP))
    # 反方向也要守:一支都沒有 = 備援線本身沒被走到,凍結範圍缺一塊(且代表 skip 名單失效)。
    missing_det = sorted(set(_CARD_STUB_SKIP) - det_syms)
    # 連一張備援卡都沒有 = 備援線整條沒被走到(例如有人把 _CARD_STUB_SKIP 清空),
    # 那是把一個盲區換成另一個盲區,同樣不准封進 golden。
    no_det = not det_syms
    if marks or no_subject or unexpected_det or missing_det or no_det or short_sent:
        raise SystemExit(
            "🔴 run_smoke 走進了退化路徑(或覆蓋缺口),基線無效:\n"
            f"   非預期的 deterministic 模板卡 {unexpected_det or '—'}"
            f"(全部備援卡:{sorted(det_syms) or '—'})\n"
            f"   故意戳的那支沒走到備援 {missing_det or '—'}"
            f"{';且一張備援卡都沒有=備援線零覆蓋' if no_det else ''}\n"
            f"   寄出 {len(sent)}/{expect_sent if expect_sent is not None else '?'} 封;"
            f"subject 為空的收件人 {no_subject or '—'}\n"
            f"   stdout 命中 {marks or '—'}\n"
            "   → 先查為什麼個人化失敗(常見:樁與生產簽章漂移),修好再 reseal。")


def _run_smoke():
    """run() 的 characterization:mock 全部網路出口,4 個合成用戶跑完整 run(),
    回傳 normalized(stdout + 寄件清單含每封 html 雜湊 + audit 狀態摘要)。

    ⚠️ 打樁的固有邊界(2026-08-18 r2 驗證者點名,別誤讀這份 golden 的綠燈):
    - 樁對所有用戶回同一份 TLDR / 同一組卡片文字 ⇒ 「內容有沒有真的**因人而異**」
      這件事本 characterization 永遠測不到;它凍的是**編排**(誰收到哪一版、走哪條路徑、
      每封信的 html 雜湊),不是內容品質。
    - 樁刻意讓 `_CARD_STUB_SKIP` 那支生不出卡,好讓備援線與 card-regen 迴圈也在凍結範圍內。"""
    import io
    import contextlib
    data = _fixture()
    analyzer, main = _load_modules()
    import publisher
    import data_fetcher

    main.MARKET = "tw"
    main.DRY_RUN = False
    _stub(main, "fetch_all", lambda *a, **kw: data)
    _stub(main, "filter_us_news", lambda x, *a, **kw: x)
    _stub(main, "filter_tw_news", lambda x, *a, **kw: x)
    _stub(main, "_hold_until_send_time", lambda *a, **kw: None)
    _stub(main, "save_hosted_digest",
          lambda html, date="", email="", *a, **kw: "https://hosted.test/digest")
    _stub(main, "_push_admin_halt_alert", lambda *a, **k: None)
    _stub(main, "_push_admin_coverage_alert", lambda *a, **k: None)
    _stub(main, "_push_preflight_alert", lambda *a, **k: None)
    # 網路 tripwire 抓到的第三個出口:HIGH check 連中 3 位會 urlopen 打 alert-worker
    _stub(main, "_push_systemic_alert", lambda *a, **k: None)
    _stub_unsub_list()
    _stub(publisher, "get_list_id", lambda *a, **kw: 1)
    _stub(publisher, "check_subscriber_count", lambda *a, **kw: 3)
    _stub(publisher, "get_all_subscribers", lambda *a, **kw: list(SUBSCRIBERS))
    sent = []
    det_cards = []
    _real_det = analyzer._deterministic_signal_card

    def _count_det(sym, *a, **kw):
        det_cards.append(sym)
        return _real_det(sym, *a, **kw)

    _stub(analyzer, "_deterministic_signal_card", _count_det)

    def _fake_send(email, date, html, key, subject=None):
        sent.append({"email": email, "subject": subject,
                     "html_sha": hashlib.sha256(_norm(html).encode()).hexdigest(),
                     "html_len": len(_norm(html))})
        return True

    # r2 F3:窄簽章的樁**才是** bind 檢查唯一發揮得了作用的形狀,而寄信這支(最要命的出口)
    # 原本是直接指派、繞過防線 —— publisher 寄信簽章哪天多一個 kwarg,TypeError 會被
    # main 的 except Exception 吃掉變成「四封寄送失敗」,而不是「樁漂移」。
    _stub(publisher, "send_transactional_email", _fake_send)
    prefs_map = {
        "tw-user@test.local": {"us_stocks": [], "tw_stocks": TW_H,
                               "digest_depth": "standard", "plan": "free"},
        "us-user@test.local": {"us_stocks": US_H, "tw_stocks": [],
                               "digest_depth": "deep", "plan": "premium"},
        "nohold-user@test.local": {"us_stocks": [], "tw_stocks": [],
                                   "digest_depth": "simple", "plan": "free"},
        "nohold2-user@test.local": {"us_stocks": [], "tw_stocks": [],
                                    "digest_depth": "simple", "plan": "free"},
    }
    _stub(main, "get_user_preferences", lambda email: dict(prefs_map[email]))
    _stub(analyzer, "council_top_picks", lambda d, mk, n=3: ["2330", "2317"])
    _intel_note_calls = _stub_live_intel_notes(analyzer)
    data_fetcher._LAST_TW_MISSING = []

    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        # 語音 manifest 的輸出路徑是**絕對**的(audio_brief/out,不隨 chdir 走),所以
        # harness 每跑一次就真的在生產樹寫一份 manifest_2026-07-03_tw.json ——
        # 該目錄在 .gitignore 裡,所以 git status 永遠看不到它,08-18 才查出來。
        # 導到臨時目錄:write_manifest 的覆蓋保留,生產樹零落檔。
        import audio_brief.manifest as _abm
        _abm.OUT = pathlib.Path(td) / "audio_out"
        with _Chdir(td):
            with contextlib.redirect_stdout(buf):
                main.run()
            audit = ""
            ap = os.path.join(td, "output", f"digest_audit_{data.get('date')}.json")
            if os.path.exists(ap):
                with open(ap, encoding="utf-8") as f:
                    audit = f.read()
    _assert_not_degraded(buf.getvalue(), sent, det_cards, len(SUBSCRIBERS))
    # 死人開關:樁裝了但**沒被呼叫**=生產端改了名字/拿掉了呼叫,活檔會從別的地方溜回 prompt,
    # 而 golden 依然全綠(這正是「裝了樁就以為隔離了」的假綠)。沒被呼叫就當場炸掉。
    _unused = [k for k, v in _intel_note_calls.items() if v == 0]
    if _unused:
        raise SystemExit("樁裝了卻沒被呼叫: " + ", ".join(_unused)
                         + " —— 生產端改名或拿掉呼叫了,活檔可能又溜進 prompt。修樁,不要 reseal golden。")
    out = ("=== STDOUT ===\n" + _norm(buf.getvalue())
           + "\n=== SENT ===\n" + json.dumps(sent, ensure_ascii=False, indent=1, sort_keys=True)
           # r2 F4:audit 報告檔**只有壞掉時才存在**(main.py 三個 list 全空就不寫檔),
           # 所以這一段在健康時永遠是空字串 =「audit 通過」這件事根本沒被 golden 守住。
           # 補一行狀態摘要:全綠本身被寫進基線,退化時這行會先變。
           + "\n=== AUDIT ===\n"
           + json.dumps({"audit_report_written": bool(audit),
                         "deterministic_cards": sorted(set(det_cards)),
                         "sent": len(sent)}, ensure_ascii=False, sort_keys=True)
           + ("\n" + _norm(audit) if audit else ""))
    return out


def cmd_run(mode):
    os.makedirs(GOLD_DIR, exist_ok=True)
    out = _run_smoke()
    _leak_guard(out, "run_smoke")
    gp = os.path.join(GOLD_DIR, "run_smoke.golden")
    if mode == "golden":
        with open(gp, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"✅ run() smoke 黃金基線 → {gp} ({len(out)} chars)")
        return
    with open(gp, encoding="utf-8") as f:
        gold = f.read()
    if out != gold:
        diff = list(difflib.unified_diff(
            gold.splitlines(), out.splitlines(),
            fromfile="golden/run_smoke", tofile="current", lineterm=""))[:50]
        print("\n".join(diff))
        print("🔴 run() smoke 與黃金基線不符")
        sys.exit(1)
    print("✅ run() smoke 一致(run() 編排行為凍結成立)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["golden"]:
        cmd_golden()
    elif args == ["diff"]:
        cmd_diff()
    elif args[:1] == ["provider"] and args[1:2] and args[1] in ("golden", "diff"):
        cmd_provider(args[1])
    elif args[:1] == ["run"] and args[1:2] and args[1] in ("golden", "diff"):
        cmd_run(args[1])
    else:
        print(__doc__)
        sys.exit(64)
