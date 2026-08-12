#!/usr/bin/env python3
"""「該不該用備援腿把 origin/main 發出去」的裁決器(2026-08-12)。

deploy_drift_check.py 只回答「線上有沒有落後」。自癒還要多回答兩件事,而這兩件事
搞錯的代價是相反方向的:
  · 發了沒用 —— origin 也沒有比較新(內容還沒 push),每 30 分鐘白跑一次 CI。
  · 發了有害 —— 線上某項比 origin 新(那份是別處部署的,例如別視窗剛用磁碟現狀發過),
    把 origin 蓋上去 = 自己製造一次 2026-08-11 那種「部署回捲」事故。守衛變成事故來源
    是這台機器踩過最貴的一類坑,所以這裡 **fail-closed**:只要任一訊號顯示線上比 origin 新,
    一律不發。

輸出(單行,給 bash case 用):
  HEAL <newest_archive_stem> <落後的訊號名,頓號分隔>   該發
  REGRESS <說明>                                       不准發(會把線上弄舊)
  NOGAIN                                               不用發(origin 沒比線上新)
  ERROR <說明>                                         判不出來(不發,但要看得見)
exit code 一律 0——裁決寫在 stdout,不用 exit code 表達,避免呼叫端把 ERROR 當成 HEAL。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_drift_check as d  # noqa: E402


def verdict(signals):
    heal = [s["name"] for s in signals if not s["ok"] and not s["skipped"]]
    regress = []
    for s in signals:
        lo, li = s.get("local"), s.get("live")
        if s["name"] == "manifest_max_date" and lo and li and li > lo:
            regress.append("manifest(線上 %s > origin %s)" % (li, lo))
        elif s["name"] == "blog_article_count" and lo and li and li > lo:
            regress.append("blog(線上 %s 篇 > origin %s 篇)" % (li, lo))
    if regress:
        return "REGRESS " + "、".join(regress)
    if not heal:
        return "NOGAIN"
    newest = next((s["local"] for s in signals if s["name"] == "newest_archive_200"), None)
    return "HEAL %s %s" % (newest or "-", "、".join(heal))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://marketdaily.ai")
    ap.add_argument("--grace-min", type=float, default=60.0)
    ap.add_argument("--ref", default="origin/main")
    a = ap.parse_args(argv)
    try:
        signals, _ = d.run(a.base.rstrip("/"), a.grace_min, d.OriginSource(a.ref))
    except Exception as e:  # noqa: BLE001
        print("ERROR %s: %s" % (type(e).__name__, e))
        return 0
    print(verdict(signals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
