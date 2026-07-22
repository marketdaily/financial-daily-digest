"""FinMind token 健康偵測(cron 每日 08:10)——token 失效機器先發現,別等連接器群靜默退回匿名被 IP ban 才察覺。

判定:
  200 success        → OK,記 log 一行
  402(額度用完)     → log only(瞬時性;token 額度 600/hr,批次撞牆屬正常波動)
  其他(no user/驗證失敗/403…)→ token 失效級,admin web push(每日至多一次)
token 存兩處:~/Delvin-agent/.env(單一真源)+ crontab 頂部環境變數(cron 全 job 生效)。
旋轉時兩處都要換——本檢查同時比對兩處一致性,漂移即告警。
"""
import datetime
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STATE_DIR = os.path.expanduser("~/.marketdaily-fallback/state")
sys.path.insert(0, HERE)


def _env_value(key):
    try:
        for line in open(os.path.join(REPO, ".env"), encoding="utf-8"):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _crontab_token():
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if line.startswith("FINMIND_TOKEN="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _alert(msg):
    day = datetime.date.today().isoformat()
    flag = os.path.join(STATE_DIR, f"finmind_alert_{day}")
    if os.path.exists(flag):
        print(f"(已告警過,跳過){msg}")
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    os.environ.setdefault("MARKETDAILY_ALERT_TOKEN", _env_value("MARKETDAILY_ALERT_TOKEN"))
    try:
        import notify_line
        if notify_line.push(f"⚠️ FinMind token 異常\n{msg}"):
            open(flag, "w").close()
    except Exception as e:
        print(f"推播失敗:{type(e).__name__}: {e}")
    print(msg)


def main():
    tok = _env_value("FINMIND_TOKEN")
    if not tok:
        return _alert(".env 裡沒有 FINMIND_TOKEN(被誰刪了?)")
    cron_tok = _crontab_token()
    if cron_tok and cron_tok != tok:
        return _alert("crontab 與 .env 的 FINMIND_TOKEN 不一致(旋轉只換了一處)")
    if not cron_tok:
        return _alert("crontab 頂部沒有 FINMIND_TOKEN 環境變數(cron 消費端全退回匿名)")
    start = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    url = (f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice"
           f"&data_id=2330&start_date={start}&token={tok}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        if e.code == 402:
            print(f"OK-ish:額度用完(402,瞬時性,不告警){body}")
            return
        return _alert(f"HTTP {e.code}:{body}")
    except Exception as e:
        print(f"網路例外(不告警,下次 cron 再試):{type(e).__name__}: {e}")
        return
    if d.get("status") == 200 and d.get("msg") == "success":
        print(f"OK:token 有效,取回 {len(d.get('data', []))} 筆")
    elif d.get("status") == 402:
        print(f"OK-ish:額度用完(402,瞬時性,不告警)")
    else:
        _alert(f"API 回異常:status={d.get('status')} msg={d.get('msg')}")


if __name__ == "__main__":
    main()
