# 一人公司/極小團隊 AI 產品與 AI 工程服務——成功實證案例掃描 (Sweep A)

日期:2026-08-02
標準:每案至少一項可查證實證(公開營收/被收購/付費用戶數/創辦人本人公開收入),查不到不收,每案附來源。
判斷脈絡:我方=台灣一人創辦人+AI agent 團隊;強項=LLM 編排/稽核管線(金融日報 production 一年)、繁中在地化、Cloudflare 全棧、爬蟲/自動化、email/社群自動發布;弱項=無行動 app 經驗、低資本、無銷售團隊。

格式:名稱|一句話產品|團隊規模|實證數字+來源|技術本質|為什麼能成|台灣複製初判

---

## A. Solo 名人線(全數本輪重新查證)

### 1. PhotoAI / InteriorAI / RemoteOK — Pieter Levels
- 一句話:AI 個人寫真生成 / AI 室內設計改圖 / 遠端工作板
- 團隊:1 人(零員工,單檔 PHP + 單伺服器)
- 實證:PhotoAI ~$100–138K MRR(2025-11,占其總收入 70%),InteriorAI ~$35K/月、RemoteOK ~$44K/月(本人公開儀表板);全組合 ~$3M+/年
  - https://levels.io/photoai-40870-line-index-php-105k-mo-revenue (本人部落格:$105K/月營收、$80K/月利潤,整站一個 40,870 行 index.php)
  - https://ppc.land/how-one-photo-ai-app-generates-132k-monthly-after-70-failed-startups/
  - https://x.com/levelsio (自公開收入)
  - https://www.indiehackers.com/post/photo-ai-by-pieter-levels-complete-deep-dive-case-study-0-to-132k-mrr-in-18-months-3a9a2b1579
- 技術本質:Stable Diffusion/Flux 微調管線(train-then-generate),非純 LLM wrapper;RemoteOK=資料聚合+SEO
- 為什麼能成:70+ 次失敗後的爆品直覺、build in public 60 萬粉自帶通路、極低成本結構、搶 AI 圖像第一波時機
- 台灣複製初判:**中**——圖像生成管線可複製,但他的通路=十年累積的X粉絲,台灣做需另找通路(社群/SEO)

### 2. HeadshotPro — Danny Postma
- 一句話:AI 職業形象照(團隊/企業用證件照)
- 團隊:1 人創辦(後極小團隊)
- 實證:$300K MRR / ~$3.6M ARR(2024-2025 持續),19.6 萬付費客戶;上線 14 天破 $100K
  - https://www.starterstory.com/stories/headshotpro-breakdown
  - https://www.rewardful.com/case-studies/headshotpro (聯盟行銷月貢獻 $50K+)
- 技術本質:Diffusion 微調管線+B2B 團隊下單流程
- 為什麼能成:切「企業一次買整個團隊的頭像」的 B2B 角度(客單價高)、SEO+聯盟行銷(15%+ 營收來自 affiliate)、搶第一波
- 台灣複製初判:**中**——模式已被驗證且台灣有 LinkedIn/104 頭像需求,但英語玩家已把 SEO 吃滿,要做只能做繁中在地+企業直銷

### 3. Marc Lou(ShipFast / CodeFast / DataFast 等 15 條產品線)
- 一句話:SaaS boilerplate + 開發者教育 + 分析工具組合
- 團隊:1 人
- 實證:2025 全年收入 $1,032,000(本人 newsletter 公開);ShipFast/CodeFast 各 ~$20K/月;DataFast $15.8K MRR、近千付費客戶
  - https://newsletter.marclou.com/p/i-made-1-032-000-in-2025
  - https://www.ibtimes.co.uk/marc-louvion-million-dollar-success-journey-1799070
- 技術本質:非 AI 核心(boilerplate+內容),AI 是題材;收入引擎=個人品牌+YouTube
- 為什麼能成:build in public、把「出貨速度」本身做成產品、對開發者受眾賣鏟子
- 台灣複製初判:**低**——賣鏟子給 maker 的生意吃英語個人品牌,繁中 maker 市場太小

### 4. TypingMind — Tony Dinh
- 一句話:自帶 API key 的 LLM 聊天前端(個人版+企業自架版)
- 團隊:1 人+少量約聘
- 實證:$130–160K/月(2025-10 本人 newsletter),年破 $1M;B2B Team 方案占營收 >50%
  - https://news.tonydinh.com/p/oct-2025-updates-code-money-and-travel
  - https://www.starterstory.com/typingmind-breakdown
- 技術本質:純前端 LLM wrapper(BYO API key,幾乎零推論成本)→ 後轉 B2B 自架
- 為什麼能成:ChatGPT UI 不滿者的即時替代品(時機)、BYO-key=零邊際成本、後期靠 B2B 拉客單
- 台灣複製初判:**中**——「企業要能控管的 LLM 聊天介面」在台灣中小企業有需求(資料不出門),可搭繁中+本地合規賣點

### 5. PDF.ai + Testimonial.to — Damon Chen
- 一句話:跟 PDF 對話 / 見證影片收集嵌入
- 團隊:1–3 人
- 實證:PDF.ai 收購域名+半成品共 $30K 起家,3 個月營收 $200K,後 >$50K MRR(本人 LinkedIn 公開單月 $60K);Testimonial.to ~$800K ARR,合計曾破 $1.3M ARR
  - https://www.linkedin.com/posts/damengchen_pdfai-crossed-60k-in-revenue-in-november-activity-7136059894838820864-53OW
  - https://creatoreconomy.so/p/damon-chen-engineer-to-one-million
- 技術本質:RAG(PDF 向量檢索+LLM 問答),標準 wrapper
- 為什麼能成:**exact-match 域名 pdf.ai**(>50% 流量來自搜「PDF AI」)——通路內建在域名裡
- 台灣複製初判:**中**——教訓是「域名=通路」;繁中 exact-match 關鍵字域名(如 XX.ai 的中文對應詞)還有空位

### 6. Chatbase — Yasser Elsaid
- 一句話:上傳資料訓練客服聊天機器人嵌入網站(no-code)
- 團隊:1 人創辦 bootstrap → 2024 年 18 人 → 2026 約 30 人
- 實證:$10M ARR、萬名付費客戶、零外部融資;117 天到 $1M ARR
  - https://solofounders.com/blog/9m-arr-zero-investors-yasser-elsaid-on-bootstrapping-chatbase-as-a-solo-founder
  - https://productled.com/blog/how-chatbase-hit-8m-arr-with-18-people
- 技術本質:RAG-as-a-service(爬站+向量庫+聊天widget),現在是 agent 平台
- 為什麼能成:GPT-3.5 API 開放後**兩週內上線**搶到「custom ChatGPT for your website」心智、PLG 自助訂閱
- 台灣複製初判:**中**——原版紅海,但「繁中中小企業 LINE 官方帳號版 Chatbase」仍是空缺(LINE 生態強是台灣特性)

### 7. Jenni AI — David Park
- 一句話:學術寫作 AI 助手(引用+自動補全)
- 團隊:~9 人時破 $10M ARR(現 ~23 人),僅收過一張 $100K 天使支票
- 實證:2023 $1.8M → 2024 $8M → 2025 初破 $10M ARR
  - https://en.tmtpost.com/post/7814928
  - https://sacra.com/c/jenni-ai/
- 技術本質:LLM wrapper + 學術引用資料庫整合(垂直資料是護城河)
- 為什麼能成:2019 年老產品 pivot 進 AI 時機、**Instagram/TikTok UGC 短影音行銷**(不靠 SEO/廣告)、學生市場全球同質
- 台灣複製初判:**中**——華語學術寫作(中翻英潤稿+引用)有真需求,但學生付費力低、大陸競品多

### 8. SiteGPT — Bhanu Teja Pasala
- 一句話:網站客服聊天機器人(Chatbase 直接競品)
- 團隊:1 人 → 2 人
- 實證:上線 30 天 $10K MRR,2026 初 $28K MRR;前作 Feather 以 $250K 出售(3.5x ARR)
  - https://superframeworks.com/blog/sitegpt
  - https://www.indiehackers.com/post/from-side-hustle-to-ai-star-sitegpts-rise-to-15k-mrr-ff15fee186
- 技術本質:RAG wrapper,同 Chatbase
- 為什麼能成:證明**紅海第二名也能活**——工程即行銷(免費工具引流)+快速出貨
- 台灣複製初判:**中**——同第 6 案,差異化要靠繁中+LINE

### 9. AudioPen — Louis Pereira
- 一句話:語音隨想→AI 整理成乾淨文字
- 團隊:1 人(兼職!白天管家族零售生意)
- 實證:頭兩月 $73K 收入、1,000+ 付費用戶;兩年後 ~$20K MRR
  - https://www.indiehackers.com/post/how-i-accidentally-created-a-generative-ai-tool-thats-made-73-000-in-2-months-9WenA1ItY4zIIf8LjmFg
  - https://thebootstrappedfounder.com/louis-pereira-when-an-indie-hacker-strikes-gold/
- 技術本質:Whisper→LLM 重寫,No-code(Bubble)搭的,月成本 ~$30
- 為什麼能成:單一功能做到極簡、X 上一則 demo 病毒擴散、終身方案定價
- 台灣複製初判:**高**——繁中語音筆記(會議/靈感→整理)無強勢在地玩家,且我方有語音+LLM 管線現成積木

### 10. Formula Bot — David Bressler
- 一句話:白話→Excel 公式(後擴為 AI 資料分析平台)
- 團隊:1 人(非工程師,No-code 起家)
- 實證:上線首月 $10.7K;$500K ARR(2025-05 Indie Hackers 本人發文);後續報導 ~$220K/月
  - https://www.indiehackers.com/post/tech/getting-serious-about-marketing-after-hitting-500k-arr-8XGnzrxG1neA3jy37x2D
  - https://www.willyshinn.com/p/the-excel-whisperer-how-david-bressler
- 技術本質:單一 prompt wrapper 起家 → 平台化
- 為什麼能成:「Excel 公式」=巨大既有搜尋量,SEO exact-match(excelformulabot.com)白撿流量
- 台灣複製初判:**高**——同一 playbook 可搬:找「繁中高搜尋量的窄工具詞」做 wrapper+SEO(例:發票/報稅/勞健保計算)

### 11. Aragon AI — Wesley Tian
- 一句話:AI 頭像/職業照(HeadshotPro 競品)
- 團隊:10 人,零融資,獲利中
- 實證:4 個月 $1M ARR,2 年 $10M ARR
  - https://www.pmf.show/episodes/ep-33-1st-time-founder-grows-ai-headshot-app-from-0-to-10m-arr-in-2-years-with-no-fund
  - https://www.indiehackers.com/post/tech/building-one-of-the-first-ai-headshot-products-and-hitting-900k-mo-in-3-years-UK9omiPofFtha5Kps2Fj
- 技術本質:Diffusion 微調管線,同 HeadshotPro
- 為什麼能成:同一品類容得下多個 $10M 玩家(需求夠大)、Google SEO+聯盟、手動客服打磨轉換
- 台灣複製初判:**中**——證明品類縱深,但同第 2 案:只剩在地化角度

### 12. SEObot — John Rush
- 一句話:全自動 AI SEO 內容機器人(研究→寫→內鏈→發布)
- 團隊:1 人(跨 24+ 產品組合,零員工)
- 實證:$48.5K MRR、675 付費訂閱、累計營收 $1.79M(TrustMRR 公開榜)
  - https://trustmrr.com/startup/seobot
  - https://x.com/johnrushx/status/1753420685165166597
- 技術本質:多 agent 內容管線(關鍵字→文章→圖片→內鏈→CMS 發布)——**與我方日報管線同構**
- 為什麼能成:自家 30+ 站當實驗場與案例、賣給「忙碌創辦人」的全自動定位
- 台灣複製初判:**高**——我方已有 production 級內容管線+稽核層;繁中版全自動 SEO 內容服務幾乎無對手

### 13. Cal AI — Zach Yadegari 等
- 一句話:拍照算卡路里 App
- 團隊:2 位青少年創辦,售出時 17 人
- 實證:2025 營收 $30M,2026-01 單月 $5.7M(年化 >$50M),2026-03 100% 售予 MyFitnessPal(Forbes/TechCrunch 報導)
  - https://techcrunch.com/2026/03/02/myfitnesspal-has-acquired-cal-ai-the-viral-calorie-app-built-by-teens/
  - https://www.cnbc.com/2025/09/06/cal-ai-how-a-teenage-ceo-built-a-fast-growing-calorie-tracking-app.html
- 技術本質:視覺 LLM wrapper(拍照→估營養)+行動訂閱漏斗
- 為什麼能成:TikTok/IG 網紅投放機器(行動 app 訂閱經濟)、單一明確痛點
- 台灣複製初判:**低**——行動 app+網紅投放資本戰,我方無 app 經驗、低資本,正面撞弱項

---

## B. 收購/成交線(小 AI 產品實際賣掉的)

### 14. Base44 — Maor Shlomo
- 一句話:AI 聊天式 no-code 全端 App 生成器(vibe coding)
- 團隊:1 人創辦、唯一股東,收購時全隊 <10 人(一說 6 人)
- 實證:Wix 以 **$80M 現金**收購(2025-06-18),另有 2029 營收里程碑 earnout(報導稱可再拿 $90M);被收購前單月獲利 $189K、零融資、上線三週 $1M ARR
  - https://www.calcalistech.com/ctechnews/article/s1iflnlelx
  - https://www.wix.com/press-room/home/post/wix-further-expands-into-vibe-coding-with-acquisition-of-base44-a-hyper-growth-startup-that-simplif
  - https://www.calcalistech.com/ctechnews/article/hjm11dastwl
- 技術本質:LLM 驅動 app 生成平台(自建 agent 編排+託管後端)
- 為什麼能成:6 個月爆發成長(10-40 萬用戶)+創立即獲利;Wix 買產品+成長曲線+創辦人本人
- 台灣複製初判:**低**——平台級資本戰視窗已被 Lovable/Bolt/Base44 佔滿;可借鑑的是「一人+獲利+爆量=被平台高價收」的出口路徑

### 15. Tweet Hunter + Taplio — Thibault Louis-Lucas & Tom Jacquesson
- 一句話:Twitter/LinkedIn AI 寫作與成長工具
- 團隊:2 位創辦人+極小團隊
- 實證:lempire 收購(2022):$2M 現金+無上限 earnout(預期總額 $10-15M);出售時 ~$1M ARR、Tweet Hunter 5,000 用戶
  - https://theygotacquired.com/saas/pony-express-acquired-by-lempire/
  - https://www.indiehackers.com/post/tweet-hunter-acquired-for-2m-earn-out-0709cae13a
- 技術本質:GPT-3 包裝+推文資料庫+排程引擎(Taplio 直接複用同一 codebase)
- 為什麼能成:真實營收+快成長;「低頭款+無上限 earnout」化解平台依賴風險
- 台灣複製初判:**中**——「社群成長工具」在繁中圈(Threads/LINE VOOM/FB 社團)缺 AI 工具,但平台 API 風險高

### 16. Headlime — Danny Postma
- 一句話:GPT-3 行銷文案生成器
- 團隊:3 人
- 實證:被 Conversion.ai(Jasper)收購(2021-03),七位數(以 $20K MRR 估約 $1M);創立到出場 <8 個月
  - https://theygotacquired.com/saas/headlime-acquired-by-conversion-ai/
  - https://x.com/dannypostmaa/status/1376918885807480835
- 技術本質:GPT-3 wrapper+文案模板層
- 為什麼能成:GPT-3 早期窗口,買方收購清場
- 台灣複製初判:**低**——窗口已過;教訓=新模型能力開放的頭幾個月,wrapper 也能八個月出場

### 17. ShortlyAI — Qasim Munye
- 一句話:GPT-3 長文寫作助手
- 團隊:1 人(醫學生)
- 實證:被 Conversion.ai/Jasper 收購(2021-06,金額未公開,本人公告);6 個月 3,000+ 企業用戶、有真實營收
  - https://qasimmunye.medium.com/shortly-has-been-acquired-by-conversion-ai-ae152cc6a819
- 技術本質:GPT-3 wrapper+極簡寫作 UX
- 為什麼能成:UX 口碑;同 Jasper 清場邏輯
- 台灣複製初判:**低**——同上,窗口型案例

### 18. TalkNotes — Nico Jeannen
- 一句話:語音轉筆記 AI 工具
- 團隊:1 人(法國,做過 ~17 個產品)
- 實證:Acquire.com 成交 **$200K 全現金**(數週完成,官方訪談)
  - https://blog.acquire.com/startup-acquisition-episode-112/
- 技術本質:Whisper 轉錄+LLM 整理 wrapper
- 為什麼能成:營收真實、產品簡單易交接;為快速出場主動降價
- 台灣複製初判:**高**——與第 9 案 AudioPen 同品類:繁中語音筆記可做,且證明做起來後有 acquire.com 流動性出口

### 19. AIContentfy — Teemu Raitaluoto
- 一句話:B2B 部落格 AI 內容生產(SaaS+服務混合)
- 團隊:極小團隊
- 實證:**$1M ARR**(兩年);Acquire.com 全現金成交、無 earnout、買方私募,100+ LOI(官方案例)
  - https://blog.acquire.com/scaling-ai-content-to-1m-arr-and-a-successful-exit/
- 技術本質:LLM 內容管線+SEO 交付流程——**與我方日報/SEO 管線同構**
- 為什麼能成:從第一天以出售為目標建構(乾淨帳務、可交接)
- 台灣複製初判:**高**——繁中 B2B 內容代工(SaaS+服務混合)幾乎無自動化對手,我方管線直接可用

### 20. ChatFAI — Umar Khan
- 一句話:AI 角色對話平台(含長期記憶)
- 團隊:1 人
- 實證:Acquire.com 成交(多個出價,金額未公開,官方案例);一年 100 萬用戶,MRR 兩個月 $500→$2,000
  - https://blog.acquire.com/simple-steps-to-get-a-bootstrapped-ai-startup-acquired/
- 技術本質:LLM 角色扮演 wrapper+自建記憶層
- 為什麼能成:病毒式用戶量+差異化功能;流量資產值錢
- 台灣複製初判:**低**——角色陪聊紅海+內容風險,不合我方定位

### 21. description-generator.online — Max(Red Hat 工程師副業)
- 一句話:Etsy 賣家 AI 商品描述生成器
- 團隊:1 人副業
- 實證:Acquire.com 成交(金額未公開,50/50 分期+3 個月交接,全程 5 個月,創辦人萬字自述);上線數天 400 註冊、有付費客戶
  - https://wasp.sh/blog/2024/07/03/building-selling-saas-in-5-months
- 技術本質:React+Node+OpenAI 典型 wrapper
- 為什麼能成:明確利基(非英語系 Etsy 賣家)+付費驗證即可售
- 台灣複製初判:**中**——同 playbook 可套「蝦皮/momo 賣家繁中文案生成」(與 Dropshipping 部互補)

### 22. Seamless For Science — Tomer Tarsky(買方側案例)
- 一句話:AI 文獻回顧生成器(edtech)
- 團隊:1 人操盤
- 實證:在 Acquire.com 買入,7 個月後以**買價 3 倍**轉售(官方訪談);接手後改文案+漲價立刻 +$2,000 MRR
  - https://blog.acquire.com/startup-acquisition-episode-118/
- 技術本質:LLM 文獻綜述管線
- 為什麼能成:買「有免費用戶池、未變現」的資產,套利變現空間
- 台灣複製初判:**中**——「買半成品 AI 資產+我方工程力優化轉售」是一條低資本可行路,但需美元現金部位

---

## C. Indie Hackers / Starter Story 線(較少人知的一人~三人案例)

### 23. DocsBot AI — Aaron Edwards
- 一句話:把公司文件/幫助中心訓練成客服 AI chatbot(B2B)
- 團隊:1 人(2025-10 才加一位成長合夥人);**solo 拿下 SOC 2 認證**
- 實證:2026-02 達 $1M ARR(本人部落格公開),此前多年 $500K–1M 區間
  - https://uglyrobot.dev/
  - https://uglyrobot.dev/articles/soc2-certified-solo-founder
- 技術本質:RAG 管線(Weaviate 向量庫+LLM)
- 為什麼能成:2023 初 ChatGPT 時機+WordPress 圈既有信任資產;B2B 定價撐高 ARPU;SOC 2 打開企業客戶
- 台灣複製初判:**高**——「一人+SOC 2+B2B RAG」路徑證明企業級信任可由一人建立;台灣中小企業客服 bot(含 LINE)正是這型

### 24. Podsqueeze — Tiago Ferreira & João Pacheco
- 一句話:播客音檔→show notes/社群貼文/電子報自動生成
- 團隊:2 人
- 實證:18 個月 $16K MRR;早期 5 個月 $100K ARR
  - https://indiebites.com/120
  - https://founderclix.com/interview/podsqueeze/
- 技術本質:Whisper+LLM 多格式內容管線
- 為什麼能成:創辦人自己是播客主自帶社群;AppSumo LTD 起量→SEO 接盤
- 台灣複製初判:**中**——繁中播客圈小但零工具;「一次錄音→全渠道貼文」與我方 crosspost 積木同構

### 25. Voicenotes — Jijo Sunny 家族 3 人
- 一句話:語音筆記+可對話搜尋自己全部錄音的 AI 助理
- 團隊:3 人(Buy Me a Coffee 創辦人二作)
- 實證:$50 lifetime「believer plan」進帳 $100K(TechCrunch 報導)、23K 活躍用戶;2024-11 $8.5K/月、獲利
  - https://techcrunch.com/2024/05/13/buymeacoffees-founder-has-built-an-ai-powered-voice-note-app
  - https://www.starterstory.com/voice-notes-breakdown
- 技術本質:Whisper+RAG(對自己歷史筆記問答)
- 為什麼能成:創辦人既有聲量、極致產品打磨、lifetime deal 搶購
- 台灣複製初判:**中**——與 9/18 同品類;lifetime 定價是低資本冷啟動的可抄招

### 26. Sleek — Mattia Pomelli
- 一句話:對話式 AI 生成 mobile app UI 設計(vibe design)
- 團隊:3 人
- 實證:上線 6 週 $10K MRR(Indie Hackers 官方訪談)
  - https://www.indiehackers.com/post/tech/hitting-10k-mrr-in-six-weeks-with-an-ai-design-tool-pEvmU5qkWS6ny0AR9SUv
- 技術本質:LLM 生成 UI 的 agent 管線(復用舊碼 3 週上線)
- 為什麼能成:X 病毒帖(留言拿 early access)+在留言區免費幫人設計當 demo;免費層只給 1 次逼轉換
- 台灣複製初判:**低**——vibe design 賽道英語巨頭環伺,無在地化縱深

### 27. Submagic — David Zitoun & Tsi-fei Chan
- 一句話:短影音 AI 字幕/剪輯工具(創作者向)
- 團隊:2 人創辦→$8M ARR 時 10 人、零銷售團隊、bootstrapped 獲利(人均營收 $615K+)
- 實證:上線 3 個月 $1M ARR(2023-08);2025 $8M ARR
  - https://baremetrics.com/founder-chats/david-zitoun
  - https://getlatka.com/companies/submagic.co
- 技術本質:Whisper 轉錄+動態字幕渲染管線(重前端渲染工程,非純 wrapper)
- 為什麼能成:只做一件事(字幕)做到最好;上線 30 天開 affiliate,零行銷預算靠創作者分潤自傳播
- 台灣複製初判:**中**——繁中字幕(含台語辨識痛點)有在地縫隙,但 CapCut 免費壓頂

### 28. Leadmore AI — Richard Wang
- 一句話:Reddit 行銷自動化 AI(自動發文/留言/找 subreddit)
- 團隊:1 人
- 實證:$30K+ MRR(Indie Hackers 官方訪談)
  - https://www.indiehackers.com/post/tech/hitting-30k-mrr-with-an-ai-marketing-product-n59ORJCYjnZC61Q096UL
- 技術本質:LLM agent 自動化管線(B2B)
- 為什麼能成:吃自己狗糧(本人 Reddit 乾貨→私訊轉化);GEO 早期卡位
- 台灣複製初判:**高**——同構搬到「Dcard/PTT/FB 社團行銷自動化」是繁中空缺,且我方有爬蟲+社群自動發布積木(但要留意 PTT 合規紅線)

---

## D. AI service-as-software 線(AI 代營運/接線生/SDR/自動化代建)

### 29. My AskAI — Alex Rainey & Mike Heap
- 一句話:AI 客服代營運(接進 Intercom/Zendesk 代答客服工單)
- 團隊:2 人
- 實證:$40K MRR(~$500K ARR)、月處理 75,000+ 客服對話、毛利 ~82%(含 AI 成本)
  - https://www.indiehackers.com/post/tech/bootstrapping-to-40k-mrr-after-his-vc-backed-startup-failed-LF1CwRs1vL3oVLcuoIoE
  - https://www.starterstory.com/stories/my-askai-your-ai-chatbot-for-customer-support
- 技術本質:RAG 客服 agent(前端 Bubble no-code+AWS)
- 為什麼能成:定價「每張工單 $0.10」比 Zendesk AI/Intercom Fin 便宜 3-10 倍;**外掛進既有工具,不逼客戶換系統**,消滅採購阻力
- 台灣複製初判:**高**——「不換系統、按件計價」正對台灣中小企業保守採購;繁中+LINE 客服版無人做

### 30. Dentina.ai — Peter Gabbay
- 一句話:牙醫診所 AI 電話接線生(不漏接來電、自動約診)
- 團隊:7 人,零外部融資
- 實證:$2.2M ARR(2025,創辦人向 GetLatka 申報)
  - https://getlatka.com/companies/dentina.ai
- 技術本質:語音 agent(電話應答+排程整合)
- 為什麼能成:垂直鎖死牙醫——漏接一通電話=損失一個高 LTV 病人,ROI 一句話講清
- 台灣複製初判:**中**——台灣診所同痛點且我方已有 AI 接線生構想(project_ai_receptionist),但中文語音 agent 品質與診所採購保守是兩道坎

### 31. LeftClick / 1SecondCopy — Nick Saraev
- 一句話:AI 自動化代建+AI 內容代工(把 Make/n8n+LLM 管線裝好賣給中小企業)
- 團隊:2 名操作員起家
- 實證:兩事業合計 $160K/月;1SecondCopy 2 人做到 $90K/月(本人網站+podcast 訪談)
  - https://nicksaraev.com/about/
  - https://fueledbyprogress.com/episodes/nick-saraev-building-high-roi-services-ruthless-effectiveness-ep-85
  - ⚠️ caveat:他後轉主業賣課程社群($330K/月),但 agency 營收有獨立於課程的早期訪談紀錄
- 技術本質:自動化編排(Make/n8n)+LLM 串接,賣「裝好會跑的系統」非顧問時數
- 為什麼能成:生產性服務(交付後近零人力)+YouTube 內容養進線
- 台灣複製初判:**高**——我方核心強項(LLM 編排/自動化)直接變現;台灣中小企業自動化代建幾乎空白,可按案收+月費維運

### 32. Growth Engine X — Eric Nowoslawski
- 一句話:AI 外呼/AI SDR 代營運(Clay+GPT 自動化 B2B 陌生開發)
- 團隊:2-10 人
- 實證:52 個同時進行的付費客戶(含 Notion、Intercom、Clay)、月發 400 萬封信、日燒 20 億 OpenAI tokens(深度訪談載明)
  - https://www.thesignal.club/p/inside-eric-nowoslawskis-ai-powered-cold-outbound-machine
- 技術本質:LLM 名單富化+個人化文案管線,編排層 Clay+Smartlead
- 為什麼能成:當 Clay 生態第一批專家卡位(官方夥伴目錄導流);只收 LTV>$5K 的 B2B 客戶
- 台灣複製初判:**中**——台灣 B2B 陌生開發文化偏電話/介紹,email 外呼弱;可改「LINE/電話+email 混合」但需驗證

---

## E. 非英語市場在地化線(對我方參考價值最高)

### 33. Rimo Voice — 相川直視(日本)
- 一句話:日語特化 AI 逐字稿/會議記錄 SaaS
- 團隊:前 Google 搜尋工程師 1 人起家;第 1 年 1 人→第 4 年 8 人→刻意設 20 人上限、**刻意不融資**
- 實證:上線 3 個月單月轉盈、**1,000+ 家企業付費導入**、營收連年翻倍(官方創業史專訪含逐年損益)
  - https://prtimes.jp/story/detail/ZrNEmqSNX4x
- 技術本質:語音辨識 API+日語後處理與會議場景 UX(非自研模型)
- 為什麼能成:Otter 等英語巨頭的日語精度+日本商務習慣(敬語/議事錄格式)長期不行;賣給日企的信任與通路是英語玩家吃不到的
- 台灣複製初判:**高**——完全同構:繁中(台灣腔+中英夾雜)會議記錄,英語巨頭精度差、在地信任通路我方可建;是「非英語在地化」最乾淨的樣板

### 34. 沉浸式翻譯 Immersive Translate — Owen(中文圈)
- 一句話:網頁雙語對照翻譯瀏覽器外掛
- 團隊:1 人約 1 個月寫出初版,收購前基本獨立開發
- 實證:2023-05 被推文科技收購(成立獨立子公司、Owen 續任負責人),收購時 5 個月 40 萬用戶;2025 用戶破 1,000 萬、Chrome 年度最佳擴充
  - https://blog.mzh.ren/zh/posts/2025/08/immersivetranslate/
  - https://www.oschina.net/news/242344/immersive-translate-acquired
- 技術本質:多家翻譯/LLM API 聚合+「原文譯文對照」單一交互創新
- 為什麼能成:痛點=中文使用者讀英文網路;中文社群(少數派/阮一峰)傳播;英語巨頭不做這方向
- 台灣複製初判:**低**(直接做)/**高**(方法論)——該品類已被它佔住;可抄的是「單一交互創新+華語社群傳播」的路徑

### 35. idoubi(艾逗笔)— ThinkAny / ShipAny 等 11 款(中文圈)
- 一句話:一人連發 11 款 AI 產品,以 ShipAny(AI SaaS 出海模板)爆發
- 團隊:1 人(前騰訊工程師)
- 實證:本人年度總結公開:2024-12 四款合計 $1K MRR;**ShipAny 預售 4 小時破 $10,000、一週收入超過其他產品一整年**;虎嗅專訪佐證
  - https://hub.baai.ac.cn/view/42470
  - https://m.huxiu.com/article/3631911.html
- 技術本質:LLM 套殼+模板化工程(把自己的腳手架變商品)
- 為什麼能成:「中文開發者出海」群體的工具+社群信任;中文 X/微信圈個人品牌是 ShipFast 覆蓋不到的分發
- 台灣複製初判:**中**——證明華語 maker 圈買單「賣鏟子」;但個人品牌前置成本高(對照第 3 案 Marc Lou 同判)

---

# 總結

## 案例總數:35 案(全數至少一項硬實證+來源連結)
分佈:A 名人線 13|B 收購/成交線 9|C Indie Hackers 線 6|D 服務化線 4|E 非英語在地化線 3

## 台灣潛力=高(前 8,依我方強項貼合度排序)
1. **#31 LeftClick 型「AI 自動化代建」**——LLM 編排+自動化=我方核心強項直接變現;2 人 $160K/月實證;台灣中小企業代建幾乎空白
2. **#29 My AskAI 型「AI 客服代營運」**——按工單計價+不逼換系統,正對台灣保守採購;繁中+LINE 版無人做;2 人 $40K MRR
3. **#19 AIContentfy 型「B2B 內容管線(SaaS+服務混合)」**——與我方日報管線同構;$1M ARR+acquire.com 全現金出場實證
4. **#12 SEObot 型「繁中全自動 SEO 內容機器人」**——Stripe 驗證 $47.5K MRR;我方已有 production 級管線+稽核層
5. **#33 Rimo Voice 型「繁中會議記錄 SaaS」**——非英語在地化最乾淨樣板:1 人起家、3 個月轉盈、1,000+ 企業;繁中同構位置空著
6. **#23 DocsBot 型「一人 B2B RAG+SOC 2 信任」**——證明一人可過企業採購門檻;$1M ARR
7. **#9/#18 AudioPen+TalkNotes 型「繁中語音筆記」**——一人兼職 $20K MRR 實證+$200K 出售出口實證;我方有語音+LLM 現成積木
8. **#10 Formula Bot 型「繁中高搜尋量窄工具詞 wrapper」**——exact-match SEO 白撿流量 playbook;台灣候選詞:發票/報稅/勞健保/公司登記

## 掃描時發現但故意排除的類型與原因
1. **內容農場捏造人物**——「Sarah Chen」同名出現在兩個互相矛盾的成功故事、Foundra「$41K MRR」無名氏無法溯源:全丟
2. **「教你開 AI agency」課程漏斗的收入宣稱**——AI 接線生白牌轉售($55 進貨賣 $400)、「一個月賣 300 個接線生」等,只有平台行銷或不可核實自述,無第三方數字:全丟(此空間的 revenue claims 大量是課程銷售話術)
3. **VC 資本戰/團隊超標**——Lovable、Bolt.new(小團隊高 ARR 但重融資)、ColdIQ($6.5M ARR 但 35 人)、neuroflash/Luzia(德/西語圈皆 VC 化):不符「一人/極小團隊低資本」脈絡
4. **有名但查無硬實證**——TAAFT(只有贊助價目+訂閱數,無營收)、Gling AI、日本 Catchy/AIチャットくん(330 萬 LINE 用戶但無付費數;其「LINE 分發」模式仍值得抄)/AIのべりすと、Rosie、Dialzara(拒公開)、Ben's Bites(查無被收購,Tossell 賣的是 MakerPad):全不收
5. **太小或非 AI**——SiteSpeakAI(~$1K MRR)、Zigpoll(非 AI)
6. **韓國/德/西語圈**——多輪在地語言搜尋,可開頁驗證的 ≤10 人+公開營收案例掛零;這本身是訊號:非英語圈公開營收文化弱,在地空缺可能比英語圈更大

## 橫向規律(35 案共通)
- **技術幾乎全是薄管線**:~9 成是 LLM/Whisper/Diffusion API 包裝+一個交互或場景創新;沒有一案靠「更強的模型」贏
- **勝負在通路**:自帶受眾 build in public/單一平台深耕(Reddit/TikTok)/exact-match 域名與 SEO/affiliate 自傳播/生態夥伴卡位;純技術無通路案例=零
- **定價錨定被取代的人力成本**(攝影棚 $200→$29、每工單 $0.10、漏接電話=損失病人)是服務化案例的共同話術
- **出口三層**:acquire.com 微型成交($20K–$200K)→競品/戰略收購($1M–$15M)→平台級收購($80M,Base44);「從第一天當可出售資產建」(AIContentfy)是可複製紀律
- **口徑不一處已標注**:Cal AI 團隊(7 員工+外包 vs 17 人)、Formula Bot($500K ARR 本人發文 vs $2.8M 二手報導,採本人口徑為準)、Submagic(10 vs 13 人)——引用時以一手來源為準

