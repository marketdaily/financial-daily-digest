"""台股集保戶股權分散表連接器(信息差引擎積木 #6)。
tw_institutional/tw_margin/tw_sbl 抓的是法人/融資融券/借券——這裡抓「誰真的持有股票」:
集保結算所(TDCC)每週五公布的股權分散表,依持股級距統計人數/股數/占比,
追蹤「千張大戶(≥1,000張,即≥100萬股)持股比」週變動——比法人買賣超更底層的籌碼歸屬指標
(法人可能只是通路,真正大股東/主力的持股比變化才是誰在長期卡位的直接證據)。

資料源:TDCC 官網 https://www.tdcc.com.tw/portal/zh/smWeb/qryStock (免token,無官方API,
表單為 Struts SYNCHRONIZER_TOKEN(CSRF)模式,每次查詢須先 GET 拿新 token 再 POST,不可重用舊 token)。
每週五公布(遇假日順延/偶爾跳過),故用「週」而非「日」比較基準,取當週與上一筆公布資料相減。

⚠️坑(2026-07-03 探測記錄,省後人重踩):
1. Python urllib/ssl 對 TDCC 憑證鏈報 `Missing Subject Key Identifier` 驗證失敗(OpenSSL 3.5.5 下
   openssl s_client 與 curl 都驗證通過,只有 Python 的預設 SSLContext 較嚴格擋下)——改用 curl 子行程
   (同 scripts/site_scan.py 既有模式),不要用 urllib 直連這個網域。
2. SYNCHRONIZER_TOKEN 是一次性 CSRF token,同一 session 內重用舊 token 會靜默失敗(回空白「資料日期：」
   無錯誤訊息,不是 4xx/5xx)——每次查詢(含同一 code 的「本週」與「上週」兩次)都必須重新 GET 拿新 token。
3. 可查詢日期只能從表單的 <select name="scaDate"> 選項清單取得(不可假設固定週五間隔,清單內偶有
   6 天/非7天間隔,對應假日調整),不要自己用 timedelta(days=7) 推算上一筆日期。

訊號定義(v1 啟發式門檻,同 tw_margin/tw_sbl 方法論——先建可行動訊號,精確門檻後續用 edge_audit 回測校準):
  🔴 千張大戶持股比週增 ≥1.0 個百分點(大戶顯著加碼卡位)
  🟡 千張大戶持股比週增 ≥0.5 個百分點(溫和加碼)
  🟡 千張大戶持股比週減 ≥1.0 個百分點(大戶出脫,籌碼鬆動)
  ⚪ 中性(只記錄不打擾)
  附註:若持股比增加同時「戶數」減少 → 籌碼更集中在更少的手上,訊號文字會加註。
"""
import os
import re
import json
import datetime
import time
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".holders_cache.json")
UA = "Mozilla/5.0"
URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
BIG_TIER = "1,000,001以上"  # 千張大戶(≥1,000張=≥100萬股)


def _curl_get(cookie_jar):
    out = subprocess.run(["curl", "-sL", "--max-time", "15", "-c", cookie_jar, "-b", cookie_jar,
                          "-A", UA, URL], capture_output=True, text=True, timeout=20)
    return out.stdout


def _curl_post(cookie_jar, data):
    args = ["curl", "-sL", "--max-time", "15", "-c", cookie_jar, "-b", cookie_jar,
            "-A", UA, "-e", URL, "-X", "POST", URL]
    for k, v in data.items():
        args += ["--data-urlencode", f"{k}={v}"]
    out = subprocess.run(args, capture_output=True, text=True, timeout=20)
    return out.stdout


def _fetch_dates_and_token(cookie_jar):
    html = _curl_get(cookie_jar)
    m = re.search(r'name="SYNCHRONIZER_TOKEN" value="([^"]*)"', html)
    token = m.group(1) if m else ""
    dates = sorted(set(re.findall(r'<option value="([0-9]{8})"', html)), reverse=True)
    return token, dates


def _query_tiers(cookie_jar, token, code, date_str):
    html = _curl_post(cookie_jar, {
        "SYNCHRONIZER_TOKEN": token, "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
        "firDate": date_str, "scaDate": date_str, "sqlMethod": "StockNo",
        "stockNo": code, "stockName": "", "method": "submit",
    })
    idx = html.find('table class="table"')
    if idx < 0:
        return {}
    end = html.find("</tbody>", idx)
    if end < 0:
        end = html.rfind("</table>")
    snippet = html[idx:end + 2000]
    cells = re.findall(r"<td[^>]*>([^<]*)</td>", snippet)
    rows = [cells[i:i + 5] for i in range(0, len(cells), 5)]
    out = {}
    for r in rows:
        if len(r) < 5:
            continue
        _, tier, hn, sh, pct = r
        tier = tier.strip()
        try:
            out[tier] = {"holders": int(hn.replace(",", "")), "shares": int(sh.replace(",", "")),
                         "pct": float(pct.replace(",", ""))}
        except ValueError:
            continue
    return out


def _load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def classify(pct_now, pct_prior, holders_now=None, holders_prior=None):
    """回 {level, signal, holder_pct_chg}。純數字判斷,不叫網路。"""
    if pct_prior is None:
        return {"level": "plain", "signal": "大戶持股比中性(無前期比較基準)", "holder_pct_chg": None}
    chg = pct_now - pct_prior
    note = ""
    if holders_now is not None and holders_prior is not None:
        h_chg = holders_now - holders_prior
        if h_chg < 0 and chg > 0:
            note = f",且戶數減少{abs(h_chg)}戶(籌碼更集中在更少大戶手中)"
    if chg >= 1.0:
        return {"level": "red", "signal": f"千張大戶持股比週增{chg:.2f}個百分點(大戶顯著加碼{note})",
                "holder_pct_chg": round(chg, 2)}
    if chg <= -1.0:
        return {"level": "yellow", "signal": f"千張大戶持股比週減{chg:.2f}個百分點(大戶出脫,籌碼鬆動)",
                "holder_pct_chg": round(chg, 2)}
    if chg >= 0.5:
        return {"level": "yellow", "signal": f"千張大戶持股比週增{chg:.2f}個百分點(溫和加碼{note})",
                "holder_pct_chg": round(chg, 2)}
    return {"level": "plain", "signal": f"千張大戶持股比週變動{chg:+.2f}個百分點(中性)",
            "holder_pct_chg": round(chg, 2)}


def holders(code, today=None):
    """回 dict:千張大戶持股比+週變動+訊號分級。抓不到回 None。"""
    today = today or datetime.date.today()
    cache = _load_cache()
    ck = f"{code}:{today.isoformat()}"
    if ck in cache:
        return cache[ck]

    cj1 = cj2 = None
    try:
        cj1 = tempfile.NamedTemporaryFile(prefix="tdcc_cj_", delete=False).name
        token, dates = _fetch_dates_and_token(cj1)
        if not token or not dates:
            return None
        tiers_now = _query_tiers(cj1, token, code, dates[0])
        big_now = tiers_now.get(BIG_TIER)
        if not big_now:
            return None

        pct_prior = holders_prior = None
        if len(dates) > 1:
            cj2 = tempfile.NamedTemporaryFile(prefix="tdcc_cj_", delete=False).name
            token2, _ = _fetch_dates_and_token(cj2)
            if token2:
                tiers_prior = _query_tiers(cj2, token2, code, dates[1])
                big_prior = tiers_prior.get(BIG_TIER)
                if big_prior:
                    pct_prior = big_prior["pct"]
                    holders_prior = big_prior["holders"]
    except Exception:
        return None
    finally:
        for cj in (cj1, cj2):
            if cj and os.path.exists(cj):
                try:
                    os.unlink(cj)
                except OSError:
                    pass

    out = {
        "date": dates[0],
        "prior_date": dates[1] if len(dates) > 1 else None,
        "big_holder_pct": big_now["pct"],
        "big_holder_count": big_now["holders"],
    }
    out.update(classify(big_now["pct"], pct_prior, big_now["holders"], holders_prior))

    cache = {k: v for k, v in cache.items() if k.endswith(today.isoformat())}
    cache[ck] = out
    _save_cache(cache)
    return out


def scan(codes, pause=0.3):
    """批次掃描,回 {code: holders_dict}。禮貌節流(TDCC 是政府機構網站,別狂打)。"""
    out = {}
    for c in codes:
        r = holders(c)
        if r:
            out[c] = r
        time.sleep(pause)
    return out


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "2330"
    print(json.dumps(holders(code), ensure_ascii=False, indent=1))
