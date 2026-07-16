"""馬克羊「尾盤強制平倉」假說檢驗 — TX 趨勢日 13:30→13:44→13:45 路徑分析。

假說(2026-02 馬克羊×群益演講):大漲/大跌日尾盤最後 15 分鐘,不停損的當沖客被強制平倉
→ ①13:30 後順趨勢有「燃料」延續 ②13:44 出場優於抱到 13:45 收盤。

資料:期交所每日成交明細 zip(官網只留最近 30 交易日;winrig ~/taifex_archive/ 每日 18:20 cron 歸檔累積)。
設計:無前視 — 趨勢以「開盤→13:30」定義,再量測其後路徑。近月=當日成交量最大合約。

用法:python3 tail_exit_study.py --dir ~/taifex_archive [--out result.json]
初測(n=30, 2026-06~07 極端波動 regime):順勢延續勝率 56-58%、最後 1 分鐘順勢方向 -3~-8 點,
方向與假說一致但統計不足。正式裁決待 Shioaji 1 分 K(2026-07-21 起可用)跑 walk-forward 分年 OOS。
"""
import argparse
import glob
import json
import os
import re
import zipfile
from collections import defaultdict


def parse_day(zp):
    """一個 zip → (date_str, TX 日盤 ticks[(hhmmss, contract, price, vol)])"""
    m = re.search(r"Daily_(\d{4})_(\d{2})_(\d{2})", zp)
    if not m:
        return None, []
    dstr = "".join(m.groups())
    try:
        z = zipfile.ZipFile(zp)
        raw = z.read(z.namelist()[0]).decode("big5", "ignore")
    except Exception:
        return dstr, []
    ticks = []
    for line in raw.splitlines()[1:]:
        p = line.split(",")
        if len(p) < 6 or p[1].strip() != "TX" or p[0].strip() != dstr:
            continue
        c = p[2].strip()
        if "/" in c:  # 排除價差合約(如 202607/202608),否則低量日會被誤選為近月
            continue
        t = p[3].strip()
        if not ("084500" <= t <= "134500"):
            continue
        ticks.append((t, c, float(p[4]), int(p[5])))
    return dstr, ticks


def day_metrics(ticks):
    vol = defaultdict(int)
    for _, c, _, v in ticks:
        vol[c] += v
    front = max(vol, key=vol.get)
    ft = sorted(x for x in ticks if x[1] == front)

    def px_at(hms):
        last = None
        for t, _, pr, _ in ft:
            if t <= hms:
                last = pr
            else:
                break
        return last

    o, p1330, p1344, p1345 = ft[0][2], px_at("133000"), px_at("134400"), ft[-1][2]
    if None in (o, p1330, p1344):
        return None
    return dict(front=front, open=o, p1330=p1330, p1344=p1344, p1345=p1345,
                trend=round(p1330 - o, 1),
                cont_1330_1344=round(p1344 - p1330, 1),
                last_min_1344_1345=round(p1345 - p1344, 1))


def summarize(rs, th):
    sel = [r for r in rs if abs(r["trend"]) >= th]
    out = dict(threshold=th, n=len(sel))
    if sel:
        sgn = lambda r: 1 if r["trend"] > 0 else -1
        cont = [sgn(r) * r["cont_1330_1344"] for r in sel]
        lastm = [sgn(r) * r["last_min_1344_1345"] for r in sel]
        out["cont_mean"] = round(sum(cont) / len(cont), 1)
        out["cont_win"] = round(sum(1 for x in cont if x > 0) / len(cont), 2)
        out["lastmin_mean"] = round(sum(lastm) / len(lastm), 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/taifex_archive"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    results = []
    for zp in sorted(glob.glob(os.path.join(args.dir, "Daily_*.zip"))):
        dstr, ticks = parse_day(zp)
        if not ticks:
            continue
        m = day_metrics(ticks)
        if m:
            m["date"] = dstr
            results.append(m)

    summary = dict(n_days=len(results),
                   thresholds=[summarize(results, th) for th in (150, 250, 400)],
                   all_days=results)
    print(json.dumps({k: v for k, v in summary.items() if k != "all_days"},
                     ensure_ascii=False, indent=1))
    if args.out:
        json.dump(summary, open(args.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
