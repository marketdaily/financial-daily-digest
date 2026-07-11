#!/usr/bin/env bash
# 每日日報媒體衍生產線:短影音(reel)+語音快報(audio)。
# extract → render → make_post(驗證+上傳+post json) → 音頻(旁白稿→TTS→驗證+上傳)。
# 窗口/每日鎖/通知由呼叫端 runner 負責(winrig: ~/.marketdaily-fallback/video_brief_runner.sh)。
# 失敗以 exit code 回報;影音互不阻斷(影片壞了音頻照出,反之亦然)。
# 用法:run_daily.sh            → 早上全套(台股 reel+台股音頻)
#      run_daily.sh us-audio   → 晚上只產美股晚間音頻(不碰 reel,避免重複發片)
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3

git pull --rebase --autostash --quiet 2>/dev/null || true
set -a; source .env 2>/dev/null || true; set +a

if [ "${1:-}" = "us-audio" ]; then
  TWDATE=$(TZ=Asia/Taipei date +%Y-%m-%d)
  "$PY" video_brief/extract.py "$TWDATE" us                                  || exit 10
  "$PY" audio_brief/build_script.py "video_brief/out/brief_${TWDATE}_us.json" || exit 13
  "$PY" audio_brief/tts.py "audio_brief/out/narration_${TWDATE}_us.txt"       || exit 14
  echo "run_daily us-audio done rc=0"
  exit 0
fi

RC=0
"$PY" video_brief/extract.py || exit 10

"$PY" video_brief/render.py    || RC=11
[ "$RC" = 0 ] && { "$PY" video_brief/make_post.py || RC=12; }

# 週末只產 reel(週末盤點版):語音快報的旁白稿/TTS 是平日格式,週末不做
TWU=$((10#$(TZ=Asia/Taipei date +%u)))
if [ "$TWU" -lt 6 ]; then
  "$PY" audio_brief/build_script.py || RC=$((RC == 0 ? 13 : RC))
  "$PY" audio_brief/tts.py          || RC=$((RC == 0 ? 14 : RC))
else
  echo "週末:僅產 reel,語音快報跳過"
fi

echo "run_daily done rc=$RC"
exit "$RC"
