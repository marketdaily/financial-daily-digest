# docs/（前端 — Cloudflare Pages → marketdaily.ai）

根規範見 `../CLAUDE.md`。本目錄鐵則：

- **只放前端**：不放 server 邏輯、不放 secret。後端在各 Worker 目錄與根目錄 pipeline
- 部署：`npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true`；重大改動部署後必跑 `python3 scripts/site_scan.py` 驗證（exit 0 才算過）
- 改 `stocks.js` 或共用 JS 記得 `?v=` cache-bust
- i18n：`data-i18n` 系列屬性＋`applyLang()`；預設中文（`localStorage("md-lang-v2") || "zh"`）
- **禁**：自訂游標（已移除勿加回）、假數字/佔位見證（placeholder 一律「—」）、動密碼/登入 flow（memory `feedback_password_flow_protect`）、hardcode 新 secret/token
- `preferences.html` 已廢棄 = redirect 到 `dashboard?focus=stocks`
- 個股功能永不與付費掛鉤（合規鐵則，見根 CLAUDE.md）
- `dashboard.html` 內嵌 JS ~2300 行待模組化：計畫見 `~/autonomous/research/2026-07-03_clean_code_audit_extraction_plan.md` Phase 5；動它＝獨立任務，禁止順手夾帶
