"""台灣 → 澳洲 出口成本模型。與 radar 的日本→台灣方向完全不同,獨立一支。

運費採中華郵政官方費率(2026-08-05 查證):
  e小包大洋洲 500g NT$280 / 1kg NT$405 / 2kg NT$655(起重100g NT$180、每續重100g NT$25)
  國際包裹澳洲 航空:起重0.5kg 310、每續0.5kg 105;陸空SAL:起重1kg 310、每續1kg 125
  EMS 大洋洲 0.5kg 600 / 3kg 1,195 / 5kg 1,675 / 10kg 2,875 / 20kg 5,075

⚠️ 尺寸硬限制(比重量更早殺死大件):任何一邊 ≤105cm、長+周圍(長+2寬+2高) ≤200cm、≤20kg。
   自行車輪組箱 70×70×20 → 長+周圍 250cm **超限,郵局不收**;不是貴而是寄不了。
⚠️ 材積重 = 長×寬×高÷6000,與實重取大者計費(102/3/1 起適用)。

未確認(不得當已知,全部標在輸出裡):
  · 澳洲 GST 10% 對低價值進口由誰收、A$1,000 門檻 —— ato.gov.au 403 未取得官方來源
  · eBay AU final value fee 實際百分比 —— 費用頁只給結構不給費率
"""
POST_RATES = {
    "epacket": [(0.5, 280), (1.0, 405), (2.0, 655)],
    "air": {"base_kg": 0.5, "base": 310, "step_kg": 0.5, "step": 105, "max_kg": 20},
    "sal": {"base_kg": 1.0, "base": 310, "step_kg": 1.0, "step": 125, "max_kg": 20},
    "ems": [(0.5, 600), (3.0, 1195), (5.0, 1675), (10.0, 2875), (20.0, 5075)],
}
MAX_SIDE_CM = 105
MAX_GIRTH_CM = 200          # 長 + 2×寬 + 2×高
MAX_KG = 20

# 未查證到官方來源的假設,一律顯性命名,方便日後替換
ASSUMED_EBAY_FVF = 0.13     # ⚠️ 未確認
ASSUMED_AU_GST = 0.10       # ⚠️ 未確認(低價值進口是否由平台代收亦未確認)
SHIP_COST_CAP = 0.15        # 運費佔售價上限的自訂判準(非查得數字)


def volumetric_kg(l, w, h):
    return l * w * h / 6000.0


def size_ok(l, w, h, kg):
    """回 (是否可寄, 原因)。尺寸不過的,運費多少都沒意義。"""
    if max(l, w, h) > MAX_SIDE_CM:
        return False, f"最長邊 {max(l, w, h)}cm > {MAX_SIDE_CM}cm"
    girth = l + 2 * w + 2 * h
    if girth > MAX_GIRTH_CM:
        return False, f"長+周圍 {girth:.0f}cm > {MAX_GIRTH_CM}cm"
    bill = max(kg, volumetric_kg(l, w, h))
    if bill > MAX_KG:
        return False, f"計費重 {bill:.1f}kg > {MAX_KG}kg"
    return True, ""


def _tiered(table, kg):
    for limit, price in table:
        if kg <= limit:
            return price
    return None


def _stepped(cfg, kg):
    if kg > cfg["max_kg"]:
        return None
    if kg <= cfg["base_kg"]:
        return cfg["base"]
    extra = kg - cfg["base_kg"]
    steps = int(-(-extra // cfg["step_kg"]))     # ceil
    return cfg["base"] + steps * cfg["step"]


def max_batch(kg):
    """單一包裹能裝的最大件數(受 20kg 上限)。"""
    return max(1, int(MAX_KG // kg))


def cheapest_ship(kg, qty=1):
    """回 (單位運費, 管道)。qty>1 代表合併寄,運費由整批攤提。"""
    total_kg = kg * qty
    opts = {}
    for name in ("epacket",):
        p = _tiered(POST_RATES[name], total_kg)
        if p:
            opts[name] = p
    for name in ("air", "sal"):
        p = _stepped(POST_RATES[name], total_kg)
        if p:
            opts[name] = p
    p = _tiered(POST_RATES["ems"], total_kg)
    if p:
        opts["ems"] = p
    if not opts:
        return None, "超過 20kg,郵局不可寄"
    name = min(opts, key=opts.get)
    return opts[name] / qty, name


def evaluate(item, aud_twd, qty=1):
    """item: {name, tw_cost, kg, dims(l,w,h), au_price_aud, ...}"""
    l, w, h = item["dims"]
    ok, why = size_ok(l, w, h, item["kg"])
    row = {**item, "qty": qty, "size_ok": ok, "size_reason": why,
           "volumetric_kg": round(volumetric_kg(l, w, h), 2)}
    if not ok:
        row["verdict"] = "寄不了"
        return row

    ship, via = cheapest_ship(item["kg"], qty)
    if ship is None:
        # 合併寄超過郵局 20kg 上限 —— 這是真限制不是錯誤,要回報可寄的最大批量
        row["verdict"] = f"批量 {qty} 件共 {item['kg']*qty:.1f}kg 超過 20kg 上限"
        row["max_qty"] = int(MAX_KG // item["kg"])
        return row
    landed = item["tw_cost"] + ship
    sell_twd = item["au_price_aud"] * aud_twd
    fees = sell_twd * ASSUMED_EBAY_FVF
    net = sell_twd - fees - landed

    row.update({
        "ship_unit": round(ship), "ship_via": via,
        "landed": round(landed), "sell_twd": round(sell_twd),
        "fees": round(fees), "margin": round(net),
        "roi": round(net / landed * 100) if landed else 0,
        "ship_ratio": round(ship / sell_twd * 100, 1),
        # 運費佔比過高 = 連平台費和進貨成本都不用算就死
        "ship_ratio_ok": (ship / sell_twd) <= SHIP_COST_CAP,
        "assumptions": ["eBay FVF 13% 未確認", "澳洲 GST 歸屬未確認"],
    })
    if not row["ship_ratio_ok"]:
        row["verdict"] = f"運費佔售價 {row['ship_ratio']}% 過高"
    elif net <= 0:
        row["verdict"] = "淨利為負"
    else:
        row["verdict"] = "待驗證(需 eBay AU sold 確認真實成交價)"
    return row


# 台灣→澳洲僅存的兩個候選(2026-08-05 全品類掃描後唯一未被判死者)
# 共同特徵:小體積 + 台灣自有品牌/產業聚落 + 2x 以上價差
CANDIDATES = [
    {"id": "kmc_x11el", "name": "KMC X11EL 11速鏈條 114目",
     "tw_cost": 650, "kg": 0.3, "dims": (18, 12, 4),
     "au_price_aud": 66.79,
     "tw_src": "露天中位 n=10,sold=31/33/25(有實際銷售紀錄)",
     "au_src": "Amazon AU 競爭價。⚠️ 代理維價 A$99.99 已作廢不用",
     "note": "台灣自有品牌 2.3x;250g 價值密度佳"},
    {"id": "tw_air_impact", "name": "台灣製 1/2\" 雙鎚式氣動扳手",
     "tw_cost": 1730, "kg": 2.5, "dims": (30, 25, 12),
     "au_price_aud": 133.0,
     "tw_src": "露天 sold=99/35/12",
     "au_src": "Amazon AU A$133-193(BGS/Güde/KS Tools 等德系)。⚠️ 多為歐洲賣家寄澳,非澳洲本地街價",
     "note": "台中產業聚落 2.5x;非電器,無 RCM/EESS 認證負擔"},
    {"id": "tw_socket_set", "name": "台灣製 72齒 1/2\" 14件套筒組",
     "tw_cost": 600, "kg": 1.8, "dims": (30, 20, 8),
     "au_price_aud": 64.89,
     "tw_src": "露天 sold=12",
     "au_src": "Amazon AU BlueSpot 12件 A$64.89 / Högert A$76.57",
     "note": "同上聚落;單價偏低是隱憂"},
]
