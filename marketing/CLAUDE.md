# marketing/（社群發文與行銷素材）

根規範見 `../CLAUDE.md`。本目錄鐵則：

- **發文唯一路徑**：winrig cron `~/.marketdaily-fallback/social_post_runner.sh`（14:00–14:19 TW 窗口＋每日鎖）跑 `daily_run.py`；絕不手動補發
- **發前必驗**：`python daily_run.py --dry` 看下一篇 id → 讀 `social_posts.json` 該 id 的 caption＋圖 → 逐字比對現行事實（價格/來源數/勝率/方案/市況）。任何一條對不上 → 停手問用戶（2026-05-26 出包教訓）
- 數字必可驗證，不可捏造（placeholder 一律「—」）；行銷素材**只放贏的**（`win_card_data.py` 資料層）
- 方案只有 **Premium**，沒有「Pro」；不送 Premium（推薦/KOL 用現金/分潤/站內額度）
- **organic only**：不投 Meta 付費廣告；ads-meta skill 輸出一律 organic 模式
- 個股分析內容不得與付費連結（合規鐵則，見根 CLAUDE.md）
