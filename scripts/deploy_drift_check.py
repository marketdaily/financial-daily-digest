#!/usr/bin/env python3
"""線上站台 vs 本機 repo 的「部署回捲」偵測器(2026-08-11 事故當場建立)。

## 為什麼(事故)
2026-08-10 08:20 TW site_scan 還是 21/21 全綠;2026-08-11 03:0x 之後,marketdaily.ai 的
production 部署被換成一份 **2026-07-22 時代的 docs/ 快照** —— 07-23 起的全部公版存檔頁
(約 30 頁,全站流量最大的頁面群)線上 404、manifest.json 退回 07-22、blog 索引從 59 篇
退回 44 篇。repo 完全正常,壞的只有「線上正在服務的那份」。

觸發者最可能是**從錯的工作目錄下的一次 `wrangler pages deploy docs`**:winrig 上有多個
worktree(例:`~/paper_trade` 是 quant 分支的 worktree,它的 docs/output 正好停在 07-22),
外加 10 支會 deploy docs 的 cron 與多個並行視窗 —— 任何一次 cd 錯地方都會把整站回捲,
**而且 git 與 CI 全部無感**(repo 是對的,錯的只有雲端那份)。

## 這支解的到底是什麼
既有的 site_scan `digest_archive_fresh` 抓得到這件事,但它一天只跑一次(08:20-08:49 窗口);
本次回捲發生在 03:00,若沒人剛好在看,線上會壞到隔天早上才被發現。這支把「線上是不是比
repo 舊」變成 30 分鐘一次的獨立守衛,判準只有一個方向:**線上落後 repo = 紅**
(線上比 repo 新不算紅,那是別台機器剛部署的正常狀態)。

## 訊號(三個,都是確定性的、零 API 金鑰)
1. manifest_max_date  線上 /output/manifest.json 的最新日期 < 本機的 → 回捲
2. blog_article_count 線上 /blog/index.html 的「N 篇免費開放」< 本機的 → 回捲
3. newest_archive_200 本機最新一篇存檔頁的線上乾淨 URL 必須 200(.html 會 308 導向)

## 新鮮度寬限
剛產出、還沒輪到部署窗口的檔案不算回捲:本機檔案 mtime 比 --grace-min(預設 60)分鐘還新的
訊號一律跳過。這是「部署延遲」與「部署回捲」的分界線,沒有它會每天早上假紅一次。

用法: python3 scripts/deploy_drift_check.py [--json] [--grace-min 60] [--base https://marketdaily.ai]
exit: 0=線上與 repo 一致(或差異在寬限內) / 1=線上落後 repo(回捲) / 2=執行失敗(網路/解析)
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch(url, tries=3):
    """回 (status, body_text)。連不上就丟 RuntimeError(由呼叫端變成 exit 2,絕不當成綠燈)。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("取不到 %s: %s" % (url, last))


def _age_min(p):
    return (time.time() - p.stat().st_mtime) / 60.0


class WorktreeSource:
    """比較基準=winrig 磁碟現狀(預設,原始行為)。"""

    name = "worktree"

    def read(self, rel):
        p = DOCS / rel
        return p.read_text(encoding="utf-8"), _age_min(p)

    def newest_archive(self):
        best = None
        for f in (DOCS / "output").glob("digest_*.html"):
            if "_personal_" in f.name:
                continue
            if best is None or f.stem > best.stem:
                best = f
        if best is None:
            return None, None
        return best.stem, _age_min(best)


class OriginSource:
    """比較基準=origin/main 上的 docs/(自癒用)。

    自癒腿(GitHub Actions)部署的是 origin/main,不是磁碟現狀——判斷「部署有沒有用」
    必須拿它真的發得出去的那份來比,否則會拿別視窗還沒 push 的草稿當作「線上落後」,
    自癒發完還是紅、每 30 分鐘白跑一次。
    年齡一律取 origin/main 的 commit 時間(剛 push 完還沒輪到部署≠回捲)。
    """

    name = "origin"

    def __init__(self, ref="origin/main"):
        import subprocess
        self._sp = subprocess
        self.ref = ref
        ts = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%ct", ref],
                            capture_output=True, text=True, check=True).stdout.strip()
        self._age = (time.time() - int(ts)) / 60.0

    def _show(self, rel):
        r = self._sp.run(["git", "-C", str(ROOT), "show", "%s:docs/%s" % (self.ref, rel)],
                         capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("%s 沒有 docs/%s" % (self.ref, rel))
        return r.stdout

    def read(self, rel):
        return self._show(rel), self._age

    def newest_archive(self):
        r = self._sp.run(["git", "-C", str(ROOT), "ls-tree", "--name-only",
                          "%s:docs/output" % self.ref], capture_output=True, text=True, check=True)
        best = None
        for n in r.stdout.splitlines():
            if not n.startswith("digest_") or not n.endswith(".html") or "_personal_" in n:
                continue
            stem = n[:-5]
            if best is None or stem > best:
                best = stem
        return best, (self._age if best else None)


def run(base, grace_min, src=None):
    src = src or WorktreeSource()
    signals = []

    def _manifest_max():
        text, age = src.read("output/manifest.json")
        dates = json.loads(text).get("dates") or []
        return (max(dates) if dates else None), age

    def _blog_count():
        text, age = src.read("blog/index.html")
        m = re.search(r"(\d+)\s*篇免費開放", text)
        return (int(m.group(1)) if m else None), age

    lmax, age = _manifest_max()
    st, body = fetch(base + "/output/manifest.json?cb=%d" % int(time.time()))
    live_max = None
    if st == 200:
        try:
            dd = json.loads(body).get("dates") or []
            live_max = max(dd) if dd else None
        except ValueError:
            live_max = None
    signals.append({
        "name": "manifest_max_date", "local": lmax, "live": live_max,
        "skipped": age < grace_min,
        "ok": (live_max is not None and lmax is not None and live_max >= lmax),
        "detail": "線上 manifest 最新日 %s vs 本機 %s(HTTP %s)" % (live_max, lmax, st),
    })

    lcnt, age = _blog_count()
    st, body = fetch(base + "/blog/index.html?cb=%d" % int(time.time()))
    m = re.search(r"(\d+)\s*篇免費開放", body or "")
    live_cnt = int(m.group(1)) if m else None
    signals.append({
        "name": "blog_article_count", "local": lcnt, "live": live_cnt,
        "skipped": age < grace_min,
        "ok": (live_cnt is not None and lcnt is not None and live_cnt >= lcnt),
        "detail": "線上 blog 索引 %s 篇 vs 本機 %s 篇(HTTP %s)" % (live_cnt, lcnt, st),
    })

    newest, n_age = src.newest_archive()
    if newest is None:
        signals.append({"name": "newest_archive_200", "local": None, "live": None,
                        "skipped": False, "ok": False,
                        "detail": "%s docs/output 找不到任何存檔頁(應有 90+ 篇)" % src.name})
    else:
        # .html 會 308 導到乾淨 URL,直接查乾淨 URL 才是使用者/爬蟲真的拿到的東西
        st, _ = fetch("%s/output/%s?cb=%d" % (base, newest, int(time.time())))
        signals.append({
            "name": "newest_archive_200", "local": newest, "live": st,
            "skipped": n_age < grace_min, "ok": st == 200,
            "detail": "線上 /output/%s → HTTP %s" % (newest, st),
        })

    drift = [s for s in signals if not s["ok"] and not s["skipped"]]
    return signals, drift


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://marketdaily.ai")
    ap.add_argument("--grace-min", type=float, default=60.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--source", choices=("worktree", "origin"), default="worktree",
                    help="比較基準:worktree=磁碟現狀(預設) / origin=origin/main(自癒腿發得出去的那份)")
    a = ap.parse_args(argv)
    try:
        src = OriginSource() if a.source == "origin" else WorktreeSource()
        signals, drift = run(a.base.rstrip("/"), a.grace_min, src)
    except Exception as e:  # noqa: BLE001
        print("deploy_drift_check 執行失敗(不等於沒問題):%s: %s" % (type(e).__name__, e),
              file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"drift": len(drift), "signals": signals},
                        ensure_ascii=False, indent=2))
    else:
        for s in signals:
            mark = "⏭" if s["skipped"] else ("✅" if s["ok"] else "🔴")
            print("%s [%s] %s" % (mark, s["name"], s["detail"]))
    if drift:
        print("🔴 線上站台落後%s(部署回捲):%s"
              % ("本機 repo" if a.source == "worktree" else "origin/main",
                 "、".join(s["name"] for s in drift)), file=sys.stderr)
        print("   修法①(本機腿):cd ~/Delvin-agent && npx wrangler pages deploy docs "
              "--project-name marketdaily --commit-dirty=true", file=sys.stderr)
        print("   修法②(備援腿,本機 wrangler OAuth 死掉時用,發的是 origin/main):"
              "bash scripts/deploy_docs_via_actions.sh \"手動補部署\"", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
