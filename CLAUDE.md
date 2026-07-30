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

### 自訂技能（Delvin Custom Skills）— 134 個
位置：`~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills/<name>/SKILL.md`
**完整目錄（每個 skill 一行中文用途）→ 同目錄 `CATALOG.md`；重疊裁決/任務唯一路徑 → `GOVERNANCE.md`（挑 skill 前先查）**

**🏢 公司組織（2026-07-29 老闆拍板）**：整個 Claude 系統=一家公司,老闆=Delvin,9 部門 hub 在記憶庫 `dept_*.md`(中心=dept_ceo_office 董事長室,Obsidian graph 橘色層+《公司組織圖.canvas》);新資產入庫要歸部門;組織變動→更新對外名片 artifact(網址與鐵則見 dept_ceo_office)。品質戰情頁=status.html+quality.json。

分類速查（只列名，說明見 CATALOG.md；⚠️=退役或 Mac-only）：
- **MarketDaily 營運**：workflow（日報pipeline）、site-doctor（全站巡檢必跑）、ui-ux-pro-max（含品牌設計系統）、claude-design、email-marketing-bible、growth-strategy、referral-program、pricing-strategy、landing-page-copy、ab-test-analyzer、sales-funnel-planner、sales-funnel-optimizer、cro（單頁轉換診斷）、onboarding（註冊後活化）、programmatic-seo（規模化SEO頁）、marketing-psychology（行為科學原則庫）、legal-compliance（⚖️法務長:上線前合規審查唯一路徑）
- **行銷鏈（「Marketing Agents」＝五連跑，順序不可跳）**：spy → competitive-ads-extractor → bulk-creative → ads-score → ads-meta（2026-07-06 起每週日 10:00 TW 由 `~/.marketdaily-fallback/marketing_agents_weekly.sh` 全自動跑：生成＋獨立驗證者核可＋入佇列，見 `marketing/CLAUDE.md`）
- **內容/創作**：content-engine、crosspost、content-repurposing、content-refresh、content-research-writer、brand-voice-amplifier（⚠️enhancer 退役）、podcast-outline、video-style、video-editing、story-script、youtube-summarizer、article-extractor
- **交易/量化**：quant-math（下注前必算）、backtest-validation（上實盤前必驗）、stock-analyzer、invest-skill、dcf-valuation、tw-financial-analysis、tw-stock-agent、tw-stock-scraper、trading-skills-pro、trade-bot、tradingagents、ccxt、finrobot（參考）、pm-mispricing、portfolio-optimization、regime-detection、order-execution、options-strategy-advisor、position-sizer、vcp-screener、market-breadth-analyzer、macro-regime-detector、institutional-flow-tracker、stanley-druckenmiller-investment、ai-trader、intel-signal-lookup（查`~/Delvin-agent/intel/`信息差引擎,免費層替代13F/insider）；edge 鏈：edge-pipeline-orchestrator → edge-signal-aggregator → edge-strategy-designer → signal-postmortem
- **AI/Agent 工程**：agentic-engineering、ai-first-engineering、ai-regression-testing、agent-eval、eval-harness、council、iterative-retrieval、cost-aware-llm-pipeline、context-budget、cost-tracking、autonomous-loops、continuous-agent-loop、continuous-learning-v2、skill-creator、skill-seekers、mcp-builder
- **開發紀律/測試/hooks**：superpowers、superpowers-lab、tdd-workflow、systematic-debugging、root-cause-tracing、finish-branch、pypict、playwright-testing、browser-qa、click-path-audit、fuzz-security、defense-in-depth、deployment-patterns、error-handling、api-connector-builder、data-scraper-agent、code-quality-hooks、typescript-quality-hooks、cc-hooks-python、claude-hooks-sdk（備用）、cc-notify（⚠️Mac-only）、claudio（⚠️Mac-only）、discord-notifier、activity-tracker、wayfinder（超大工程決策票地圖）、domain-modeling（詞彙表+ADR）、code-review-skill（⚠️退役→內建 /code-review）
- **研究/知識**：deep-research、tapestry、research-indexer、academic-analyzer、knowledge-ops、doc-coauthoring、grill-me（idea 拷問/壓力測試）
- **產能/雜項**：docx、pptx、xlsx、pdf、invoice-organizer、file-organizer、website-design-team（⚠️做整站/landing 唯一入口）、web-artifacts-builder、dashboard-builder、sql-generator、excel-formula、api-docs-generator、genai-prompt-pro（⚠️生成prompt/任務spec強制前置層）、nano-banana-pro、antigravity、open-generative-ai、ui-wireframe-generator、creative-direction、color-palette-generator、font-pairing（⚠️typography-pairing 退役）、defi-amm-security、evm-token-decimals

## 📋 未收尾事項必須主動報（2026-07-30 Delvin 追責，最高優先）
Delvin 原話：「你為什麼沒有直接收掉而是要等我問你才跟我講…我以後沒有問你怎麼辦，誰要負責」。

- **收工摘要不准只講已完成**：還沒收乾的、還沒在生產驗證的、我自己造成的風險，一律當場講，不等他問。
- 任何未收乾的事項在做的當下就登記：`scripts/open_items.py add "一句話" --why "為什麼還沒收" [--risk high|med|low] [--owner me|delvin]`；收掉了 `close <id> --note`。
- **機器保證，不靠良心**：`.claude/settings.json` 的 Stop hook 在每次 session 結束執行 `open_items.py push`，還有 open 項就自動推播到 Delvin 手機（零 open 項時完全靜默，不製造噪音）。
- 判準：「已完成」= 已在**生產/真實排程**跑過並驗證；只有單元測試/模擬驗證過的一律是 open 項，寫明「尚未在生產跑過」。

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
- **🔁 skill 自主學習迴圈(2026-07-29 老闆親令,全 skill 適用)**:每個 skill 目錄可有 `LESSONS.md` 教訓帳本;全域 PostToolUse hook(`~/.claude/hooks/skill-lessons.py`)在每次 skill 被呼叫時自動注入該帳本+回寫指令。使用 skill 撞到門檻/bug/更好做法且解決後,**收尾前必須 append 一節**(日期+坑+修法,≤6行);過時條目順手修正;沒新教訓不寫不灌水
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
- **🔔 告警解決回寫（2026-07-30 Delvin 拍板工作流）**：所有 admin 推播自動落 KV `admin_events`,admin.html「系統告警」頁可看歷史。Delvin 的流程=收到告警截圖丟給 Claude 處理。**修完任何曾推播 admin 告警的事故後,必須呼叫 `scripts/resolve_admin_alert.sh "<告警關鍵字>" "<一句怎麼解的>"` 把該則標「✅ 已解決」+解決說明**——Delvin 只看後台就知道哪些處理完,不用自己判斷。token 在 winrig .env（Mac 的 MARKETDAILY_ALERT_TOKEN 是舊值,Mac session 經 winrig MCP `run_bash` 打）。
- **🤖 cron 呼叫 `claude -p` 的模型分層(2026-07-30 Delvin 親令,先「都用 opus」再「分層,日常小任務走 sonnet」)**：一律用 `scripts/lib_cron_runner.sh` 的 `claude_model TIER`，禁止自己寫 `--model`（會疊成兩個旗標）。**切法是「失敗代價」不是「任務大小」**：`heavy`=會改到生產程式碼／對外發布／做合規把關 → opus(降級 sonnet)；`light`=只讀資料的內部整理、摘要、機械性檢查 → sonnet(降級 haiku)。現役 heavy：site_scan 自修站、digest_selfheal 自癒、marketing_agents_weekly(對外投放素材)、news_reactive 起草+驗證(Python 端鏈 opus→sonnet→haiku)；現役 light：line_group(讀 LINE 截圖產內部 md/推播)。⚠️ **驗證者／把關者不准降級**——把關者變寬鬆＝放行壞內容，省的 token 不值那個風險。絕不吃 CLI 預設(=Fable 5,週額度見底整批 cron 同時失敗刷屏,07-30 news_reactive 每 10 分鐘告警即此因)。
- **日報整點寄出**：cron 早 05:20/晚 19:00 TW 觸發只為生成（2026-07-26 起：早報夜盤收完即起跑，05:20 取夏冬令制都安全＋數據落定緩衝；runway 100 分供品質重生迴圈），main.py `_hold_until_send_time` 等到 07:00/20:00 整點一齊寄。⚠️ 05:30 preflight 已隨 GitHub Actions 停擺退役(2026-07-06 才發現,勿當它還在);寄前防線=①`build_email_html` 未定義 CSS class 確定性修復層 ②同一 HIGH audit check 生成中連中 3 位即熔斷推 admin(`_push_systemic_alert`,趕在整點寄出前)。
- **日報備援防線三層(2026-07-24,Delvin「絕對不要再看到閹割版」,不要重複建)**：①**老闆護盾**——老闆本人若只因「軟錯」check(`_SOFT_HIGH_CHECKS`:reason_shallow/vague、tldr_too_short)要掉備援→改寄 AI 完整版(main.py `_owner_shield_applies`);硬錯仍走安全備援。②**老闆掉備援紅色 canary**——`_push_admin_halt_alert` 老闆在名單即最上方刺眼告警+push 重試3次。③**寄後自動根因修**——`~/.marketdaily-fallback/digest_selfheal_runner.sh`(cron */10,窗口 TW08:50-09:10/US21:20-21:40)用 `scripts/digest_selfheal_detect.py` 偵測「檢查造成的硬錯備援」(排除 429/503 infra)→spawn `claude -p`(playbook=`scripts/digest_fix_playbook.md`)worktree 內根因修+白名單guard+digest測試把關→過才 push;修未來不重寄今日;kill-switch=`~/.marketdaily-fallback/digest_selfheal.DISABLED`。owner email 由 env `MARKETDAILY_OWNER_EMAIL` 定(預設 delvin)。
- 相關 token（同一把值,**旋轉要「八處」一起**,2026-07-30 再校正,原記「三端/七處」不完整——漏了 Mac 守衛那份）：
  - **alert-worker 四把 secret**：`ADMIN_PUSH_TOKEN`、`ADMIN_PUSH_TOKEN_2`、`MARKETING_TARGETS_TOKEN`、`INTERNAL_TOKEN`（admin-line-push 的候選清單全接受同值 → 漏換任一把舊 token 就還活）
  - **watchdog** `ALERT_TOKEN`（/hb 心跳驗證 + 反向推 alert-worker）
  - **winrig `.env`** `MARKETDAILY_ALERT_TOKEN` + `MARKETDAILY_INTERNAL_TOKEN`（`heartbeat.sh` 直讀前者,改 .env 自動跟上不用改腳本）
  - GH secret `MARKETDAILY_ALERT_TOKEN`（Actions 已死→runtime 無關,可略）
  - **Mac `~/.mac-guard/.alert_token`**（Mac 兩支守衛唯一的告警管道:排程守衛 guard.sh + winrig tunnel 守衛;launchd 下讀不到 ~/Downloads 所以自成一份）⚠️ 2026-07-30 查出這端是**旋轉前的舊值**,推播 403——07-09 上線的 Mac 排程守衛自那次旋轉後一直啞著,因為沒違規所以沒人發現。**旋轉後必須真發一則自測推播驗 200**(沉默的守衛=沒有守衛)。
  - ⚠️ 旋轉法：`wrangler secret put` 後 **CF 傳播 30–60s**（首測太早會假陰,舊 token 看似還活）；驗證=舊 token 打兩 worker 皆須 403、新 token 皆 200 + 真實 `main._push_admin_alert` status=200。
- 坑:workers.dev 同帳號互打被 1042 擋（用 service binding）;GH Actions skip 步驟 output=null,`null=='0'` 數字強轉=true。

## 重要慣例（從過去 session 學到）
- **🪟 Mac=純視窗（2026-07-30 Delvin 拍板 A 級，最高優先）**：所有思考/編碼/commit 走 winrig。**Mac 不跑 git 也不跑 sync**（launchd 已停用）；winrig 用 SSH 主動來收（`brain_collect_mac.sh`，`--ignore-existing` 只收新增、尊重墓碑防殭屍復活）、主動送回（`brain_deliver_mac.sh`，含墓碑刪除）。**排程一律 winrig**——Mac 會睡眠，放這裡會靜默不執行（07-01 的 update_stocks 就這樣沒跑、資料停更近兩個月）。⚠️ 代價：Mac 無本地能力，winrig 不可達時互動工作全停——**備援通道=`ssh winrig`（Windows 帳號，Tailscale）**，可經它 `wsl -d Ubuntu` 進 WSL 救援。詳見 memory `project_mac_pure_window`。
- **🧠 記憶單機主寫制 → B 級（2026-07-30 升級，A 級的基礎）**：記憶索引 `MEMORY.md` 唯一寫者=winrig。**Mac 可「新增」記憶 topic 檔（winrig 會收走），但不能「修改」既有記憶/skill 檔**——寫入權由程式收掉（`--ignore-existing`），不靠自律；在 Mac 改既有檔不會生效，會被偵測並推播。新增記憶仍需登記 `MEMORY_INBOX_MAC.md`（winrig 每 2h SSH 拉走；該檔已排除在 sync 之外）。winrig 端改索引只准 Edit 錨定，禁整檔 Write。詳見 memory `feedback_memory_single_writer`、`project_brain_sync_realtime`。
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
