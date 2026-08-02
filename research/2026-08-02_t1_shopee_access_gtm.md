# 蝦皮客服代營運:接入路徑與獲客實務查證(2026-08-02)

> 任務:Dropshipping 部「蝦皮聊聊代營運」T1 查證。方法:WebFetch 官方文件(open.shopee.com 經 r.jina.ai 鏡像、seller.shopee.tw)+ DuckDuckGo 檢索。WebSearch 額度當日已罄,部分次要項標「未能查證」。

---

## 1. 接入路徑結論(最重要)

### 1a. Shopee Open Platform 官方 API — **正門對「新第三方客服工具」已關閉**

- **關鍵條款(官方 FAQ 原文)**:
  > "Applications for Customer Service Apps from Individual Third Parties and Third-party Partner Platforms have been closed **since November 18, 2024**."
  — 來源:Shopee Open Platform FAQ「Conditions of using Chat API」 https://open.shopee.com/faq/56
- 同一頁的其他硬條款:
  - **禁止 chatbot 自動回覆**:"Certain automatic chat messages such as proactive order updates, promotional chat broadcasts and **chatbot replies are prohibited**"。不得把自動訊息偽裝成人工訊息(反之亦然);聊聊資料不得用於回覆買家以外用途。
  - **量門檻(既有 ISV 續用資格)**:ISV 過去 30 天授權店鋪**平均訂單數 >100**(單一店鋪 >21)才保有 Chat API 權限;不達標或偵測到異常行為,"Shopee reserves the right to remove your access to the Chat API"。
- Chat API 本身存在且完整(18 個 endpoint:`v2.sellerchat.send_message` / `get_message` / `get_conversation_list` / `reply_offer` / `upload_image` / `send_autoreply_message` 等),文件:https://open.shopee.com/documents/v2/v2.sellerchat.get_message?module=109&type=1 、權限清單 FAQ:https://open.shopee.com/faq?top=186&sub=187&page=1&faq=240 —— **但拿不到 Customer Service App 類別授權就用不到**。
- 開發者註冊本身:開放平台帳號獨立於賣場帳號;申請資格為「商城賣家(自行串接)或第三方系統供應商」(第三方中文教學:https://global.lianlianpay.com/channel/30-28504.html 、https://www.e-com-net.com/article/1698260821852893184.htm )。**「商城賣家自用 App」能否在 2024-11-18 後仍申請到 Chat API 權限,官方頁面未明寫 → 未能查證,需開 ticket 向 Shopee 官方確認**(open.shopee.com Ticket System)。
- ⚠️ open.shopee.com 直接抓取被擋,以上為 jina 鏡像 + FAQ 快取內容;上線前應登入開發者後台逐字複核。

**結論:「用 API 做 AI 自動回覆的第三方 SaaS」這條路現在走不通**——新客服 App 停收 + chatbot 回覆明文禁止 + 訂單量門檻。這反而是護城河:合規玩家都進不來,**「人+AI 草稿」代營運不碰 API,完全繞開此限制**。

### 1b. 最快合規路徑(建議採用)

**蝦皮子帳號(Sub-account)+ 網頁版聊聊,人工送出**:
- 蝦皮賣家中心原生支援子帳號/多客服,把子帳號給代營運方=賣家自己授權員工,不涉 Open Platform、不違反 Chat API 條款。
- 半自動輔助的合規邊界:AI 只產「建議回覆草稿」,**由真人審閱後按送出**(瀏覽器側邊欄/另開視窗貼上,不注入、不自動送出、不模擬點擊)。蝦皮官方規則罰的是「自動訊息/垃圾訊息/違規言論」,不是「客服打字前先看小抄」。
- 加分:蝦皮台灣官方自己有「問答小幫手/離線自動回覆/AI 客服」內建功能,且官方明文「AI 客服完全解決的訊息不列入回應率計算」(https://seller.shopee.tw/edu/article/201 )→ 官方內建自動化+我方人審 AI 草稿,雙層並用即為最快合規組合。
- **紅線**:不用「模擬人工發送」類外掛(見競品表阿靳條目)——該類工具正踩 FAQ/56 的 chatbot 禁令與「偽裝自動為人工」條款,帳號被封=客戶死。

### 1c. LINE OA Messaging API(完全開放的第二戰場)

把蝦皮買家導去賣家自有 LINE OA 做售後/回購,這條 API 全開放、無審核門檻:
- 台灣 LINE 官方帳號定價(官方:https://tw.linebiz.com/faq/oa-price/message-price-list/ ):
  - **輕用量:月費 NT$0,免費 200 則/月**
  - **中用量:月費 NT$800,3,000 則/月(不可加購)**
  - **高用量:月費 NT$1,200,6,000 則/月,加購每則 NT$0.2 起階梯遞減**
  - 計費的是主動推送(push/廣播);**回覆用戶來訊(reply)不計費** → 純客服情境幾乎零訊息成本。
- 注意:蝦皮聊聊內**引導站外交易/留站外聯絡方式屬違規**(聊聊違規:https://seller.shopee.tw/edu/article/12768 ),導 LINE 只能透過出貨小卡、包裹內卡片等站外觸點,不可在聊聊裡發 LINE ID。

---

## 2. 競品盤點(台灣可及的蝦皮聊聊工具)

| 工具 | 類型 | 功能 | 定價 | AI | 代營運 | 合規風險 |
|---|---|---|---|---|---|---|
| 蝦皮官方:問答小幫手/離線自動回覆/AI 客服 | 平台內建 | FAQ 自動回、離線回、AI 解題(不扣回應率) | 免費 | 有(官方) | 無 | 零(官方功能) |
| 阿靳 聊聊群發(ajin.tw/products/shopeechat) | 桌面工具/模擬人工 | 聊聊群發、自動關注;另有「智能客服」自動回覆 | 30天/7.2萬封 NT$69,800 起,一年 NT$699,800 | 部分 | 無 | **高**:群發+「模擬人工發送」直踩官方禁令;頁面完全不提風險 |
| 阿靳 聊聊自動回覆(Chrome 擴充) | 瀏覽器擴充 | 自訂問答範本 24h 自動回,「模擬人工發送」 | 未查得 | 規則式 | 無 | **高**(同上) |
| 蝦皮聊聊助手(黑科技研究院 shopee777.com) | 桌面軟體(中國系) | 多帳號分組、逾時自動回覆、快捷模板、翻譯、售後登記;號稱回覆率95%+ | 未公開 | 無明確 AI | 無 | 中高:自動回覆繞官方管道 |
| 蝦皮助手 Shopee Fans(keyouyun.com) | 瀏覽器擴充(中國系,主攻跨境) | 數據分析、引流、聊聊置頂等 | 未查得 | 無 | 無 | 中 |
| SaleSmartly | 全通路客服 SaaS(中國系) | 官網主打 FB/IG/WhatsApp/LINE 聚合;有 Shopee 生態合作夥伴(Shopdora) | 未查得 | 有 | 無 | 依接入方式而定;台灣本地支援弱 |
| Sellercraft OmniChat(sellercraft.co,東南亞) | ISV 聚合面板 | Shopee/Lazada/TikTok 聊天單一儀表板 | 未查得 | 未知 | 無 | 屬既有 ISV 存量;台灣站支援未查證 |
| Omnichat(台灣 omnichat.ai) | 台灣全通路客服 SaaS | LINE/FB/IG/WhatsApp;**官網未列蝦皮聊聊整合** | 未查得 | 有 | 無 | — |
| AgentAI 智庫「聊聊快速回覆器」 | 網頁 prompt 工具 | 貼上買家問題→AI 產三種語氣回覆(人工貼回) | 免費樣態 | 有 | 無 | 低(人工送出) |

**競品結論**:市場現況兩極——合規端只有「官方內建」與「人工貼上小工具」,自動化端全是灰色模擬人工工具(且貴得離譜:阿靳年約 70 萬)。**「AI 草稿+真人送出+整段客服外包(代營運)」在台灣是空位**,沒有任何一家做「代營運」。

## 3. 獲客通路

### FB 社團前 5(成員數需登入 FB 逐一確認,DDG 查不到準確數 → 標未驗證)
1. 蝦皮賣家互助聯盟 — facebook.com/groups/shopee178/(檢索中規模最大、最活躍;成員數未驗證)
2. 【蝦皮台灣 Shopee Taiwan】買賣交易討論區(非官方) — facebook.com/groups/shopeetaiwan/
3. 成為蝦皮熱門賣家社群 — facebook.com/groups/shoppeseller/
4. 蝦皮賣家互助社團 — facebook.com/groups/937942163897010/
5. 台灣蝦皮副業交流群SHOPEE.TW — facebook.com/groups/twshopee/
(另:蝦皮賣家討論區 groups/1568192893508593、蝦皮買家賣家討論交流區 groups/966217333777287)

### 其他
- **PTT**:e-seller 板(電商賣家板,蝦皮政策/經營討論)
- **Dcard**:網路購物板、創業板、「蝦皮賣家」話題頁(dcard.tw/topics/蝦皮賣家)
- **官方**:蝦皮大學 university.shopee.tw(官方講座/社群,可觀察痛點但不宜直接招攬)
- **LINE OpenChat**:臺灣蝦皮買家賣家交流社群(檢索有見,未逐一驗證)

### 免費 pilot 招募貼文草稿(由老闆本人或新品牌帳號發;發前需照社團版規)

**A 版(痛點直球)**
> 【聊聊回不完的賣家看過來】
> 白天上班/晚上包貨,聊聊訊息一堆「有現貨嗎」「什麼時候到」,12 小時內沒回,回應率就掉、單就飛。
> 我們是小團隊,幫賣家「代看聊聊」:真人客服+AI 輔助,詢價、催件、售後全接,平均 X 分鐘內回,回應率拉回 95%+。
> 現在找 3 位賣家**免費體驗 30 天**(不用裝任何軟體,開子帳號給我們就好,全程符合蝦皮規範、絕不用外掛)。
> 有興趣留言「+1」或私訊,額滿為止。

**B 版(數據誘因)**
> 【免費幫你顧 30 天聊聊,換一個成效案例】
> 做個實驗:我們幫你代營運蝦皮聊聊 30 天,完全免費,只要求結束後讓我們把「前後數據」做成匿名案例(回應率、平均回覆時間、詢問轉單率)。
> 你會拿到:每天早 9 到晚 11 有人顧聊聊、AI 整理的常見問題庫、週報。
> 我們拿到:一個真實案例。雙贏。
> 條件:日均聊聊 ≥10 則的賣場優先。名額 3 個,私訊聊。

## 4. 計價錨

- **台灣蝦皮/電商客服人力行情**(104/1111/518/比薪水,2026-08 檢索):
  - 全職文字客服月薪 **NT$32,000–45,000**(蝦皮總部文字客服 40–42k;平均約 43.1k)
  - 兼職小幫手時薪約 NT$190–264(蝦皮智取門市時薪 264 為參考上緣;台灣基本時薪之上)
- **換算按件錨(自行推算,標明)**:月薪 35k ÷ 22 天 ÷ 8h ≈ NT$199/h;人工每小時可處理 15–30 則對話 → **每則對話人力成本約 NT$7–13**。AI 輔助若讓單人吞吐 ×2–3,按件報 **NT$5–10/則** 或月費 3,000–8,000(日均 10–50 則賣場)即有毛利、又遠低於自聘。
- **對照灰色工具**:阿靳群發 30 天 NT$69,800 —— 顯示賣家對聊聊自動化的付費意願天花板不低。
- **蝦皮官方壓力=需求來源**(定價的「痛」錨):
  - 聊聊回應率:30 天窗口、**12 小時內回覆**否則算延遲拉低回應率(https://seller.shopee.tw/edu/article/201 ;營運指標:article/22383)
  - 低回應率罰則:檢索到「30 天內 ≥10 筆訂單且回應率 ≤20% → 計 1 分」(第三方轉述,官方原文未逐字驗證 → 標)
  - 賣家計分:**累計 ≥15 分凍結帳號 28 天**(官方:https://seller.shopee.tw/edu/article/197 );商城賣家 ≥3 分即觸發額外限制(article/665)
  - 聊聊違規(不當言論/濫發):**當季 1–2 次每次 2 分,3 次以上每次 15 分**(https://seller.shopee.tw/edu/article/599 、article/12768)→ 一次重罰=直接凍結,「合規代營運」本身就是賣點

## 5. 風險紅線清單

1. **不碰 Chat API 自動回覆**:新第三方客服 App 已停收(2024-11-18)且 chatbot replies 明文禁止(open.shopee.com/faq/56)。
2. **不用模擬人工外掛**(阿靳類):偽裝自動為人工=條款明禁;群發=濫發違規計分,3 次以上每次 15 分=凍結 28 天。
3. **不在聊聊導站外**:留 LINE/站外連結屬聊聊違規;LINE 導流只走包裹小卡等站外觸點。
4. **子帳號授權要白紙黑字**:與客戶簽委任,聊聊資料只用於回覆該賣場買家(呼應官方資料使用限制),不得拿客戶對話資料訓練跨客戶模型。
5. **AI 草稿必經真人送出**:這是整個模式的合規基石;任何「省掉人按送出」的提案一律否決。
6. **未驗證項**:①商城賣家「自用 App」能否仍獲 Chat API 權限(需官方 ticket)②FB 社團成員數 ③「回應率≤20% 計 1 分」官方原文 ④Sellercraft/SaleSmartly 台灣站實際支援。

## 來源
- Shopee Open Platform FAQ/56(Chat API 條件)、FAQ 240(權限清單)、sellerchat 文件 — open.shopee.com(經鏡像抓取,上線前後台複核)
- 蝦皮賣家幫助中心:article/201(回應率)、197(計分)、599(不當言論計分)、12768(聊聊違規)、665(商城額外規範)、22383(聊聊營運指標)
- LINE 定價:tw.linebiz.com/faq/oa-price/message-price-list/
- 開發者註冊教學:global.lianlianpay.com/channel/30-28504.html、e-com-net.com/article/1698260821852893184.htm
- 競品:ajin.tw/products/shopeechat、shopee777.com、keyouyun.com/zh-hant/shopee-fans/、salesmartly.com、sellercraft.co/omnichat/、omnichat.ai/tw/、agentai.tw
- 人力行情:104/1111/518/salary.tw 檢索(2026-08)
