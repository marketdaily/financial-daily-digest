#!/usr/bin/env bash
# 每日日報媒體衍生產線:短影音(reel)+語音快報(audio)。
# extract → render → make_post(驗證+上傳+post json) → 音頻(旁白稿→TTS→驗證+上傳)。
# 窗口/每日鎖/通知由呼叫端 runner 負責(winrig: ~/.marketdaily-fallback/video_brief_runner.sh)。
# 失敗以 exit code 回報;影音互不阻斷(影片壞了音頻照出,反之亦然)。
# 用法:run_daily.sh      → 早上全套(台股 reel+台股音頻;reel 由 social runner 09:00 開盤前發)
#      run_daily.sh us   → 晚上全套(美股 reel+美股晚間音頻;reel 21:30 美股開盤前發)
#                          us-audio 為 2026-07-17 前的舊名,當別名收(當時晚場不產 reel)
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3

git pull --rebase --autostash --quiet 2>/dev/null || true
set -a; source .env 2>/dev/null || true; set +a

if [ "${1:-}" = "us" ] || [ "${1:-}" = "us-audio" ]; then
  TWDATE=$(TZ=Asia/Taipei date +%Y-%m-%d)
  "$PY" video_brief/extract.py "$TWDATE" us || exit 10
  RC=0
  "$PY" audio_brief/build_script.py "video_brief/out/brief_${TWDATE}_us.json" || RC=13
  [ "$RC" = 0 ] && { "$PY" audio_brief/tts.py "audio_brief/out/narration_${TWDATE}_us.txt" || RC=14; }
  [ "$RC" = 0 ] && { "$PY" audio_brief/personal.py "$TWDATE" us || RC=15; }
  # 美股 reel(2026-07-17 起):與音頻互不阻斷;social_post_runner 20:30-21:29 窗口發
  REEL_RC=0
  "$PY" video_brief/render.py "video_brief/out/brief_${TWDATE}_us.json" || REEL_RC=11
  [ "$REEL_RC" = 0 ] && { "$PY" video_brief/make_post.py "video_brief/out/brief_${TWDATE}_us.json" || REEL_RC=12; }
  [ "$RC" = 0 ] && RC=$REEL_RC
  echo "run_daily us done rc=$RC"
  exit "$RC"
fi

RC=0
"$PY" video_brief/extract.py || exit 10

# 語音先行(公版+個人):postcheck 07:45 窗口要驗到個人音檔;reel 發文窗 08:00 起,緊接在後。
# 週末只產 reel(週末盤點版):語音快報的旁白稿/TTS 是平日格式,週末不做
TWU=$((10#$(TZ=Asia/Taipei date +%u)))
if [ "$TWU" -lt 6 ]; then
  TWDATE=$(TZ=Asia/Taipei date +%Y-%m-%d)
  "$PY" audio_brief/build_script.py || RC=$((RC == 0 ? 13 : RC))
  "$PY" audio_brief/tts.py          || RC=$((RC == 0 ? 14 : RC))
  "$PY" audio_brief/personal.py "$TWDATE" tw || RC=$((RC == 0 ? 15 : RC))
else
  echo "週末:僅產 reel,語音快報跳過"
fi

# reel 產線(語音壞了 reel 照出,反之亦然:REEL_RC 獨立追蹤再合併)
REEL_RC=0
"$PY" video_brief/render.py    || REEL_RC=11
[ "$REEL_RC" = 0 ] && { "$PY" video_brief/make_post.py || REEL_RC=12; }
[ "$RC" = 0 ] && RC=$REEL_RC

echo "run_daily done rc=$RC"
exit "$RC"
