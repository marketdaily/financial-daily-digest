#!/bin/bash
# 突變測試:證明 scripts/test_archive_cta.py 真的會變紅(不是裝飾品)。
# 每則突變在**沙盒副本**上改壞 archive_cta.py 一處,測試必須 FAIL;沒咬到就報 MISSED。
# 用法:bash scripts/test_archive_cta_mutcheck.sh   (exit 0 = 全部咬到)
#
# ⚠️ 2026-08-03 驗證者 F1:舊版直接把突變寫回 repo 內的**生產中那支** archive_cta.py,
# 中斷(Ctrl-C/SIGTERM/OOM/重開機)就會在 repo 留下被改壞的版本,而唯一備份住在
# trap 會刪掉的暫存目錄裡;隔天 07:20 的 cron 只對 docs 做 scoped 髒檔守門,看不到
# scripts/ 髒掉 → 直接拿突變版跑 84 篇公開頁再 deploy(M5 那格=把捏造訂閱人數發上線)。
# 現在整份測試素材複製進沙盒 repo,突變只發生在沙盒;真檔全程唯讀,收尾以 md5 對帳。
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3
SRC="$REPO/scripts/archive_cta.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# INT/TERM 若只清暫存不離開,bash 會回到迴圈繼續跑「素材已被刪掉」的後續突變,刷出一整排
# 假 MISSED;中斷就該當場結束(真檔本來就沒被碰過)。
trap 'rm -rf "$WORK"; echo "archive_cta mutations: 中斷(生產檔未被碰過)"; exit 130' INT TERM

SRC_MD5_BEFORE="$(md5sum "$SRC" | awk '{print $1}')"

# --- 建沙盒 repo:test_archive_cta.py 以自身位置推出 ROOT,故只要目錄結構對就能跑 ---
SANDBOX="$WORK/repo"
mkdir -p "$SANDBOX/scripts" "$SANDBOX/marketing" "$SANDBOX/docs/output"
cp "$SRC" "$SANDBOX/scripts/archive_cta.py"
cp "$REPO/scripts/test_archive_cta.py" "$SANDBOX/scripts/"
cp "$REPO/scripts/build_track_record.py" "$SANDBOX/scripts/"
cp "$REPO/marketing/tldr_extract.py" "$SANDBOX/marketing/"
# 下游迴歸測試只取最後 3 篇非 personal 存檔頁,複製同一批即可(真檔內容,不是合成 fixture)
for f in $(ls "$REPO"/docs/output/digest_*.html 2>/dev/null | grep -v _personal_ | tail -3); do
  cp "$f" "$SANDBOX/docs/output/"
done
cp "$SANDBOX/scripts/archive_cta.py" "$WORK/orig.py"
MUT_SRC="$SANDBOX/scripts/archive_cta.py"
MUT_TEST="$SANDBOX/scripts/test_archive_cta.py"

# --- baseline:沙盒未突變時測試必須 PASS ---
# 沙盒素材缺一件(少複製一個依賴、docs/output 空)會讓測試恆紅 → 每則突變都「caught」,
# 一份什麼都證明不了的假綠。基準線先確認沙盒是活的,才有資格判定突變被咬到。
if ! "$PY" "$MUT_TEST" >"$WORK/baseline.log" 2>&1; then
  echo "!! 沙盒基準線失敗:未突變的副本測試就不過,突變結果無意義"
  tail -20 "$WORK/baseline.log"
  exit 1
fi

MISSED=0
CAUGHT=0

mutate() {
  local name="$1" sed_expr="$2"
  cp "$WORK/orig.py" "$MUT_SRC"
  if ! sed -i "$sed_expr" "$MUT_SRC"; then echo "  !! sed 失敗:$name"; MISSED=$((MISSED+1)); return; fi
  if diff -q "$WORK/orig.py" "$MUT_SRC" >/dev/null; then
    echo "  !! 突變沒改到任何東西(pattern 過期):$name"; MISSED=$((MISSED+1)); return
  fi
  if "$PY" "$MUT_TEST" >/dev/null 2>&1; then
    echo "  MISSED  $name  ← 測試沒咬到"
    MISSED=$((MISSED+1))
  else
    echo "  caught  $name"
    CAUGHT=$((CAUGHT+1))
  fi
}

echo "archive_cta mutation check (sandbox: $SANDBOX)"
mutate "M1 不剝舊區塊(冪等/重算失效)"        's/    clean = strip_existing_block(html)/    clean = html/'
mutate "M2 頂部橫幅認最後一個 header"          "s/i_header = clean.find('<div class=\"header\">')/i_header = clean.rfind('<div class=\"header\">')/"
mutate "M3 CTA 連結不帶 utm_content"           's/&utm_content={slot}#email-step/#email-step/'
mutate "M4 美股版沿用台股版文案"               's/        headline = "每天晚上 8:00,美股日報直接寄到你信箱"/        headline = "每天早上 7:00,台股日報直接寄到你信箱"/'
mutate "M5 文案摻入捏造訂閱人數"               's/你剛讀完的是公開存檔。/已有 3000 位讀者訂閱。/'
mutate "M6 錨點缺失時靜默跳過而非回報原因"     's/        return None, "no_footer_anchor"/        return html, None/'
mutate "M7 personal 檔混進處理清單"            's/if "_personal_" not in p.name and _FNAME_RE.match(p.name)/if _FNAME_RE.match(p.name) or "_personal_" in p.name/'
mutate "M8 底部 CTA 插到 footer 之後"          's/out = clean\[:i_footer\] + bottom + clean\[i_footer:\]/out = clean + bottom/'
mutate "M9 marker 半毀不擋(靜默安定在錯誤固定點)" 's/^    defect = marker_defect(html)/    defect = None/'
mutate "M10 寫檔改回非原子(截斷視窗)"         's/^        os.replace(tmp, path)$/        path.write_text(text, encoding="utf-8")/'
mutate "M11 單檔例外炸整批"                    's/        except (OSError, UnicodeDecodeError) as e:/        except SystemExit as e:/'

echo "caught=$CAUGHT missed=$MISSED"

# --- 收尾對帳:真檔全程沒被碰過(F1 的迴歸守衛,不是裝飾) ---
SRC_MD5_AFTER="$(md5sum "$SRC" | awk '{print $1}')"
if [ "$SRC_MD5_BEFORE" != "$SRC_MD5_AFTER" ]; then
  echo "!! 生產檔 $SRC 在突變測試期間被改動($SRC_MD5_BEFORE -> $SRC_MD5_AFTER)——沙盒隔離破功"
  exit 1
fi

if [ "$MISSED" -gt 0 ]; then echo "archive_cta mutations: MISSED $MISSED"; exit 1; fi
echo "archive_cta mutations: ALL CAUGHT (生產檔 md5 未變)"
