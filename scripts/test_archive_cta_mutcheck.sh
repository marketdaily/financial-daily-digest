#!/bin/bash
# 突變測試:證明 scripts/test_archive_cta.py 真的會變紅(不是裝飾品)。
# 每則突變在暫存副本上改壞 archive_cta.py 一處,測試必須 FAIL;沒咬到就報 MISSED。
# 用法:bash scripts/test_archive_cta_mutcheck.sh   (exit 0 = 全部咬到)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3
SRC="$REPO/scripts/archive_cta.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$SRC" "$WORK/orig.py"

MISSED=0
CAUGHT=0

mutate() {
  local name="$1" sed_expr="$2"
  cp "$WORK/orig.py" "$SRC"
  if ! sed -i "$sed_expr" "$SRC"; then echo "  !! sed 失敗:$name"; MISSED=$((MISSED+1)); return; fi
  if diff -q "$WORK/orig.py" "$SRC" >/dev/null; then
    echo "  !! 突變沒改到任何東西(pattern 過期):$name"; MISSED=$((MISSED+1)); return
  fi
  if "$PY" "$REPO/scripts/test_archive_cta.py" >/dev/null 2>&1; then
    echo "  MISSED  $name  ← 測試沒咬到"
    MISSED=$((MISSED+1))
  else
    echo "  caught  $name"
    CAUGHT=$((CAUGHT+1))
  fi
}

echo "archive_cta mutation check"
mutate "M1 不剝舊區塊(冪等/重算失效)"        's/    clean = strip_existing_block(html)/    clean = html/'
mutate "M2 頂部橫幅認最後一個 header"          "s/i_header = clean.find('<div class=\"header\">')/i_header = clean.rfind('<div class=\"header\">')/"
mutate "M3 CTA 連結不帶 utm_content"           's/&utm_content={slot}#email-step/#email-step/'
mutate "M4 美股版沿用台股版文案"               's/        headline = "每天晚上 8:00,美股日報直接寄到你信箱"/        headline = "每天早上 7:00,台股日報直接寄到你信箱"/'
mutate "M5 文案摻入捏造訂閱人數"               's/你剛讀完的是公開存檔。/已有 3000 位讀者訂閱。/'
mutate "M6 錨點缺失時靜默跳過而非回報原因"     's/        return None, "no_footer_anchor"/        return html, None/'
mutate "M7 personal 檔混進處理清單"            's/if "_personal_" not in p.name and _FNAME_RE.match(p.name)/if _FNAME_RE.match(p.name) or "_personal_" in p.name/'
mutate "M8 底部 CTA 插到 footer 之後"          's/out = clean\[:i_footer\] + bottom + clean\[i_footer:\]/out = clean + bottom/'

cp "$WORK/orig.py" "$SRC"
echo "caught=$CAUGHT missed=$MISSED"
if [ "$MISSED" -gt 0 ]; then echo "archive_cta mutations: MISSED $MISSED"; exit 1; fi
echo "archive_cta mutations: ALL CAUGHT"
