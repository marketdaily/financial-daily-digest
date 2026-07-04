"""信息差引擎統一查詢介面(P2.6 整合層,curriculum I 節最後一塊)。
12 個 connector 各自寫進 intel/briefs/latest.json 的 by_code,但呼叫端(日報/推播/交易系統/
CB分析)若要用訊號,得自己知道 source 字串代表什麼、要不要信任、latest.json 新不新鮮——這層
把「查訊號」「訊號代表什麼行動」「資料新不新鮮」三件事收成一個函式呼叫,之後任何消費者
(trading_bot/cb_analyzer/成長實驗室)都從這裡取,不必各自重新解析 latest.json。

用法(同 repo):
    from intel import query
    query.signals_for("2330")
    query.summary()
用法(跨 repo,同 brainsearch/local_llm 慣例):
    python3 -m intel.query --code 2330
    python3 -m intel.query --summary --json
"""
import os
import sys
import json
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BRIEFS = os.path.join(HERE, "briefs")
LATEST = os.path.join(BRIEFS, "latest.json")

# 「何謂可行動訊號」——每個 source 字串對應的白話定義,新 connector 上線務必補一條,
# 否則 explain_source() 會回傳 unknown 並印警告(防止訊源默默失去可解讀性)。
SOURCE_MEANING = {
    "institutional": {"label": "三大法人買賣超", "action": "連續買超=認養訊號可跟;連續賣超=籌碼鬆動避開", "direction": "trend_follow"},
    "mops_news": {"label": "MOPS重大訊息", "action": "公司自揭事件,依內容個案判斷(庫藏股/併購=正向,裁罰/訴訟=負向)", "direction": "context"},
    "revenue": {"label": "月營收異常變化", "action": "營收年增/月增劇變,提示基本面轉折,需配合財報確認", "direction": "context"},
    "us_analyst": {"label": "美股分析師評等/目標價異動", "action": "升評/上調目標價=情緒轉多;降評/下修=情緒轉空", "direction": "sentiment"},
    "us_insider": {"label": "美股內部人交易(Form 4)", "action": "群聚買進=高層信心訊號可跟;大額賣出需排除10b5-1常規計畫雜訊", "direction": "conviction"},
    "margin": {"label": "台股融資融券", "action": "融資暴增=散戶追高過熱風險;搭配法人動向看背離(法人賣+散戶買=警訊)", "direction": "contrarian_risk"},
    "sbl": {"label": "台股借券賣出餘額", "action": "餘額遽減=機構回補(偏多);遽增=機構加碼放空(偏空)", "direction": "contrarian_risk"},
    "holders": {"label": "集保戶股權分散(千張大戶)", "action": "大戶持股比週增=籌碼集中偏多;週減=大戶出脫偏空", "direction": "trend_follow"},
    "twse_notice": {"label": "TWSE注意股", "action": "官方對異常交易發出警示,提高短線波動風險,不代表基本面變化", "direction": "risk_flag"},
    "twse_notetrans": {"label": "TWSE注意累計次數異常", "action": "多次被注意後的升級警示,流動性風險上升", "direction": "risk_flag"},
    "twse_punish": {"label": "TWSE處置股", "action": "交易方式已被限制(如人工管制/分盤),短線流動性大幅惡化,避開", "direction": "risk_flag"},
    "fsc_penalty": {"label": "金管會裁罰", "action": "金融機構遭裁罰,提示合規/聲譽風險,對股價影響通常有限但需留意連續案件", "direction": "risk_flag"},
    "us_sec_admin": {"label": "美股SEC行政程序", "action": "個股遭SEC行政程序調查/裁決,合規風險訊號,需看程序階段(調查中vs已裁決)", "direction": "risk_flag"},
    "news_us": {"label": "美股新聞事件", "action": "規則式關鍵字命中(訴訟/裁罰/政治/總經衝擊),提示需留意最新頭條", "direction": "context"},
    "news_tw": {"label": "台股新聞事件", "action": "同 news_us,中文關鍵字比對", "direction": "context"},
    "investor_conf": {"label": "法說會時程/簡報摘要", "action": "法說會逼近=財測/展望修正機率上升的事件窗口,有簡報摘要時參考highlights", "direction": "event_window"},
}

DIRECTION_LABEL_ZH = {
    "trend_follow": "順勢可跟",
    "contrarian_risk": "逆勢/風險訊號",
    "sentiment": "情緒指標",
    "conviction": "信心指標",
    "risk_flag": "風險警示(非方向訊號)",
    "context": "事件脈絡(需個案判斷)",
    "event_window": "時間窗口逼近度",
}


def load_brief(path=None):
    """回傳 latest.json 內容,缺檔/壞格式回 None(呼叫端自行決定要不要降級,不硬湊假資料)。"""
    p = path or LATEST
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def freshness(today=None, max_age_days=2):
    """latest.json 新不新鮮。cron 21:30 跑,日報/推播全天消費,容忍 1-2 天(週末/假日巡邏仍每天跑,
    正常情況 age 應為 0 或 1)。回傳 dict,exists=False 代表整個 intel 系統從未跑過或路徑跑掉。"""
    brief = load_brief()
    if brief is None or "date" not in brief:
        return {"exists": False, "is_fresh": False, "age_days": None, "date": None}
    try:
        d = datetime.date.fromisoformat(brief["date"])
    except Exception:
        return {"exists": True, "is_fresh": False, "age_days": None, "date": brief.get("date")}
    ref = today or datetime.date.today()
    age = (ref - d).days
    return {"exists": True, "is_fresh": 0 <= age <= max_age_days, "age_days": age, "date": brief["date"]}


def signals_for(code, level=None, brief=None):
    """回傳某檔(台股代碼或美股 ticker,不分大小寫)命中的訊號列表,無命中回 []。"""
    b = brief if brief is not None else load_brief()
    if not b:
        return []
    items = (b.get("by_code") or {}).get(str(code).upper(), [])
    if level:
        items = [it for it in items if it.get("level") == level]
    return items


def all_codes(level=None, brief=None):
    """回傳有訊號的所有代碼(可篩 level),用於「今天誰亮燈」這類全市場掃描。"""
    b = brief if brief is not None else load_brief()
    if not b:
        return []
    by_code = b.get("by_code") or {}
    if not level:
        return sorted(by_code)
    return sorted(c for c, items in by_code.items() if any(it.get("level") == level for it in items))


def explain_source(source):
    """回傳 source 的白話定義;未登記的 source(新 connector 忘了補表)印警告後回 unknown 佔位,
    不靜默吞掉——這是防止統一介面隨連接器增加而悄悄失去可解讀性的守門。"""
    meta = SOURCE_MEANING.get(source)
    if meta is None:
        print(f"[intel.query] 警告:source={source!r} 未登記在 SOURCE_MEANING,"
              f"新增 connector 時請補上「何謂可行動訊號」定義", file=sys.stderr)
        return {"label": source, "action": "(未登記,含義未知)", "direction": "unknown"}
    return meta


def summary(brief=None):
    """給推播/CLI 用的一段話摘要:今天幾則紅黃、有沒有全新紅燈、資料新不新鮮。"""
    b = brief if brief is not None else load_brief()
    fresh = freshness()
    if not b:
        return {"exists": False, "text": "intel 巡邏尚未產生任何簡報"}
    red_n, yellow_n = len(b.get("red") or []), len(b.get("yellow") or [])
    new_n = b.get("new_red_count") or 0
    n_codes = len(b.get("by_code") or {})
    text = (f"{b.get('date')}(age={fresh['age_days']}d,{'新鮮' if fresh['is_fresh'] else '⚠️過期'})"
            f":{n_codes} 檔有訊號,紅 {red_n}/黃 {yellow_n}"
            + (f",較上次新增 {new_n} 則紅燈" if new_n else ""))
    return {"exists": True, "date": b.get("date"), "red_n": red_n, "yellow_n": yellow_n,
            "new_red_n": new_n, "n_codes_with_signal": n_codes, "freshness": fresh, "text": text}


def _cli():
    ap = argparse.ArgumentParser(description="信息差引擎統一查詢介面")
    ap.add_argument("--code", help="查單一代碼(台股4碼或美股ticker)")
    ap.add_argument("--level", choices=["red", "yellow"], help="篩層級")
    ap.add_argument("--summary", action="store_true", help="今日訊號摘要")
    ap.add_argument("--freshness", action="store_true", help="latest.json 新鮮度")
    ap.add_argument("--explain", help="查某個 source 字串的白話定義")
    ap.add_argument("--json", action="store_true", help="輸出 JSON(給程式呼叫端用)")
    args = ap.parse_args()

    out = None
    if args.explain:
        out = explain_source(args.explain)
    elif args.freshness:
        out = freshness()
    elif args.summary:
        out = summary()
    elif args.code:
        out = signals_for(args.code, level=args.level)
    else:
        out = summary()

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        if isinstance(out, dict) and "text" in out:
            print(out["text"])
        else:
            print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _cli()
