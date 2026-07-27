"""股票中英文名稱對照 — 讓日報顯示公司名,不只有代號。"""

import re

US_NAMES = {
    "AAPL": ("蘋果", "Apple"),
    "MSFT": ("微軟", "Microsoft"),
    "GOOGL": ("谷歌", "Alphabet"),
    "GOOG": ("谷歌", "Alphabet"),
    "AMZN": ("亞馬遜", "Amazon"),
    "META": ("Meta", "Meta"),
    "NVDA": ("輝達", "Nvidia"),
    "TSLA": ("特斯拉", "Tesla"),
    "AMD": ("超微", "AMD"),
    "TSM": ("台積電 ADR", "TSMC"),
    "ARM": ("安謀", "Arm"),
    "JPM": ("摩根大通", "JPMorgan"),
    "GS": ("高盛", "Goldman Sachs"),
    "BRK-B": ("波克夏", "Berkshire"),
    "AVGO": ("博通", "Broadcom"),
    "NFLX": ("網飛", "Netflix"),
    "INTC": ("英特爾", "Intel"),
    "MU": ("美光", "Micron"),
    "QCOM": ("高通", "Qualcomm"),
    "PLTR": ("Palantir", "Palantir"),
    "COST": ("好市多", "Costco"),
    "DIS": ("迪士尼", "Disney"),
    "BABA": ("阿里巴巴", "Alibaba"),
    "SMCI": ("美超微", "Supermicro"),
    "MSTR": ("微策略", "MicroStrategy"),
    "COIN": ("Coinbase", "Coinbase"),
    "UBER": ("優步", "Uber"),
    "CRM": ("賽富時", "Salesforce"),
    "ORCL": ("甲骨文", "Oracle"),
    "ADBE": ("奧多比", "Adobe"),
    "PYPL": ("PayPal", "PayPal"),
    "BA": ("波音", "Boeing"),
    "WMT": ("沃爾瑪", "Walmart"),
    "KO": ("可口可樂", "Coca-Cola"),
    "MCD": ("麥當勞", "McDonald's"),
    "NKE": ("耐吉", "Nike"),
    "V": ("Visa", "Visa"),
    "MA": ("萬事達卡", "Mastercard"),
    "XOM": ("艾克森美孚", "ExxonMobil"),
    "LLY": ("禮來", "Eli Lilly"),
    "JNJ": ("嬌生", "Johnson & Johnson"),
    "UNH": ("聯合健康", "UnitedHealth"),
    "IONQ": ("IonQ", "IonQ"),
    "QBTS": ("D-Wave", "D-Wave"),
    "QUBT": ("Quantum Computing", "Quantum Computing"),
    "RGTI": ("Rigetti", "Rigetti"),
    "VZ": ("威訊", "Verizon"),
    "PFE": ("輝瑞", "Pfizer"),
    "SFTBY": ("軟銀", "SoftBank"),
    "T": ("AT&T", "AT&T"),
    "CSCO": ("思科", "Cisco"),
    "IBM": ("IBM", "IBM"),
    "GE": ("奇異", "GE"),
    "MRK": ("默克", "Merck"),
    "ABBV": ("艾伯維", "AbbVie"),
    "HD": ("家得寶", "Home Depot"),
    "C": ("花旗", "Citigroup"),
    "BAC": ("美國銀行", "Bank of America"),
    "WFC": ("富國銀行", "Wells Fargo"),
    "MS": ("摩根士丹利", "Morgan Stanley"),
    "SBUX": ("星巴克", "Starbucks"),
    "GME": ("遊戲驛站", "GameStop"),
    "DELL": ("戴爾", "Dell"),
    "HPQ": ("惠普", "HP"),
    "MRVL": ("邁威爾", "Marvell"),
    "ASML": ("艾司摩爾", "ASML"),
    "MARA": ("Marathon", "Marathon Digital"),
    "RIOT": ("Riot", "Riot Platforms"),
}

TW_NAMES = {
    # 半導體 / IC 設計
    "2330": ("台積電", "TSMC"),
    "2454": ("聯發科", "MediaTek"),
    "2303": ("聯電", "UMC"),
    "2379": ("瑞昱", "Realtek"),
    "3034": ("聯詠", "Novatek"),
    "3037": ("欣興", "Unimicron"),
    "3711": ("日月光投控", "ASE"),
    "5347": ("世界先進", "VIS"),
    "6488": ("環球晶", "GlobalWafers"),
    "8046": ("南電", "NYPCB"),
    "6669": ("緯穎", "Wiwynn"),
    "8299": ("群聯", "Phison"),
    "3481": ("群創", "Innolux"),
    "2474": ("可成", "Catcher"),
    "2327": ("國巨", "Yageo"),
    "2492": ("華新科", "Walsin Tech"),
    "3661": ("世芯-KY", "Alchip"),
    "6533": ("晶心科", "Andes"),
    "5269": ("祥碩", "ASMedia"),
    "3045": ("台灣大", "Taiwan Mobile"),
    "3105": ("穩懋", "WIN Semi"),
    "6770": ("力積電", "PSMC"),
    "8016": ("矽創", "Sitronix"),
    "6415": ("矽力-KY", "Silergy"),
    # 電子代工 / 硬體
    "2317": ("鴻海", "Hon Hai"),
    "2308": ("台達電", "Delta"),
    "2382": ("廣達", "Quanta"),
    "2357": ("華碩", "ASUS"),
    "3231": ("緯創", "Wistron"),
    "2376": ("技嘉", "Gigabyte"),
    "4938": ("和碩", "Pegatron"),
    "2353": ("宏碁", "Acer"),
    "2049": ("上銀", "HIWIN"),
    "3008": ("大立光", "Largan"),
    "6531": ("中華精測", ""),
    "6196": ("帆宣", "Marketech"),
    "3702": ("大聯大", "WPG"),
    # 金融
    "2881": ("富邦金", "Fubon"),
    "2882": ("國泰金", "Cathay"),
    "2891": ("中信金", "CTBC"),
    "2884": ("玉山金", "E.SUN"),
    "2885": ("元大金", "Yuanta"),
    "2886": ("兆豐金", "Mega"),
    "2887": ("台新金", "Taishin"),
    "2890": ("永豐金", "SinoPac"),
    "2892": ("第一金", "First Financial"),
    "2880": ("華南金", "Hua Nan"),
    "5871": ("中租-KY", "Chailease"),
    # 通訊 / 電信
    "2412": ("中華電", "Chunghwa Telecom"),
    "4904": ("遠傳", "FET"),
    # 航運 / 運輸
    "2603": ("長榮", "Evergreen"),
    "2615": ("萬海", "Wan Hai"),
    "2609": ("陽明", "Yang Ming"),
    "2618": ("長榮航", "EVA Air"),
    "2610": ("華航", "China Airlines"),
    # 傳產 / 鋼鐵 / 塑化
    "2002": ("中鋼", "China Steel"),
    "1301": ("台塑", "Formosa Plastics"),
    "1303": ("南亞", "Nan Ya"),
    "1326": ("台化", "Formosa Chem"),
    "1101": ("台泥", "TCC"),
    "1102": ("亞泥", "ACC"),
    "2105": ("正新", "Cheng Shin"),
    "6505": ("台塑化", "FPCC"),
    # 民生 / 食品 / 零售
    "1216": ("統一", "Uni-President"),
    "2912": ("統一超", "President Chain"),
    "2207": ("和泰車", "Hotai"),
    "8454": ("富邦媒", "momo"),
    "9904": ("寶成", "Pou Chen"),
    "9910": ("豐泰", "Feng Tay"),
    "9914": ("美利達", "Merida"),
    "9921": ("巨大", "Giant"),
    # ETF
    "0050": ("元大台灣50", "Yuanta 0050"),
    "0056": ("元大高股息", "Yuanta 0056"),
    "00878": ("國泰永續高股息", "Cathay 00878"),
    "006208": ("富邦台50", "Fubon FB50"),
}


def _names(code, tw_hint=None):
    c = (code or "").strip().upper()
    if c in US_NAMES:
        return US_NAMES[c]
    if c in TW_NAMES:
        return TW_NAMES[c]
    if tw_hint:
        return (tw_hint.strip(), "")
    return ("", "")


def is_tw_symbol(sym) -> bool:
    """台股/美股代碼判別唯一事實來源:台股代碼首字必為數字(含 00981A 主動式 ETF、
    00631L 槓桿、00632R 反向、00400A 債券這類字母尾碼商品),美股代碼首字必為字母。
    「全數字」判別(str.isdigit)會把字母尾碼台股誤當美股/直接丟棄——2026-07-27
    事故家族:hfks996 的 00981A 晨間鐵則不注入+TWSE 全表解析丟棄 127 檔字母尾碼。"""
    s = str(sym or "")
    return bool(s) and s[:1].isdigit()


def is_known(code):
    c = (code or "").strip().upper()
    return c in US_NAMES or c in TW_NAMES


def display_name(code, tw_hint=None):
    """回傳『中文 英文』,例如 '輝達 Nvidia';無資料回 code 本身。"""
    cn, en = _names(code, tw_hint)
    if cn and en and cn != en:
        return f"{cn} {en}"
    return cn or code


def _is_tw(code):
    return (code or "").strip().isdigit()


def label_with_code(code, tw_hint=None):
    """美股回『中文 代號』(輝達 NVDA);台股優先顯示台股名稱,代號可省(台積電)。"""
    cn, _ = _names(code, tw_hint)
    if cn and cn != code:
        return cn if _is_tw(code) else f"{cn} {code}"
    return code


def badge_html(code, tw_hint=None):
    """ticker 徽章 HTML。台股:只顯示台股名稱(代號不一定要顯示);美股:公司中英文名 + 小灰代號。"""
    if _is_tw(code):
        cn, _ = _names(code, tw_hint)
        name = cn or code
        if name == code:
            return code
        return (
            '<span style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
            f'font-weight:800;">{name}</span>'
        )
    name = display_name(code, tw_hint)
    if name == code:
        return code
    return (
        '<span style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        f'font-weight:800;">{name}</span>'
        '<span style="font-family:\'SF Mono\',ui-monospace,monospace;font-size:10px;'
        f'color:#8e8e93;margin-left:5px;font-weight:700;">{code}</span>'
    )


def pick_code(content):
    """從一段文字裡挑出第一個看起來像股票代號的 token。"""
    for tok in re.split(r'[\s（）()／/|｜·,，、]+', (content or "").strip()):
        t = tok.strip().upper()
        if not t:
            continue
        if is_known(t) or re.fullmatch(r'\d{4,6}', t) or re.fullmatch(r'[A-Z]{1,5}(?:-[A-Z])?', t):
            return t
    return (content or "").strip()
