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
import json
import os
import pickle
import re
import sys
import tempfile
import types
import datetime as _real_dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX_DIR = os.path.join(ROOT, "scripts", "fixtures")
GOLD_DIR = os.path.join(FIX_DIR, "golden")
FROZEN = _real_dt.datetime(2026, 7, 2, 11, 30, tzinfo=_real_dt.timezone.utc)  # 週四 19:30 TW
US_H = ["AAPL", "NVDA", "TSLA"]
TW_H = ["2330", "2317", "2454"]


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


def _load_modules():
    import time as _t
    _t.sleep = lambda *a, **k: None
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import analyzer
    import main
    import premailer  # noqa: F401  真 datetime 下先載完(lxml/cssutils C 擴充)
    FrozenDateTime = _install_frozen_datetime()
    main.datetime = FrozenDateTime  # main 頂層 from datetime import datetime 的補丁

    def fake_llm(prompt: str, prefer_strong: bool = False) -> str:
        h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        return (
            '<div class="section-label">AI 觀點(樁)</div>'
            f"<p>LLM固定樁 {h} len={len(prompt)} strong={int(bool(prefer_strong))}。"
            "台積電(2330)昨日走勢平穩,AAPL 亦無重大波動,信心 65%。</p>"
        )

    analyzer._llm_generate = fake_llm

    # council 席次不走 _llm_generate 而是直呼各 _call_*(2026-07-03 首跑實測打到真 Gemini
    # 還吃了 429)——8 個 provider caller 全打樁,保證整個 golden 流程零 LLM 網路呼叫。
    def _stub_provider(tag):
        def _stub(prompt, *a, **kw):
            h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:10]
            return f"看多|信心65|{tag}樁{h}|MA20支撐,量縮整理,逢低分批。"
        return _stub

    for _name in ("_call_gemini", "_call_claude", "_call_openai", "_call_groq",
                  "_call_cf_ai", "_call_openrouter", "_call_cerebras", "_call_ollama"):
        setattr(analyzer, _name, _stub_provider(_name.replace("_call_", "")))

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
            print(f"🔴 {name}: DIFF")
            diff = list(difflib.unified_diff(
                gold.splitlines(), now.splitlines(),
                fromfile=f"golden/{name}", tofile="current", lineterm=""))[:40]
            print("\n".join(diff))
        else:
            print(f"  ✅ {name}")
    if bad:
        print(f"🔴 {bad} 個變體與黃金基線不符")
        sys.exit(1)
    print("✅ 全部變體與黃金基線一致(行為凍結成立)")


def _provider_snaps():
    for k, dummy in {
        "ANTHROPIC_API_KEY": "TESTKEY-ANT", "OPENAI_API_KEY": "TESTKEY-OAI",
        "GROQ_API_KEY": "TESTKEY-GROQ", "CF_AI_PROXY_TOKEN": "TESTKEY-CF",
        "CF_AI_PROXY_URL": "https://cf-proxy.test/ai",
        "OPENROUTER_API_KEY": "TESTKEY-OR", "CEREBRAS_API_KEY": "TESTKEY-CER",
    }.items():
        os.environ[k] = dummy
    import time as _t
    _t.sleep = lambda *a, **k: None
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import analyzer  # provider 快照不需要凍時鐘,不動 sys.modules(防 pandas segfault)
    analyzer.GEMINI_API_KEY = "TESTKEY-GEM"

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


def _run_smoke():
    """run() 的 characterization:mock 全部網路出口,3 個合成用戶跑完整 run(),
    回傳 normalized(stdout + 寄件清單含每封 html 雜湊 + audit 報告)。"""
    import io
    import contextlib
    data = _fixture()
    analyzer, main = _load_modules()
    import publisher
    import data_fetcher

    main.MARKET = "tw"
    main.DRY_RUN = False
    main.fetch_all = lambda **kw: data
    main.filter_us_news = lambda x: x
    main.filter_tw_news = lambda x: x
    main._hold_until_send_time = lambda mk: None
    main.save_hosted_digest = lambda html, date="": "https://hosted.test/digest"
    main._push_admin_halt_alert = lambda *a, **k: None
    main._push_admin_coverage_alert = lambda *a, **k: None
    main._push_preflight_alert = lambda *a, **k: None
    publisher.get_list_id = lambda: 1
    publisher.check_subscriber_count = lambda lid: 3
    publisher.get_all_subscribers = lambda lid: [
        "tw-user@test.local", "us-user@test.local", "nohold-user@test.local",
        "nohold2-user@test.local"]  # 與 nohold 同(depth,tier)→覆蓋精選版快取命中路徑
    sent = []

    def _fake_send(email, date, html, key, subject=None):
        sent.append({"email": email, "subject": subject,
                     "html_sha": hashlib.sha256(_norm(html).encode()).hexdigest(),
                     "html_len": len(_norm(html))})
        return True

    publisher.send_transactional_email = _fake_send
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
    main.get_user_preferences = lambda email: dict(prefs_map[email])
    analyzer.council_top_picks = lambda d, mk, n=3: ["2330", "2317"]
    data_fetcher._LAST_TW_MISSING = []

    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        with _Chdir(td):
            with contextlib.redirect_stdout(buf):
                main.run()
            audit = ""
            ap = os.path.join(td, "output", f"digest_audit_{data.get('date')}.json")
            if os.path.exists(ap):
                with open(ap, encoding="utf-8") as f:
                    audit = f.read()
    out = ("=== STDOUT ===\n" + _norm(buf.getvalue())
           + "\n=== SENT ===\n" + json.dumps(sent, ensure_ascii=False, indent=1, sort_keys=True)
           + "\n=== AUDIT ===\n" + _norm(audit))
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
