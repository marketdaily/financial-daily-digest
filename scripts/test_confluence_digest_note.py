#!/usr/bin/env python3
"""analyzer.py `_pp_confluence_note` 迴歸測試(2026-08-06)。

confluence.rank() 的跨源信念榜之前只接了推播那一段下游(scripts/test_confluence_notify.py),
main.py/analyzer.py 對 intel/ 完全零 import——automation_scorecard.md「confluence 匯流評分」
B⚠️ 格記錄的第二個缺口(digest 下游)。本檔測 `_pp_confluence_note` 這個新的確定性
postprocess 函式:讀 confluence 匯流榜,對命中的卡片附一行中性資訊 div。

凍結語意:
- 命中 confluence_bull/confluence_bear 的卡片附一行 note,含來源標籤與方向詞。
- 未命中(code 不在榜上、或 kind 是 single/none/divergence/confluence_risk)的卡片原樣不動。
- confluence 模組 import 失敗 / load_by_code 拋例外 / by_code 為空 → 整個函式 no-op 回傳原 html
  (fail-safe,絕不讓情報層故障擋住日報生成)。
- note 措辭刻意不包含「買進/賣出/建議」等祈使詞,只描述「另有 N 源同向」+「僅供補充參考」——
  避免跟卡片本身已經算好的買賣判斷產生視覺矛盾(卡片可能是 sell 但 confluence 是 bull)。
- 多張卡片時,只有命中的那張被附註,其餘卡片內容逐字元不變。

用法: python3 scripts/test_confluence_digest_note.py   (exit 0=全過)
"""
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyzer
from intel import confluence

FAILS = []


def check(label, cond):
    print(("PASS" if cond else "FAIL") + f": {label}")
    if not cond:
        FAILS.append(label)


def _card(sym, cls="hold"):
    return (f'<div class="signal-card {cls}"><!--h:{sym}-->'
            f'<div class="signal-card-top"><span class="signal-ticker">{sym}</span></div>'
            f'<div class="signal-body"><div class="signal-reason">測試理由文字</div></div></div>')


def _brief_with(by_code):
    return {"by_code": by_code}


def _write_brief(tmp_path, by_code):
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(_brief_with(by_code), f, ensure_ascii=False)


def test_hit_bull():
    by_code = {
        "1234": [
            {"source": "institutional", "level": "red", "signal": "測試(1234):買超"},
            {"source": "holders", "level": "yellow", "signal": "測試(1234):加碼"},
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, by_code)
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = _card("1234") + '<div class="signal-disclaimer">disc</div>'
            out = analyzer._pp_confluence_note(html, {})
            check("bull hit: note injected", "情報雷達" in out)
            check("bull hit: direction word 看多", "看多" in out)
            check("bull hit: neutral disclaimer present", "僅供補充參考" in out)
            check("bull hit: original reason text untouched", "測試理由文字" in out)
    finally:
        os.unlink(tf.name)


def test_hit_bear():
    by_code = {
        "5678": [
            {"source": "institutional", "level": "red", "signal": "測試(5678):賣超"},
            {"source": "sbl", "level": "yellow", "signal": "測試(5678):放空"},
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, by_code)
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = _card("5678", cls="sell") + '<div class="signal-disclaimer">disc</div>'
            out = analyzer._pp_confluence_note(html, {})
            check("bear hit: note injected", "情報雷達" in out)
            check("bear hit: direction word 看空", "看空" in out)
    finally:
        os.unlink(tf.name)


def test_no_hit_untouched():
    by_code = {"9999": [{"source": "institutional", "level": "red", "signal": "另一檔(9999):買超"}]}
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, by_code)
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = _card("1111") + '<div class="signal-disclaimer">disc</div>'
            out = analyzer._pp_confluence_note(html, {})
            check("no-hit code: html byte-identical", out == html)
    finally:
        os.unlink(tf.name)


def test_single_source_not_ranked():
    # 只有 1 個乾淨方向源 → kind=single,不上榜(min_conviction=2 門檻),不該被附註。
    by_code = {"2222": [{"source": "institutional", "level": "red", "signal": "測試(2222):買超"}]}
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, by_code)
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = _card("2222") + '<div class="signal-disclaimer">disc</div>'
            out = analyzer._pp_confluence_note(html, {})
            check("single-source (below conviction floor): untouched", out == html)
    finally:
        os.unlink(tf.name)


def test_multi_card_only_hit_one():
    by_code = {
        "3333": [
            {"source": "institutional", "level": "red", "signal": "測試(3333):買超"},
            {"source": "holders", "level": "yellow", "signal": "測試(3333):加碼"},
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, by_code)
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = (_card("4444") + _card("3333") + _card("5555")
                    + '<div class="signal-disclaimer">disc</div>')
            out = analyzer._pp_confluence_note(html, {})
            check("multi-card: exactly one note injected", out.count("情報雷達") == 1)
            check("multi-card: hit card is the right one",
                  '<!--h:3333-->' in out.split("情報雷達")[1][:200] or
                  ("情報雷達" in out.split("<!--h:3333-->")[1][:300]))
    finally:
        os.unlink(tf.name)


def test_missing_brief_file_noop():
    with mock.patch.object(confluence, "LATEST", "/tmp/__does_not_exist_confluence_brief__.json"):
        html = _card("1234") + '<div class="signal-disclaimer">disc</div>'
        out = analyzer._pp_confluence_note(html, {})
        check("missing brief file: fail-safe no-op", out == html)


def test_import_failure_noop():
    html = _card("1234") + '<div class="signal-disclaimer">disc</div>'
    with mock.patch.dict(sys.modules, {"intel.confluence": None}):
        out = analyzer._pp_confluence_note(html, {})
        check("intel.confluence import failure: fail-safe no-op", out == html)


def test_malicious_signal_text_escaped():
    # 驗證者分離 2026-08-06 F1 [HIGH]:_short_tag() 對沒被 _TAG_PATTERNS 涵蓋的措辭會
    # fallback 成外部來源(mops_news 等)原文前 12 字,未 escape 時一個未閉合的 `<a href=...>`
    # 會吃掉緊跟其後的 `</div>`,把卡片其餘內容(含 reason)劫持進一個惡意連結,同時流進
    # 訂閱信與公開存檔頁。
    by_code = {
        "2330": [
            {"source": "mops_news", "level": "yellow",
             "signal": "測試(2330):<a href=//evil.example/phish>增持</a>公告"},
            {"source": "mops_news", "level": "yellow", "signal": "測試(2330):庫藏股公告"},
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, by_code)
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = _card("2330") + '<div class="signal-disclaimer">disc</div>'
            out = analyzer._pp_confluence_note(html, {})
            check("malicious signal text: raw <a href unclosed> not present verbatim",
                  "<a href=//evil.example" not in out)
            check("malicious signal text: escaped form present instead",
                  "&lt;a href=" in out or "evil.example" not in out)
            check("malicious signal text: signal-body div structure intact (2 closes before signal-reason)",
                  out.count("</div>") >= html.count("</div>"))
    finally:
        os.unlink(tf.name)


def test_last_card_no_trailing_markup_still_gets_note():
    # 驗證者分離 2026-08-06 F2 [MEDIUM]:lookahead 若沒有 `|$` fallback,命中的卡片若剛好是
    # 整段 HTML 最後一個節點(後面沒有下一張卡/disclaimer/section-label),regex 零匹配,
    # 真命中會被靜默漏掉。
    by_code = {
        "6666": [
            {"source": "institutional", "level": "red", "signal": "測試(6666):買超"},
            {"source": "holders", "level": "yellow", "signal": "測試(6666):加碼"},
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, by_code)
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = _card("6666")  # 刻意不附 disclaimer/後續卡片
            out = analyzer._pp_confluence_note(html, {})
            check("last card with no trailing markup: note still injected", "情報雷達" in out)
    finally:
        os.unlink(tf.name)


def test_empty_by_code_noop():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        _write_brief(tf.name, {})
    try:
        with mock.patch.object(confluence, "LATEST", tf.name):
            html = _card("1234") + '<div class="signal-disclaimer">disc</div>'
            out = analyzer._pp_confluence_note(html, {})
            check("empty by_code: no-op", out == html)
    finally:
        os.unlink(tf.name)


if __name__ == "__main__":
    test_hit_bull()
    test_hit_bear()
    test_no_hit_untouched()
    test_single_source_not_ranked()
    test_multi_card_only_hit_one()
    test_malicious_signal_text_escaped()
    test_last_card_no_trailing_markup_still_gets_note()
    test_missing_brief_file_noop()
    test_import_failure_noop()
    test_empty_by_code_noop()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED'}")
    sys.exit(1 if FAILS else 0)
