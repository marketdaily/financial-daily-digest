# 小型 AI 新創商業模式掃描 B(2026-08-02)

任務:掃出「種子輪以下或小團隊 AI 新創正在驗證的商業模式」,重點=垂直 AI agent 與 AI 工程基礎設施,評估一人+AI 團隊在台灣的可複製性。
方法:WebSearch/WebFetch 逐案查證(YC W25/S25/F25/W26、YC RFS Fall 2026 全文、歐美 AI 代營運、未 bundled 專業服務、日韓東南亞在地化案例)。
判斷脈絡:我方強項=LLM 編排+稽核閘門(金融 production 實證)、繁中、爬蟲自動化、CF 全棧、零邊際成本管線;台灣=中小企業密度高、LINE 滲透極高、專業服務人力貴且數位化低。

---

## 第一部分:YC 近批次總體觀察

- **F25(2025 秋)**:約 150 家,B2B 佔近 2/3,92% 核心含 AI;13 家做 agent 基礎設施(記憶體系統、整合平台、觀測工具)——agent pilot 大量暴露 infra 缺口([PitchBook](https://pitchbook.com/news/articles/y-combinator-is-going-all-in-on-ai-agents-making-up-nearly-50-of-latest-batch)、[CB Insights](https://cbinsights.com/research/y-combinator-fall2025/))。
- **W26(2026 冬)**:180+ 家、YC 史上最大批;敘事從「AI agent for X 產業」轉向「讓 agent 可靠上線的支撐棧」(訓練環境、runtime 控制、事故回應、成本管理)([The Agent Report](https://the-agent-report.com/2026/07/ai-agent-startup-explosion-2026-yc-ecosystem/)、[Forbes](https://www.forbes.com/sites/dariashunina/2026/03/16/21-most-promising-startups-from-y-combinators-latest-batch/))。
- 對一人團隊的含意:**垂直應用層(尤其 service-as-software)進入門檻仍低、靠領域知識+通路取勝;infra 層已開始資本化(Coval $28M A、Avoca $125M B),適合「用」不適合「做」**。

---

## 第二部分:模式清單(21 個)

### A. 垂直 AI agent(對本地中小商家收月費)

#### 1. AI 餐廳電話接線員
- 代表:**Loman AI**(Austin,2024 創,$3.5M seed,[Revmo 比較](https://revmo.ai/blog/revmo-vs-slang-vs-loman))、Slang.ai、Hostie、Goodcall(服務 400 萬+通話)
- 收費:美國行情 **$99–599/店/月**;Loman 入門 $149/月+$0.18/分鐘([SalesCaptain 成本拆解](https://blog.salescaptain.com/ai-phone-answering-service-cost-in-2025-full-breakdown/))
- 技術本質:STT+LLM+TTS 語音管線+訂位系統整合(Resy/OpenTable);call completion 僅 60–63%,可靠性是主戰場
- 關鍵成功因子:POS/訂位系統整合深度、口音與嘈雜環境魯棒性、每店 onboarding 成本壓到近零
- 一人縮小版:鎖單一菜系連鎖或商圈,用現成語音 API(Retell/Vapi 類)+自建稽核閘門(錯單=賠錢,我方 audit 強項直接遷移)
- 台灣初判:⚠️ **訂位這格已被大咖佔走**——inline+LINE+台灣大 2025 已推 AI 語音預約([TechNews](https://technews.tw/2025/07/01/inline-ai-powered-smart-reservation-service/)、[LINE Biz](https://tw.linebiz.com/column/ai-reservation-restoshift-2025/));但「外帶點餐電話+LINE 未讀回覆」的小店長尾仍空

#### 2. AI 居家服務(水電/空調/修繕)前台
- 代表:**Avoca**(YC W23→2026-04 $125M Series B、$1B 估值,起點是小團隊語音 agent,[Idlen](https://www.idlen.io/news/avoca-ai-1-billion-valuation-kleiner-perkins-services-economy-voice-agents-april-2026/))
- 收費:不公開,第三方估 **$1,000–3,000/月**(中型業者)([ServiceAgent 分析](https://serviceagent.ai/blogs/avoca-ai-pricing/))
- 技術本質:語音 CSR+排程系統(ServiceTitan/Housecall Pro)整合+通話品質評分(QA 模組是第二隻腳)
- 關鍵成功因子:綁死行業排程軟體、以「多接一通=多一單 $300+」的 ROI 敘事賣
- 一人縮小版:台灣沒有 ServiceTitan——先做「水電行 LINE 官方帳號代管+報價單自動生成+行程排班」輕版,月費 NT$3,000–8,000
- 台灣初判:✅ 高潛力空白。台灣水電/裝修行幾乎零數位化、全靠電話+LINE;無既有 vertical SaaS 可整合反而=無守門人

#### 3. 日本電話 AI SaaS(對台最有預測力的單一案例)
- 代表:**IVRy**(日本,2019 創,Series D 累計 **$58.4M**,2025-11 再募 $26M,[CB Insights](https://www.cbinsights.com/compare/ivry-vs-toku-4)、[PR Times](https://prtimes.jp/main/html/rd/p/000000093.000056805.html))
- 收費:**月額 ¥3,000 起**,AI 電話代行方案約 ¥13,000/月(基本費+從量)([SMIINA](https://smiina.com/ai-denwa/ivry/))
- 技術本質:IVR 樹+LLM 對話+留言轉文字+SMS 回覆,自助 onboarding(10 分鐘開通)
- 關鍵成功因子:**超低價自助式**(非銷售驅動)、按業種出模板(診所/餐廳/不動產)、缺工敘事
- 一人縮小版:完全可行——CF Workers+電信語音 API+業種模板庫,自助註冊,月費 NT$1,500 起
- 台灣初判:✅✅ 日本缺工敘事=台灣正在發生;台灣尚無「¥3,000 級自助電話 AI」等價物;需解台灣市話/070 網路電話介接(法規較日本鬆)

#### 4. AI 牙醫/診所前台
- 代表:**Arini**(YC W24,pre-seed **$500K**,[Tracxn](https://tracxn.com/d/companies/arini/__cLzw44_x8Uut3EKdLC9TXgBJ8h4aestWMVnVzRdbEWw));**Patientdesk.ai**(W26,牙科診所 AI OS);中文圈對照:診所 LINE 掛號
- 收費:未公開(美國牙科前台 SaaS 行情 $300–800/月)
- 技術本質:語音+簡訊雙通道、掛號系統整合、爽約召回(recall)自動化
- 關鍵成功因子:診所管理系統(PMS)整合、HIPAA 級合規姿態、以「爽約率下降」計價
- 一人縮小版:台灣版=「LINE 掛號+看診進度推播+爽約召回」;健保診所不缺病人,痛點在**行政人力**(電話改約、慢箋提醒)
- 台灣初判:✅ 高潛力。台灣診所密度世界級、櫃檯人力難請;切入點=LINE 官方帳號代管而非電話;個資法(醫療特種資料)需設計好資料落地

#### 5. 醫療行政電話代打(打給保險公司/機構,而非接聽)
- 代表:**SuperDial**($15M Series A,SignalFire 領投,[GlobeNewswire](https://www.globenewswire.com/news-release/2025/06/24/3104265/0/en/SuperDial-raises-15M-to-automate-healthcare-s-endless-admin-phone-calls.html))
- 收費:按通話量計價(未公開單價)
- 技術本質:**outbound** 語音 agent 導航電話樹+等待保留+與真人客服對話;失敗自動轉真人
- 關鍵成功因子:選「打出去」而非「接進來」——期望值低、容錯高、量大重複
- 一人縮小版:台灣對應=替診所打電話向健保署/保險公司查詢、替代辦業者打電話催件查進度
- 台灣初判:🔶 中等。台灣商保理賠查詢量遠小於美國;但「代辦業催進度電話」(勞保/移民/車籍)是未被想過的長尾

#### 6. 貨運/物流語音 agent
- 代表:**HappyRobot**(YC,2022 創,累計 ~$62M,Series B 估值 ~$500M,客戶 DHL/Ryder/Flexport,[Sacra](https://sacra.com/c/happyrobot/)、[FreightWaves](https://www.freightwaves.com/news/happyrobot-raises-44m-to-revolutionize-supply-chains))
- 收費:訂閱制按「AI worker 部署數」計價(未公開)
- 技術本質:電話+email+文字多通道 agent,整合 TMS/load board;check call、詢價、追蹤全自動
- 關鍵成功因子:物流溝通=結構化高頻重複對話,是語音 agent 最佳場景之一
- 一人縮小版:台灣貨運行/報關行的「到貨通知+司機調度電話」自動化,搭配第 14 案報關 AI 打包
- 台灣初判:🔶 台灣物流已高度 LINE 化(司機群組),切「LINE 群組訊息結構化+自動回報」比語音更對頻

#### 7. AI 招聘面試官/篩選
- 代表:**Alex(原 Apriora)**(YC W24,**$2.8M seed**,1984 Ventures 領投,[Alex blog](https://www.alex.com/blog/we-raised-2-8m-to-build-the-ai-future-of-interviewing))
- 收費:未查得(B2B 訂閱)
- 技術本質:即時視訊/電話 AI 面試+追問生成+ATS 整合
- 關鍵成功因子:大量時薪職缺(零售/餐飲)初篩=高頻低風險場景
- 一人縮小版:台灣餐飲/門市時薪人力初篩:LINE 上完成非同步 AI 面試+雇主儀表板
- 台灣初判:🔶 台灣 104/1111 生態強勢;差異化=LINE 非同步面試(求職者無需下載 app)

#### 8. AI 記帳/簿記(bookkeeping)
- 代表:**Kick**(**$9M seed**,2024-10,與 FreshBooks 策略合作,[Accounting VC Round-Up](https://theaccountingvc.substack.com/p/the-accounting-vc-round-up-8));**Truewind**($13M Series A,Thomson Reuters Ventures,[CPA Practice Advisor](https://www.cpapracticeadvisor.com/2025/01/08/truewind-accounting-ai-platform-raises-13-million-in-series-a-funding/154157/));Basis(未查得本輪細節)
- 收費:Kick 消費級訂閱;Truewind 賣給會計師事務所(工作底稿自動化)
- 技術本質:銀行流水+發票 OCR→交易分類→報表;「reviewer-first」人審設計
- 關鍵成功因子:兩條路線——直接服務小企業 vs 賣給事務所當槓桿;後者獲客成本低
- 一人縮小版:台灣版切「電子發票 API+銀行 CSV→自動分類→給記帳士的月結底稿」,**賣給記帳士事務所**而非終端商家
- 台灣初判:✅✅ 台灣記帳士人力貴、一人接 80–120 家客戶、全手工;電子發票整合度全球最高(財政部平台)=資料取得比美國容易;我方爬蟲+稽核閘門直接命中

#### 9. 韓國式退稅/報稅自動化(consumer service-as-software)
- 代表:**삼쩜삼(3.3)/Jobis&Villains**(韓國,**2,000 萬用戶**,LLM 訓練 1,220 萬筆退稅資料、4,608 條個人化流程,[VentureSquare](https://www.venturesquare.net/967413))
- 收費:成功退稅抽成(freemium+成功報酬)
- 技術本質:自動撈稅務資料→試算可退額→一鍵申報;後端規則引擎+LLM 個人化
- 關鍵成功因子:「先告訴你能退多少」的鉤子+成功才收費=零心理門檻
- 一人縮小版:台灣綜所稅已半自動(財政部做得好),空間小;**替代標的=勞保/國民年金給付試算、汽燃費/罰單、補助資格掃描**(「你有 X 元沒領」)
- 台灣初判:🔶 台灣報稅體驗已佳,直接複製不成立;「未領給付/補助資格掃描器」是變形機會,惟需 MyData 授權介接

### B. 未 bundled 的專業服務(AI 產品化)

#### 10. AI-native 法律事務所(合約審閱定價制)
- 代表:**Crosby**(**$5.8M seed** Sequoia 領投→2026-03 $60M Series B,客戶含 Cursor,[Artificial Lawyer](https://www.artificiallawyer.com/2025/06/19/crosby-raises-5-8m-seed-for-hybrid-ai-law-firm/));**General Legal**(YC W26,**團隊 25 人**,**$500/份合約、3 小時內交付**,創辦人=前 Casetext CTO,[YC 頁面](https://www.ycombinator.com/companies/general-legal))
- 收費:按件定價($500/合約)取代按小時計費
- 技術本質:是**律所不是軟體公司**——雇律師+內部 AI 工作流,賣「完成的服務」;監管上以律所執照解決 UPL 問題
- 關鍵成功因子:按件定價+極速交付=可比價;AI 是成本結構優勢不是賣點
- 一人縮小版:台灣**不可行直接複製**(律師法限制)——變形=與一位執業律師合夥,一人做 AI 管線,律師掛名審核,先切「英文合約中文摘要+風險標記」給中小企業出口商
- 台灣初判:🔶 需律師合夥;但台灣中小出口商看不懂英文合約=真痛點,願付 NT$3,000–10,000/份

#### 11. AI 小額債務催收法律流程
- 代表:**Garfield AI**(英國,**SRA 核准的第一家純 AI 律所**,2 人創辦(前訴訟律師+量子物理學家),£2/催告信、£7.5/律師函、£50 起訴狀,2026-05 首勝訴(£400 成本收回 £7,000),[Law Gazette](https://www.lawgazette.co.uk/news/sra-approves-2-letter-ai-law-firm/5123191.article)、[Computer Weekly](https://www.computerweekly.com/news/366644941/Artificial-intelligence-based-law-firm-wins-in-court))
- 收費:超低單價按件(£2–50/件)、走量
- 技術本質:小額訴訟程序=高度模板化流程,LLM 填表+程序狀態機
- 關鍵成功因子:監管突破(SRA 核准)是護城河;單價低到無人想競爭
- 一人縮小版:台灣對應=**支付命令聲請自動化**(民訴 508 條,不需律師!當事人可自行聲請)——中小企業被欠款,AI 生成聲請狀+送件指引,收 NT$500–1,500/件
- 台灣初判:✅✅ **台灣獨有機會**:支付命令本人聲請合法、程序完全模板化、中小企業應收帳款糾紛極多;不觸律師法(非訴訟代理,是文書自動化)

#### 12. AI 金融法遵(AML/KYC 審查)
- 代表:**Greenlite AI→Bretton**(YC,**$4.8M seed** Greylock→$15M A→2026-02 **$75M B**,[Bretton blog](https://www.bretton.com/blog/greenlite-seed-round)、[AML Intelligence](https://www.amlintelligence.com/2026/02/latest-bretton-ai-raises-75m-for-compliance-platform-rebrands-from-greenlite-ai/));**Veriad**(YC W26,AI 合規官)
- 收費:企業訂閱(未公開)
- 技術本質:LLM 做 alert 初審+證據鏈生成,人審終判;「可稽核的 AI 工作流」是賣點
- 關鍵成功因子:審計軌跡完整性>模型聰明度——**這正是我方稽核閘門架構的同構問題**
- 一人縮小版:台灣中小型券商/投信/虛擬資產業者(VASP 洗防登記)的 AML 警示初篩+文件生成
- 台灣初判:✅ 金管會對 VASP 洗防要求趨嚴、小業者養不起法遵團隊;惟 B2B 金融銷售週期長,一人團隊要靠一家燈塔客戶

#### 13. 資安/合規認證自動化(SOC2/ISO 27001)
- 代表:**Delve**(YC,AI agent 做合規雜務,[delve.co](https://delve.co/));前輩=Vanta/Drata(已巨頭化)
- 收費:年訂閱(Vanta 行情 $10K+/年)
- 技術本質:整合雲端設定+自動蒐證+報告生成
- 一人縮小版:台灣版=「資安法遵包」——上市櫃資安長義務、個資法 DPIA 文件自動化
- 台灣初判:🔶 台灣中小企業合規預算低;機會在「上市櫃供應鏈被要求填資安問卷」的代填服務

#### 14. AI 報關/關稅分類
- 代表:**Caspian**(**$5.4M seed**,Primary Venture Partners,2024 創,本身持美國報關執照,[BusinessWire](https://www.businesswire.com/news/home/20250729878632/en/));**Gaia Dynamics**(**$1.5M pre-seed**,Andrew Ng 的 AI Fund,HS code 自動分類 92% 準確率,[StartupIntros](https://startupintros.com/orgs/gaia-dynamics));traide AI(250+ 企業)
- 收費:SaaS 訂閱+按件;Caspian 另賺退稅(duty drawback)抽成
- 技術本質:商品描述→HS/HTS 稅則歸類(檢索+LLM)+申報文件生成;2025 關稅亂局=需求爆發
- 關鍵成功因子:錯誤成本高→「AI 建議+持照報關師覆核」混合模式;抽成型收入(退稅)優於訂閱
- 一人縮小版:台灣**報關行 copilot**:invoice/packing list OCR→稅則預歸類→C1/C2/C3 申報草稿;賣給報關行按票計費
- 台灣初判:✅✅ 台灣報關行數千家、高齡化、全手工 key 單;貿易依存度極高;關港貿單一窗口 XML 格式公開=可自動化;我方爬蟲+管線設計直接適用

#### 15. 標案書/補助申請書代寫
- 代表:**AutogenAI**(英,企業級,Fortune 500 客戶,[autogenai.com](https://autogenai.com/));**DeepRFP**(月費自助,[DeepRFP](https://deeprfp.com/blog/best-rfp-tools-2025-ai-comparison/));**Grantboost**(非營利,$19.99/月,[grantboost.io](https://www.grantboost.io/));日本 **補助金Express**(2WINS Inc.,書類作成時間削減 80–90%,對接 jGrants,服務首次申請的中小企業+顧問業,[hojokin.ai](https://www.hojokin.ai/))
- 收費:兩極——自助 $20–200/月 vs 企業 POC 起跳;日本模式=也賣給「補助金顧問」當產能槓桿
- 技術本質:RFP/公告解析→需求矩陣→過往案例庫檢索→草稿生成;勝率資料迴圈是護城河
- 關鍵成功因子:**賣給代寫顧問(B2B2B)比賣給申請者好**——顧問按成功抽成 10–15%,付得起工具費
- 一人縮小版:台灣 SBIR/CITD/數位轉型補助的申請書生成器,先賣給輔導顧問;政府採購標案(服務建議書)是第二市場
- 台灣初判:✅✅ 台灣補助顧問業抽成 10–20%、全手工;政府補助公告全公開可爬;**日本已有直接前例**(補助金Express)=模式驗證過,台灣尚無等價物

#### 16. AI 翻譯產品化(取代按字計費人工)
- 代表:**Widn.AI**(Unbabel 分拆,自有 Tower LLM、32 語言,母公司為此募 $20–50M,[CNBC](https://www.cnbc.com/2024/11/13/unbabel-launches-ai-translation-app-looks-for-fresh-funding.html))
- 收費:訂閱/按量,單價遠低於人工按字
- 技術本質:領域微調翻譯模型+術語庫+品質預估(QE)分流(高風險句才人審)
- 一人縮小版:不做通用翻譯(紅海)——切**法遵/財報/公開說明書中英互譯**垂直,QE 分流+我方稽核閘門保品質
- 台灣初判:🔶 通用翻譯已死價;上市櫃英文年報義務化(金管會)=「財報英譯+檢核」是付費垂直

#### 17. AI 股票研究(僱不起分析師的機構)
- 代表:**Fintool**(2023 創,累計募 ~$6.7M,**2026-04 被 Microsoft 收購**,[Tracxn](https://tracxn.com/d/companies/fintool/__t6BbKAqQgkqE84JWa-Ep3CFtJRzEIHY-hM2CxAgiXMk))
- 收費:~€50–500/月分級訂閱
- 技術本質:SEC filings+法說會逐字稿即時解析+可溯源引用——**與 MarketDaily 管線同構**
- 關鍵成功因子:資料源覆蓋+引用可驗證性;退出證明(被 MS 收購)=模式被大廠認可
- 一人縮小版:我方已在做(MarketDaily);升級方向=公開資訊觀測站+法說音檔的「台股 Fintool」,賣投顧/自營/財經媒體 API
- 台灣初判:✅ 我方存量資產最大重疊;⚠️ 合規紅線已知(個股分析不得與付費掛鉤),B2B 資料 API 形式可繞開 B2C 限制(賣資料非賣建議,仍需 legal-compliance 覆核)

### C. AI 工程基礎設施(eval/監控/測試/整合)

#### 18. 語音 agent 測試/QA(「賣鏟子的鏟子」)
- 代表:**Hamming**(YC S24,**$3.8–4.3M seed**,1,000+ 併發模擬通話,[Hamming blog](https://hamming.ai/blog/hamming-ai-seed-funding-to-make-voice-agents-more-reliable));**Coval**(**$3.3M seed**→2026 **$28M Series A** Norwest,創辦人=前 Waymo eval 主管,[TNW](https://thenextweb.com/news/coval-28m-series-a-voice-ai-testing))
- 收費:B2B 訂閱按測試量
- 技術本質:模擬對話生成+audio-native 評分+production 回放;自駕模擬方法論移植
- 關鍵成功因子:掛在爆發垂直(voice agent)上游;先發者已 A 輪=窗口收窄
- 一人縮小版:**中文語音 agent 測試集**(台灣口音/台語/中英夾雜)是英文玩家做不好的縫隙;賣給亞洲 voice agent 業者
- 台灣初判:🔶 市場小但零競爭;可當第 2/3 案(自營語音 agent)的內部工具外部化,不必獨立成業

#### 19. LLM eval/觀測(開源+雲託管)
- 代表:**Langfuse**(**$4M seed** Lightspeed+YC,開源,[Langfuse blog](https://langfuse.com/blog/announcing-our-seed-round));Confident AI/DeepEval(YC);Ragas(YC,RAG 專用)
- 收費:開源免費+雲託管訂閱(PLG)
- 技術本質:trace 收集+指標評分+資料所有權(自架)
- 關鍵成功因子:開源社群=獲客;小團隊可撐(Langfuse seed 時個位數人)
- 一人縮小版:不做通用平台(已飽和);做**繁中 eval 資料集/繁中 guardrail 規則庫**開源,託管收費
- 台灣初判:🔶 繁中 eval 是真缺口(我方 ai_slop_lint/audit 積木可直接開源化),但變現天花板低;定位=獲客資產而非主業

#### 20. Agent 整合/MCP 基礎設施
- 代表:**Metorial**(YC F25,「Vercel for MCP」,~600–1200 個 MCP server 目錄,serverless runtime,[HN Show](https://news.ycombinator.com/item?id=45580771)、[GitHub](https://github.com/metorial/metorial));**Hyperspell**(YC F25,agent 記憶層+MCP,[YC 頁](https://www.ycombinator.com/companies/metorial));F25 同梯還有 Multifactor(agent 零信任授權)、Dari(browser agent)
- 收費:PLG 訂閱(未公開)
- 技術本質:MCP server 託管/目錄/狀態管理
- 一人縮小版:**台灣在地 MCP server 包**:電子發票、關港貿、公開資訊觀測站、健保申報、LINE OA——英美玩家永遠不會做的整合
- 台灣初判:✅ 做為「台灣 agent 生態的水電行」有先發空間;且每個 server 同時是自家垂直產品(第 8/14/15 案)的積木——**做一次賣兩次**

### D. 亞洲在地化前例(對台預測力最高)

#### 21. 亞洲 SMB 對話式客服+AI agent 升級
- 代表:**Channel Talk/Channel Corp**(韓國,22 萬企業用戶、**日本 2.5 萬客戶、年增 50%**,AI agent「ALF」上線 2 個月 1,000 家採用,累計募 ~$39.3M,[Seoul Economic Daily](https://en.sedaily.com/markets/2026/06/07/channel-corp-targets-global-markets-with-ai-powered-japan)、[WOWTALE](https://en.wowtale.net/2025/01/13/228987/));**Kata.ai**(印尼,WhatsApp 客服,$8.3M,[Crunchbase](https://www.crunchbase.com/organization/kata));**WIZ.AI**(新加坡,多語 talkbot 含 Singlish,累計 $56M,[Tracxn](https://tracxn.com/d/companies/wiz-ai/__a1f1OhMY6Vs0ktD7DJhdoYBnkoIG9vDvBKcIDeTXx_0))
- 收費:SaaS 分級月費+AI 用量
- 技術本質:在地通訊渠道(KakaoTalk/LINE/WhatsApp)深整合+AI 分流;「缺工」是共同敘事
- 關鍵成功因子:**渠道在地化>模型能力**——Channel Talk 贏日本靠的是 LINE 世代的 UX 與日語支援,不是更強的 LLM
- 一人縮小版:台灣 LINE OA 生態的「AI 店員」:商家後台已有(基礎版行情 NT$1,000–3,000/月,[livechat.com.tw](https://livechat.com.tw/ai-recommend/)),但**垂直深度版**(診所/房仲/補習班專用流程)仍空
- 台灣初判:✅ 通用 LINE 客服機器人已紅海;贏法=垂直流程(掛號/帶看/試聽預約)+行業資料整合,即第 2/4 案的載體

---

## 第三部分:YC Requests for Startups(Fall 2026 現行版)全文 13 條+一人可做版本

來源:[ycombinator.com/rfs](https://www.ycombinator.com/rfs)(2026-08-02 抓取)。另註:Summer 2026 版為 15 條(AI-Native Service Companies、Software for Agents、SaaS Challengers、Company Brain 等,[The VC Corner 整理](https://www.thevccorner.com/p/yc-summer-2026-requests-for-startups-ideas)),其中「AI-Native Service Companies」正是本報告 A/B 區全部案例的官方背書。

| # | RFS | 內容一句話 | 一人可做版本 |
|---|-----|-----------|-------------|
| 1 | The Primer | 私人家教品質的自適應兒童讀寫算 AI | 繁中版國小數學/英文 LINE 家教 bot,家長月費制;鎖單科起步 |
| 2 | Future of American Defense | 美陸軍要模組化地面作戰科技 | ❌ 不適用(國防/地緣門檻) |
| 3 | A Cloud for Small Software | 「小軟體」部署雲:讓非工程師安全分享自製工具 | 台灣中小企業「vibe-coded 內部工具託管+權限」代管服務;CF 全棧正是我方主場 |
| 4 | Multiplayer AI | 團隊協作原生的 agent(多人同看/接手長任務) | 小團隊版:LINE 群組內可被多人指揮的工作 agent(記帳/排班/追單) |
| 5 | Compute at Sea | 海上資料中心 | ❌ 不適用(資本密集) |
| 6 | AI Consumer Products for 1B People | 十億人級 AI 消費產品 | 繁中利基消費工具(命理/理財教育)可小做,難大成;非重點 |
| 7 | AI for Aging Population | 高齡照護:語音介面/安全監測/家庭照護協調 | ✅ 台灣超高齡社會 2025 達標;「長輩 LINE 語音助理+家屬儀表板」月費制,無硬體純軟切入 |
| 8 | OS for the Physical World | 人+機器人+agent 混合工班的派工/計費 OS | 台灣版=清潔/保全/看護派遣行的排班派工 SaaS(先純人力,agent 後加) |
| 9 | Best Time to Build in Crypto | 穩定幣/agentic commerce/機構產品 | 我方已有 defi-amm-security 積木;台灣法規未明,觀望 |
| 10 | Data for the Real World | 實體世界密集資料收集 | 台灣店家人流/租金/招牌更替爬蟲資料庫,賣給展店決策——我方爬蟲強項,可低成本試 |
| 11 | Proving You're Human | 深偽時代的真人驗證 | 🔶 infra 級難題,一人不宜主攻 |
| 12 | AI-Native Compliance Infrastructure | 金融合規自動化(監測/報告/稽核軌跡) | =本報告第 12 案;台灣 VASP/投信投顧法遵文件自動化 |
| 13 | Self-Maintaining APIs | API 商派 agent 進客戶 codebase 自動升級 | 做成服務:替台灣 SaaS 商維護客戶端 SDK 相容性(外包型),驗證後產品化 |

---

## 第四部分:結論

### 總數:21 個模式(+RFS 13 條逐條評估)

### 最適合我方直接開工的前 5(一行理由)

1. **#15 補助/標案申請書生成器(先賣顧問)**——日本補助金Express 已驗證模式、台灣顧問抽成 10–20% 付得起工具費、公告全公開可爬、我方 LLM 編排+驗證者分離直接命中,零語音技術風險。
2. **#8 記帳士事務所 AI 底稿管線**——台灣電子發票整合度全球第一=資料唾手可得,記帳士一人 100 家客戶全手工,B2B2B 獲客集中;我方稽核閘門=品質保證的天然賣點。
3. **#11 支付命令自動化(台灣版 Garfield)**——不需律師執照(本人聲請合法)、程序 100% 模板化、單價低到無人想做、中小企業欠款糾紛量大;台灣獨有法規紅利。
4. **#3 日式低價自助電話 AI(IVRy 台灣版)**——¥3,000 級自助模式在台無等價物、缺工敘事同步發生、CF 全棧+語音 API 可一人搭建;先從診所/水電行模板切(避開已被 inline+LINE 佔走的餐廳訂位)。
5. **#20 台灣在地 MCP server 包(電子發票/關港貿/公開資訊觀測站/LINE OA)**——每個 server 既是獨立 infra 產品又是上面 4 案的積木,做一次用兩次;英美玩家永遠不會來做。

### 掃描中冒出的「台灣獨有、歐美無對應物」機會

- **支付命令文書自動化**(#11 變形):歐美小額訴訟需出庭或律師,台灣支付命令純書面+本人可聲請——全球少見的「純文件自動化就能完成法律程序」場景。
- **電子發票強制化紅利**(#8 底層):台灣 B2C/B2B 發票電子化+財政部統一平台,歐美 bookkeeping 新創花一半力氣在資料擷取,台灣這步是免費的。
- **關港貿單一窗口 XML**(#14 底層):報關資料標準化程度高於美國 ABI 生態的碎片化,自動化成本更低,而報關行數位化程度卻更低=落差即機會。
- **LINE 單一渠道壟斷**(#2/4/21 載體):歐美 SMB 溝通碎片化(電話/email/SMS/FB),台灣一個 LINE OA 打通全部——垂直 agent 的分發成本結構性低於歐美。
- **競爭確認**:餐廳訂位 AI 已被 inline+LINE+台灣大聯盟佔位([TechNews](https://technews.tw/2025/07/01/inline-ai-powered-smart-reservation-service/)),勿正面進入;通用 LINE 客服 bot 為紅海(NT$1,000–3,000/月行情),勝負在垂直流程深度。

### 紅線聲明
- 各案融資/價位皆附來源連結;Basis(bookkeeping)、Alex 收費、Patientdesk/Veriad/Alt-X 細節標「未查得」或僅列名。
- 第 17 案(台股 Fintool)涉個股分析,任何商業化前須過 legal-compliance(投信投顧法紅線:個股分析內容永不與付費掛鉤)。
