"""日本代標 → 台灣落地成本:**全系統唯一真源**(正解與反解同源)。

為什麼獨立成一支:2026-08-05 之前這套算式被手刻兩份 —— `radar.landed_cost`(正解)
與 `bidcap`(反解)。兩份都漏了同一批 Buyee 實際費用,於是「雷達說的毛利」與
「出價上限」**同時**高估,而且互相對得起來、看不出破綻。同一份邏輯手刻兩次的下場
就是兩份一起錯(見 memory hub_guard_incidents:cron_call_resolver 同款)。

成本結構(2026-08-05 首單真實結帳頁量到,取代先前的 ¥300 估值):
  - 落札價(JPY)
  - Buyee 代標手續費 ¥500/單
  - Buyee 檢品方案 ¥500/件 —— 桿身線的 sales_playbook 要求逐件拍序號驗真,**預設加購**
  - JPY→TWD 換匯:Buyee 收款匯率比中價貴約 5.9%(付款頁實測),所以有效匯率 = 中價 × 1.059
  - 日本國內運費 / 國際運費(以 NTD 估,item 給值)
  - 關稅(CIF × duty)+ 營業稅((CIF+關稅) × 5%)

⚠️ 關稅基礎(CIF)只含**商品本體 + 國際運費**。代標手續費與檢品費是付給代標商的服務費,
   不進完稅價格 —— 這是刻意的選擇,不是漏算;想改成保守估法把 `FEES_IN_CIF` 打開即可。

代數(讓反解有封閉解,不用數值逼近):
    k      = 1 + duty + (1 + duty) × 0.05          # CIF 的稅倍數
    e      = rate × (1 + FX_PREMIUM)               # 有效匯率
    landed = k × (jpy × e + intl_ship) + fees_jpy × e + jp_ship
    jpy    = ((landed - jp_ship - k × intl_ship) / e - fees_jpy) / k
"""

BUYEE_FEE_JPY = 500      # 代標手續費 /單
INSPECT_JPY = 500        # 檢品方案 /件(item 可用 "inspect": False 關掉)
FX_PREMIUM = 0.059       # Buyee 收款匯率相對中價的溢價
VAT = 0.05
DEFAULT_DUTY = 0.05
FEES_IN_CIF = False      # 服務費是否計入完稅價格(預設否,見上面說明)

COST_MODEL = "v2-buyee-fees"


def _k(duty):
    return 1 + duty + (1 + duty) * VAT


def effective_rate(rate):
    """中價匯率 → Buyee 實際收款匯率。"""
    return rate * (1 + FX_PREMIUM)


def fees_jpy(item):
    """每筆訂單固定的日圓費用(手續費 + 檢品)。"""
    f = item.get("buyee_fee_jpy", BUYEE_FEE_JPY)
    if item.get("inspect", True):
        f += item.get("inspect_jpy", INSPECT_JPY)
    return f


def breakdown(jpy, rate, item):
    """完整成本拆解(NTD),給儀表板/報告逐項秀出來用。"""
    duty_rate = item.get("duty", DEFAULT_DUTY)
    e = effective_rate(rate)
    f_jpy = fees_jpy(item)
    goods = jpy * e
    fees = f_jpy * e
    intl = item["intl_ship"]
    cif = goods + intl + (fees if FEES_IN_CIF else 0)
    duty = cif * duty_rate
    vat = (cif + duty) * VAT
    landed = goods + fees + item["jp_ship"] + intl + duty + vat
    return {
        "goods": round(goods),
        "buyee_fees": round(fees),
        "fees_jpy": f_jpy,
        "jp_ship": item["jp_ship"],
        "intl_ship": intl,
        "duty": round(duty),
        "vat": round(vat),
        "landed": round(landed),
        "effective_rate": round(e, 5),
        "cost_model": COST_MODEL,
    }


def landed_from_jpy(jpy, rate, item):
    """日圓落札價 → 台灣落地成本(NTD,未四捨五入)。"""
    duty_rate = item.get("duty", DEFAULT_DUTY)
    k = _k(duty_rate)
    e = effective_rate(rate)
    f = fees_jpy(item)
    extra = k if FEES_IN_CIF else 1
    return k * (jpy * e + item["intl_ship"]) + f * e * extra + item["jp_ship"]


def jpy_for_landed(target_landed, rate, item):
    """反解:給定可接受的落地成本,回推最高日圓出價。不可行回 0。"""
    duty_rate = item.get("duty", DEFAULT_DUTY)
    k = _k(duty_rate)
    e = effective_rate(rate)
    if e <= 0:
        return 0
    f = fees_jpy(item)
    extra = k if FEES_IN_CIF else 1
    goods_jpy = ((target_landed - item["jp_ship"] - k * item["intl_ship"]) / e
                 - f * extra) / k
    if goods_jpy <= 0:
        return 0
    return goods_jpy
