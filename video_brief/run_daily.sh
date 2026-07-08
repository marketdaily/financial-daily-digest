#!/usr/bin/env bash
# 每日日報媒體衍生產線:短影音(reel)+語音快報(audio)。
# extract → render → make_post(驗證+上傳+post json) → 音頻(旁白稿→TTS→驗證+上傳)。
# 窗口/每日鎖/通知由呼叫端 runner 負責(winrig: ~/.marketdaily-fallback/video_brief_runner.sh)。
# 失敗以 exit code 回報;影音互不阻斷(影片壞了音頻照出,反之亦然)。
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3

git pull --rebase --autostash --quiet 2>/dev/null || true
set -a; source .env 2>/dev/null || true; set +a

RC=0
"$PY" video_brief/extract.py || exit 10

"$PY" video_brief/render.py    || RC=11
[ "$RC" = 0 ] && { "$PY" video_brief/make_post.py || RC=12; }

"$PY" audio_brief/build_script.py || RC=$((RC == 0 ? 13 : RC))
"$PY" audio_brief/tts.py          || RC=$((RC == 0 ? 14 : RC))

echo "run_daily done rc=$RC"
exit "$RC"
