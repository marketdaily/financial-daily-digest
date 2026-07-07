"""即時報價(TWSE MIS API):現股 + CB 百元報價,免費免 token,約 5 秒快照。
- 一支 API 同時涵蓋上市(tse)/上櫃(otc);CB(債券代碼)在櫃買等價系統,一樣查得到。
- 15 秒檔案快取(--watch 迴圈與 rank 批次不重複打);另記住每個代碼的市場歸屬,之後只查一邊。
- 收盤後 MIS 仍回當日最後快照 → 自動等於「今日收盤價」;完全失敗回 None(呼叫端退回日線)。
價格判定順序:z(最新成交) → pz(前一筆) → 買賣中價 → 開盤 → 昨收。"""
import os
import json
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, ".quote_cache.json")
MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TTL = 15          # 秒
CHUNK = 10        # 每請求最多 10 個代碼(未知市場時 ×2 個 ex_ch)


def _num(s):
    try:
        v = float(str(s).replace(",", ""))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _load():
    """快取檔壞掉/形狀不對(合法 JSON 但不是預期結構)一律當空快取,絕不讓報價層 crash。"""
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            c = json.load(f)
        if (isinstance(c, dict) and isinstance(c.get("quotes"), dict)
                and isinstance(c.get("market"), dict)):
            return c
    except Exception:
        pass
    return {"quotes": {}, "market": {}}


def _save(c):
    try:
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception:
        pass


def _parse_msg(m):
    """MIS 單檔訊息 → quote dict 或 None。"""
    code = m.get("c") or ""
    if not code or not (m.get("y") or m.get("o") or m.get("z")):
        return None
    bid = _num((m.get("b") or "").split("_")[0])
    ask = _num((m.get("a") or "").split("_")[0])
    z = _num(m.get("z"))
    pz = _num(m.get("pz"))
    mid = (bid + ask) / 2 if (bid and ask) else None
    price = z or pz or mid or _num(m.get("o")) or _num(m.get("y"))
    if not price:
        return None
    d = m.get("d") or ""
    return {
        "code": code, "name": m.get("n"), "price": price,
        "src_price": "成交" if (z or pz) else ("中價" if mid else "開盤/昨收"),
        "bid": bid, "ask": ask,
        "open": _num(m.get("o")), "high": _num(m.get("h")), "low": _num(m.get("l")),
        "prev_close": _num(m.get("y")), "volume": _num(m.get("v")),
        "date": f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d,
        "time": (m.get("%") or m.get("t") or "")[:8],
        "ex": m.get("ex"),
    }


def _fetch(ex_chs):
    url = f"{MIS}?ex_ch={'|'.join(ex_chs)}&json=1&delay=0&_={int(time.time()*1000)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        j = json.loads(r.read().decode())
    out = {}
    for m in j.get("msgArray", []):
        q = _parse_msg(m)
        if q:
            out[q["code"]] = q
    return out


def get_quotes(codes, ttl=TTL):
    """批次即時報價。回 {code: quote};抓不到的代碼不在結果裡。"""
    codes = [str(c).strip() for c in codes if c]
    cache = _load()
    now = time.time()
    out, need = {}, []
    for c in codes:
        ent = cache["quotes"].get(c)
        if (isinstance(ent, dict) and ent.get("q")
                and now - ent.get("ts", 0) < ttl):
            out[c] = ent["q"]
        else:
            need.append(c)
    if not need:
        return out

    # 已知市場只查一邊;未知查兩邊
    chans, per_code = [], {}
    for c in need:
        mk = cache["market"].get(c)
        exs = [mk] if mk in ("tse", "otc") else ["tse", "otc"]
        per_code[c] = exs
        chans += [f"{e}_{c}.tw" for e in exs]

    fetched = {}
    for i in range(0, len(chans), CHUNK * 2):
        try:
            fetched.update(_fetch(chans[i:i + CHUNK * 2]))
        except Exception:
            continue
    # 記憶的市場歸屬查不到 → 歸屬可能過期(上櫃轉上市等):立即雙市場補查,仍無則清除記憶
    retry = [c for c in need if c not in fetched and per_code[c] != ["tse", "otc"]]
    if retry:
        chans2 = [f"{e}_{c}.tw" for c in retry for e in ("tse", "otc")]
        for i in range(0, len(chans2), CHUNK * 2):
            try:
                fetched.update(_fetch(chans2[i:i + CHUNK * 2]))
            except Exception:
                continue
        for c in retry:
            if c not in fetched:
                cache["market"].pop(c, None)
    for c in need:
        q = fetched.get(c)
        if q:
            out[c] = q
            cache["quotes"][c] = {"ts": now, "q": q}
            if q.get("ex"):
                cache["market"][c] = q["ex"]
    _save(cache)
    return out


def get_quote(code, ttl=TTL):
    """單檔即時報價。回 quote dict 或 None。"""
    return get_quotes([code], ttl=ttl).get(str(code).strip())


if __name__ == "__main__":
    import sys
    for c, q in get_quotes(sys.argv[1:] or ["2330"]).items():
        print(c, json.dumps(q, ensure_ascii=False))
