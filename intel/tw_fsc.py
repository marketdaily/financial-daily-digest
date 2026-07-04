"""金管會重大裁罰案件連接器(信息差引擎 #10,curriculum I 節「法規監控」補金管會端):
免費 RSS(www.fsc.gov.tw),不需金鑰,涵蓋銀行局/證期局/保險局全部重大裁罰。
跟 tw_surveillance.py(交易所對「交易行為」的監理:注意/處置)不同維度——這裡是主管機關對
「金融機構本身」的行政裁罰,對象是上市金控/銀行/證券/保險子公司,不是一般上市公司,
因此用獨立的靜態對照表(子公司法定名稱 → 上市股票代碼)比對,不依賴 CB watchlist
(CB 標的多為非金融產業,天生零命中;金控/銀行股才是一般訂閱者常見持股)。
訊號定義:
  紅燈 🔴:裁罰內容含停業/撤照/解除職務等結構性處分(業務/人事層級,非只是罰錢)
  黃燈 🟡:一般罰鍰/糾正/命令改善(合規瑕疵,尚未動搖經營層級)
"""
import datetime
import subprocess
import xml.etree.ElementTree as ET

FEED_URL = "https://www.fsc.gov.tw/RSS/Messages?serno=201202290003&language=chinese"

# 上市金控/銀行/證券/保險子公司法定名稱關鍵字 → (股票代碼, 顯示名稱)。
# 只收錄有獨立上市代碼的金融機構,子公司裁罰視同母公司監理風險訊號。
INSTITUTIONS = [
    ("華南商業銀行", "2880", "華南金"), ("華南產物保險", "2880", "華南金"), ("華南永昌證券", "2880", "華南金"),
    ("台北富邦銀行", "2881", "富邦金"), ("富邦人壽", "2881", "富邦金"), ("富邦產物保險", "2881", "富邦金"), ("富邦證券", "2881", "富邦金"),
    ("國泰世華商業銀行", "2882", "國泰金"), ("國泰人壽", "2882", "國泰金"), ("國泰產物保險", "2882", "國泰金"), ("國泰證券", "2882", "國泰金"),
    ("凱基商業銀行", "2883", "開發金"), ("凱基銀行", "2883", "開發金"), ("凱基證券", "2883", "開發金"),
    ("玉山商業銀行", "2884", "玉山金"), ("玉山證券", "2884", "玉山金"),
    ("元大商業銀行", "2885", "元大金"), ("元大證券", "2885", "元大金"), ("元大人壽", "2885", "元大金"),
    ("兆豐國際商業銀行", "2886", "兆豐金"), ("兆豐產物保險", "2886", "兆豐金"), ("兆豐證券", "2886", "兆豐金"),
    ("台新國際商業銀行", "2887", "台新金"), ("台新產物保險", "2887", "台新金"),
    ("新光人壽保險", "2888", "新光金"),
    ("國際票券", "2889", "國票金"), ("國票綜合證券", "2889", "國票金"),
    ("永豐商業銀行", "2890", "永豐金"), ("永豐證券", "2890", "永豐金"), ("永豐金租賃", "2890", "永豐金"),
    ("中國信託商業銀行", "2891", "中信金"), ("中國信託人壽", "2891", "中信金"), ("中國信託證券", "2891", "中信金"),
    ("第一商業銀行", "2892", "第一金"), ("第一產物保險", "2892", "第一金"), ("第一金證券", "2892", "第一金"),
    ("王道商業銀行", "2897", "王道銀行"),
    ("日盛國際商業銀行", "5820", "日盛金"), ("日盛證券", "5820", "日盛金"),
    ("上海商業儲蓄銀行", "5876", "上海商銀"),
    ("合作金庫商業銀行", "5880", "合庫金"), ("合庫人壽", "5880", "合庫金"), ("合庫證券", "5880", "合庫金"),
    ("彰化商業銀行", "2801", "彰銀"),
    ("京城商業銀行", "2809", "京城銀行"),
    ("台中商業銀行", "2812", "台中銀行"),
    ("台灣中小企業銀行", "2834", "台企銀"),
    ("高雄銀行", "2836", "高雄銀行"),
    ("聯邦商業銀行", "2838", "聯邦銀"),
    ("遠東國際商業銀行", "2845", "遠東銀"),
    ("安泰商業銀行", "2849", "安泰銀"),
    ("中國人壽保險", "2823", "中壽"),
    ("新光產物保險", "2850", "新產"),
    ("三商美邦人壽", "2867", "三商壽"),
    ("群益金鼎證券", "6005", "群益證"),
    ("康和綜合證券", "6016", "康和證"),
]

RED_KW = ["停止營業", "停業", "撤照", "廢止許可", "解除職務", "限制部分業務"]


def _match_institution(text):
    """回傳命中的第一個 (code, name);查無回 None。"""
    for kw, code, name in INSTITUTIONS:
        if kw in text:
            return code, name
    return None


def _level(text):
    for kw in RED_KW:
        if kw in text:
            return "red"
    return "yellow"


def _get(url):
    """fsc.gov.tw 憑證鏈讓 Python 預設 SSLContext 驗證失敗(同 TDCC 坑,curl 驗證正常),改走 curl 子行程。"""
    out = subprocess.run(["curl", "-sL", "--max-time", "25", "-A", "Mozilla/5.0", url],
                          capture_output=True, timeout=30)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"curl failed rc={out.returncode}")
    return out.stdout


def _parse(xml_bytes):
    """回 list[{date, title}] 新到舊(feed 原生順序),壞資料回空 list。"""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        try:
            d = datetime.date.fromisoformat(pub)
        except ValueError:
            continue
        if title:
            out.append({"date": pub, "_d": d, "title": title})
    return out


def scan(days=90):
    """近 N 日金管會重大裁罰,命中上市金控/銀行/證券/保險子公司才回傳。
    回 {code: {level, signal, source, name}},同碼多筆取最嚴重一則(紅 > 黃)。"""
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    out = {}
    try:
        rows = _parse(_get(FEED_URL))
    except Exception:
        return out
    for r in rows:
        if r["_d"] < cutoff:
            continue
        hit = _match_institution(r["title"])
        if not hit:
            continue
        code, name = hit
        lvl = _level(r["title"])
        existing = out.get(code)
        if existing is not None and not (lvl == "red" and existing["level"] != "red"):
            continue
        out[code] = {
            "level": lvl, "source": "fsc_penalty", "name": name,
            "signal": f"{name}({code}) 金管會裁罰[{r['date']}]:{r['title'][:70]}",
        }
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(scan(), ensure_ascii=False, indent=1))
