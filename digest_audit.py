"""
日報品質自動稽核 — 使用者視角 checklist。

呼叫方式:
    from digest_audit import audit_digest
    failures = audit_digest(html, today_iso, us_holdings, tw_holdings, mkt_status)
    # failures = [{"check": "tldr_has_tw", "msg": "..."}], 空 list = 全 pass

設計理念:每個 check 都對應一次「用戶曾經 / 將會生氣」的場景。
新加 check 比修 bug 更便宜 — 抓到越多越好,寧可 false positive 也不漏。
"""
import re
from typing import List, Dict


def _strip_html_to_text(html: str) -> str:
    """粗略去 tag,留下純文字供 keyword 比對。"""
    txt = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    txt = re.sub(r"<style[\s\S]*?</style>", "", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _section(html: str, class_name: str) -> str:
    """抓出特定 class 的 div 內容,**支援巢狀 div**(配對開合,不被內層 </div> 提早切斷)。"""
    m = re.search(rf'<div class="{class_name}"[^>]*>', html, re.I)
    if not m:
        return ""
    start = m.start()
    i = m.end()
    depth = 1
    while i < len(html) and depth > 0:
        open_m = re.search(r'<div\b', html[i:], re.I)
        close_m = re.search(r'</div\s*>', html[i:], re.I)
        if not close_m:
            return html[start:]
        if open_m and open_m.start() < close_m.start():
            depth += 1
            i += open_m.end()
        else:
            depth -= 1
            i += close_m.end()
    return html[start:i]


def _all_sections(html: str, class_name: str) -> List[str]:
    """抓所有同 class 的 div 區塊(支援巢狀)。"""
    sections = []
    cursor = 0
    pattern = re.compile(rf'<div class="{class_name}"[^>]*>', re.I)
    while True:
        m = pattern.search(html, cursor)
        if not m:
            break
        sec = _section(html[m.start():], class_name)
        if sec:
            sections.append(sec)
            cursor = m.start() + len(sec)
        else:
            cursor = m.end()
    return sections


def audit_digest(
    html: str,
    today_iso: str,
    us_holdings: List[str] = None,
    tw_holdings: List[str] = None,
    mkt_status: Dict = None,
    market: str = "both",
    earnings_estimates: bool = False,
) -> List[Dict]:
    """
    回傳 failures list,空 list 代表通過。
    每筆 failure: {"check": <name>, "severity": "high|med|low", "msg": <人話>}

    market: "both"=台美合併(預設) / "tw"=早 7:00 台股盤前版 / "us"=晚 20:00 美股盤前版。
            us 版台股已收盤,可寫「今日台股漲/跌」完成式 → 停用台股盤前時序檢查;
            tw 版美股不是主軸 → 停用「今晚美股開盤動作」檢查。
    """
    us_holdings = us_holdings or []
    tw_holdings = tw_holdings or []
    mkt_status = mkt_status or {}
    fails = []
    text = _strip_html_to_text(html)

    # ───── 時序紀律 ─────
    # 1. 早上 7 點不可寫「今天台股已 X」(台股 9:00 才開盤)
    # us 晚報例外:台股 13:30 已收盤,「今日台股漲/跌」是合法完成式,不檢查。
    if market != "us":
        if re.search(r"今天台股(已|正|超|大)?(漲|跌|狂|挫|爆|沖|噴)", text):
            fails.append({"check": "tw_pre_market_tense", "severity": "high",
                          "msg": "TW 早上 7 點台股還沒開盤,卻寫「今天台股漲/跌」"})
        if re.search(r"今早台股(已|正)(漲|跌)", text):
            fails.append({"check": "tw_pre_market_tense_zaoshen", "severity": "high",
                          "msg": "「今早台股已漲/跌」— 9:00 前盤前不可能知道"})

    # 2. 美股休市日不可寫「今天美股漲/跌」「昨晚美股收紅/黑」
    if mkt_status.get("us_traded_last_session") is False:
        if re.search(r"(今天|昨晚)美股(漲|跌|收紅|收黑|大漲|大跌)", text):
            fails.append({"check": "us_holiday_tense", "severity": "high",
                          "msg": f"昨晚美股休市({mkt_status.get('us_last_trading_date')}),卻寫「昨晚美股漲/跌」"})

    # 3. 台股休市日不可寫「今早 9:00 開盤」(us 晚報台股已收盤、非主軸,不檢查)
    if market != "us" and mkt_status.get("tw_will_open_today") is False:
        if re.search(r"今早.{0,4}開盤|今日早盤|9:?00.{0,4}開盤", text):
            fails.append({"check": "tw_holiday_open_tense", "severity": "high",
                          "msg": "今天台股休市,卻寫「今早 9:00 開盤」"})

    # 4. 美股休市日不可寫「今晚開盤」
    if mkt_status.get("us_will_open_tonight") is False:
        if re.search(r"今晚.{0,4}開盤|今晚美股.{0,4}開", text):
            fails.append({"check": "us_holiday_tonight_tense", "severity": "high",
                          "msg": "今晚美股休市,卻寫「今晚開盤」"})

    # ───── TLDR 個人化 ─────
    tldr = _section(html, "tldr")
    if tldr:
        tldr_text = _strip_html_to_text(tldr)
        # 5. 用戶持有台股 → TLDR 至少要有一條提到台股關鍵字或台股代號(us 晚報台股非主軸,不檢查)
        if tw_holdings and market != "us":
            tw_keywords = tw_holdings + ["台股", "台積電", "聯發科", "鴻海", "加權"]
            if not any(k in tldr_text for k in tw_keywords):
                fails.append({"check": "tldr_missing_tw", "severity": "high",
                              "msg": f"用戶持有台股 {tw_holdings} 但 TLDR 30 秒重點完全沒提到台股"})
        # 5b. us 晚報:用戶持有美股 → TLDR 至少一條提到美股(盤前布局是主軸)
        if us_holdings and market == "us":
            us_keywords = us_holdings + ["美股", "標普", "S&P", "那斯達克", "道瓊", "費半", "盤前"]
            if not any(k in tldr_text for k in us_keywords):
                fails.append({"check": "tldr_missing_us", "severity": "high",
                              "msg": f"美股晚報但 TLDR 30 秒重點完全沒提到美股(用戶持有 {us_holdings})"})
        # 6. TLDR 至少 3 條 bullet
        bullets = re.findall(r"<li[^>]*>", tldr)
        if len(bullets) < 3:
            fails.append({"check": "tldr_too_short", "severity": "med",
                          "msg": f"TLDR 只有 {len(bullets)} 條,至少要 3 條"})

    # ───── 操作建議具體性 ─────
    # 7. 禁止孤立的「先觀望」「先別動」「保守為上」(必須附條件)
    isolated_wait = re.findall(r"(先觀望|先別動|保守為上|靜觀其變|按兵不動)(?:[^,。\n]{0,12})", text)
    bad_isolated = []
    for m in isolated_wait:
        # 看後面 30 字內有沒有具體條件(價位/事件/日期)
        idx = text.find(m)
        ctx = text[idx:idx + 60]
        has_cond = re.search(r"\$\d|NT\$?\d|\d+\s*(元|美元|塊|點)|(等|直到).{0,12}(再|才|後)|財報|FOMC|\d+月\d+", ctx)
        if not has_cond:
            bad_isolated.append(m)
    if bad_isolated:
        fails.append({"check": "isolated_wait_phrase", "severity": "med",
                      "msg": f"出現孤立的觀望/別動字眼,沒附條件:{bad_isolated[:3]}"})

    # 8. signal-card 必須每張都有「battle-row」三件套(進場/目標/停損)
    # 例外:deterministic fallback 卡片(reason 內有「備援/異常/修復」字眼)豁免,因為刻意不給價位以免誤導
    signal_cards = _all_sections(html, r"signal-card[^\"]*")
    cards_missing_battle = 0
    real_cards = 0
    for card in signal_cards:
        is_fallback = bool(re.search(r"備援|個人化生成異常|fallback|主編將.{0,8}修復|無即時報價|待.{0,8}數據更新|見網頁", card))
        if is_fallback:
            continue
        real_cards += 1
        if "battle-row" not in card or card.count("battle-row") < 3:
            cards_missing_battle += 1
    if cards_missing_battle > 0:
        fails.append({"check": "signal_card_missing_battle", "severity": "high",
                      "msg": f"{cards_missing_battle}/{real_cards} 張 signal-card 缺少進場/目標/停損價位"})

    # 9. 持股覆蓋率:用戶每支持股**都**要在 signal-card 出現,漏一支都 high
    # 2026-05-26 用戶:「使用者選擇每一個台股美股都要顯示下一步」
    all_holdings = us_holdings + tw_holdings
    if all_holdings and signal_cards:
        signal_text = " ".join(signal_cards)
        missing = [s for s in all_holdings if s not in signal_text]
        if missing:
            fails.append({"check": "holdings_uncovered", "severity": "high",
                          "msg": f"用戶選的 {len(missing)}/{len(all_holdings)} 支持股沒給 signal-card 下一步:{missing[:10]}"})

    # 9b. 每張 signal-reason 必須有「下一步」具體性:至少一個 $/NT$/數字+元 或時間窗
    if signal_cards:
        vague_cards = []
        for card in signal_cards:
            if re.search(r"備援|個人化生成異常|fallback|主編將.{0,8}修復|無即時報價|見網頁", card):
                continue
            reason_m = re.search(r'<div class="signal-reason"[^>]*>(.*?)</div>', card, re.S)
            if not reason_m:
                continue
            reason = reason_m.group(1)
            has_price = re.search(r"\$\s*\d|NT\$?\s*\d|\d+\s*(元|美元|塊|點)", reason)
            has_time_window = re.search(r"今早|今晚|盤後|盤前|財報前|財報後|開盤|收盤|本週|下週|\d+\s*月\s*\d+", reason)
            if not (has_price or has_time_window):
                ticker_m = re.search(r'<span class="signal-ticker"[^>]*>([^<]+)</span>', card)
                vague_cards.append(ticker_m.group(1).strip() if ticker_m else "?")
        if vague_cards:
            fails.append({"check": "signal_reason_vague", "severity": "high",
                          "msg": f"{len(vague_cards)} 張 signal-card 的「下一步」沒附價位或時間窗(虛詞卡):{vague_cards[:10]}"})

    # ───── 大盤覆蓋 ─────
    market_sec = _section(html, "market-summary")
    if market_sec:
        msec_text = _strip_html_to_text(market_sec)
        # 10. 「大盤怎麼了」若用戶有台股,必須提到台股大盤
        if tw_holdings and not re.search(r"台股|加權|台灣加權|TWII", msec_text):
            fails.append({"check": "market_summary_missing_tw", "severity": "med",
                          "msg": "「大盤怎麼了」沒提到台股大盤(用戶持有台股)"})

    # ───── 中英文股名 ─────
    # 11. 內文出現純代號(NVDA / 2330) 沒有中英文公司名
    code_only_us = re.findall(r"(?<![A-Za-z])(NVDA|AAPL|MSFT|TSLA|GOOGL|META|AMD|TSM|JPM|AMZN)(?![A-Za-z])", text)
    if code_only_us:
        # 抽樣檢查:每個代號前後 12 字是否有中文公司名
        for code in set(code_only_us[:5]):
            idx = text.find(code)
            ctx = text[max(0, idx - 12):idx + 12]
            has_zh = re.search(r"[一-鿿]{2,}", ctx)
            if not has_zh:
                fails.append({"check": "ticker_no_zh_name", "severity": "low",
                              "msg": f"代號 {code} 附近沒有中文公司名"})
                break  # 抽樣一個就夠

    # ───── 編造/假數據 ─────
    # 12. URL 必須是 http(s):// 開頭,不可是 example.com / xxx.com
    fake_urls = re.findall(r"https?://(?:www\.)?(example|xxx|test|placeholder|todo)\.[a-z]+", html, re.I)
    if fake_urls:
        fails.append({"check": "fake_urls", "severity": "high",
                      "msg": f"出現假網址:{fake_urls[:3]}"})

    # 13. 價位/數字 token 必須是真數字,不可是 XXX / YYY / $xxx
    #     (2026-06-25:新聞「為什麼重要」洩出「金額高達 XXX 億元」→ 擴大到任何 XXX 佔位符)
    placeholder_prices = re.findall(r"\$X+|NT\$X+|\$\?+|[XＸ]{2,}\s*(?:億元|億|兆|萬元|美元|元|點|%|％)|(?<![A-Za-z])[XＸ]{3,}(?![A-Za-z])", html)
    if placeholder_prices:
        fails.append({"check": "placeholder_prices", "severity": "high",
                      "msg": f"留下數字佔位符 XXX 沒填:{placeholder_prices[:3]}"})

    # ───── 實質稽核(2026-06-10 起:不只查格式,還查內容自洽與編造)─────
    # 13b. 財報區編造預期:資料端沒有「已核實預期數字」時,財報區出現預期 EPS/營收 = LLM 編的
    # (6/10 實鍋:日報寫 AAPL 預期 EPS 3.60,真實 FMP 預期 1.86;還寫「iPhone 15 仍是重點」)
    if not earnings_estimates:
        earn_sec = _section(html, "earnings-list")
        if earn_sec and re.search(r"預期\s*EPS|市場預期|EPS\s*[\d.]+\s*美元|營收\s*[\d.,]+\s*億",
                                  _strip_html_to_text(earn_sec)):
            fails.append({"check": "earnings_fabricated_estimates", "severity": "high",
                          "msg": "財報區出現「預期 EPS/營收」但資料端沒有核實的預期數字 — LLM 編造"})

    # 17. verdict 同質性:≥4 張真卡全部同向,且全文同時喊「先觀望/等數據」= 自相矛盾
    # (6/10 實鍋:結論「普通人應該先觀望等 CPI」,四張卡全部「應即刻分批買進」)
    biases = []
    for card in signal_cards:
        if re.search(r"備援|個人化生成異常|fallback|無即時報價|見網頁", card):
            continue
        if "signal-bias bullish" in card:
            biases.append("bull")
        elif "signal-bias bearish" in card:
            biases.append("bear")
        elif "signal-bias neutral" in card:
            biases.append("neut")
    if len(biases) >= 4 and len(set(biases)) == 1:
        wait_tone = re.search(r"先觀望|等數據|等.{0,10}公布(再|後)|先別急", text)
        fails.append({"check": "verdict_monoculture",
                      "severity": "med" if wait_tone else "low",
                      "msg": f"{len(biases)} 張操作卡全部同向({biases[0]})"
                             + (",但 TLDR/結論同時喊「先觀望/等數據」— 卡片與結論自相矛盾" if wait_tone else
                                " — 機械式同質模板,缺乏逐支差異")})

    # 18. 信心過度自信:>75% 的信心顯示(postprocess 用歷史校準表覆寫,上限 75;
    # 出現更高 = 校準防線破口)
    over_conf = re.findall(r"信心\s*(7[6-9]|[8-9]\d|100)\s*%", text)
    if over_conf:
        fails.append({"check": "confidence_overclaim", "severity": "med",
                      "msg": f"出現超出校準上限的信心數字:{over_conf[:3]}%(校準覆寫上限 75,>75 = 防線破口)"})

    # 19. 臆測因果:「可能與 XXX 有關」這種無來源歸因
    spec = re.findall(r"可能與[^。<]{2,30}有關", text)
    if spec:
        fails.append({"check": "speculative_causality", "severity": "low",
                      "msg": f"無來源的因果臆測:{spec[:2]}"})

    # 20. 新聞標題與內文方向矛盾(6/10 實鍋:標題「油價反彈 1.10%」內文「油價反而下跌」)
    contradictions = []
    for nc in _all_sections(html, "news-card"):
        hm = re.search(r'<div class="news-headline"[^>]*>(.*?)</div>', nc, re.S)
        wm = re.search(r'<div class="news-why"[^>]*>(.*?)</div>', nc, re.S)
        if not (hm and wm):
            continue
        head = _strip_html_to_text(hm.group(1))
        why = _strip_html_to_text(wm.group(1))
        if re.search(r"反彈|上漲|大漲|漲\s*[\d.]", head) and re.search(r"反而(下跌|走跌|收黑)", why):
            contradictions.append(head[:20])
        elif re.search(r"下跌|大跌|重挫|跌\s*[\d.]", head) and re.search(r"反而(上漲|走揚|收紅)", why):
            contradictions.append(head[:20])
    if contradictions:
        fails.append({"check": "news_headline_body_conflict", "severity": "med",
                      "msg": f"新聞標題與內文方向矛盾:{contradictions[:2]}"})

    # ───── AI 輸出被截斷 ─────
    # 16. HTML 結尾不該是 unclosed tag / 半行字 (代表 LLM token 超出上限被切)
    tail = html.rstrip()[-200:]
    truncation_signals = []
    if signal_cards:
        last_card = signal_cards[-1]
        if last_card.count("<div") > last_card.count("</div"):
            truncation_signals.append("最後一張 signal-card 沒收尾")
        if "signal-disclaimer" in html and not re.search(r"signal-disclaimer[^<]*</div>", html):
            truncation_signals.append("disclaimer 結尾不完整")
    # tail 沒有結束標籤 / 句點 / 半行字
    if re.search(r"[a-zA-Z一-鿿]$", tail) and not tail.endswith((">", "。", "！", "？", "」", ")", "．")):
        truncation_signals.append(f"HTML 結尾像被截斷:'...{tail[-40:]}'")
    if truncation_signals:
        fails.append({"check": "ai_output_truncated", "severity": "high",
                      "msg": "AI 輸出疑似被截斷(token 超上限):" + " | ".join(truncation_signals)})

    # ───── 美股動作窗口對稱 ─────
    # 14. 若今晚美股將開盤,signal-card 應該有「今晚」字眼至少一張(tw 早報美股非主軸,不檢查)
    if market != "tw" and mkt_status.get("us_will_open_tonight") and us_holdings and signal_cards:
        signal_text = " ".join(signal_cards)
        if "今晚" not in signal_text and "盤後" not in signal_text:
            fails.append({"check": "us_tonight_action_missing", "severity": "med",
                          "msg": "今晚美股開盤,但 signal-card 沒有任何「今晚開盤後」動作指示"})

    # 15. 若今早台股將開盤,signal-card 應該有「今早 / 開盤」字眼(us 晚報台股非主軸,不檢查)
    if market != "us" and mkt_status.get("tw_will_open_today") and tw_holdings and signal_cards:
        signal_text = " ".join(signal_cards)
        if not re.search(r"今早|早盤|9.{0,2}開盤", signal_text):
            fails.append({"check": "tw_morning_action_missing", "severity": "med",
                          "msg": "今早台股將開盤,但 signal-card 沒有「今早開盤後」動作指示"})

    # ───── 版型守門:未定義 CSS class(2026-06-29 事故防線) ─────
    # LLM 內容層偶爾會自創 class 名(如 news-card-title / market-summary-item),
    # 若 <style> 沒對應規則 → 該區塊整個沒上樣式 = 版型跑掉。
    # 此 check 直接比對「body 用到的 class」vs「<style> 定義的 class」,
    # 命中 high severity → 走既有 retry→deterministic fallback,絕不寄壞版。
    # 注意:只有當 html 仍含 <style> 區塊時才檢查(premailer inline 化後 class 仍在,
    #       但若樣式被完全 inline、<style> 被移除,跳過以免誤判)。
    style_m = re.search(r"<style[^>]*>(.*?)</style>", html, re.I | re.S)
    if style_m:
        style_block = style_m.group(1)
        defined_classes = set(re.findall(r"\.([A-Za-z_][\w-]*)", style_block))
        body_start = html.lower().find("<body")
        body_html = html[body_start:] if body_start != -1 else html
        used_classes = set()
        for attr in re.findall(r'class\s*=\s*"([^"]*)"', body_html):
            for c in attr.split():
                used_classes.add(c)
        undefined = sorted(used_classes - defined_classes)
        if undefined:
            preview = ", ".join("." + c for c in undefined[:8])
            more = f" 等 {len(undefined)} 個" if len(undefined) > 8 else ""
            fails.append({"check": "undefined_css_class", "severity": "high",
                          "msg": f"版型跑掉:body 用到未定義 class（{preview}{more}）— <style> 無對應規則,該區塊不會上樣式"})

    return fails


def format_failures(fails: List[Dict]) -> str:
    """把 failure list 格式化成人話,供 admin LINE / stdout 印用。"""
    if not fails:
        return "✅ 日報通過所有 audit checklist"
    by_sev = {"high": [], "med": [], "low": []}
    for f in fails:
        by_sev.get(f.get("severity", "med"), by_sev["med"]).append(f)
    lines = [f"🚨 日報 audit 失分 {len(fails)} 條:"]
    for sev in ["high", "med", "low"]:
        for f in by_sev[sev]:
            tag = {"high": "🔴 HIGH", "med": "🟡 MED ", "low": "🔵 LOW "}[sev]
            lines.append(f"  {tag} [{f['check']}] {f['msg']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # CLI 模式:python digest_audit.py <html_path> <today_iso>
    import sys
    if len(sys.argv) < 3:
        print("usage: python digest_audit.py <html_path> <today_iso> [us_holdings_csv] [tw_holdings_csv]")
        sys.exit(1)
    html = open(sys.argv[1], encoding="utf-8").read()
    today = sys.argv[2]
    us = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else []
    tw = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else []
    try:
        from analyzer import _market_status
        mkt = _market_status(today)
    except Exception:
        mkt = {}
    fails = audit_digest(html, today, us, tw, mkt)
    print(format_failures(fails))
    sys.exit(1 if any(f["severity"] == "high" for f in fails) else 0)
