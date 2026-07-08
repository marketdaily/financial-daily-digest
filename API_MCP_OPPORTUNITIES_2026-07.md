# API / MCP 機會地圖（2026-07-08 調研）

> 5 個平行研究 agent 上網調研的彙整。範圍：MarketDaily、量化/intel、自主機器、AI 接線生、撲克網站、影片頻道、房地產。
> 現有 key 盤點：Anthropic / Gemini / Groq / OpenAI / FAL / MuAPI / Kling(cookie) / FMP / Finnhub / FinMind / OANDA / Meta(FB+IG) / Threads / X / YouTube / Reddit / Brevo / Beehiiv / NewsAPI。LINE 全退役。

---

## 🔴 第一梯隊：立刻接（零成本或近零成本，直接治現有痛點）

| # | 項目 | 成本 | 治什麼 |
|---|------|------|--------|
| 1 | **TWSE / TPEx OpenAPI** | 免費無 key | Yahoo chart 官方備援（previousClose / 除權息兩個病歷）＋三大法人買賣超新訊號源 |
| 2 | **edgartools（pip）** | 免費 | 取代 intel 引擎手刮 EDGAR，Form 4 insider + 13F 直接出 DataFrame，維護成本砍半 |
| 3 | **Cloudflare Workers Bindings MCP** | 免費（OAuth 5 分鐘） | 對話式讀寫 KV / 管 Workers，不用再手打 `npx wrangler kv:key get` |
| 4 | **Cloudflare Workers Observability MCP** | 免費 | 直接查 Worker logs/錯誤；日報事故一半在 worker 層，配 watchdog 成完整診斷鏈 |
| 5 | **Edge-TTS（zh-TW 曉臻/雲哲）** | 免費無限 | Gemini TTS 3 RPM 瓶頸直接消失；Azure F0（50 萬字/月）當正規備援 |
| 6 | **Groq 免費層 + DeepSeek 付費** | 免費 / <$1/月 | ⚠️ Gemini 免費層 2025/12 被砍 92%（Flash 剩 ~20 RPD），429 正解=「Gemini Tier1 → Groq(1,000 RPD) → DeepSeek」三層 fallback 鏈 |
| 7 | **Seedance Fast（或 fal 上 Wan 2.5）** | ~$0.11/5秒 | 貓咪影片 $3-5/支 → $0.1-0.4/支，成本降 90% |
| 8 | **IndexNow** | 免費無審核 | 公版日報 archive 每日 push Bing 系收錄，部署後 curl 一行 |
| 9 | **PostHog 免費層** | 免費（1M events/月） | landing→註冊→Premium 完整轉換漏斗，GTM 決策終於可量化 |
| 10 | **marketdata.app** | 免費 100 req/day | 唯一免費美股選擇權鏈＋greeks，自算 put/call 異動當土製 unusual activity |
| 11 | **FRED + DBnomics** | 免費 | 日報宏觀段真源＋regime detection 輸入；DBnomics 補台灣/亞洲數據 |
| 12 | **Alpaca MCP（paper key）** | 免費 | edge 驗證從回測走到模擬實盤，補「上實盤前必驗」最後一環 |

## 🟡 第二梯隊：低成本高回報（要一點工或小錢）

- **Threads API 自動發文** — 免費、250 則/日，復用現有 Meta app；先開發模式自測 2-4 週再送 App Review（首輪退件率高，備 screencast＋隱私政策；long-lived token 60 天必排程 refresh）。
- **X Pay-Per-Use** — 2026/4 改制後新戶只有按次計費：純文字 $0.015/則、含 URL $0.20/則 → 每日一則約 $6/月，X 分發從不可行變零用錢等級。
- **自建 Cloudflare Worker 短連結**（`go.marketdaily.ai`）— $0、一天工，全通路 UTM 歸因＋X 貼文可省 URL 費（連結放短域）。
- **Axiom（0.5TB/月免費）+ Better Stack（10 monitors 免費）** — Workers log 集中查詢＋外部 uptime 心跳，補「watchdog 自己掛了沒人知道」盲區。
- **Groq Whisper turbo（$0.04/hr）** — 股癌 666 集全轉約 $27，或與本地 faster-whisper 分流。
- **winrig 5080 架 ComfyUI** — Flux 量化產圖＋Wan 2.2 本地影片（lightx2v 4-step，~2 分鐘/5秒片）＋可訓貓咪 LoRA 固定角色；長期邊際成本≈0。
- **Voyage embedding（前 200M tokens 免費）或本地 bge-m3** — brainsearch 中文檢索升級，零成本。
- **ZeroBounce（100 次/月免費，每月重置）+ double opt-in** — 註冊即時 email 驗證防 bounce。
- **富果 Fugle API** — 開戶即免費 60 req/min + WebSocket 台股真即時，日報要盤中提醒時的第一名。
- **Alpha Vantage MCP / API（25 req/day）+ Marketaux（100 req/day）** — 免費新聞情緒層；或 Finnhub 免費新聞本體＋自家 LLM 打分（零增支）。
- **EarningsCall（earningscall.biz）** — 財報季日報加「法說會重點」段，9,000+ 公司 transcript。

## 🟢 第三梯隊：高潛力觀察（新產品/未來）

- **Cloudflare Durable Objects（+partyserver）** — 撲克網站後端正解：每桌一 DO＝天然防作弊房間模型，免費層即可開發，零新廠商依賴。
- **Paddle（MoR，5%+$0.50/筆）** — 台灣個人開發者賣全球的稅務合規一次解決；新產品（接線生 SaaS、撲克）收款層直接用，MarketDaily 既有 Stripe 不動。
- **AI 接線生技術棧 2026 現況** — 全包成本已降到 $0.07-0.12/min（Vapi/Retell 託管）或 ~$0.04-0.05/min（LiveKit 自架＋gpt-realtime / Inworld $0.05/min 封頂）；3 分鐘預約電話≈NT$4-11，月費制毛利充足。⚠️ 台灣落地真瓶頸=本地市話號碼要 SIP trunk 商，不是 AI 層。
- **台灣實價登錄 Open Data + Domain API（澳洲）** — 免費批次 CSV（每旬）→ cron 入庫自建全台成交 DB；Domain 免費開發者層追黃金海岸公寓 comparable sales。
- **Daytona（$200 免費額度）/ E2B（$100）** — 自主機器的不可信自生成碼隔離沙箱，安全性大升級。
- **Stagehand（Browserbase）** — 自然語言 `act()/extract()` 取代選擇器，網頁改版不再炸 script；升級現有 Playwright 自動化脆弱點。
- **Inngest（50K runs/月免費）/ Cloudflare Workflows** — GH Actions 停擺後的雲端 durable 工作流備援（winrig cron 之外的第二腿）。
- **x402（Coinbase+Cloudflare）** — HTTP 402 機器對機器付款協議，2026/3 已破 35M 筆；未來 agent 自動買數據的標準軌道，MarketDaily 數據可反向按次賣給別人的 agent。
- **Exa MCP** — 語意搜尋與 Firecrawl 互補，等自主機器研究 loop 出現覆蓋缺口再加。
- **Sentry 免費層（5K errors/月）** — Python pipeline 加兩行 SDK 得 stack trace 聚合。
- **ntfy.sh / Pushover（$5 買斷）** — 自建 web push 的死信第二通道。
- **MiniMax Speech-02** — 付費但中文 TTS 第一梯隊，貓咪影片配音升級選項。
- **OpenBB Platform** — quant_lab 研究層統一數據介面（換源不改碼）；不進日報生產管線（多依賴=多故障點）。

## ⚠️ 明確不接 / 暫緩

- **Memory 類 MCP（官方 memory / mem0 / Basic Memory）** — 自建 brainsearch+GraphRAG 已勝出。
- **yfinance / Notion / Obsidian / E2B / Slack MCP** — 重疊或無場景；Obsidian MCP 會破壞「vault 唯讀鏡像」單一真源紀律。
- **GitHub MCP 寫權限** — 帳號曾被 flag，先 read-only fine-grained PAT，避免高頻自動化寫操作。
- **Reddit 發文全自動** — 風控風險>效率收益，維持「生成自動＋送出人工」；API 只做讀取監測（PRAW 關鍵字通知）。
- **YouTube Shorts 自動上傳** — 可行但未過 API audit 的專案上傳會被鎖 private，先送審再排程。
- **Dub.co**（免費層已死，最低 $90/月）、**Product Hunt**（API 不能發佈＋平台價值下滑）、**Unusual Whales**（$48+/月暫不值）、**Cohere 試用 key**（禁商用）、**Cerebras**（模型無預告下架，只當第二備援且模型名要可配置）。

## Email 遷移路線（訂戶成長觸發）

Brevo Free（<300 封/日）→ 300-2,500 訂戶：Resend Pro $20 或 Brevo Starter $9 → >2,500：Amazon SES（$0.10/1k 封，月 $3-10）＋自建 SNS→webhook 記 bounce。送達率出問題時的砸錢選項=Postmark。

## 兩個作廢舊假設（要更新到相關腳本/記憶）

1. **Gemini 免費層已不能當備援主力**（2025/12 砍 92%：Flash ~20 RPD、TTS 10 RPD、免費產圖移除）。
2. **Groq 免費層降到 1,000 RPD**（原 14,400）——對日報量仍夠，但別再引舊數字。
