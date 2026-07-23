"""魚C 盤中即時執行(winrig cron 平日 08:40 啟動,13:46 自動收工)。
每 60 秒拉當日 1 分 K → 即時判斷 OR30 突破/停損/尾盤出場 → 虛擬成交入共用帳本。
期貨戶開通後把 _virtual_fill 換成 place_order 即為真單;現在=完整鏈路演練。
晚間 paper_daily 重播看到今日已有 C 紀錄會自動跳過(live 主、重播備援)。
用法:python3 live_intraday.py
"""
import os
import time
import datetime

import tx_data
from paper_daily import (load_state, realize, halted, write_report, log_ev,
                         c_gates, pick_mode, c_done_today, STATE, PDIR, COST_B)
import json

SLIP = 0.5           # 虛擬成交滑價(點)
POLL_S = 60
LOG = os.path.join(PDIR, "live_log.txt")


def note(msg):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    os.makedirs(PDIR, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def day_bars(api, r1, today):
    """今日日盤 1分K → [(hm,o,h,l,c)](Shioaji ts=牆鐘當epoch+結束標籤)。"""
    kb = api.kbars(r1, start=today, end=today)
    out = []
    for ts, o, h, l, c in zip(kb.ts, kb.Open, kb.High, kb.Low, kb.Close):
        t = datetime.datetime.utcfromtimestamp(int(ts) / 1e9)
        hm = t.strftime("%H:%M")
        if "08:46" <= hm <= "13:45":
            out.append((hm, o, h, l, c))
    return out


def main():
    today = datetime.date.today().isoformat()
    if datetime.date.today().weekday() >= 5:
        note("週末,收工")
        return
    st = load_state()
    bars = tx_data.load("2020-01-01")            # 用昨晚快取即可(閘門只需到昨日)
    if c_done_today(today):
        note("今日已有魚C紀錄,收工")
        return
    g, vol_ok = c_gates(bars)
    stop_all, dd = halted(st)
    fish, fdir = pick_mode(bars)
    note(f"閘門:方向={g} 波動OK={vol_ok} 煞車={stop_all}(回撤{dd:.1%}) → "
         + ("觀望" if (fish is None or stop_all) else f"魚{fish}({'順勢突破' if fish=='C' else 'fade反手'})"))
    if fish is None or stop_all:
        note("今日不進場,收工")
        return

    from shioaji_adapter import login_env
    api = login_env()
    time.sleep(4)
    r1 = api.Contracts.Futures.TXF["TXFR1"]
    note(f"上線;近月 {r1.code} 參考 {r1.reference}")

    orh = orl = None
    pos, entry, stop, entry_hm = 0, 0.0, 0.0, ""
    seen = 0
    while True:
        now = datetime.datetime.now().strftime("%H:%M")
        if now >= "13:46":
            break
        try:
            rows = day_bars(api, r1, today)
        except Exception as e:
            note(f"拉K失敗(續跑):{e}")
            time.sleep(POLL_S)
            continue
        if now >= "09:20" and len(rows) < 5:
            note("09:20 仍無K線=休市,收工")
            api.logout()
            return
        if orh is None and len(rows) >= 30:
            orh = max(x[2] for x in rows[:30])
            orl = min(x[3] for x in rows[:30])
            note(f"OR30 定型:{orl:.0f} ~ {orh:.0f}")
        if orh is not None:
            for hm, o, h, l, c in rows[max(seen, 30):]:
                if pos == 0:
                    if hm >= "13:30":
                        break
                    if fish == "C":
                        if fdir > 0 and c > orh:
                            pos, entry, stop, entry_hm = 1, c + SLIP, orl, hm
                        elif fdir < 0 and c < orl:
                            pos, entry, stop, entry_hm = -1, c - SLIP, orh, hm
                    else:  # E fade:突破反手
                        if c > orh:
                            pos, entry, stop, entry_hm = -1, c - SLIP, orh + 30, hm
                        elif c < orl:
                            pos, entry, stop, entry_hm = 1, c + SLIP, orl - 30, hm
                    if pos:
                        note(f"⚡ 魚{fish} 進場 {'多' if pos>0 else '空'} @{entry:.0f}(bar {hm})停損 {stop:.0f}")
                elif (pos > 0 and l <= stop) or (pos < 0 and h >= stop):
                    pnl = pos * (stop - entry) - COST_B
                    realize(st, fish, pnl, {"fish": fish, "type": "trade", "mode": "live",
                            "date": today, "side": pos, "entry": entry, "exit": stop,
                            "entry_hm": entry_hm, "exit_hm": hm, "reason": "stop"})
                    with open(STATE, "w", encoding="utf-8") as f:
                        json.dump(st, f, ensure_ascii=False, default=str)
                    note(f"🛑 停損出場 @{stop:.0f} pnl {pnl:+.1f} 點,收工")
                    write_report()
                    api.logout()
                    return
                elif hm >= "13:44":
                    pnl = pos * (c - entry) - COST_B
                    realize(st, fish, pnl, {"fish": fish, "type": "trade", "mode": "live",
                            "date": today, "side": pos, "entry": entry, "exit": c,
                            "entry_hm": entry_hm, "exit_hm": hm, "reason": "eod"})
                    with open(STATE, "w", encoding="utf-8") as f:
                        json.dump(st, f, ensure_ascii=False, default=str)
                    note(f"🏁 尾盤出場 @{c:.0f} pnl {pnl:+.1f} 點,收工")
                    write_report()
                    api.logout()
                    return
            seen = len(rows)
        time.sleep(POLL_S)
    note(f"13:46 收工(進場={pos != 0} 或全日無訊號)")
    api.logout()
    write_report()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        note(f"live_intraday 異常結束:{type(e).__name__} {e}")
