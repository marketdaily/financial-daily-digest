# marketing/（社群發文與行銷素材）

根規範見 `../CLAUDE.md`。本目錄鐵則：

- **發文唯一路徑**：winrig cron `~/.marketdaily-fallback/social_post_runner.sh`（14:00–14:19 TW 窗口＋每日鎖）先跑 `post_daily_reel.py`（當日日報短影音 reel，冪等）再跑 `daily_run.py`（品牌貼文）；絕不手動補發
- **日報短影音產線（2026-07-08 上線）**：winrig cron `video_brief_runner.sh`（07:20–07:39 TW＋每日鎖）跑 `video_brief/run_daily.sh`：公版日報→`extract.py`（數字逐字回驗）→`render.py`（Playwright 錄 1080x1920 品牌動畫+程序配樂）→`make_post.py`（確定性驗證:數字回對/禁用詞/規格/非黑幀→KV 上傳 `media.marketdaily.ai`→post json）。**內容鐵則：只上市場級重點＋事實性漲跌%，絕不上買賣價位/建議文字**（2026-06-02 明牌出包根因修正）；驗證不過=不產 post json=當天不發，生成失敗推 admin
- **發前必驗**：`python daily_run.py --dry` 看下一篇 id → 讀 `social_posts.json` 該 id 的 caption＋圖 → 逐字比對現行事實（價格/來源數/勝率/方案/市況）。任何一條對不上 → 停手問用戶（2026-05-26 出包教訓）
- **內容補產唯一路徑（2026-07-06 Delvin 親令全自動化；2026-07-08 升級多代理 Workflow）**：winrig cron `~/.marketdaily-fallback/marketing_agents_weekly.sh`（每週日 10:00–10:29 TW）跑 Marketing Agents 5-skill 鏈。主路徑=headless claude 用 Workflow 工具跑 `.claude/workflows/marketing-generate.js`（研究→6 創作代理平行→評分平行→定稿）與 `marketing-verify.js`（**每則草稿一個全新 context 獨立驗證者平行裁決**，逐字比對 pricing/track-record 事實＋中英一致性＋合規，缺席=fail-closed 駁回——「發前必逐字驗」由這步履行）→ `promote_ad_creatives.py` 重掃合規＋產圖卡入佇列 → deploy docs。舊單體 prompt 在 `~/.marketdaily-fallback/ma_*_prompt_legacy.md` 僅當 Workflow 工具不可用時 fallback；shell 端計數/格式驗證不變是最後防線。成功/失敗都推播 admin，絕不無聲。人工不再是閘門，但 Delvin 隨時可改 `ad_creative_drafts.json` 的 status 駁回還沒發出去的草稿
- **social_posts.json 欄位慣例（2026-07-09）**：`images`（list）= IG carousel 多圖貼文（2–10 張，僅 instagram，auto_post.py 走 CAROUSEL API）；`retired`（字串=原因）= 永久跳過不發。**清舊存貨一律標 retired 不硬刪**——promote_win_cards/promote_tldr 只用本檔 id 去重，硬刪會被 runner 殭屍回填
- 數字必可驗證，不可捏造（placeholder 一律「—」）；行銷素材**只放贏的**（`win_card_data.py` 資料層）
- 方案只有 **Premium**，沒有「Pro」；不送 Premium（推薦/KOL 用現金/分潤/站內額度）
- **organic only**：不投 Meta 付費廣告；ads-meta skill 輸出一律 organic 模式
- 個股分析內容不得與付費連結（合規鐵則，見根 CLAUDE.md）
