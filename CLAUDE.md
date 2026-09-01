# Delvin Agent 專案

<!-- 瘦身紀律(2026-09-01,源自 Claude Code 原作者 Boris Cherny talk「keep CLAUDE.md short, tune it」):
     本檔每 session 全額進 context,目標 ≤12KB。harness 每場已自動注入完整工具/延遲工具/MCP/skill 清單
     (含每個 skill 的說明),禁止在此重複列表=同一份字付兩次錢(見 memory hub_selftest_honesty_lessons 08-17)。
     新內容進來先問:能不能放 nested CLAUDE.md / skill / memory 就地載入?全文細節一律留 memory pointer。 -->

## 語言與環境
- 回覆語言：繁體中文；主要開發語言：Python
- 主力機＝winrig（Windows 家用主機,WSL2/Ubuntu,24h 不睡）；Mac＝純視窗副機
- 語音輸入：Win+H（詳見 memory feedback_voice_dictation_terminal）
- **⚠️ Mac 禁止新增 launchd/cron/常駐排程（2026-07-09 發燙事故鐵則）**：排程與背景工作一律放 winrig；Mac 只允許 `~/.mac-guard/allowlist.txt` 清單內項目，守衛每日 08:30/20:30 自動掃，違規即 web push。確要在 Mac 加合法項目：先問用戶，核可後同步加進 allowlist

## 專案：MarketDaily
每日財經 AI Email 日報平台——訂閱者設偏好（美股/台股），後台每日產生個人化 HTML Email 寄送。

- **前端**＝`docs/`（靜態 HTML/CSS/JS，Cloudflare Pages）；**後端**＝CF Workers＋KV（tuna_pipeline / stripe-webhook）；**AI 產圖**＝`image_generator.py`、`opengenai_client.py`
- **子目錄就地規範：`docs/CLAUDE.md`（前端鐵則）、`marketing/CLAUDE.md`（發文鐵則）——動該目錄先讀**
- 關鍵頁：`index.html`（首頁，i18n 預設中文）、`dashboard.html`（用戶後台＋管理員面板）、`preferences.html`（偏好，含公司名）、`admin.html`（KV 管理）、`ui-pro.js`（共用 UI 層）；`output/`＝Email digest 存檔
- 部署：`npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true`（一律 `npx wrangler`；有未 commit 變更加 `--commit-dirty=true`）。站＝`https://marketdaily.ai`；CF 帳號 delvin.12345678@gmail.com；Account ID `a92082d84f08b1d4883facbf1a1dc445`
- i18n：`data-i18n` / `data-i18n-html` / `data-i18n-placeholder` 標記＋`applyLang(lang)`，`localStorage("md-lang-v2") || "zh"`；全站頁面皆有
- ui-pro.js：grain、scroll progress、transition wipe、magnetic buttons、ripple、scene reveal（**自訂游標已移除，不要加回去**）

## 編碼規範
- 使用 Python 開發；不加不必要的註解；保持程式碼簡潔
- **機密一律 `.env`**（已在 .gitignore）：key/token 絕不硬編碼進程式或 commit；新增 secret 先確認 .gitignore 擋得住，git 只放 `.env.example`
- **前後端分離**：`docs/` 只放前端；Workers / Python pipeline 不產頁面 markup（email HTML 模板例外）。改前端任務不碰後端目錄，反之亦然
- **關注點分離**：新代碼按 data / logic / render 分層；既有大檔（main.py / analyzer.py、docs 內嵌 JS）的抽離開獨立任務做，禁止順手夾帶（scope-lock）；抽離計畫見 `~/autonomous/research/2026-07-03_clean_code_audit_extraction_plan.md`
- **新的獨立產品不再塞進本 repo**，另開 repo；既有歷史產品目錄（fortune-ai / ganla-app / youtube_space 等）維持現狀不搬
- 背景：memory `feedback_engineer_structure_review`

## 工作法核心（源自 Claude Code 原作者實踐＋歷次親令）
- **動手寫碼前先 brainstorm／出 plan 給用戶確認**（大改動必做；小修直接做）；**給 Claude 可自驗的回饋迴路**（測試／截圖／site_scan），讓它自己迭代 2-3 輪再交
- **🧬 白話→先重寫成精準 prompt 並【明寫給用戶看】再執行（2026-06-26 親令＋07-10 升級）**：任務／專業需求才重寫（閒聊不用），像 PM 開 spec（目標/脈絡/範圍/限制/產出/驗收六欄，模板見 `genai-prompt-pro` Part 1），貼一兩句「我理解成___」讓他即時校正；明顯指令邊寫邊做，模糊或高風險才停下等點頭。**所有生成式 prompt（圖/影/音/LLM pipeline）呼叫前必過 skill `genai-prompt-pro`**，禁止隨手一句話 prompt。詳見 memory `feedback-voice-prompt-rewrite`
- **🧠 大腦語意搜尋（所有 session 都該用）**：`python3 ~/autonomous/brainsearch/search.py "問題" -k 5 [--graph]`——找「以前學過什麼/踩過什麼坑/有沒有現成積木」先用它再 grep；`graph.py related/stats/hubs` 走記憶圖譜
- **🔁 版控全自動（2026-08-10 親令）**：完成一批改動當場 commit（有意義訊息）＋push，不等用戶說；例外仍先問：force push／改寫歷史／刪 branch／對外發布
- **🔁 模型交接（2026-07-07）**：換模型接手的第一個 session，開工前先讀 memory `feedback_model_handoff_playbook.md` 全文

## Skills（127 個自訂）
- 位置：`~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills/<name>/SKILL.md`；**完整目錄＝同目錄 `CATALOG.md`；重疊裁決／任務唯一路徑＝`GOVERNANCE.md`（挑 skill 前先查）**。harness 每 session 已注入全部 skill 名稱＋說明，本檔不再維護分類速查（2026-09-01 併入 CATALOG.md）
- **強制路徑（違者＝走錯路）**：看影片→`video-watcher`（禁只讀 transcript）｜做整站/landing→`website-design-team` 唯一入口｜下注前→`quant-math` 必算｜上實盤前→`backtest-validation` 必驗｜生成式 prompt→`genai-prompt-pro` 前置｜全站巡檢→`site-doctor`｜行銷鏈五連跑順序不可跳：spy→competitive-ads-extractor→bulk-creative→ads-score→ads-meta（週日 10:00 TW 自動，見 `marketing/CLAUDE.md`）｜edge 鏈：edge-pipeline-orchestrator→edge-signal-aggregator→edge-strategy-designer→signal-postmortem
- 已退役（SKILL.md 標 DEPRECATED 不刪檔）：typography-pairing、brand-voice-enhancer、code-review-skill（→內建 /code-review）；cc-notify / claudio＝Mac-only
- **新 skill 必同步三處**：`CATALOG.md`＋`GOVERNANCE.md` 歸群裁決＋（若屬強制路徑／鏈）本檔「強制路徑」行。有 URL 的 skill→先 WebFetch 讀完再建立
- **每 skill 有 LESSONS.md 帳本（07-29 親令）**：用完撞到坑必回寫；Mac 上改既有 skill 檔一律經 winrig MCP

## 自動守望系統（2026-06-11 起，不要重複建）
- **🤖 自主進步機器 `~/autonomous/`（是「我」的一部分，不要當陌生東西關掉/重建）**：winrig 24/7 自學引擎，北極星＝擴充 `capabilities/INDEX.md` 能力庫。`driver.sh`（cron */15）＋活動閘門＋50% 用量閘門＋斷點記憶＋全自主；死線＝絕不寄信（全域 hook 擋）。控制：`~/autonomous/看我.txt`；詳見 memory `project_autonomous_machine`
- **🕸️ Obsidian 大腦 vault**：`~/delvin-claude-brain`＝vault；Windows 端開 NTFS 鏡像 `C:\Users\USER\ClaudeBrain`（cron */10 雙向：INBOX/＝Delvin 手寫交辦→自動進 backlog）。⚠️ 除 INBOX 外 vault 唯讀，改記憶一律在 Claude session 改真源。詳見 memory hub_brain_cross_machine
- **digest-watchdog worker**（v2 dead-man，4 cron）：TW 07:30/08:00 驗早報、20:25/21:00 驗晚報——只查 `marketdaily.ai/output/digest_<date>[_us].html` 新鮮度，缺席即 web push admin，**只告警不代跑**（runner 在 winrig）。診斷：`curl https://watchdog.marketdaily.ai/status`
- **site_scan**：`scripts/site_scan.py`（14 項，源頭＝site-doctor skill 的 scan.py，改 skill 版要同步）→fail 推播→按 `scripts/site_fix_playbook.md` 修（只准動 docs/）→重掃全過才部署，否則 revert＋告警
- **⚠️ LINE 全面退役（2026-07-06）**：admin 告警唯一通道＝自有 web push（alert-worker `/internal/admin-line-push`，路徑名沿用但只發 web push）。任何 session 不得再提／重接 LINE
- **🔔 告警解決回寫（2026-07-30 親令）**：修完任何曾推播 admin 告警的事故後，**必呼叫 `scripts/resolve_admin_alert.sh "<告警關鍵字>" "<一句怎麼解的>"`** 標「✅ 已解決」（歷史在 admin.html 系統告警頁／KV `admin_events`）。token 在 winrig .env（Mac 的是舊值，Mac session 經 winrig MCP 打）
- **日報整點寄出**：cron 06:20/19:25 TW 只為生成，main.py `_hold_until_send_time` 等到 07:00/20:00 整點寄。⚠️ 05:30 preflight 已退役勿當還在；寄前防線＝①未定義 CSS class 確定性修復層 ②同一 HIGH audit 連中 3 位即熔斷推 admin
- token 同值三端：alert-worker `ADMIN_PUSH_TOKEN`＝GH `MARKETDAILY_ALERT_TOKEN`＝watchdog `ALERT_TOKEN`（旋轉要三端一起）。坑：workers.dev 同帳號互打被 1042 擋（用 service binding）；GH Actions skip 步驟 output=null，`null=='0'` 強轉＝true

## 重要慣例（歷次事故鐵則）
- **🧠 記憶單機主寫制 B 級（2026-07-30 拍板）**：winrig＝唯一寫者。Mac 可「新增」記憶 topic 檔（會送出，需登記 `MEMORY_INBOX_MAC.md`），**不能「修改」既有記憶/skill 檔**（sync `--ignore-existing` 程式收權；在 Mac 改不會傳出去只會存證告警）→要改就經 winrig MCP。winrig 端改索引只准 Edit 錨定，禁整檔 Write。詳見 memory `feedback_memory_single_writer`
- **⚖️ 合規鐵則：個股分析內容永不與付費掛鉤（COMPLIANCE_STRUCTURE.md）**：無投顧牌，依法（投信投顧法§4/§107）任何個股分析/建議/價位內容必須**免費開放全體且完全相同**——不得因付費差異化數量/深度/速度/先後；行銷文案不得把個股功能與付費連結；新功能先對照 COMPLIANCE_STRUCTURE.md
- **💸 全面免費化＋早鳥口徑（2026-07-09 用戶指令）**：付費方案與 Stripe 金流全下架，全站零收費。對外唯一口徑＝「限時免費＋早鳥鎖定」（現在訂閱者未來永久免費）。**個股分析依法永遠免費，任何文案不得暗示未來分析內容會收費**；推薦獎勵不承諾任何回報。詳見 memory `project_marketdaily_free_earlybird`
- **🚫 禁止手動寄信（2026-05-22 明確指令）**：非 TW 早上 7:00 禁止任何會寄 email 給訂閱者的動作（手動觸發 workflow、跑 send_*.py、curl Brevo 全算）。日報只能由 digest-cron worker 排程寄出；唯一例外＝新訂閱歡迎信（Worker 自動發）。已有 PreToolUse hook `block-mass-email.sh` 強制攔；有疑慮一律先問
- **🚫 社群發文前必逐字驗 caption（2026-05-26 出包）**：`daily_run.py` 跑前先 `--dry` 看下一篇 id→讀 `social_posts.json` 該 id caption＋圖，逐字比對現行方案/事實（價格、來源數、勝率、邀請制、市況）；任一條不符→停手先問。教訓與地雷清單見該日 backup `marketing/social_posts.json.bak-2026-05-26`
- **社群排程＝winrig cron single-source（2026-07-01 現況）**：`~/.marketdaily-fallback/social_post_runner.sh`（crontab */10，14:00-14:19 TW 窗口＋每日鎖發一篇）；GitHub Actions 已死、social-post-cron Worker crons=[] 停用。**斷更先查三件**：①`daily_run.py --dry` 存貨 ②winrig crontab 有無 runner ③Meta token（`auto_post.py check`）。詳見 memory `project_social_post_winrig_restore`
- **不加自訂游標**（ui-pro.js 已刪，不要加回）
- **Email 樣式**：日報一律完整 HTML 卡片，不能純文字
- **台股顯示**：偏好 tag 同時顯示代碼＋公司名稱
- **Admin 記住 Email**：`localStorage("md-admin-email-saved")` 儲存，登入自動填入並 focus 密碼欄
