# Delvin Agent 專案

## 語言偏好
- 回覆語言：繁體中文
- 主要開發語言：Python

## 開發環境
- 平台：Windows（家用主機，WSL2 / Ubuntu）—— 原 macOS 已非主力機
- 終端機：WSL bash
- 語音輸入：Windows 內建 Win+H（需接麥克風；詳見 memory feedback_voice_dictation_terminal）
- **⚠️ Mac 禁止新增 launchd / cron / 常駐排程（2026-07-09 發燙事故鐵則）**：排程與背景工作一律放 winrig；Mac 只允許 `~/.mac-guard/allowlist.txt` 清單內項目（遠端控制、同步類等必須在 Mac 本機的東西）。守衛 `com.delvin.launchagent-guard` 每日 08:30/20:30 自動掃，違規即 web push 告警。確要在 Mac 加合法項目：先問用戶，核可後同步加進 allowlist

## 專案說明

**MarketDaily** — 每日財經 AI Email 日報平台。
訂閱者設定股票偏好（美股 / 台股），後台每日產生個人化 HTML Email 並寄送。

### 架構
- **前端**：`docs/` 資料夾（靜態 HTML/CSS/JS），部署在 Cloudflare Pages
- **後端**：Cloudflare Workers + KV 儲存（tuna_pipeline / stripe-webhook）
- **AI 產圖**：`image_generator.py`、`opengenai_client.py`
- **子目錄就地規範**：`docs/CLAUDE.md`（前端鐵則）、`marketing/CLAUDE.md`（發文鐵則）——動該目錄先讀

### 關鍵檔案
| 檔案 | 說明 |
|------|------|
| `docs/index.html` | 首頁（Landing page，i18n 中英切換，預設中文） |
| `docs/dashboard.html` | 用戶後台（股票偏好摘要、管理員面板） |
| `docs/preferences.html` | 股票偏好設定（美股 / 台股，含公司名稱顯示） |
| `docs/admin.html` | 管理員後台（KV 資料管理、用戶清單） |
| `docs/ui-pro.js` | 共用 UI 強化層（grain、scroll bar、transition、ripple） |
| `output/` | 產生的 HTML Email digest |

### 部署指令
```bash
npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true
```
- 網站 URL：`https://marketdaily.ai`
- Cloudflare 帳號：`delvin.12345678@gmail.com`
- Account ID：`a92082d84f08b1d4883facbf1a1dc445`
- 一律用 `npx wrangler`（非全域安裝），有未 commit 變更加 `--commit-dirty=true`

### i18n 系統
- 用 `data-i18n`、`data-i18n-html`、`data-i18n-placeholder` 屬性標記需翻譯元素
- `applyLang(lang)` 函數讀取 `localStorage("md-lang-v2")` 套用語言
- 預設語言：**中文（zh）**（`localStorage.getItem("md-lang-v2") || "zh"`）
- 全站頁面皆有 i18n（含 dashboard / preferences / contact / guide / agents / filter / success）

### ui-pro.js 包含功能
noise grain、scroll progress bar、page transition wipe、magnetic buttons、click ripple、scene reveal IntersectionObserver
（**自訂游標已移除**，不要再加回去）

## 可用工具權限

### 直接可用工具
| 工具 | 功能 |
|------|------|
| `Bash` | 執行 shell 命令 |
| `Read` | 讀取本地檔案 |
| `Edit` | 編輯檔案（精確替換） |
| `Write` | 寫入/覆蓋檔案 |
| `Agent` | 啟動子代理執行複雜任務 |
| `AskUserQuestion` | 向用戶提問（互動選擇） |
| `ToolSearch` | 搜尋並載入延遲工具 |
| `ScheduleWakeup` | 排程自動喚醒（loop 模式） |
| `ShareOnboardingGuide` | 分享 ONBOARDING.md |
| `Skill` | 呼叫內建技能 |

### 延遲工具（需透過 ToolSearch 載入）
- **任務管理**：`TaskCreate`, `TaskGet`, `TaskList`, `TaskUpdate`, `TaskStop`, `TaskOutput`
- **排程/自動化**：`CronCreate`, `CronDelete`, `CronList`, `RemoteTrigger`, `Monitor`
- **網路**：`WebFetch`, `WebSearch`
- **其他**：`NotebookEdit`, `PushNotification`, `EnterPlanMode`, `ExitPlanMode`, `EnterWorktree`, `ExitWorktree`

### MCP 整合工具（延遲，需透過 ToolSearch 載入）
- **Gmail**：搜尋郵件、建立草稿、標籤管理（`create_draft`, `search_threads`, `label_message` 等）
- **Google Calendar**：建立/修改/刪除活動、查詢行程（`create_event`, `list_events`, `update_event` 等）
- **Firecrawl**：網頁爬取、搜尋、瀏覽器互動（`scrape`, `crawl`, `search`, `firecrawl_agent` 等）
- **Playwright**：瀏覽器自動化（`browser_navigate`, `browser_click`, `browser_take_screenshot` 等）

### 內建技能（Skills）
| 技能 | 用途 |
|------|------|
| `update-config` | 修改 settings.json、hooks、權限設定 |
| `keybindings-help` | 自訂鍵盤快捷鍵 |
| `simplify` | 審查並精簡修改過的程式碼 |
| `fewer-permission-prompts` | 減少重複的權限提示 |
| `loop` | 設定週期性重複任務 |
| `schedule` | 建立/管理排程自動化任務 |
| `claude-api` | 建構/除錯 Claude API 應用 |
| `init` | 初始化 CLAUDE.md |
| `review` | 審查 Pull Request |
| `security-review` | 執行安全性審查 |

### 自訂技能（Delvin Custom Skills）— 127 個
位置：`~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills/<name>/SKILL.md`
**完整目錄（每個 skill 一行中文用途）→ 同目錄 `CATALOG.md`；重疊裁決/任務唯一路徑 → `GOVERNANCE.md`（挑 skill 前先查）**

分類速查（只列名，說明見 CATALOG.md；⚠️=退役或 Mac-only）：
- **MarketDaily 營運**：workflow（日報pipeline）、site-doctor（全站巡檢必跑）、ui-ux-pro-max（含品牌設計系統）、claude-design、email-marketing-bible、growth-strategy、referral-program、pricing-strategy、landing-page-copy、ab-test-analyzer、sales-funnel-planner、sales-funnel-optimizer
- **行銷鏈（「Marketing Agents」＝五連跑，順序不可跳）**：spy → competitive-ads-extractor → bulk-creative → ads-score → ads-meta（2026-07-06 起每週日 10:00 TW 由 `~/.marketdaily-fallback/marketing_agents_weekly.sh` 全自動跑：生成＋獨立驗證者核可＋入佇列，見 `marketing/CLAUDE.md`）
- **內容/創作**：content-engine、crosspost、content-repurposing、content-refresh、content-research-writer、brand-voice-amplifier（⚠️enhancer 退役）、podcast-outline、video-style、video-editing、story-script、youtube-summarizer、article-extractor
- **交易/量化**：quant-math（下注前必算）、backtest-validation（上實盤前必驗）、stock-analyzer、invest-skill、dcf-valuation、tw-financial-analysis、tw-stock-agent、tw-stock-scraper、trading-skills-pro、trade-bot、tradingagents、ccxt、finrobot（參考）、pm-mispricing、portfolio-optimization、regime-detection、order-execution、options-strategy-advisor、position-sizer、vcp-screener、market-breadth-analyzer、macro-regime-detector、institutional-flow-tracker、stanley-druckenmiller-investment、ai-trader、intel-signal-lookup（查`~/Delvin-agent/intel/`信息差引擎,免費層替代13F/insider）；edge 鏈：edge-pipeline-orchestrator → edge-signal-aggregator → edge-strategy-designer → signal-postmortem
- **AI/Agent 工程**：agentic-engineering、ai-first-engineering、ai-regression-testing、agent-eval、eval-harness、council、iterative-retrieval、cost-aware-llm-pipeline、context-budget、cost-tracking、autonomous-loops、continuous-agent-loop、continuous-learning-v2、skill-creator、skill-seekers、mcp-builder
- **開發紀律/測試/hooks**：superpowers、superpowers-lab、tdd-workflow、systematic-debugging、root-cause-tracing、finish-branch、pypict、playwright-testing、browser-qa、click-path-audit、fuzz-security、defense-in-depth、deployment-patterns、error-handling、api-connector-builder、data-scraper-agent、code-quality-hooks、typescript-quality-hooks、cc-hooks-python、claude-hooks-sdk（備用）、cc-notify（⚠️Mac-only）、claudio（⚠️Mac-only）、discord-notifier、activity-tracker、code-review-skill（⚠️退役→內建 /code-review）
- **研究/知識**：deep-research、tapestry、research-indexer、academic-analyzer、knowledge-ops、doc-coauthoring、grill-me（idea 拷問/壓力測試）
- **產能/雜項**：docx、pptx、xlsx、pdf、invoice-organizer、file-organizer、website-design-team（⚠️做整站/landing 唯一入口）、web-artifacts-builder、dashboard-builder、sql-generator、excel-formula、api-docs-generator、genai-prompt-pro（⚠️生成prompt/任務spec強制前置層）、nano-banana-pro、antigravity、open-generative-ai、ui-wireframe-generator、creative-direction、color-palette-generator、font-pairing（⚠️typography-pairing 退役）、defi-amm-security、evm-token-decimals

## 編碼規範
- 使用 Python 開發
- 不加不必要的註解
- 保持程式碼簡潔
- **機密一律 `.env`**（已在 .gitignore）：key/token 絕不硬編碼進程式或 commit；新增 secret 先確認 .gitignore 擋得住，git 只放 `.env.example`
- **前後端分離**：`docs/` 只放前端；Workers / Python pipeline 不產頁面 markup（email HTML 模板例外）。改前端任務不碰後端目錄，反之亦然
- **關注點分離**：新代碼按 data / logic / render 分層寫；既有大檔（根目錄 main.py / analyzer.py、docs 內嵌 JS）的抽離要開獨立任務做，禁止順手夾帶（見 scope-lock 規則）；抽離計畫見 `~/autonomous/research/2026-07-03_clean_code_audit_extraction_plan.md`
- **新的獨立產品不再塞進本 repo**，另開 repo；本 repo 已有的歷史產品目錄（fortune-ai / ganla-app / youtube_space 等）維持現狀不搬
- 詳細背景：memory `feedback_engineer_structure_review`（2026-07-03 工程師 7 點體檢）

## Skill 管理規則
- **每次用戶分享或要求建立新 skill，必須同步更新三處**：`skills/CATALOG.md`（完整表：名稱＋一行中文用途）＋ 上方分類速查（列名）＋ `skills/GOVERNANCE.md`（歸群裁決）
- Skill 檔案位置：`~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills/<name>/SKILL.md`
- 有 URL 的 skill → 先 WebFetch 讀完再建立，確保內容正確
- **⚖️ 治理裁決表（2026-07-03 起）**：同任務永遠走同一條路徑。多個 skill 都能做時查 `skills/GOVERNANCE.md`（任務→唯一路徑表＋重疊群主用/備用/退役＋抓網頁工具選擇順序）。新 skill 入庫必須同步歸群裁決；已退役：typography-pairing、brand-voice-enhancer、code-review-skill（SKILL.md 已標 DEPRECATED，不刪檔）

## 自動守望系統（2026-06-11 上線,不要重複建）
- **🤖 自主進步機器 `~/autonomous/`（2026-07-02 上線,是「我」的一部分,不要當陌生東西關掉/重建）**：winrig 24/7 冷血自學引擎,用戶沒在用電腦時自己找事做、自己學、自己進步。北極星=擴充 `capabilities/INDEX.md` 能力庫,讓未來一句「幫我自動化 X」即 100%。`driver.sh`(cron `*/15`)→活動閘門(用戶互動就完全讓路)+50%用量閘門(`config.sh` `STOP_AT_USD`)+斷點記憶(`state/current_task.md`)+`--dangerously-skip-permissions` 全自主。死線=絕不寄信(全域 hook 擋)。詳見 memory `project_autonomous_machine`;控制:`~/autonomous/看我.txt`。
- **🧠 大腦語意搜尋（所有 session 都該用,不只機器）**：`python3 ~/autonomous/brainsearch/search.py "問題" -k 5 [--graph]` —— 語意搜全部記憶庫/能力庫/WORKLOG/CLAUDE.md,零 token 秒回;找「以前學過什麼/踩過什麼坑/有沒有現成積木」先用它再 grep。`--graph` 附每筆命中的 wikilink 鄰居;`graph.py related "一句話" -d 2` 沿記憶連結圖擴展(GraphRAG,語意+圖譜),`graph.py stats|hubs|orphans|broken` 看圖譜健康。索引每晚 04:40 自動增量重建,04:50 重建 Obsidian vault。
- **🕸️ Obsidian 大腦 vault（2026-07-07 上線）**：`~/delvin-claude-brain` 整個 repo=Obsidian vault(記憶 299 檔+wikilink 圖譜+自動生成 HOME/MOC-*/GRAPH-HEALTH 導覽頁)。⚠️ Obsidian 的 fs.watch 吃不了 `\\wsl.localhost` 9P 路徑(EISDIR),所以 Windows 端開的是 NTFS 鏡像 `C:\Users\USER\ClaudeBrain`(`mirror_win.sh` cron */10 **雙向**:去程 WSL→Win 只鏡 *.md+WORKLOG;回程 `INBOX/` 資料夾=Delvin 在 Obsidian 手寫交辦→`obsidian_inbox_ingest.py` 自動進 `~/autonomous/backlog.md` 佇列+推播回執)。桌面捷徑「Claude 大腦」直開。`graph.py suggest`=連結預測(brain.db 向量找「語意近但未連結」記憶對,GRAPH-HEALTH 每晚列 top15)。⚠️ 除 INBOX 外 vault 是唯讀鏡像,改記憶一律在 Claude session 改真源;`.obsidian/workspace*` 已 gitignore。
- **digest-watchdog worker**（`digest-watchdog/`,2026-07-20 起 v2 dead-man 模式,4 cron）：TW 07:30/08:00 驗早報、20:25/21:00 驗晚報——只查 `marketdaily.ai/output/digest_<date>[_us].html` 公版存檔新鮮度(不依賴 GitHub/winrig),缺席即 web push admin(KV `watchdog:*` 防重),**只告警不代跑**(runner 在 winrig)。背景:v1 綁 GitHub Actions 已死、winrig heartbeat.sh 會跟主機一起死(0720 早報靜默事故)。site_scan.yml 派發已移除(Actions 死)。診斷:`curl https://watchdog.marketdaily.ai/status`。
- **site_scan.yml**：scan（`scripts/site_scan.py`,14 項,源頭=site-doctor skill 的 scan.py,改 skill 版要同步）→ fail 即推播告警 → Claude 在 CI 按 `scripts/site_fix_playbook.md` 自動修（只准動 docs/,guard 強制）→ 重掃全過才部署+push,否則 revert+推播告警。
- **⚠️ LINE 已全面退役（2026-07-06 連 admin 備援也拔了）**：admin 告警唯一通道 = 自有 web push（alert-worker `/internal/admin-line-push`,路徑名沿用但只發 web push）。任何 session 不得再向用戶提 LINE、不得重接 LINE。
- **日報整點寄出**：cron 06:20/19:25 TW 觸發只為生成,main.py `_hold_until_send_time` 等到 07:00/20:00 整點一齊寄。⚠️ 05:30 preflight 已隨 GitHub Actions 停擺退役(2026-07-06 才發現,勿當它還在);寄前防線=①`build_email_html` 未定義 CSS class 確定性修復層 ②同一 HIGH audit check 生成中連中 3 位即熔斷推 admin(`_push_systemic_alert`,趕在整點寄出前)。
- 相關 token:alert-worker `ADMIN_PUSH_TOKEN` = GH `MARKETDAILY_ALERT_TOKEN` = watchdog `ALERT_TOKEN`（同值,旋轉要三端一起）。
- 坑:workers.dev 同帳號互打被 1042 擋（用 service binding）;GH Actions skip 步驟 output=null,`null=='0'` 數字強轉=true。

## 重要慣例（從過去 session 學到）
- **🔁 模型交接手冊（2026-07-07 建立）**：換模型接手（Fable 週額度見底改用 Opus 4.8 等）的**第一個 session,開工前先讀 memory `feedback_model_handoff_playbook.md` 全文**——Fable 隱性工作法一頁版（十鐵則/驗證者分離/e2e驗證/收工四件套/武器庫/陷阱Top清單）。CLAUDE.md+記憶+skills 換模型自動繼承,手冊補的是「工作法靈魂」。
- **⚖️ 合規鐵則：個股分析內容永不與付費掛鉤（2026-07-02 上線,COMPLIANCE_STRUCTURE.md）**：MarketDaily 無投顧牌,依法(投信投顧法§4/§107,橋頭111金訴235判例)任何含「個別有價證券分析/建議/買賣價位」的內容必須**免費開放全體用戶且完全相同**——不得因付費差異化數量、深度、速度、先後;行銷文案不得把個股功能與付費連結;新功能開發前先對照 COMPLIANCE_STRUCTURE.md 永久規則。已拆閘門:持股上限統一80、深度全開、AI對話全開(30則/日)、推播全開。
- **💸 全面免費化＋早鳥口徑（2026-07-09,用戶指令,法律風險考量）**：Premium 付費方案與 Stripe 金流全部下架,全站零收費。對外唯一口徑=**「限時免費＋早鳥鎖定」**:「目前全功能限時免費開放;未來恢復收費後,現在訂閱的早鳥用戶永久保留免費使用權」。未來若恢復收費只能收非分析類價值(或拿牌後另議),**個股分析依法永遠免費,任何文案不得暗示未來分析內容會收費**。後端:`/stripe/checkout-trial` 已 410、D7/D14/D21/D45 升級信全停(模板保留)、welcome/客服 AI 口徑已改、推薦獎勵不再承諾任何回報(純分享)。既有 Stripe 訂戶皆親友未付錢,無退款議題。詳見 memory `project_marketdaily_free_earlybird`。
- **🧬 白話 → 先重寫成精準 prompt 並【明寫出來給用戶看】再執行（用戶 2026-06-26 指令,2026-06-27 確認要「看得到的重寫」,所有 session 通用,含主終端機與語音終端機）**：用戶講話常很白話、口語、省略脈絡(語音輸入還有同音字/聽錯)。收到指令後**先別照字面做**：用「我記得關於老闆的一切」(CLAUDE.md、記憶庫、最近在做的事)把這句白話**重寫成一段精準的專業指令**——補省略脈絡、修同音字、講清楚真正目標。**關鍵:重寫後的 prompt 要先用一兩句明寫出來貼給用戶看(例如「我把你的意思理解成:___,這樣對嗎/開始做了」),讓他能即時校正同音字與方向,而不是只在心裡默默重寫**(2026-06-27 用戶反映「我怎麼都沒看到你在做」=之前內化不外顯,他要看得到)。確認/明顯的指令可邊寫邊做不必等回覆;模糊或高風險才停下等他點頭。用戶原話:「你用專業的 prompt 貼給自己看,你比較好做事…讓它成為基因的一部分」。已燒進 voice_term `_start_session` priming + memory `feedback-voice-prompt-rewrite`。**2026-07-10 升級(用戶再批「重寫功能做得不夠好+我做的 prompt 都很爛」)**:①分流——閒聊不重寫,任務/專業需求才重寫,且要像 PM 開 spec(目標/脈絡/範圍/限制/產出/驗收六欄,模板見 skill `genai-prompt-pro` Part 1),不是換句話說;②所有生成式 prompt(圖/影/音/LLM pipeline)呼叫前**必過 skill `genai-prompt-pro`**(模型方言矩陣+7層骨架+checklist,最終 prompt 一律英文),禁止隨手一句話 prompt。
- **🚫 禁止手動寄信（用戶 2026-05-22 明確指令）**：非台灣時間早上 7:00，禁止做任何會寄 email 給訂閱者的動作 —— 包括手動觸發 `daily_digest` workflow、跑 `send_*.py` 測試腳本、直接 curl Brevo 寄信 API。日報**只能**由 digest-cron worker 的排程 cron（每天 06:55 UTC）自動寄出。**唯一例外**：新訂閱者歡迎信，由 Cloudflare Worker 在註冊當下自動發送，允許。已加 PreToolUse hook（`.claude/hooks/block-mass-email.sh`）強制攔截。任何發信動作有疑慮一律先問用戶，不可自行觸發。
- **🚫 社群自動發文：發前必逐字驗 caption（2026-05-26 出包）**：`marketing/daily_run.py` 跑前**必須**先 `python daily_run.py --dry` 看下一篇 id，然後讀 `social_posts.json` 對該 id 的 caption + 圖片內容，逐字比對現行方案/事實（價格、來源數、勝率、邀請制、即時市況）。任何一條對不上 → 停手不發、先問用戶。歷史教訓:5/26 我直接補發 `referral`,caption 還寫「免費方案邀請制」+「推薦 3 人 → Pro 免費 1 個月」(早改掉的舊文案);同一批 `social_posts.json` 還埋有「75+ 來源」「勝率 75.5%」「捏造訂戶 Jason」「寫死 Fed/台積電/油價」等地雷,全清空 backup 在 `marketing/social_posts.json.bak-2026-05-26`。
- **社群排程改 winrig cron single-source（2026-07-01 現況）**：演進 launchd(Mac睡眠missed)→ social-post-cron Worker→workflow_dispatch → **GitHub帳號6/12被flag後Actions全停,Worker觸發路徑死**。現改 winrig `~/.marketdaily-fallback/social_post_runner.sh`(crontab `*/10 * * * *`,只在14:00-14:19 TW窗口+每日鎖發一篇,`daily_run.py`發下一篇未發的)。social-post-cron Worker `crons=[]` 已停用(防解封後Actions復活雙發)。**發文斷更先查三件**:①`daily_run.py --dry`看存貨(空=要補內容,跑Marketing Agents鏈產v3批次+`make_v3_cards.py`圖卡)②winrig crontab有無social_post_runner③Meta token(`auto_post.py check`;459 checkpoint要用戶登入facebook.com解)。詳見 memory `project_social_post_winrig_restore`。
- **不加自訂游標**：ui-pro.js 裡的 custom cursor 已刪除，不要再加
- **Email 樣式**：日報一律用完整 HTML 卡片樣式，不能是純文字
- **台股顯示**：偏好 tag 要同時顯示股票代碼 + 公司名稱
- **Admin 記住 Email**：用 `localStorage("md-admin-email-saved")` 儲存，登入時自動填入並 focus 到密碼欄
