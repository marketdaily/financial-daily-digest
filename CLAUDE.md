# Delvin Agent 專案

## 語言偏好
- 回覆語言：繁體中文
- 主要開發語言：Python

## 開發環境
- 平台：Windows（家用主機，WSL2 / Ubuntu）—— 原 macOS 已非主力機
- 終端機：WSL bash
- 語音輸入：Windows 內建 Win+H（需接麥克風；詳見 memory feedback_voice_dictation_terminal）

## 專案說明

**MarketDaily** — 每日財經 AI Email 日報平台。
訂閱者設定股票偏好（美股 / 台股），後台每日產生個人化 HTML Email 並寄送。

### 架構
- **前端**：`docs/` 資料夾（靜態 HTML/CSS/JS），部署在 Cloudflare Pages
- **後端**：Cloudflare Workers + KV 儲存（tuna_pipeline / stripe-webhook）
- **AI 產圖**：`image_generator.py`、`opengenai_client.py`

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

### 自訂技能（Delvin Custom Skills）
位置：`~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills/`

| 技能 | 用途 |
|------|------|
| `ui-ux-pro-max` | 全方位 UI/UX 設計智能（50+ 樣式、161 色板、57 字型配對、99 UX 規範、25 圖表類型，涵蓋 React/Next.js/Vue/Svelte/SwiftUI/React Native/Flutter/Tailwind/shadcn/HTML）；同時包含 MarketDaily 品牌設計系統（深色玻璃卡片、indigo 漸層、Inter 字體、scene-reveal 動畫） |
| `spy` | 競品廣告偵察:抓 Meta Ad Library / TikTok Creative Center / Google Ads Transparency 上競品在跑什麼廣告,找 hook / promo / whitespace |
| `competitive-ads-extractor` | 從 /spy 抓到的競品廣告中拆出可複製骨架:hook pattern、pain framing、social proof、CTA、視覺 grid |
| `bulk-creative` | 批量產 10-30 套廣告 variant(headline × body × CTA × 視覺),強制多樣性(hook 類型、pain framing、視覺方向)|
| `ads-score` | 對廣告 variants 5 維打分(hook / CTA / value / target / risk),自動 flag 法規違規(保證/穩賺)直接 kill |
| `ads-meta` | 把 top creative 包成完整 Meta Ads Campaign / Ad Set / Ad spec(audience, budget, schedule, UTM, conversion event),手動或 API 模式 |
| **Marketing Agents 串聯** | 用戶說「Marketing Agents」= 5 個工具按序跑:`/spy` → `/competitive-ads-extractor` → `/bulk-creative` → `/ads-score` → `/ads-meta` |
| `nano-banana-pro` | 快速生成 AI 影片概念或網站，單一想法直接輸出 |
| `open-generative-ai` | 使用 OpenAI / DALL-E 生成圖片或內容（opengenai_client.py / image_generator.py） |
| `workflow` | 執行 MarketDaily 每日日報 Pipeline（tuna_pipeline → HTML → 部署） |
| `antigravity` | 生成大膽動態的 AI 影片或反重力視覺效果網站/TikTok 內容 |
| `claude-design` | 審查並統一 MarketDaily 所有頁面的設計系統一致性 |
| `site-doctor` | MarketDaily 全站自動巡檢+自動修復:scan.py 掃用戶可見錯誤(報價卡···、0 變—、undefined/NaN、API 砍資料、戰績/日報過期、console error、資產回歸)→ 對照歷史病歷表診斷 → 直接修+部署+重掃驗證;網站重大改動後或用戶反映前台怪象時必跑 |
| `email-marketing-bible` | Email 行銷聖經（68K字、908來源、19產業 playbook）：策略、自動化序列、送達率、文案、分群、合規、開信率優化 |
| `growth-strategy` | 增長策略框架：北極星指標、AARRR 海盜指標、增長迴圈、實驗方法論、留存與降低 churn |
| `referral-program` | 推薦計畫與病毒迴圈設計：雙邊/單邊獎勵、viral coefficient、推薦連結系統、大使計畫 |
| `pricing-strategy` | 定價策略與定價頁優化：Freemium/試用/分級/用量計費、定價心理學、錨定效應、SaaS 定價最佳實踐 |
| `stock-analyzer` | 美股/中港股技術+情緒分析：單股/多股/大盤復盤，輸出核心結論+進出場作戰計畫+風控清單 |
| `tw-financial-analysis` | 台股三維財務分析：從 Goodinfo.tw 抓財報，生成互動式 HTML 儀表板（經營/獲利/財務健全度），含三層驗證 |
| `ai-trader` | AI 交易訊號平台（ai4trade.ai）：發布訊號、跟單、管理美股/加密貨幣/Polymarket 模擬部位 |
| `tw-stock-agent` | 台股即時數據 MCP Server：TWSE/TPEx 報價、技術分析四點信號、基本面與市值 |
| `invest-skill` | 美股 AI 投資分析 21 框架：DCF 估值、財報解讀、內部人交易、機構持股、選擇權策略、競爭分析 |
| `tw-stock-scraper` | 台股盤後數據爬蟲：TWSE/OTC 歷史數據、K線圖（5/10/20/60MA）、三大法人買賣超視覺化 |
| `trading-skills-pro` | A股量化交易 CLI（Tushare Pro）：7大模組含期貨/外匯/Alpha因子/概念板塊，50+查詢工具 |
| `trade-bot` | 多平台自動交易機器人框架（`trading_bot/`）：回測、模擬交易、實盤（ccxt 100+ 交易所）、風控/緊急停損、Polymarket 錯價掃描；預設 paper 模式 |
| `tradingagents` | TradingAgents 多代理 LLM 交易框架：分析師/多空辯論/交易員/風控協作做交易決策，支援 Claude/GPT/Gemini/Grok 等多模型 |
| `ccxt` | CCXT 加密貨幣交易所統一函式庫：一套 API 接 100+ 交易所，行情/下單/餘額/websocket/testnet，含金鑰安全規範 |
| `finrobot` | FinRobot 開源金融 AI 代理平台：多代理做市場預測、財報/SEC 分析、股票投研報告、演算法交易 |
| `quant-math` | 交易/決策核心數學：機率與貝氏、期望值與 edge、校準（Brier/log loss）、Kelly 下注、波動拖累、Sharpe/回撤、統計顯著性、套利與投組相關性；任何下注/風險/績效計算前必算 |
| `backtest-validation` | 判斷交易策略回測 edge 是真實還是過度擬合：walk-forward 樣本外測試、參數敏感度（平台 vs 尖峰）、N≈1/edge² 樣本量、多重檢定/Deflated Sharpe、真實成本建模、regime 覆蓋；策略上實盤前必驗（範本 trading_bot/analyze_robustness.py） |
| `pm-mispricing` | 預測市場結構性錯價：二元 Dutch book 套利（YES+NO<$1）、多結果 under/overround、favorite-longshot bias（冷門高估）；扣費利潤+Kelly 下注（範本 quant_lab/pm_mispricing.py） |
| `dcf-valuation` | 折現現金流估值：兩階段 FCF 投影、CAPM 求股東權益成本、WACC、Gordon 永續終值、每股合理價、WACC×終值成長敏感度網格（範本 quant_lab/dcf_valuation.py） |
| `portfolio-optimization` | 投組權重配置：Markowitz 最小變異/最大 Sharpe 切點、風險平價（equal risk contribution）、1/N 基準;估計誤差為何讓最佳化脆弱（範本 quant_lab/portfolio_optimizer.py） |
| `regime-detection` | 偵測市場狀態（趨勢/均值回歸/隨機漫步）：Hurst 指數、variance ratio、漂移vs動能差別、當策略進場閘門;含「過濾器不會無中生有 edge」的誠實教訓（範本 trading_bot/bot/regime.py） |
| `order-execution` | 進場/下單執行的真學問：為何散戶贏不了延遲競賽（HFT 結構性現實:co-location/微波/FPGA）、maker vs taker、捕捉價差、滑價/市場衝擊、逆選擇、訊號時效;maker 是條件性成本優勢非必勝（範本 quant_lab/execution_cost.py） |

### 邊際/量化進階技能（edge pipeline + 投資選股）
| 技能 | 用途 |
|------|------|
| `edge-pipeline-orchestrator` | 串起完整 edge 研究管線：候選偵測→策略設計→匯整排名→postmortem |
| `edge-signal-aggregator` | 匯整並排名多個 edge-finding skill 輸出的訊號，產出統一候選清單 |
| `edge-strategy-designer` | 把抽象 edge 概念轉成策略草稿變體，可選匯出成可執行 ticket |
| `signal-postmortem` | 記錄並分析 edge pipeline 等 skill 產生的訊號實際交易結果，回饋學習 |
| `institutional-flow-tracker` | 追蹤機構投資人持股變動與資金流向（13F/持股異動） |
| `macro-regime-detector` | 偵測結構性總經 regime 轉折（1-2 年視角），跨資產比率分析 |
| `market-breadth-analyzer` | 用 TraderMonty 公開 CSV 量化市場廣度健康度，輸出 0-100 綜合分 |
| `options-strategy-advisor` | 選擇權策略分析與模擬：理論定價、希臘字母、策略損益 |
| `position-sizer` | 多單風險式部位大小計算（依停損距離與帳戶風險） |
| `vcp-screener` | 篩 S&P 500 的 Minervini VCP 波動收縮型態 |
| `stanley-druckenmiller-investment` | Druckenmiller 策略合成器：整合 8 個上游 skill 輸出（市場廣度/總經 regime 等）做投資決策 |

### DeFi / 鏈上安全技能
| 技能 | 用途 |
|------|------|
| `defi-amm-security` | Solidity AMM/流動性池/swap 安全檢查清單（重入、價格操縱等） |
| `evm-token-decimals` | 防跨鏈 token decimals 靜默不一致 bug：runtime decimal 查詢、鏈別差異 |

### AI / Agent 工程技能
| 技能 | 用途 |
|------|------|
| `agentic-engineering` | 以 agentic engineer 模式運作：eval-first 執行、任務分解、成本感知 |
| `ai-first-engineering` | AI agent 產出大量實作的團隊工程運作模型 |
| `ai-regression-testing` | AI 輔助開發的回歸測試策略：sandbox-mode API 測試不污染 prod |
| `agent-eval` | 多 coding agent（Claude Code/Aider/Codex 等）在自訂任務上的對打比較 |
| `eval-harness` | Claude Code session 的正式評估框架，eval-driven 開發 |
| `council` | 四聲音 council 處理模糊決策/取捨/go-no-go 判斷 |
| `iterative-retrieval` | 漸進式精煉 context 檢索，解 subagent context 問題 |
| `cost-aware-llm-pipeline` | LLM API 成本優化：依任務複雜度路由模型、預算控管 |
| `context-budget` | 稽核 Claude Code context window 消耗（agent/skill/MCP/rules） |
| `cost-tracking` | 追蹤並回報 Claude Code token 用量、花費、預算 |
| `autonomous-loops` | 自主 Claude Code loop 的模式與架構（序列/管線/品質閘） |
| `continuous-agent-loop` | 連續自主 agent loop：品質閘、eval、恢復條件 |
| `continuous-learning-v2` | 本能式學習系統：經 hooks 觀察 session、產生原子 instinct |
| `skill-creator` | 建立/修改/改善既有 skill，並量測 skill 效能 |
| `mcp-builder` | 建構高品質 MCP server 的指南 |

### 開發 / 工程實務技能
| 技能 | 用途 |
|------|------|
| `api-connector-builder` | 依目標 repo 既有整合模式建立新 API connector/provider |
| `browser-qa` | 用瀏覽器自動化做視覺測試與 UI 互動驗證 |
| `click-path-audit` | 追蹤每個 user-facing 按鈕完整狀態變化序列找 bug |
| `deployment-patterns` | 部署工作流：CI/CD、Docker 容器化、health check、rollback |
| `error-handling` | TypeScript/Python/Go 穩健錯誤處理模式（typed errors 等） |
| `data-scraper-agent` | 為任何公開來源建全自動 AI 資料收集 agent（職缺板等） |

### 內容 / 研究 / 文件技能
| 技能 | 用途 |
|------|------|
| `content-engine` | 為 X/LinkedIn/TikTok/YouTube/電子報建平台原生內容系統 |
| `crosspost` | 跨平台內容分發（X/LinkedIn/Threads/Bluesky），自動適配各平台 |
| `deep-research` | 用 firecrawl + exa MCP 做多來源深度研究與綜合（內建 /deep-research） |
| `doc-coauthoring` | 結構化流程協作共筆文件 |
| `knowledge-ops` | 知識庫管理：多儲存層的 ingestion/sync/retrieval |

### Office 檔案處理技能（Anthropic 官方）
| 技能 | 用途 |
|------|------|
| `docx` | 建立/讀取/編輯 Word 文件 |
| `pptx` | 處理 .pptx 簡報（輸入/輸出皆可） |
| `xlsx` | 處理試算表檔案 |
| `pdf` | 處理 PDF 檔案（讀取/編輯/表單等） |

### 開發 / 技術技能（from github.com/obra + BehiSecc）
| 技能 | 用途 |
|------|------|
| `superpowers` | 多步驟執行、調試全框架：任何回應前先找 skill，強制根因分析+TDD+驗證 |
| `superpowers-lab` | 實驗性高級工作流：mcp-cli、tmux互動CLI、Slack訊息、Windows VM、語意重複偵測 |
| `skill-seekers` | 將任何文件網站/代碼自動轉換為 Claude AI skill，數分鐘完成打包 |
| `tdd-workflow` | 先寫測試再開發：強制 RED-GREEN-REFACTOR，禁止在測試失敗前寫產品代碼 |
| `systematic-debugging` | 系統性除錯：4階段根本原因分析（調查→假設→修復→驗證），禁止猜測修復 |
| `root-cause-tracing` | 根因追蹤：從錯誤症狀逆向追蹤多層呼叫鏈到真正的錯誤起源 |
| `finish-branch` | 完成開發分支：測試通過後引導選擇合併/PR/保留/捨棄並執行清理 |
| `pypict` | PyPict 組合測試：用 PICT 方法設計全面測試案例，最少測試組合達最大覆蓋率 |
| `playwright-testing` | 劇本測試：用 Playwright 自動化測試本地 Web 應用，截圖、驗證 UI 行為 |
| `fuzz-security` | Fuzz 安全測試：整合 ffuf 模糊測試器進行漏洞偵測（需授權的滲透測試/CTF）|
| `defense-in-depth` | 深度防禦：多層安全編碼規範防範 IDOR/XSS/CSRF/SQL注入，以 bug hunter 視角審查 |

### 研究 / 知識技能（from michalparkola + ComposioHQ）
| 技能 | 用途 |
|------|------|
| `tapestry` | 從多個來源構建知識圖譜：連結相關文件、找出共識與衝突、輸出結構化知識網絡 |
| `youtube-summarizer` | YouTube 摘要：下載字幕並生成結構化摘要（TL;DR + 要點 + 詳細說明）|
| `article-extractor` | 文章提取器：從 URL 萃取乾淨正文（去除廣告/導覽），存為可讀文字檔 |
| `research-indexer` | 深度研究索引：分層來源（Tier 1-3），追蹤引用，支援 PhD 級研究深度 |
| `content-research-writer` | 內容研究寫手：協作撰寫高品質文章，加入引用、改善鉤子、逐段回饋，保留作者聲音 |
| `academic-analyzer` | 學術文獻分析：解析 EPUB/PDF 學術書籍，輸出論文主旨/方法論/發現/限制 |

### 生產力 / 自動化技能（from ComposioHQ）
| 技能 | 用途 |
|------|------|
| `invoice-organizer` | 發票整理器：自動整理收據/發票以備稅務申報，標準化命名 + 分類資料夾 + 匯出 CSV |
| `file-organizer` | 文件整理器：智慧整理混亂資料夾，找出重複檔案，建議分類結構並自動執行 |
| `web-artifacts-builder` | 網頁資產生成器：用 React+TypeScript+shadcn/ui 建立精緻 HTML artifacts，打包為單一檔案 |

### Claude 程式碼 / 自動化 Hooks（from hesreallyhim）
| 技能 | 用途 |
|------|------|
| `cc-hooks-python` | CC Hooks Python SDK：輕量 Python API 撰寫 Claude Code hooks，支援攔截/放行/封鎖工具呼叫 |
| `cc-notify` | 桌面通知：任務完成或錯誤時觸發 macOS 系統通知（osascript）|
| `claude-hooks-sdk` | Claude Hooks SDK：Laravel 風格的結構化 hooks 框架，含 middleware pipeline 和 DI |
| `claudio` | Claudio 語音提醒：用 macOS `say` 指令讓 Claude Code 任務完成時開口說話 |
| `discord-notifier` | Discord/Slack 通知器：透過 webhook 發送 Claude Code 活動到團隊頻道 |
| `activity-tracker` | 活躍度追蹤器：記錄 Claude Code 使用統計並發送每日報告到 Slack |
| `code-quality-hooks` | Code Quality Hooks：自動 lint/format + 攔截 hardcoded secrets + 強制代碼風格 |
| `typescript-quality-hooks` | TypeScript 質量 Hooks：寫入後自動 tsc 型別檢查 + ESLint fix + Prettier 格式化 |

### 進階技能（from ComposioHQ/awesome-claude-skills）
| 技能 | 用途 |
|------|------|
| `code-review-skill` | 程式碼審查：派子 agent 做完整 code review（正確性/安全/性能/可維護性），輸出審查報告 |
| `api-docs-generator` | API 文件生成器：從代碼分析路由生成 OpenAPI 3.0 spec + Markdown API 參考文件 |
| `sql-generator` | SQL 生成技能：自然語言描述 → 優化 SQL 查詢，含 CTE/窗口函數/索引建議 |
| `excel-formula` | Excel 公式技能：自然語言 → Excel/Google Sheets 公式，涵蓋 XLOOKUP/財務/動態陣列 |
| `dashboard-builder` | 儀表板技能：CSV/JSON → 互動式視覺化儀表板，支援 D3.js 和 Python matplotlib |
| `ab-test-analyzer` | A/B 測試分析器：計算統計顯著性、置信區間、相對提升和業務影響，給出 SHIP/HOLD 建議 |
| `landing-page-copy` | 落地頁複製技能：生成高轉換率的落地頁文案（標題/價值主張/社交證明/CTA）|
| `content-repurposing` | 內容再利用：一篇文章 → Twitter 串文 + LinkedIn + Email + 短影片腳本 + Instagram |
| `content-refresh` | 內容重組技能：更新過時數據、改善結構、強化 SEO、現代化語氣，讓舊內容重獲流量 |
| `sales-funnel-planner` | 銷售漏斗規劃器：設計完整 TOFU/MOFU/BOFU 漏斗策略、引流機制和轉換路徑 |
| `sales-funnel-optimizer` | 銷售漏斗優化器：找出最大流失點、競品分析、按優先順序排列 A/B 測試實驗 |
| `brand-voice-amplifier` | 品牌聲音強化器：定義聲音屬性、建立風格指南、將內容重寫為一致的品牌語氣 |

### 創意 / 設計技能（from ComposioHQ）
| 技能 | 用途 |
|------|------|
| `color-palette-generator` | 配色方案生成器：為品牌/網站生成協調色盤，含 Hex 代碼、用法指引和無障礙對比度檢查 |
| `typography-pairing` | 排版配對技能：為任何設計風格推薦互補字型組合，含 CSS 實作代碼 |
| `font-pairing` | 字體搭配技能：按使用場景（SaaS/行銷/金融/創意）推薦具體字型對，附 Google Fonts 導入代碼 |
| `creative-direction` | 創意方向技能：制定品牌視覺語言、設計哲學宣言、情緒板和 Do/Don't 設計規範 |
| `ui-wireframe-generator` | UI 線框圖生成器：生成 ASCII 線框圖或 Tailwind HTML 骨架，涵蓋各類頁面佈局 |
| `brand-voice-enhancer` | 品牌聲音強化器（精簡版）：審查全通路內容一致性、消除術語、建立聲音鎖定文件 |

### 創作者經濟技能（from ComposioHQ）
| 技能 | 用途 |
|------|------|
| `podcast-outline` | 播客大綱技能：生成完整節目結構（單人/訪談/圓桌），含問題弧線、時間戳和 show notes |
| `video-style` | 視頻風格技能：分析和複製特定創作者的剪輯風格（節奏/色調/文字/音效）|
| `video-editing` | 視頻剪輯技能：短影片 ffmpeg 指令 + TikTok 腳本模板 + 字幕生成 + 剪輯清單 |
| `story-script` | 故事腳本技能：用英雄旅程/問題解決/品牌起源框架撰寫敘事腳本和案例研究 |

## 編碼規範
- 使用 Python 開發
- 不加不必要的註解
- 保持程式碼簡潔

## Skill 管理規則
- **每次用戶分享或要求建立新 skill，必須立刻更新下方自訂技能表**
- Skill 檔案位置：`~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills/<name>/SKILL.md`
- 有 URL 的 skill → 先 WebFetch 讀完再建立，確保內容正確
- 格式：名稱 + 一行中文用途說明

## 自動守望系統（2026-06-11 上線,不要重複建）
- **digest-watchdog worker**（`digest-watchdog/`,5 cron）：07:20/08:00 TW 驗早報、20:20/21:00 驗晚報——run failure/卡死/cron 沒觸發 → 自動重派一次（KV `watchdog:*` 防重）+ LINE 通知 admin;07:50 TW 派發 `site_scan.yml`。診斷:`curl .../status`。
- **site_scan.yml**：scan（`scripts/site_scan.py`,14 項,源頭=site-doctor skill 的 scan.py,改 skill 版要同步）→ fail 即 LINE → Claude 在 CI 按 `scripts/site_fix_playbook.md` 自動修（只准動 docs/,guard 強制）→ 重掃全過才部署+push,否則 revert+LINE。
- **日報整點寄出**：cron 06:20/19:25 TW 觸發只為生成,main.py `_hold_until_send_time` 等到 07:00/20:00 整點一齊寄;preflight 05:30。
- 相關 token:alert-worker `ADMIN_PUSH_TOKEN` = GH `MARKETDAILY_ALERT_TOKEN` = watchdog `ALERT_TOKEN`（同值,旋轉要三端一起）。
- 坑:workers.dev 同帳號互打被 1042 擋（用 service binding）;GH Actions skip 步驟 output=null,`null=='0'` 數字強轉=true。

## 重要慣例（從過去 session 學到）
- **🧬 白話 → 先重寫成精準 prompt 並【明寫出來給用戶看】再執行（用戶 2026-06-26 指令,2026-06-27 確認要「看得到的重寫」,所有 session 通用,含主終端機與語音終端機）**：用戶講話常很白話、口語、省略脈絡(語音輸入還有同音字/聽錯)。收到指令後**先別照字面做**：用「我記得關於老闆的一切」(CLAUDE.md、記憶庫、最近在做的事)把這句白話**重寫成一段精準的專業指令**——補省略脈絡、修同音字、講清楚真正目標。**關鍵:重寫後的 prompt 要先用一兩句明寫出來貼給用戶看(例如「我把你的意思理解成:___,這樣對嗎/開始做了」),讓他能即時校正同音字與方向,而不是只在心裡默默重寫**(2026-06-27 用戶反映「我怎麼都沒看到你在做」=之前內化不外顯,他要看得到)。確認/明顯的指令可邊寫邊做不必等回覆;模糊或高風險才停下等他點頭。用戶原話:「你用專業的 prompt 貼給自己看,你比較好做事…讓它成為基因的一部分」。已燒進 voice_term `_start_session` priming + memory `feedback-voice-prompt-rewrite`。
- **🚫 禁止手動寄信（用戶 2026-05-22 明確指令）**：非台灣時間早上 7:00，禁止做任何會寄 email 給訂閱者的動作 —— 包括手動觸發 `daily_digest` workflow、跑 `send_*.py` 測試腳本、直接 curl Brevo 寄信 API。日報**只能**由 digest-cron worker 的排程 cron（每天 06:55 UTC）自動寄出。**唯一例外**：新訂閱者歡迎信，由 Cloudflare Worker 在註冊當下自動發送，允許。已加 PreToolUse hook（`.claude/hooks/block-mass-email.sh`）強制攔截。任何發信動作有疑慮一律先問用戶，不可自行觸發。
- **🚫 社群自動發文：發前必逐字驗 caption（2026-05-26 出包）**：`marketing/daily_run.py` 跑前**必須**先 `python daily_run.py --dry` 看下一篇 id，然後讀 `social_posts.json` 對該 id 的 caption + 圖片內容，逐字比對現行方案/事實（價格、來源數、勝率、邀請制、即時市況）。任何一條對不上 → 停手不發、先問用戶。歷史教訓:5/26 我直接補發 `referral`,caption 還寫「免費方案邀請制」+「推薦 3 人 → Pro 免費 1 個月」(早改掉的舊文案);同一批 `social_posts.json` 還埋有「75+ 來源」「勝率 75.5%」「捏造訂戶 Jason」「寫死 Fed/台積電/油價」等地雷,全清空 backup 在 `marketing/social_posts.json.bak-2026-05-26`。
- **社群排程改 Cloudflare Worker cron（2026-05-26）**：原本 `~/Library/LaunchAgents/com.marketdaily.socialpost.plist` 因 Mac 睡眠 missed 14:00 firing → 改 05:00 補跑導致時間亂掉,已 unload + rename `.disabled-by-cf-worker`。改用 `social-post-cron/` worker 觸發 `social_post.yml` workflow。**目前 cron = []**(暫停,等 social_posts.json 重填新文案才開回 `0 6 * * *` = 14:00 TW)。要重啟:改 `social-post-cron/wrangler.toml` 內 `crons` 後 `npx wrangler deploy`。手動觸發:`/trigger?token=<INTERNAL_TOKEN>`。
- **不加自訂游標**：ui-pro.js 裡的 custom cursor 已刪除，不要再加
- **Email 樣式**：日報一律用完整 HTML 卡片樣式，不能是純文字
- **台股顯示**：偏好 tag 要同時顯示股票代碼 + 公司名稱
- **Admin 記住 Email**：用 `localStorage("md-admin-email-saved")` 儲存，登入時自動填入並 focus 到密碼欄
