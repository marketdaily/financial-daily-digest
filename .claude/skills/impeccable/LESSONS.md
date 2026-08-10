### 2026-08-10 「detect」不是 command 是腳本
- 坑:CLAUDE.md 寫 `/impeccable detect`,但 Commands 表沒有 detect;真身是 `scripts/detect.mjs`。
- 修:`node <skill>/scripts/detect.mjs <files...>` 直接跑,`--no-advisory` 靜音進階提示;中文站的「——」破折號會觸發 em-dash advisory,屬正當標點可保留。
