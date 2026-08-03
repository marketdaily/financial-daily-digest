#!/usr/bin/env python3
"""
公版日報存檔頁(docs/output/digest_*.html)注入「免費訂閱」轉換入口(成長線 domain③)。

## 為什麼
GSC 逐頁流量帳本(capabilities/seo_page_traffic)顯示:全站流量最大的頁面群就是這批
公版存檔(近 7 日前 5 名全是 digest_*,單頁 3 天 232 visits),但整頁**沒有任何訂閱
入口**——唯一的 CTA 是「前往個人專區設定股票偏好」,那是對已訂閱者說的話。從搜尋進來
的陌生讀者讀完一整份免費產品後無處可訂 = 轉換漏斗最大的洞(151 uniques/日 vs 21 訂閱)。

## 邊界(刻意的)
- 只後製「已寫出的靜態檔案」docs/output/,**不碰 output/ 的 email 版、不碰 main.py 的
  render_email_shell**(email 寄送路徑有 golden byte-frozen 保護,且訂閱者不需要看到
  「訂閱」CTA)。與 scripts/site_structured_data.py 同一套解耦模式。
- 只 append 區塊,不刪改原內容 → build_track_record / tldr_extract 的解析輸出不變
  (有迴歸測試 scripts/test_archive_cta.py 鎖住)。
- `*_personal_*`(訂閱者持股個資)一律跳過:那些檔案不該公開,也不該有公開 CTA。

## 冪等
注入區塊包在具名 marker 之間;每次執行先剝掉舊區塊再重算,結果相同就不寫檔
(改文案後重跑會自動更新既有頁面,不需 force flag)。
⚠️ 冪等只在 marker 成對完整時成立:若某頁的 marker 被外力弄壞(docs/ 是 site_scan CI
允許 LLM 自動修改的目錄),孤兒 marker 會讓「剝舊區塊」比對不到而變成每跑一次疊一份、
或反過來吃掉正文。故注入前先 `marker_defect()` 成對掃描、寫檔前再驗一次 post-condition,
任一不成立即 fail-loud 走 exit 3 告警路徑,絕不靜默安定在錯誤固定點(2026-08-03 F3)。

## 並行/當機安全
寫檔走 tmp+os.replace 原子替換(避免行程被 kill 時磁碟留下 0 byte / 半截的公開頁,
下一輪 wrangler deploy 會把它推上線);tmp 落在 logs/tmp 而非 docs/,免得殘留檔案讓
docs-scoped cron 守門從此 abort。整支 run() 外層有 flock,手動執行與 cron 互斥
(2026-08-03 驗證者實測雙行程可讀到 0 byte,F5)。

## 歸因
CTA 連結帶 utm_source=digest_archive / utm_medium=public_archive /
utm_campaign=digest_<date>[_us] / utm_content=top|bottom,落地頁 index.html 既有的
beacon 會把 UTM 記進 attr:visit,轉換時 join 回來 → 這條管道的成效可被
capabilities/funnel_attribution 量測。
⚠️ stripe-webhook 的 normalizeSource ATTR_SOURCES 尚未含 "digest_archive",故
`/admin/analytics-summary` 的 by_source 會把它歸進 "other"(逐筆 attr:convert 記錄仍
保留原字串,分析工具讀得到)。要讓 admin 桶看得見需在下次 worker 部署時補該常數。

用法:
  python scripts/archive_cta.py --dry     # 預覽(印會改幾檔,不寫檔)
  python scripts/archive_cta.py           # 真寫入(冪等)
exit code: 0=全部成功 / 3=有檔案找不到注入錨點(已寫入其他檔,需告警) / 2=用法錯誤
"""
import argparse
import fcntl
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_OUTPUT = ROOT / "docs" / "output"
LOCK_PATH = ROOT / "logs" / "locks" / "archive_cta.lock"
TMP_DIR = ROOT / "logs" / "tmp"
BASE = "https://marketdaily.ai"

MARKER_START = "<!-- archive_cta:start -->"
MARKER_END = "<!-- archive_cta:end -->"
_BLOCK_RE = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n?", re.S)
_MARKER_TOKEN_RE = re.compile(re.escape(MARKER_START) + "|" + re.escape(MARKER_END))
_TOP_SIG = "這是 MarketDaily"
_BOTTOM_SIG = "免費訂閱明天的日報"

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Noto Sans TC','PingFang TC',sans-serif"
_FNAME_RE = re.compile(r"^digest_(\d{4}-\d{2}-\d{2})(_us)?\.html$")


def strip_existing_block(html: str) -> str:
    """移除先前執行留下的注入區塊,讓每次重跑都從『無本腳本痕跡』的乾淨狀態重算。"""
    return _BLOCK_RE.sub("", html)


def marker_defect(html: str):
    """成對掃描既有 marker;健康回 None,否則回損壞原因字串。

    非貪婪的 `START.*?END` 對「半毀」有兩種相反的災難:少一個 END 會讓 regex 從上方
    START 一路吃到下方 END(刪掉正文);少一個 START 會讓舊區塊比對不到而降級成普通
    內文永久留著、同時又插一份新的(該頁固定兩份 CTA 且文案永遠更新不到,全程零告警)。
    兩者都必須在 strip 之前擋下來——strip 完就分辨不出來了。
    """
    toks = _MARKER_TOKEN_RE.findall(html)
    if len(toks) % 2:
        return "marker_orphan"
    for i in range(0, len(toks), 2):
        if toks[i] != MARKER_START or toks[i + 1] != MARKER_END:
            return "marker_unpaired"
    return None


def parse_filename(name: str):
    """digest_2026-08-03[_us].html -> (date, is_us);不符合命名回傳 None。"""
    m = _FNAME_RE.match(name)
    if not m:
        return None
    return m.group(1), bool(m.group(2))


def cta_url(date: str, is_us: bool, slot: str) -> str:
    campaign = f"digest_{date}{'_us' if is_us else ''}"
    return (
        f"{BASE}/?utm_source=digest_archive&utm_medium=public_archive"
        f"&utm_campaign={campaign}&utm_content={slot}#email-step"
    )


def _top_block(date: str, is_us: bool) -> str:
    edition = "美股版" if is_us else "台股版"
    url = cta_url(date, is_us, "top")
    return (
        f'<div style="margin:0 12px 14px;background:#eef2ff;border:1px solid #e0e7ff;'
        f'border-radius:10px;padding:10px 14px;font-size:12px;line-height:1.8;color:#4338ca;'
        f'text-align:center;font-family:{_FONT};">'
        f'📬 這是 MarketDaily <b>{date} {edition}</b>日報的公開存檔 · 想每天自動收到嗎?&nbsp;'
        f'<a href="{url}" style="color:#4338ca;font-weight:800;text-decoration:underline;">免費訂閱 →</a>'
        f'</div>'
    )


def _bottom_block(date: str, is_us: bool) -> str:
    url = cta_url(date, is_us, "bottom")
    if is_us:
        headline = "每天晚上 8:00,美股日報直接寄到你信箱"
        watches = "你自己持有的美股"
    else:
        headline = "每天早上 7:00,台股日報直接寄到你信箱"
        watches = "你自己持有的台股與美股"
    # 視覺上刻意做成深色主面板:同一頁尾已有一個淺紫的「前往個人專區」區塊(那是對
    # 已訂閱者說的話),兩個等重 CTA 會讓陌生讀者不知道該點哪個。深底白字讓「免費訂閱」
    # 明確是主要行動(CRO:one clear primary action)。
    return (
        f'<div style="margin:22px 12px 8px;background:#312e81;border-radius:14px;'
        f'padding:26px 22px;text-align:center;font-family:{_FONT};">'
        f'<p style="font-size:18px;font-weight:800;color:#ffffff;margin:0 0 10px;line-height:1.55;">{headline}</p>'
        f'<p style="font-size:13px;color:#c7d2fe;line-height:1.9;margin:0 0 20px;">'
        f'你剛讀完的是公開存檔。訂閱後 AI 每天幫你盯<b style="color:#ffffff;">{watches}</b>——'
        f'多源查證、假訊息過濾,30 秒讀完。</p>'
        f'<a href="{url}" style="display:inline-block;background:#ffffff;color:#312e81;'
        f'font-size:15px;font-weight:800;padding:14px 34px;border-radius:10px;text-decoration:none;">'
        f'免費訂閱明天的日報 →</a>'
        f'<p style="font-size:11px;color:#a5b4fc;line-height:1.8;margin:16px 0 0;">'
        f'不需信用卡。目前全功能限時免費開放;未來恢復收費後,現在訂閱的早鳥用戶永久保留免費使用權。</p>'
        f'</div>'
    )


def _wrap(block: str) -> str:
    return MARKER_START + "\n" + block + "\n" + MARKER_END + "\n"


def inject(html: str, date: str, is_us: bool):
    """回傳 (new_html, reason)。reason=None 代表成功;否則是跳過原因(找不到錨點)。

    錨點:頁首橫幅插在**第一個** `<div class="header">` 之前(少數早期檔案內文嵌了
    第二份完整 HTML,故只認第一個);頁尾主 CTA 插在 `<div class="footer">` 之前。
    兩個錨點缺任一 → 不寫該檔並回報(fail-loud,不靜默略過)。
    """
    defect = marker_defect(html)
    if defect:
        return None, defect
    clean = strip_existing_block(html)
    i_header = clean.find('<div class="header">')
    i_footer = clean.rfind('<div class="footer">')
    if i_header < 0:
        return None, "no_header_anchor"
    if i_footer < 0:
        return None, "no_footer_anchor"
    if i_footer < i_header:
        return None, "anchor_order"

    bottom = _wrap(_bottom_block(date, is_us))
    out = clean[:i_footer] + bottom + clean[i_footer:]
    # 頁尾插入不會動到 header 位置(在它之後),故 header 索引仍有效
    top = _wrap(_top_block(date, is_us))
    out = out[:i_header] + top + out[i_header:]
    # post-condition:恰好一組頂+底區塊。任何非預期倍數(marker 殘留、頁面內嵌第二份
    # 已注入的 HTML)都寧可不寫檔並告警,不寫出無法再被冪等收斂的頁面。
    if (out.count(MARKER_START) != 2 or out.count(MARKER_END) != 2
            or out.count(_TOP_SIG) != 1 or out.count(_BOTTOM_SIG) != 1):
        return None, "marker_postcondition"
    return out, None


def archive_files(directory=None):
    """待處理的公版存檔頁。directory 可注入(自測用),預設 docs/output。

    雙層排除 `*_personal_*`(訂閱者持股個資):命名 regex 本身不接受,外加顯式條件——
    這種檔案就算誤入 docs/ 也絕不能被當公開頁處理(privacy_deploy_guard 是另一層)。
    """
    d = Path(directory) if directory else DOCS_OUTPUT
    if not d.is_dir():
        return []
    return sorted(
        p for p in d.glob("digest_*.html")
        if "_personal_" not in p.name and _FNAME_RE.match(p.name)
    )


def atomic_write(path: Path, text: str) -> None:
    """tmp + os.replace:公開頁永遠是「舊的完整版」或「新的完整版」,不會是半截。

    tmp 刻意落在 logs/tmp 而非 docs/ 旁邊——殘留檔若留在 docs/ 會被 wrangler 上傳,
    也會讓所有 docs-scoped cron 守門(cron_abort_if_untracked_scoped)從此 abort 餓死。
    同一個檔案系統故 os.replace 原子有效;跨裝置時退回直接寫(至少不比原本差)。
    """
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TMP_DIR / f"{path.name}.{os.getpid()}.tmp"
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        path.write_text(text, encoding="utf-8")


def run(dry: bool = False, verbose: bool = True, directory=None):
    changed, skipped, unchanged = [], [], 0
    for path in archive_files(directory):
        parsed = parse_filename(path.name)
        if not parsed:
            continue
        date, is_us = parsed
        # 一顆壞檔(非 UTF-8 位元組、迴圈中被刪、權限)不得炸掉整批:整支 traceback
        # 會讓排序在後的檔案全部不處理、前面的已寫入,而當日鎖已消耗=當天不會重試,
        # docs 樹髒著讓所有 docs-scoped runner 餓死。降級成單檔 skip → exit 3 告警。
        try:
            html = path.read_text(encoding="utf-8")
            out, reason = inject(html, date, is_us)
            if reason:
                skipped.append((path.name, reason))
                continue
            if out == html:
                unchanged += 1
                continue
            if not dry:
                atomic_write(path, out)
        except (OSError, UnicodeDecodeError) as e:
            skipped.append((path.name, f"io_error:{e.__class__.__name__}"))
            continue
        changed.append(path.name)
    if verbose:
        print(f"archive_cta: {'DRY ' if dry else ''}changed={len(changed)} "
              f"unchanged={unchanged} skipped={len(skipped)}")
        for name in changed[:5]:
            print(f"  + {name}")
        if len(changed) > 5:
            print(f"  + ...({len(changed) - 5} more)")
        for name, reason in skipped:
            print(f"  ! SKIPPED {name}: {reason}")
    return changed, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true", help="只預覽不寫檔")
    args = ap.parse_args()
    # 手動執行與 cron 互斥:cron_daily_lock 只涵蓋 cron 路徑,而模組說明鼓勵手動跑。
    # 拿不到鎖=另一個實例正在寫同一批檔,靜默讓路(它會做完同樣的事)。
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("archive_cta: 另一個實例正在執行,本次讓路")
            return 0
        _, skipped = run(dry=args.dry)
    return 3 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
