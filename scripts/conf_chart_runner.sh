#!/bin/bash
# 法說會簡報圖表抽取 worker(intel/conf_charts.py):把 patrol 排進佇列的簡報,用本地
# Unlimited-OCR 找出圖表頁 + Gemini vision 讀出數字,寫進 intel/.conf_chart_cache.json。
# 下一輪 patrol(21:30)自動把快取併進 Ollama 摘要輸入,補掉「財測數字在圖片裡」的天花板。
#
# 窗口 03:20-03:49:刻意避開 21:30 intel_patrol(GPU 重活不與主巡邏搶資源)、03:10
# cardvault twwarm、04:40 brainsearch 索引重建。快取檔 gitignore(衍生資料,可重建),
# 故不做 git_persist。
# GPU venv:模型只在 ~/unlimited_ocr/.venv,repo 主 venv 不裝 torch,兩者用 PYTHONPATH 橋接。
REPO="$HOME/Delvin-agent"
OCR_PY="$HOME/unlimited_ocr/.venv/bin/python"
source "$REPO/scripts/lib_cron_runner.sh"
cron_time_gate "03:20" "03:49"

# GPU 互斥(必須在 daily_lock 之前:讓路的 tick 不可佔掉今天的鎖,窗口內 */10 還有機會重試)。
# OCR 模型約 9GB、Ollama qwen2.5:14b 約 9GB,16GB 卡塞不下兩個——硬撞的結果是 Ollama 靜默
# 退回 CPU(慢到摘要逾時)或直接 OOM,兩種都不會明顯報錯,只會讓夜間產出默默變爛。
#
# ⚠️ 判定用「常駐模型總大小」不是「有沒有模型」:brainsearch 的 nomic-embed-text(323MB)
# 幾乎常態常駐,用 grep '"model"' 會每天都讓路 → worker 永遠餓死。門檻 3GB 只擋真正的大模型。
BIG_MODEL=$(curl -s -m 5 http://localhost:11434/api/ps 2>/dev/null | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print(0); sys.exit()
print(sum(m.get('size',0) for m in d.get('models',[])))
" 2>/dev/null || echo 0)
if [ "${BIG_MODEL:-0}" -gt 3000000000 ]; then
  echo "Ollama 常駐大模型($((BIG_MODEL/1000000))MB),本 tick 讓路(不佔每日鎖,稍後重試)"
  exit 0
fi

cron_daily_lock "conf_charts"
cd "$REPO" || exit 1

if [ ! -x "$OCR_PY" ]; then
  echo "OCR venv 不存在($OCR_PY),跳過(fail-open:patrol 照舊只用文字層)"
  exit 0
fi

cron_run_and_alert "conf_charts" -- env PYTHONPATH="$REPO" "$OCR_PY" "$REPO/intel/conf_charts.py"
exit $?
