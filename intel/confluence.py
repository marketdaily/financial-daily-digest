#!/usr/bin/env python3
"""跨源信念評分器（confluence / divergence）——信息差引擎輸出側的「拼圖」層。

信息差引擎的 26 個連接器各自產出訊號，brief 扁平地按連接器類型分組列出。
但 Delvin 核心哲學（信息差 #11）最強的訊號是【多個獨立信息源指向同一標的】：
  - 匯流（confluence）：≥2 個獨立源同向 → 高信念（對手沒把這些拼起來看）
  - 背離（divergence）：同一檔並存看多/看空源 → 資訊性分歧，最值得深究
    （curriculum tw_margin 節早點名：「法人賣+散戶買=法人趁散戶熱度出貨的背離警訊」）

本模組【唯讀】brief 的 by_code（絕不寫 signal_ledger），把逐訊號用確定性關鍵字
分類成 bull/bear/risk/neutral，逐檔聚合成信念榜。無 LLM——方向判定全是可審計關鍵字。

設計要點：
- per-source 關鍵字隔離：holders 的「加碼」不會污染 sbl 的「加碼放空」（各源查各自表）。
- bull_hit and not bear_hit 邏輯：同一訊號若同時命中多空關鍵字 → 歸 neutral（安全，不假匯流）。
- sbl 先判「回補」(bull) 再判「放空」(bear)，刻意不碰「空頭」二字（「回補潮空頭力道減弱」是看多）。
- 新連接器上線：在 BULL_KW/BEAR_KW 補一行；未列的 source 預設 neutral（不會誤判匯流）。
"""
import json
import os
import re
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
LATEST = os.path.join(HERE, "briefs", "latest.json")

# 各 source 的「看多 / 看空」關鍵字表（per-source 隔離，first-any 命中）。
# 對齊 query.py SOURCE_MEANING 的白話定義；只列連接器實際會 emit 的措辭。
BULL_KW = {
    "institutional": ["買超"],
    "holders": ["週增", "加碼"],
    "revenue": ["強勁"],
    "sbl": ["回補"],
    "us_analyst": ["升評", "上調", "調升", "調高目標"],
    "tw_analyst": ["調升", "上修"],
    "us_insider": ["群聚買", "買進"],
    "mops_news": ["庫藏", "併購", "買回", "增持"],
    "tw_financials": ["轉盈", "年增", "改善"],
}
BEAR_KW = {
    "institutional": ["賣超"],
    "holders": ["週減", "出脫", "減碼", "鬆動"],
    "revenue": ["衰退"],
    "sbl": ["放空"],
    "margin": ["斷頭", "停損", "過熱", "追高", "續跌"],
    "us_analyst": ["降評", "下修", "調降", "調低目標"],
    "tw_analyst": ["調降", "下修"],
    "us_insider": ["賣出", "出脫"],
    "mops_news": ["裁罰", "訴訟", "違約", "跳票", "下市", "解任"],
    "tw_financials": ["轉虧", "年減", "驟降", "虧損", "轉弱"],
}
# 純風險/避開類（非方向訊號）——不計入多空匯流，但 ≥2 個同時示警會另立「多重風險」榜。
RISK_SOURCES = {"twse_punish", "twse_notice", "twse_notetrans",
                "fsc_penalty", "us_8k", "us_sec_admin"}
# 明確「不下多空判斷」的 source（事件窗口 / 頭條脈絡太雜訊）→ 強制 neutral，不計入。
# 注意：mops_news 刻意【不】在此——它是內容型方向源（庫藏/併購=多、裁罰/訴訟=空，見 BULL/BEAR_KW）。
NEUTRAL_SOURCES = {"investor_conf", "us_13f", "news_us", "news_tw"}

# 【陣營 camp】HIGH-2：conviction=獨立資料源數，但多個源可能是【同一群經濟主體】的不同投影
# （法人買賣/大戶/借券放空多半都是機構 smart-money 在動），4「源」可能只是 ~2 個獨立主體。
# 誠實的證據強度＝獨立【陣營】數，非源數。下注前看陣營數，不要被源數灌高的信念騙。
SOURCE_CAMP = {
    "institutional": "機構籌碼", "holders": "機構籌碼", "sbl": "機構籌碼", "us_13f": "機構籌碼",
    "us_insider": "內部人",
    "margin": "散戶槓桿",
    "revenue": "基本面", "tw_financials": "基本面",
    "us_analyst": "分析師", "tw_analyst": "分析師", "mops_news": "公司行動",
    "twse_punish": "監理風險", "twse_notice": "監理風險", "twse_notetrans": "監理風險",
    "fsc_penalty": "監理風險", "us_8k": "監理風險", "us_sec_admin": "監理風險",
}

# 顯示用：把常見措辭壓成短標籤（render 時讓 Delvin 一眼看懂各源在說什麼）。
_TAG_PATTERNS = [
    (r"外資連\s*\d+\s*日買超", "外資連買"),
    (r"外資連\s*\d+\s*日賣超", "外資連賣"),
    (r"投信連\s*\d+\s*日買超", "投信認養"),
    (r"投信連\s*\d+\s*日賣超", "投信連賣"),
    (r"法人.*淨買超", "法人淨買"),
    (r"法人.*淨賣超", "法人淨賣"),
    (r"大戶.*加碼", "大戶加碼"),
    (r"大戶.*(出脫|鬆動|週減)", "大戶減碼"),
    (r"融資.*(斷頭|停損)", "融資斷頭"),
    (r"融資.*(追高|過熱)", "融資過熱"),
    (r"借券.*回補", "借券回補"),
    (r"借券.*放空", "借券放空"),
    (r"營收.*強勁", "營收強勁"),
    (r"營收.*衰退", "營收衰退"),
    (r"處置", "處置中"),
    (r"注意", "注意股"),
]


def classify_polarity(source, signal_text):
    """回傳 'bull' | 'bear' | 'risk' | 'neutral'。純關鍵字，無副作用。"""
    if source in RISK_SOURCES:
        return "risk"
    if source in NEUTRAL_SOURCES:
        return "neutral"
    bull = any(k in signal_text for k in BULL_KW.get(source, []))
    bear = any(k in signal_text for k in BEAR_KW.get(source, []))
    if bull and not bear:
        return "bull"
    if bear and not bull:
        return "bear"
    return "neutral"


def _short_tag(signal_text):
    body = signal_text.split(":", 1)[-1]
    for pat, tag in _TAG_PATTERNS:
        if re.search(pat, body):
            return tag
    # fallback：取冒號後首個括號前的短描述
    return re.sub(r"\(.*", "", body).strip()[:12] or body[:12]


def _name_of(sigs):
    # MED-3：各源給的名不一致（revenue 給乾淨「宏致」，籌碼源給帶集保級別碼「宏致四」）。
    # 取所有候選中最短者＝最乾淨（tie 取首見）；剝除純級別尾碼避免顯示雜訊。
    cands = []
    for s in sigs:
        m = re.match(r"^(.+?)\((\d+|[A-Z.]+)\)", s["signal"])
        if m:
            cands.append(m.group(1))
    if not cands:
        return ""
    return min(cands, key=lambda n: (len(n), cands.index(n)))


def _camps(srcs):
    """這組 source 橫跨幾個獨立經濟陣營（HIGH-2 誠實證據強度）。"""
    return sorted({SOURCE_CAMP.get(s, s) for s in srcs})


def score_code(code, sigs):
    """把單一 code 的多源訊號聚合成信念判定。

    回傳 dict：kind ∈ {confluence_bull, confluence_bear, divergence, confluence_risk, single, none}
    conviction=計入方向的乾淨獨立來源數；camps=橫跨的獨立陣營數（誠實證據強度，看這個下注）；
    red_directional=其中 red 級的乾淨源數（排序 tiebreak）。
    mixed_srcs=同一源內部多空自相矛盾者（如外資賣+投信買同掛 institutional）——只當 overlay 註記，
    【不】強制整檔判背離、也【不】灌 conviction（修 MED-1/MED-2）。
    """
    # 每個 source 匯總其所有訊號的極性與最高 level
    src_pol = collections.defaultdict(set)      # source -> {polarities}
    src_level = {}                               # source -> 'red'|'yellow'
    src_tags = collections.defaultdict(list)     # source -> [short tag,...]
    for s in sigs:
        src = s["source"]
        src_pol[src].add(classify_polarity(src, s["signal"]))
        lv = s.get("level", "yellow")
        if src_level.get(src) != "red":
            src_level[src] = lv
        tag = _short_tag(s["signal"])
        if tag not in src_tags[src]:
            src_tags[src].append(tag)

    bull_srcs, bear_srcs, mixed_srcs, risk_srcs = [], [], [], []
    for src, pols in src_pol.items():
        directional = pols & {"bull", "bear"}
        if directional == {"bull"}:
            bull_srcs.append(src)
        elif directional == {"bear"}:
            bear_srcs.append(src)
        elif directional == {"bull", "bear"}:
            mixed_srcs.append(src)     # 同源內部矛盾：只當註記
        elif "risk" in pols:
            risk_srcs.append(src)
        # 純 neutral 的 source 不計入任何桶

    nb, nbe, nm, nr = len(bull_srcs), len(bear_srcs), len(mixed_srcs), len(risk_srcs)
    if nb and nbe:
        # 真背離：不同【乾淨】源指相反方向（mixed 不觸發、不計 conviction）
        kind = "divergence"
        conviction = nb + nbe
    elif nb >= 2:
        kind = "confluence_bull"        # 乾淨匯流；有 mixed 源時仍成立，mixed 當內部分歧註記
        conviction = nb
    elif nbe >= 2:
        kind = "confluence_bear"
        conviction = nbe
    elif nm and (nb or nbe or nm >= 2):
        # 沒有乾淨的跨源匯流，但有自相矛盾源（±搭配另一乾淨源或多個 mixed）→ 低調背離
        kind = "divergence"
        conviction = nb + nbe + nm
    elif nb or nbe:
        kind = "single"
        conviction = 1
    elif nr >= 2:
        kind = "confluence_risk"        # MED-4：≥2 獨立監理/風險源同時示警
        conviction = nr
    else:
        kind = "none"
        conviction = 0

    directional_all = bull_srcs + bear_srcs
    red_directional = sum(1 for s in directional_all if src_level.get(s) == "red")
    camps = _camps(bull_srcs + bear_srcs + mixed_srcs) if kind != "confluence_risk" else _camps(risk_srcs)

    return {
        "code": code,
        "name": _name_of(sigs),
        "kind": kind,
        "conviction": conviction,
        "camps": camps,
        "n_camps": len(camps),
        "red_directional": red_directional,
        "bull_srcs": sorted(bull_srcs),
        "bear_srcs": sorted(bear_srcs),
        "mixed_srcs": sorted(mixed_srcs),
        "risk_srcs": sorted(risk_srcs),
        "src_tags": {k: v for k, v in src_tags.items()},
        "src_level": src_level,
    }


# 上榜的類別（single/none 不上）
RANKED_KINDS = ("confluence_bull", "confluence_bear", "divergence", "confluence_risk")


def rank(by_code, min_conviction=2):
    """回傳排序後的信念榜（只留匯流/背離/多重風險，conviction≥門檻）。

    排序：獨立【陣營】數優先（誠實證據強度），再源數，再紅燈數——避免被同陣營灌高的源數騙。
    """
    scored = [score_code(c, sigs) for c, sigs in by_code.items()]
    keep = [s for s in scored
            if s["kind"] in RANKED_KINDS and s["conviction"] >= min_conviction]
    keep.sort(key=lambda s: (s["n_camps"], s["conviction"], s["red_directional"]),
              reverse=True)
    return keep


def _fmt_srcs(s, srcs):
    parts = []
    for src in srcs:
        tags = "／".join(s["src_tags"].get(src, [src]))
        mark = "" if s["src_level"].get(src) == "red" else "°"
        parts.append(tags + mark)
    return "｜".join(parts)


def _head(s):
    """×N源/M陣營 標頭——陣營數是誠實證據強度。"""
    camp = "／".join(s["camps"])
    return f"**{s['name']}({s['code']})** ×{s['conviction']}源·{s['n_camps']}陣營（{camp}）"


def _mixed_note(s):
    if not s["mixed_srcs"]:
        return ""
    return "｜⟳" + _fmt_srcs(s, s["mixed_srcs"]) + "(源內部分歧)"


def render_markdown(ranked, top=None):
    if top:
        ranked = ranked[:top]
    bull = [s for s in ranked if s["kind"] == "confluence_bull"]
    bear = [s for s in ranked if s["kind"] == "confluence_bear"]
    div = [s for s in ranked if s["kind"] == "divergence"]
    risk = [s for s in ranked if s["kind"] == "confluence_risk"]
    out = ["## 🎯 跨源信念榜（多個獨立信息源指向同一標的＝最高信息差）",
           "> °=黃燈(較弱)；無標=紅燈。**陣營數＝誠實證據強度**（同陣營的源非統計獨立，看陣營數下注勿被源數騙）。"]
    if bull:
        out.append("\n### 🟢 匯流做多（多源同向看多）")
        for s in bull:
            out.append(f"- {_head(s)}：{_fmt_srcs(s, s['bull_srcs'])}{_mixed_note(s)}")
    if bear:
        out.append("\n### 🔴 匯流做空／避開（多源同向看空）")
        for s in bear:
            out.append(f"- {_head(s)}：{_fmt_srcs(s, s['bear_srcs'])}{_mixed_note(s)}")
    if div:
        out.append("\n### ⚡ 背離（獨立源彼此矛盾＝資訊性分歧，最值得深究）")
        for s in div:
            bulls = _fmt_srcs(s, s["bull_srcs"]) or "—"
            bears = _fmt_srcs(s, s["bear_srcs"]) or "—"
            rk = ("｜⚠️" + _fmt_srcs(s, s["risk_srcs"])) if s["risk_srcs"] else ""
            out.append(f"- {_head(s)} 多【{bulls}】vs 空【{bears}】{_mixed_note(s)}{rk}")
    if risk:
        out.append("\n### 🚫 多重風險警示（≥2 獨立監理/風險源同時示警＝避開）")
        for s in risk:
            out.append(f"- {_head(s)}：{_fmt_srcs(s, s['risk_srcs'])}")
    if not (bull or bear or div or risk):
        out.append("\n（今日無 conviction≥門檻的跨源匯流/背離/多重風險）")
    return "\n".join(out)


def load_by_code(path=None):
    with open(path or LATEST, encoding="utf-8") as f:
        return json.load(f).get("by_code", {})


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="跨源信念評分器（confluence/divergence）")
    ap.add_argument("--brief", help="brief json 路徑（預設 briefs/latest.json）")
    ap.add_argument("--min-conviction", type=int, default=2, help="最低獨立來源數門檻")
    ap.add_argument("--top", type=int, help="只印前 N 檔")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    args = ap.parse_args()
    by_code = load_by_code(args.brief)
    ranked = rank(by_code, min_conviction=args.min_conviction)
    if args.json:
        print(json.dumps(ranked[:args.top] if args.top else ranked,
                         ensure_ascii=False, indent=2))
    else:
        print(render_markdown(ranked, top=args.top))


if __name__ == "__main__":
    _cli()
