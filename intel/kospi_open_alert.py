#!/usr/bin/env python3
"""08:15 韓股開盤預警掃描器 — 外盤重挫閘 phase 2(2026-07-21)。

KOSPI 09:00 KST(=08:00 TW)開盤,比台股早一小時。開盤 gap <= -2%(預先登記門檻)
→ 打 alert-worker /internal/market-open-alert 推全體「今日高危,開盤別搶進」。
回測 16.5 年見 quant_lab/crash_gate_night/GLOBAL_LEAD.md:gap<=-2% 共 64 天,
台股當日均 -2.21%、95% 收黑、P(<=-3%)=29.7%;其中日報閘門沒警告到的日子 ~1.1 次/年。

cron 08:05 TW 平日觸發,內部輪詢到 08:25 等 Yahoo 出今日 K 棒(開盤競價一出就有)。
fail-silent:任何資料異常只 log 不推,絕不推錯誤數字;worker 端另有 -2% 二次強制+按日去重。

用法:
  python3 -m intel.kospi_open_alert           # 正式(cron 用)
  python3 -m intel.kospi_open_alert --dry     # 演練:真實 gap 但 worker 只推 admin
  python3 -m intel.kospi_open_alert --test    # 端到端測試:假 gap -2.5% + dry
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev"
THRESHOLD = -2.0
DEADLINE_HOUR, DEADLINE_MIN = 8, 25


def log(msg):
    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def _token():
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("MARKETDAILY_ALERT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def tw_is_holiday(today):
    """TWSE 休市日查詢(fail-open:查不到就當開市——韓股崩+台股恰休市的誤推代價極低)。"""
    try:
        req = urllib.request.Request(
            "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        rows = json.loads(urllib.request.urlopen(req, timeout=10).read())
        for r in rows:
            d = str(r.get("Date", ""))
            # ROC 格式 1150721 或 115/07/21
            digits = "".join(c for c in d if c.isdigit())
            if len(digits) == 7:
                y, m, dd = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7])
                if (y, m, dd) == (today.year, today.month, today.day):
                    return True
    except Exception as e:
        log(f"TWSE 休市表查詢失敗(fail-open 當開市): {e}")
    return False


def kospi_open_gap(today):
    """Yahoo ^KS11 日線:今日 open vs 前一交易日 close。今日 K 棒還沒出回 None(外層輪詢)。"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EKS11?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    bars = [(datetime.fromtimestamp(t, tz=timezone(timedelta(hours=9))).date(), o, c)
            for t, o, c in zip(d["timestamp"], q["open"], q["close"]) if o or c]
    if len(bars) < 2 or bars[-1][0] != today:
        return None
    open_today, prev_close = bars[-1][1], bars[-2][2]
    if not open_today or not prev_close or prev_close <= 0:
        return None
    gap = (open_today / prev_close - 1) * 100
    if abs(gap) > 15:
        log(f"gap {gap:+.2f}% 超出合理範圍,視為髒資料丟棄")
        return None
    return round(gap, 2), round(open_today, 2), round(prev_close, 2)


def push(gap, today, dry):
    tok = _token()
    if not tok:
        log("缺 MARKETDAILY_ALERT_TOKEN,中止")
        return False
    body = json.dumps({"id": f"kospi-open-{today.isoformat()}",
                       "gap_pct": gap, "dry": dry}).encode()
    req = urllib.request.Request(
        f"{WORKER}/internal/market-open-alert", data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                 "User-Agent": "kospi-open-alert/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read().decode())
    log(f"worker 回應: {res}")
    return bool(res.get("ok"))


def main():
    dry = "--dry" in sys.argv
    test = "--test" in sys.argv
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    today = now.date()

    if test:
        log("端到端測試:假 gap -2.5%(dry,只推 admin)")
        push(-2.5, today, dry=True)
        return

    if now.weekday() >= 5:
        log("週末,跳過")
        return
    if tw_is_holiday(today):
        log("台股休市日,跳過")
        return

    deadline = now.replace(hour=DEADLINE_HOUR, minute=DEADLINE_MIN)
    result = None
    while True:
        try:
            result = kospi_open_gap(today)
        except Exception as e:
            log(f"KOSPI 抓取失敗: {e}")
        if result is not None:
            break
        if datetime.now(timezone.utc) + timedelta(hours=8) >= deadline:
            log("到 08:25 仍無今日 K 棒(韓股休市或資料源異常),放棄——fail-silent 不推")
            return
        time.sleep(90)

    gap, o, pc = result
    log(f"KOSPI 開盤 {o} vs 昨收 {pc} → gap {gap:+.2f}%(門檻 {THRESHOLD}%)")
    if gap <= THRESHOLD:
        push(gap, today, dry=dry)
    else:
        log("未達門檻,今日安靜")


if __name__ == "__main__":
    main()
