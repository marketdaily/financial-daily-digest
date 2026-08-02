# B2B GTM 提案包:把 MarketDaily 的「可稽核 LLM Pipeline」賣給台灣持牌金融機構

日期:2026-08-02
撰寫:Claude(研究代理)
狀態:提案草稿,所有法律論述**需真律師確認**;所有事實均附來源連結,查不到的明標「查無公開資訊」或「假設」。

---

## 0. 一頁摘要

**賣什麼**:不賣內容、不賣分析(那條路被投顧法封死),賣「受監管環境下可稽核的 LLM 基礎設施」——一套已在 production 跑一年多的管線:多模型 council + judge 仲裁、audit 檢查清單、重試與確定性回退、絕不送出壞輸出、完整稽核軌跡。

**賣給誰**:已持牌的證券商、投顧、投信——他們有合法資格對客戶說「買賣建議」,但缺的是讓 LLM 產出「敢送出、敢被金管會檢查」的工程防線。

**為什麼是現在**:
- 金管會 2024-06 發布[《金融業運用人工智慧(AI)指引》](https://www.fsc.gov.tw/websitedowndoc?file=chfsc%2F202408231741530.pdf&filedisplay=%E9%99%84%E4%BB%B6_%E9%87%91%E8%9E%8D%E6%A5%ADAI%E6%8C%87%E5%BC%95.pdf),六大原則含「透明性與可解釋性」「系統穩健性與安全性」;2026 年更規劃把[代理 AI、AI 風險分類納入指引、建立「AI 管 AI」架構](https://udn.com/news/story/7239/9486677),且[高風險 AI 應用恐禁止全自動、須保留人工介入](https://udn.com/news/story/7239/9486443)——「可稽核、可攔截、可回退」正是監管方向本身。
- [金管會 2025-05 公布調查](https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0%2C2&mcustomize=news_view.jsp&dataserno=202505200001&dtable=News):383 家受查金融機構已有 126 家(33%)導入 AI,61 家導入生成式 AI(年增 21 個百分點),47%(179 家)表示未來將導入或擴大——需求端正在放量,而治理/稽核層是共同缺口。
- 這正對上 [YC Requests for Startups 的「AI-Native Compliance Infrastructure」](https://www.ycombinator.com/rfs):監管審計軌跡、報告產生、異常攔截是 AI 原生問題,而監管複雜度是抄不走的護城河([YC RFS 解析](https://quasa.io/media/yc-fall-2026-rfs-how-to-build-ai-native-compliance-infrastructure))。

**賣方定位**:22 歲一人團隊 + 一年多 production 實戰(每日雙市場日報、零缺信死線、多層防線與事故偵測器文化)+ 懂台灣投顧法邊界(自家產品就是被這條法塑形的)。劣勢(採購資格、資安審查、key-man risk)在第 7 節誠實列出,並給對策。

---

## 1. 市場盤點

### 1.1 潛在買方母體(持牌機構)

| 類別 | 家數與名冊來源 |
|---|---|
| 證券商 | 精確家數見證期局[「證券服務事業家數統計表」開放資料集](https://data.gov.tw/dataset/104010)(欄位含經紀/自營/承銷分項)與[證期局證券期貨統計](https://www.sfb.gov.tw/ch/home.jsp?id=109&parentpath=0%2C4);合法業者名單見[「本會核准之合法證券商、期貨業、投信投顧業」](https://www.sfb.gov.tw/ch/home.jsp?id=776&parentpath=0%2C5%2C775) |
| 投信(證券投資信託) | 同上開放資料集;會員名單見[投信投顧公會會員名錄查詢](https://www.sitca.org.tw/ROC/MemData/MD2001N.aspx?PGMID=AS0701) |
| 投顧(證券投資顧問) | 同上;另依[投信投顧公會 2025-09 新聞稿](https://www.sitca.org.tw/CWEB/%E5%A2%83%E5%85%A7%E5%9F%BA%E9%87%91%E6%96%B0%E8%81%9E%E7%A8%BF1140912.pdf),經營全權委託業務之投信投顧業者達數十家規模(截至 114 年 8 月底) |

註:本檔不引用未經核實的具體家數數字;打名單前一律以上述官方名冊拉最新清單(開放資料集為 CSV,可程式化拉取)。

### 1.2 需求端訊號:誰已經在用生成式 AI(公開新聞)

**監管統計面**([金管會 2025-05 新聞稿](https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0%2C2&mcustomize=news_view.jsp&dataserno=202505200001&dtable=News)、[工商時報報導](https://www.ctee.com.tw/news/20250521700635-430301)、[聯合報報導](https://udn.com/news/story/7239/8752600)):
- 33% 金融機構已導入 AI(126/383 家),銀行導入率最高(87%)。
- 生成式 AI:61 家已導入,占用 AI 業者 48%,年增 21 個百分點;應用集中在內部行政作業(39%)與智能客服(15%)。
- 47% 機構表示未來將導入或擴大。
- 隱含解讀:**證券/投信/投顧的導入率遠低於銀行**——這是尚未被服務商吃掉的空檔。

**個別機構面**:
- **國泰金控**:自建生成式 AI 框架 [GAIA](https://www.cathayholdings.com/holdings/brand/fintech/ctc/trends/2024cathay_gaia)(200+ 資料類別知識庫、50+ 模型 Model Hub、**70 道安全防護檢查點的 AI 護欄**),2025 年發表 [GAIA 2.0 與雲端優先](https://www.cio.com.tw/100118/),並[與 OpenAI 展開長期合作、部署 Agentic AI](https://3c.yipee.cc/333816/%E5%9C%8B%E6%B3%B0%E9%87%91%E6%8E%A7%E6%94%9C%E6%89%8B-openai-%E5%B1%95%E9%96%8B%E9%95%B7%E6%9C%9F%E5%90%88%E4%BD%9C%EF%BC%8Cai-%E6%87%89%E7%94%A8%E5%B0%87%E5%B0%8E%E5%85%A5%E5%85%A8%E9%9B%86%E5%9C%98/)。→ 大型金控會自建護欄,不是我們的首發客戶,但證明「AI 護欄/檢查點」是業界公認必需品。
- **富邦金控**:2025-07 組[「生成式 AI 應用推動團隊」](https://www.fubon.com/financialholdings/news/news_1251107_482220.htm),號召含**富邦證券、富邦投信**在內 5 家子公司,[近 20 個專案開發中](https://money.udn.com/money/story/11799/9131287)(員工助手、虛擬助手、流程輔助)。
- **玉山**:內部智能助理 GENIE、[12 項 GenAI 應用](https://www.ithome.com.tw/news/162551)、[通用型 GenAI 平台](https://www.ithome.com.tw/news/162549),並[攜手 IBM 建立 AI 治理框架](https://3c.yipee.cc/330753/%E7%8E%89%E5%B1%B1%E9%8A%80%E8%A1%8C%E6%94%9C%E6%89%8B-ibm-%E5%BB%BA%E7%AB%8B-ai-%E6%B2%BB%E7%90%86%E6%A1%86%E6%9E%B6%EF%BC%8C%E7%82%BA%E9%87%91%E8%9E%8D%E6%A5%AD%E5%A4%A7%E8%A6%8F%E6%A8%A1%E5%B0%8E/)——「AI 治理框架」本身已成採購品項。
- **永豐金證券**:AI 工具[「豐搜」](https://news.pchome.com.tw/living/cna/20251002/index-17593706501438618009.html)每日從 2 萬+ 則台股資訊萃取熱詞、結合 LLM 五分鐘生成文章;[生成式 AI 助研究團隊寫產業分析與個股報告、AI Agent 進交易與投顧服務](https://udn.com/news/story/7251/8190182);[大戶投 App 下載破百萬、單月交易破千億](https://www.businessweekly.com.tw/business/blog/3020679)。→ **證券業「LLM 產出面向投資人內容」已有先行者**,這是最有力的需求存在證明。
- **元大證券**:AI 選股 App[「投資先生」](https://www.yuanta.com.tw/file-repository/content/0919news/notice107_0919.htm),逾百萬用戶([改版介紹](https://www.stockfeel.com.tw/%E5%85%83%E5%A4%A7%E8%AD%89%E5%88%B8-%E6%8A%95%E8%B3%87%E5%85%88%E7%94%9F/))。
- **富果 Fugle(× 元富證券)**:[Fugle.AI](https://www.fugle.ai/) 讓用戶把 ChatGPT/Claude 接上台股資料查詢——新創券商生態已把 LLM 當介面。

### 1.3 監管態度(詳見第 6 節)
- [《金融業運用 AI 指引》](https://www.fsc.gov.tw/websitedowndoc?file=chfsc%2F202408231741530.pdf&filedisplay=%E9%99%84%E4%BB%B6_%E9%87%91%E8%9E%8D%E6%A5%ADAI%E6%8C%87%E5%BC%95.pdf)(2024-06,行政指導性質,六大原則:治理問責、公平以人為本、隱私保護、穩健安全、**透明可解釋**、永續)。
- [證券商業同業公會《證券商運用人工智慧技術自律規範》](https://www.twsa.org.tw/F01/doc/%E4%B8%AD%E8%8F%AF%E6%B0%91%E5%9C%8B%E8%AD%89%E5%88%B8%E5%95%86%E6%A5%AD%E5%90%8C%E6%A5%AD%E5%85%AC%E6%9C%83%E8%AD%89%E5%88%B8%E5%95%86%E9%81%8B%E7%94%A8%E4%BA%BA%E5%B7%A5%E6%99%BA%E6%85%A7%E6%8A%80%E8%A1%93%E8%87%AA%E5%BE%8B%E8%A6%8F%E7%AF%84%E5%8F%8A%E8%AA%AA%E6%98%8E.pdf)(2024-11-19 金管會准予備查)——券商用 AI 已有自律規範要遵循,合規負擔=我們的賣點。
- 2026 年金管會規劃[把可程式化 AI、代理 AI、AI 風險分類納入指引](https://www.epochtimes.com/b5/26/5/7/n14758846.htm),[「AI 管 AI」、高風險應用須保留人工介入](https://udn.com/news/story/7239/9486443)。
- 投顧業既有的自動化服務框架:[投信投顧公會 Robo-Advisor 作業要點](https://www.rootlaw.com.tw/LawArticle.aspx?LawID=A040390051146500-1131121)、金管會 2024-10 [修正投顧事業管理規則強化自動化投資顧問監理](https://www.lawbank.com.tw/news/NewsContent.aspx?NID=204962.00)(明定財業務條件、內控、外部監理)。→ 投顧要用演算法/自動化工具服務客戶,**本來就要證明系統可控**,我們的 audit trail 直接對到這個舉證需求。

---

## 2. Offering:三個候選包裝

### 包裝①:白牌日報引擎授權(White-label Digest Engine)
- **賣什麼**:整條 production 管線授權——資料接入 → 多模型 council 生成 → judge 仲裁 → audit 檢查(數十項確定性 check)→ 重試/降級/確定性回退 → 排版寄送 → 完整稽核軌跡與事故偵測。買方掛自己牌照與品牌,對自己客戶發個人化台美股日報。
- **價值主張**:持牌機構「一個月內」擁有等同一年多打磨的個人化內容引擎;每一封信都有生成鏈路紀錄可回放,主管機關檢查時拿得出完整證據鏈。
- **對比買方現狀**:研究員手寫晨報+主管人工複核,或行銷用 ChatGPT 起草再人工逐字檢查——無法個人化到每位客戶、無法保證每日準時、無稽核軌跡。
- **為什麼買不如自建**:自建要踩完我們踩過的坑(模型配額荒、429 連鎖、審計誤殺、時區/休市邏輯、重複寄送、樣式在 email client 崩壞……),至少 1–2 名全職工程師 × 一年;而大機構(國泰 GAIA 有 70 道護欄檢查點)證明防線工程量巨大——中小券商/投顧根本養不起這條線。

### 包裝②:LLM 輸出稽核閘門 SaaS(Audit Gate as a Service)——**主推**
- **賣什麼**:不碰買方的生成端,只賣「送出前的最後一道門」:買方任何 LLM 產出(晨報、客服回覆、研究摘要、行銷文案)過 API 進閘門 → 多項確定性+LLM-judge 檢查(事實性、禁語、數字幻覺、法遵字眼、時效錯誤)→ 通過/攔截/降級回退 → 每一筆留完整 audit log,一鍵匯出「監理檢查文件包」。
- **價值主張**:直接對應金管會 AI 指引「透明性與可解釋性」「穩健性與安全性」與券商公會自律規範的落地舉證;對 2026 年「AI 管 AI」監理方向([經濟日報](https://money.udn.com/money/story/5613/9486677)),這就是那個「管 AI 的 AI」。
- **對比買方現狀**:法遵人員抽樣人工複核+Excel 登記——覆蓋率低、無法即時、留痕零散;或者乾脆因為怕出事而不敢上線 LLM 對客功能(這是最大的隱形市場:47% 想導入還沒導入的機構)。
- **為什麼買不如自建**:護欄是「負面知識」的累積——什麼會出錯、怎麼錯、錯了怎麼兜底,只能用 production 事故換;我們的檢查清單就是一年多真實事故的結晶。且閘門獨立於生成端,天然符合「驗證者與生成者分離」的治理邏輯(自家生成自家驗=審計獨立性存疑)。

### 包裝③:顧問式導入+訓練(AI Pipeline Enablement)
- **賣什麼**:以顧問專案把買方既有 AI 專案「補上防線」:盤點其 LLM 應用 → 設計 audit checklist 與回退策略 → 陪跑導入 → 訓練其工程與法遵團隊 → 交付對照金管會 AI 指引六原則的落差報告。
- **價值主張**:大機構(富邦近 20 個專案並行)缺的不是模型,是把「示範專案」變「敢上線的生產系統」的工程紀律;顧問案是進大門的低摩擦楔子。
- **對比買方現狀**:請四大或系統整合商做 AI 治理框架(如玉山×IBM 路線)——貴、慢、產出偏文件;我們產出偏可跑的 code + 可查的 log。
- **為什麼買不如自建**:這本來就是「教你自建」的包裝,不衝突;賺的是時間差與經驗差。

### 三包裝關係
③是敲門磚(低客單、快成交、建立信任)→ ②是主力經常性收入(SaaS,黏著、續約)→ ①是大單(白牌授權,適合沒有工程隊的中小投顧/投信行銷部門)。

---

## 3. 目標清單(Top 15,含佐證;查不到佐證的明標)

分三個 tier。「切入點」= 第一封信/第一次會議講什麼。

### Tier A:挑戰者/純數位券商(組織小、決策快、內容量大)——首攻
| # | 名稱 | 類型 | 為什麼是好目標 | 切入點 | 佐證 |
|---|---|---|---|---|---|
| 1 | 口袋證券 | 純網路券商 | 台灣純網路券商,自營內容量大(口袋學堂、社群、YouTube),團隊小無力自建 LLM 防線 | 「口袋學堂+行情快訊的 LLM 產線+稽核閘門,30 天 PoC」 | [官網](https://www.pocket.tw/)、[口袋學堂](https://www.pocket.tw/school/);App 內建 AI 動能分析([App Store](https://apps.apple.com/us/app/%E5%8F%A3%E8%A2%8B%E5%8F%B0%E8%82%A1-%E5%8F%A3%E8%A2%8B%E8%AD%89%E5%88%B8/id1606477393));**其導入生成式 AI 之具體新聞:查無公開資訊** |
| 2 | 好好證券(FundSwap) | 基金交易新創券商 | 內容行銷驅動獲客([基金總體檢等長文內容](https://www.fundswap.com.tw/posts-index/fund-news/taiwan2025/)),小團隊 | 「內容產線自動化+合規閘門」 | 內容站佐證如左;**其 AI 導入新聞:查無公開資訊** |
| 3 | 富果 Fugle × 元富證券 | 券商數位品牌/新創 | 已把 LLM 當產品介面([Fugle.AI 接 ChatGPT/Claude 查台股](https://www.fugle.ai/)),對 LLM 風險有體感 | 「你們讓用戶用 LLM 查資料,誰在稽核 LLM 對用戶說了什麼?」;也可能是**夥伴**而非客戶 | [Fugle.AI](https://www.fugle.ai/)、[INSIDE 報導](https://www.inside.com.tw/article/18995-taiwan-fintech-startup-fugle) |

### Tier B:已公開喊 AI 的中大型證券/投信(需求已證明、預算已編)
| # | 名稱 | 類型 | 為什麼是好目標 | 切入點 | 佐證 |
|---|---|---|---|---|---|
| 4 | 富邦證券 | 大型券商 | 母集團 GenAI 推動團隊點名 5 子公司、近 20 專案開發中,正是「專案多、防線缺」階段 | 包裝③:「幫 20 個專案補同一層稽核閘門」 | [富邦金新聞稿](https://www.fubon.com/financialholdings/news/news_1251107_482220.htm)、[經濟日報](https://money.udn.com/money/story/11799/9131287) |
| 5 | 富邦投信 | 投信 | 同上,且投信對外文件(月報、基金快訊)量大格式固定,最適合白牌引擎 | 包裝①變體:「基金月報/快訊引擎」 | 同上(推動團隊成員) |
| 6 | 永豐金證券 | 大型券商 | 已自建豐搜/AI 產文——不會買生成端,但「5 分鐘生成文章」的量產線正需要獨立稽核層 | 包裝②:「生成者與驗證者分離」 | [中央社/PChome](https://news.pchome.com.tw/living/cna/20251002/index-17593706501438618009.html)、[聯合報](https://udn.com/news/story/7251/8190182) |
| 7 | 元大證券 | 最大零售券商 | 投資先生百萬用戶、AI 選股既有品牌;採購慢,放後期用成果敲 | 包裝②接投資先生內容流 | [元大新聞稿](https://www.yuanta.com.tw/file-repository/content/0919news/notice107_0919.htm) |
| 8 | 元大投信 | 最大投信 | 發行主動式 AI ETF(00990A),對外 AI 敘事需要「AI 治理」背書 | 「主動式 ETF 的 AI 決策鏈可稽核性」 | [StockFeel 00990A](https://www.stockfeel.com.tw/00990a-%E5%85%83%E5%A4%A7%E5%85%A8%E7%90%83ai%E6%96%B0%E7%B6%93%E6%BF%9F%E4%B8%BB%E5%8B%95%E5%BC%8F-etf/) |
| 9 | 國泰證券 | 金控子券商 | 母集團 GAIA 2.0 + OpenAI 合作,子公司落地時需要輕量閘門而非集團大平台排隊 | 包裝③:「GAIA 排程外的快速落地」 | [GAIA](https://www.cathayholdings.com/holdings/brand/fintech/ctc/trends/2024cathay_gaia)、[CIO Taiwan](https://www.cio.com.tw/100118/)、[國泰證期 10 大趨勢](https://tw.stock.yahoo.com/news/ai-%E5%85%88%E9%80%B2%E5%B0%81%E8%A3%9D%E8%88%87%E9%AB%98%E8%B3%87%E7%94%A2%E8%B2%A1%E7%AE%A1%E6%88%90%E7%84%A6%E9%BB%9E-%E5%9C%8B%E6%B3%B0%E8%AD%89%E6%9C%9F%E9%BB%9E%E5%90%8D10%E5%A4%A7%E6%8A%95%E8%B3%87%E8%B6%A8%E5%8B%A2-042044057.html) |
| 10 | 凱基證券/凱基投顧 | 大型券商+投顧 | 對外以 AI 為行銷主軸辦投資論壇,投顧研究產出量大 | 「研究報告產線的稽核閘門」 | [凱基 AI 論壇報導](https://udn.com/news/story/7251/9595734);**其內部導入生成式 AI 之新聞:查無公開資訊** |
| 11 | 玉山證券 | 金控子券商 | 母行 GenAI 平台/AI 治理最積極(GENIE、IBM 治理框架、與富果合作淵源),文化上接受新創供應商 | 包裝②以「治理框架的執行層」切入 | [iThome](https://www.ithome.com.tw/news/162549)、[IBM 治理](https://3c.yipee.cc/330753/%E7%8E%89%E5%B1%B1%E9%8A%80%E8%A1%8C%E6%94%9C%E6%89%8B-ibm-%E5%BB%BA%E7%AB%8B-ai-%E6%B2%BB%E7%90%86%E6%A1%86%E6%9E%B6%EF%BC%8C%E7%82%BA%E9%87%91%E8%9E%8D%E6%A5%AD%E5%A4%A7%E8%A6%8F%E6%A8%A1%E5%B0%8E/) |

### Tier C:投顧/投信長尾與通路(用名冊掃,個別佐證待補)
| # | 名稱 | 類型 | 為什麼 | 切入點 | 佐證 |
|---|---|---|---|---|---|
| 12 | 提供 Robo-Advisor 服務之投顧業者群 | 投顧 | 依規則本就要向監理方證明演算法可控,audit trail 是現成舉證工具 | 包裝②+合規文件包 | [Robo-Advisor 作業要點](https://www.rootlaw.com.tw/LawArticle.aspx?LawID=A040390051146500-1131121)、[管理規則修正](https://www.lawbank.com.tw/news/NewsContent.aspx?NID=204962.00);個別業者名單以[公會名錄](https://www.sitca.org.tw/ROC/RoboAdvisor/index.html)為準 |
| 13 | 中小型專營投顧(電子報/會員制) | 投顧 | 人力最薄、內容量大、最怕違規罰單;白牌引擎=整個內容部門 | 包裝① | 名單來源:[投信投顧公會會員名錄](https://www.sitca.org.tw/ROC/MemData/MD2001N.aspx?PGMID=AS0701);個別 AI 導入佐證:**查無公開資訊,需逐家盡調** |
| 14 | 嘉實資訊(XQ 全球贏家) | 金融資訊服務商(通路,非持牌買方) | 白牌金融資訊服務占其營收約 43%、[券商系統整合市占約 9 成,2025-11 上櫃](https://finance.technews.tw/2025/10/20/xq/)——把稽核閘門包進其白牌方案=一次觸達全體券商 | 通路合作/OEM,非直售 | [TechNews](https://finance.technews.tw/2025/10/20/xq/)、[嘉實官網](https://www.sysjust.com.tw/Products/XQ.aspx) |
| 15 | 野村投信 | 投信 | 產品創新積極(全台首檔主動式 ETF 連結基金),對外投資人溝通材料量大 | 包裝①變體 | [鉅亨](https://news.cnyes.com/news/id/6540489);**其 AI 導入新聞:查無公開資訊** |

刻意不湊數:群益、統一、兆豐、華南永昌等券商之 AI 導入**查無公開佐證**,不列入首波名單;掃 Tier C 時以官方名冊+逐家官網盡調補位。

---

## 4. 側翼進攻打法

**通則**:想進 A(大機構),先跟 A 的競爭對手 B(小而快的挑戰者)做出**可驗證成果**,再拿成果敲 A。大機構不敢當第一個,但很怕當最後一個。

### 三步 sequence

**Step 1(第 1–2 月):拿下 B = 口袋證券(備選:好好證券)**
- 為什麼挑它:純網路券商、組織小決策鏈短、內容行銷是其獲客命脈([口袋學堂](https://www.pocket.tw/school/)、社群、教學內容)、沒有母金控的集團 AI 平台包袱,也沒有自建團隊的本錢。
- Offer:**免費或極低價 30 天 PoC**(包裝②),接其一條既有內容產線(如盤後快訊/教學文),我方閘門只做「送出前檢查+留痕」,不改其工作流。
- **第一個可驗證成果長這樣**:一份《LLM 內容稽核月報》——30 天 × N 篇產出、攔截 X 篇(附攔截原因分類:數字幻覺/時效錯誤/禁語)、0 篇壞輸出流出、每篇附完整生成-審核-放行鏈路 log、對照金管會 AI 指引六原則與[券商公會自律規範](https://www.twsa.org.tw/F01/doc/%E4%B8%AD%E8%8F%AF%E6%B0%91%E5%9C%8B%E8%AD%89%E5%88%B8%E5%95%86%E6%A5%AD%E5%90%8C%E6%A5%AD%E5%85%AC%E6%9C%83%E8%AD%89%E5%88%B8%E5%95%86%E9%81%8B%E7%94%A8%E4%BA%BA%E5%B7%A5%E6%99%BA%E6%85%A7%E6%8A%80%E8%A1%93%E8%87%AA%E5%BE%8B%E8%A6%8F%E7%AF%84%E5%8F%8A%E8%AA%AA%E6%98%8E.pdf)逐條打勾的合規對照表。這份文件同時是 B 的法遵資產與我們的 sales deck。

**Step 2(第 3–5 月):把成果變成「業界標準」敘事**
- 徵得 B 同意後發共同案例(或匿名化為「某純網路券商」);投稿 iThome/數位時代等曾大量報導金融 GenAI 的媒體;把《稽核月報》模板開源一小部分(checklist 骨架)建立話語權——對應 YC「compliance infrastructure」敘事,也累積出海故事。
- 同步以此文件包接觸嘉實資訊談 OEM(其白牌方案 43% 營收、觸達全體券商),談不成也摸清通路價格帶。

**Step 3(第 6 月起):拿成果敲 A = 富邦證券(備選:永豐金證券)**
- 話術:「貴集團 20 個 GenAI 專案開發中([公開新聞](https://money.udn.com/money/story/11799/9131287)),每個專案自己做防線=20 套不一致的治理;某券商同業已用我們的閘門跑了 N 個月、攔截率與 log 如附件;金管會明年要求 AI 風險分級與人工介入([報導](https://udn.com/news/story/7239/9486443)),現在補一層橫向閘門,比明年被檢查時補便宜。」
- 進門形式選包裝③(顧問案,50–150 萬,不觸發重大委外門檻、不用打 procurement 大戰),做完自然長成包裝②訂閱。

---

## 5. 定價假設

台灣金融業對「LLM 稽核閘門」尚無公開行情——以下區間多為**假設**,錨點盡量給依據。

| 包裝 | 區間(NT$) | 依據 |
|---|---|---|
| ③ 顧問式導入 | 8,000–15,000/人日;單一專案 50 萬–150 萬(1–3 個月) | 錨點:台灣程式外包行情公開參考([PRO360](https://www.pro360.com.tw/price/software_outsourcing)、[Tasker 出任務](https://www.tasker.com.tw/services/engineering));金融領域+法遵知識溢價上調——溢價幅度為**假設**。四大/外商顧問同型專案報價常為數倍(**查無公開行情,假設**) |
| ② 稽核閘門 SaaS | 3 萬–15 萬/月/條管線(年約 36 萬–180 萬);PoC 期 0–3 萬/月 | **假設**。錨點:替代 0.5–1 名法遵/工程複核人力(台灣金融業該職能年薪約 80–150 萬,**假設**);對照國際 compliance SaaS 常見 US$1–5 萬/年中型客單(**查無台灣公開行情,假設**) |
| ① 白牌日報引擎 | 設置費 30 萬–80 萬 + 授權 60 萬–200 萬/年(依訂戶數分級) | **假設**。錨點:自建同等管線至少 1–2 名工程師×一年(人事成本 150 萬–300 萬+/年,依市場常識,**假設**)+一年試錯期;授權價訂在自建成本 1/3–1/2 才有「買不如自建」的算術 |

定價紀律:第一單重點不是價格是**證據**(logo + 稽核月報);PoC 可免費,但正式約絕不免費,否則在金融業反而顯得不可信。

---

## 6. 法規段(⚠️ 全段需真律師確認,以下為業務邏輯論證)

### 6.1 為什麼「賣 infra」不觸投顧法
- [《證券投資信託及顧問法》](https://law.fsc.gov.tw/LawContent.aspx?id=FL030633)規範的「證券投資顧問」核心構成要件:**直接或間接自委任人或不特定人取得報酬,對有價證券、相關商品提供分析意見或推介建議**。
- 我們的商品是**軟體與工程服務**:生成框架、檢查器、稽核軌跡、回退機制。對「哪支股票該買」不產生、不背書任何意見;**對客戶提供分析行為的主體是持牌買方**,其對投資人的建議責任由其牌照與內控承擔。類比:嘉實資訊賣 XQ 給券商、彭博賣終端機給投顧,均非經營投顧業務。
- 風險邊界(要跟律師確認的點):
  1. 若我們的引擎「內建」選股邏輯且輸出直接到達投資人,是否可能被認定「間接」提供建議?→ 合約與架構上必須讓買方對輸出有**最終審核權與編輯權**(我們的 audit gate 設計剛好天然支持「人工介入點」),且行銷上絕不對投資人宣傳。
  2. 參考反面案例:金管會對**向不特定散戶兜售**自動交易程式曾有認定違法經營顧問業務之函釋方向([查詢入口:證期局法令函釋](https://www.sfb.gov.tw/ch/home.jsp?id=3&parentpath=0);另見[投信投顧公會《認定經營證券投資顧問業務之問答集》](https://www.sitca.org.tw/ROC/Legal/files/%E8%AA%8D%E5%AE%9A%E7%B6%93%E7%87%9F%E8%AD%89%E5%88%B8%E6%8A%95%E8%B3%87%E9%A1%A7%E5%95%8F%E6%A5%AD%E5%8B%99%E4%B9%8B%E5%95%8F%E7%AD%94%E9%9B%86.pdf))——**我們的紅線:只 B2B 賣給持牌機構,永不對散戶賣「分析工具/訊號」**。
  3. 廣告紅線:非投顧業者之廣告不得使人誤信經核准經營投顧業務——官網與提案一律自稱「軟體/基礎設施供應商」。

### 6.2 買方視角:採用第三方 AI 要過哪些關(我們要替買方準備好答案)
- **委外規範**:~~《金融機構作業委託他人處理內部作業制度及程序辦法》(G0380200)~~ **⚠️ 2026-08-02 法務部更正:該辦法適用主體是銀行體系,不適用券商/投顧/投信;本案正確法源=證期局《證券商作業委託他人處理注意事項》(GL003688)與《投信投顧事業作業委託他人處理注意事項》(GL003689,112.08.31 修正),詳見 `2026-08-02_b2b_legal_opinion_internal.md` 第 2 節。** 原引用(僅供銀行類比參考):[G0380200](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0380200)(2023-08 [修正,採風險基礎方法](https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0%2C2&mcustomize=news_view.jsp&dataserno=202308040001&toolsflag=Y&dtable=News)):重大性委外需申請/報備;客戶資料儲存地以境內為原則;複委託需書面同意;雲端另有[雲端委外問答集](https://www.fsc.gov.tw/userfiles/file/%E9%9B%B2%E7%AB%AF%E5%95%8F%E7%AD%94%E9%9B%86%E7%99%BC%E5%B8%83%E7%89%88112%E5%B9%B410%E6%9C%88.pdf)(開發/測試環境若不涉重大性消金系統,毋須依委外辦法申請——PoC 的合規空間)。→ 產品設計對策:**支援地端/買方自有雲部署**、資料不出買方環境、我們只碰 prompt 與輸出不碰客戶個資,盡量把合作定性為「軟體授權」而非「作業委外」(定性**需律師確認**)。
- **AI 指引第三方管理**:[金融業運用 AI 指引](https://www.fsc.gov.tw/websitedowndoc?file=chfsc%2F202408231741530.pdf&filedisplay=%E9%99%84%E4%BB%B6_%E9%87%91%E8%9E%8D%E6%A5%ADAI%E6%8C%87%E5%BC%95.pdf)要求金融機構對第三方 AI 供應商做風險管理與問責安排;[券商自律規範](https://www.twsa.org.tw/F01/doc/%E4%B8%AD%E8%8F%AF%E6%B0%91%E5%9C%8B%E8%AD%89%E5%88%B8%E5%95%86%E6%A5%AD%E5%90%8C%E6%A5%AD%E5%85%AC%E6%9C%83%E8%AD%89%E5%88%B8%E5%95%86%E9%81%8B%E7%94%A8%E4%BA%BA%E5%B7%A5%E6%99%BA%E6%85%A7%E6%8A%80%E8%A1%93%E8%87%AA%E5%BE%8B%E8%A6%8F%E7%AF%84%E5%8F%8A%E8%AA%AA%E6%98%8E.pdf)同向。→ 我們主動附上「供應商盡職調查包」(架構圖、資料流、模型清單、log 保存政策、事故通報 SLA),把買方法遵的作業幫他做完——這本身就是差異化。
- **投顧自動化服務**:若買方是投顧且用於對客服務,適用 [Robo-Advisor 作業要點](https://www.rootlaw.com.tw/LawArticle.aspx?LawID=A040390051146500-1131200)與[修正後投顧管理規則的演算法監理要求](https://www.lawbank.com.tw/news/NewsContent.aspx?NID=204962.00)——我們的稽核軌跡=其向監理方舉證的現成材料。

---

## 7. 誠實風險段:一人團隊賣 B2B 金融的真實阻力

| 阻力 | 現實描述 | 對策 |
|---|---|---|
| 採購週期 | 金控/大券商採購 6–18 個月起跳,要過資訊、法遵、風管、採購四關;一人團隊現金流撐不起純大客戶 pipeline | 順序上先吃 Tier A 小客戶與包裝③顧問案(數十萬級、部門預算可決);大客戶當 12–18 個月期權而非主餐 |
| 資安審查 | 買方會要求 ISO 27001/SOC 2、滲透測試報告、資安問卷數百題;一人團隊多半沒有 | 短期:地端/買方環境部署繞開「資料出境」大題+以完整 audit log 展示替代部分書面認證;中期:預算允許再上 ISO 27001(**認證費用行情查無單一公開數字,假設數十萬台幣級**);或掛靠已有認證的系統整合商(嘉實、資服商)當其分包 |
| 公司資格 | 買方採購常要求:設立滿 N 年、資本額門檻、近年財報、兩名以上聯絡窗口;自然人或新設公司常直接出局 | 立即設立公司開始養年資;首批合作用「顧問服務契約/軟體授權契約」走部門簽核而非集團採購;必要時與整合商聯合投標 |
| Key-man risk | 買方最合理的質疑:「你被卡車撞了我的日報明天誰發?」 | 產品端:地端部署+完整 runbook+程式碼 escrow(源碼託管條款);商務端:SLA 誠實寫、以「確定性回退」設計本身回答——系統壞了也只會退到安全版本,不會沉默 |
| 信任門檻(22 歲/無 logo) | 金融業極度 logo 導向,第一單最難 | 第一單用免費 PoC 買 logo;把 MarketDaily 一年多 production 紀錄(準時率、攔截事故清單、防線架構)做成公開技術白皮書——用工程證據補資歷;YC/國際敘事當第二信任源 |
| 大廠/整合商競爭 | 國泰自建 GAIA、玉山找 IBM;精誠/嘉實隨時可做「夠用的」閘門 | 不跟集團平台正面打,吃「集團平台排不到/養不起自建」的中小與子公司;對嘉實採「合作優先、競爭墊底」;護城河=事故換來的 checklist 與台灣投顧法域知識,持續把新監管動態(代理 AI 指引)搶先產品化 |
| 收入結構風險 | 顧問案吃時間,一人接 2–3 案就滿載,與 MarketDaily 本業互搶 | 顧問案只當敲門磚,每案必須沉澱成包裝②的可複用模組;明訂同時最多 2 個顧問案 |

---

## 8. 建議與下一步(給 Delvin 拍板)

1. **先推包裝②(稽核閘門 SaaS)**:最不碰投顧法、最對監管風向(AI 管 AI/人工介入)、與大機構自建生成端互補不衝突、是 recurring revenue;①②③中唯一能講 YC「AI-Native Compliance Infrastructure」故事的主體。
2. **第一個敲的門:口袋證券**(備選:好好證券)——小、快、內容命脈、無集團包袱;offer = 30 天免費 PoC 換《LLM 內容稽核月報》共同案例。
3. **並行三件事**:設立公司(養採購資格年資)、把 MarketDaily 防線寫成公開技術白皮書(信任資產)、約一位熟證券法規的律師確認第 6 節(一次諮詢即可,先問「軟體授權 vs 作業委外定性」與「間接提供建議」兩題)。
4. 本檔為研究與提案,**未做任何 outreach、未寄任何 email**。

---

### 附:本檔主要來源清單
- 金管會《金融業運用 AI 指引》(2024-06):https://www.fsc.gov.tw/websitedowndoc?file=chfsc%2F202408231741530.pdf&filedisplay=附件_金融業運用AI指引.pdf
- 金管會 AI 調查新聞稿(2025-05):https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0%2C2&mcustomize=news_view.jsp&dataserno=202505200001&dtable=News
- 券商公會 AI 自律規範(2024-11 備查):https://www.twsa.org.tw/F01/doc/中華民國證券商業同業公會證券商運用人工智慧技術自律規範及說明.pdf
- 金管會 AI 監理三方向/代理 AI 納指引(2026):https://udn.com/news/story/7239/9486677 、https://udn.com/news/story/7239/9486443 、https://www.epochtimes.com/b5/26/5/7/n14758846.htm
- 委外辦法:https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0380200 ;雲端委外問答集:https://www.fsc.gov.tw/userfiles/file/雲端問答集發布版112年10月.pdf
- 投信投顧法:https://law.fsc.gov.tw/LawContent.aspx?id=FL030633 ;認定經營投顧業務問答集:https://www.sitca.org.tw/ROC/Legal/files/認定經營證券投資顧問業務之問答集.pdf
- Robo-Advisor 作業要點:https://www.rootlaw.com.tw/LawArticle.aspx?LawID=A040390051146500-1131121 ;投顧管理規則修正:https://www.lawbank.com.tw/news/NewsContent.aspx?NID=204962.00
- 家數/名冊:https://data.gov.tw/dataset/104010 、https://www.sitca.org.tw/ROC/MemData/MD2001N.aspx?PGMID=AS0701 、https://www.sfb.gov.tw/ch/home.jsp?id=776&parentpath=0%2C5%2C775
- 個別機構新聞:國泰 GAIA(cathayholdings.com、cio.com.tw)、富邦金(fubon.com、money.udn.com)、玉山(ithome.com.tw)、永豐金證券(pchome/udn/businessweekly)、元大(yuanta.com.tw)、富果(fugle.ai)、嘉實(technews.tw)
- YC RFS:https://www.ycombinator.com/rfs 、https://quasa.io/media/yc-fall-2026-rfs-how-to-build-ai-native-compliance-infrastructure
- 外包行情參考:https://www.pro360.com.tw/price/software_outsourcing 、https://www.tasker.com.tw/services/engineering
