// 美股產業級通用上下游鏈(手工整理,2026-07-22)。key=Finnhub profile2 finnhubIndustry。
// 節點 t=可點跳轉代號(美股 universe 內);無 t=非美股上市或泛稱。前端標「產業通用鏈」。
const US_CHAIN_GENERIC = {
"Semiconductors": {
  up: [
    {n: "EDA 設計工具", t: "SNPS", r: "Synopsys/Cadence 晶片設計軟體"},
    {n: "半導體設備", t: "ASML", r: "ASML 曝光機、應用材料 AMAT、科林 LRCX"},
    {n: "IP 授權", t: "ARM", r: "處理器架構授權"},
    {n: "晶圓代工", t: "TSM", r: "台積電 ADR、格芯 GFS"},
    {n: "材料/耗材", t: "ENTG", r: "Entegris 特用材料、化學品"},
    {n: "封裝測試", t: "AMKR", r: "Amkor 委外封測"},
  ],
  down: [
    {n: "雲端資料中心", t: "MSFT", r: "微軟/亞馬遜/Google AI 伺服器需求"},
    {n: "消費電子", t: "AAPL", r: "手機、PC 品牌"},
    {n: "伺服器 OEM", t: "SMCI", r: "美超微、戴爾 DELL"},
    {n: "車用電子", t: "TSLA", r: "電動車、ADAS"},
    {n: "網通設備", t: "CSCO", r: "交換器、路由器"},
  ],
},
"Technology": {
  up: [
    {n: "半導體", t: "NVDA", r: "處理器/記憶體晶片(NVDA/AMD/INTC/AVGO/MU)"},
    {n: "代工組裝", t: "FLEX", r: "偉創力、捷普 JBL(EMS)"},
    {n: "面板/零組件", r: "顯示器、光學、機構件"},
    {n: "雲端基礎設施", t: "AMZN", r: "AWS/Azure/GCP 運算資源"},
  ],
  down: [
    {n: "企業 IT 支出", t: "ACN", r: "系統整合(埃森哲/IBM)"},
    {n: "消費者", r: "個人裝置、訂閱服務"},
    {n: "電商/零售通路", t: "BBY", r: "百思買、亞馬遜"},
  ],
},
"Media": {
  up: [
    {n: "內容製作", t: "DIS", r: "影視工作室、體育版權"},
    {n: "雲端/CDN", t: "NET", r: "串流分發基礎設施(Cloudflare/AWS)"},
    {n: "廣告技術", t: "TTD", r: "程序化購買(The Trade Desk)"},
  ],
  down: [
    {n: "廣告主", r: "品牌行銷預算(景氣循環)"},
    {n: "訂閱用戶", r: "串流/會員收入"},
    {n: "電信/有線通路", t: "CMCSA", r: "康卡斯特等分發管道"},
  ],
},
"Retail": {
  up: [
    {n: "品牌/製造商", t: "PG", r: "寶僑、可樂 KO、耐吉 NKE 等供貨"},
    {n: "物流配送", t: "UPS", r: "UPS/FedEx/自建物流"},
    {n: "支付網絡", t: "V", r: "Visa/Mastercard 金流"},
    {n: "商用不動產", t: "SPG", r: "購物中心 REIT"},
  ],
  down: [
    {n: "消費者", r: "民間消費力(就業/薪資連動)"},
    {n: "外送/最後一哩", t: "DASH", r: "DoorDash/Instacart"},
  ],
},
"Automobiles": {
  up: [
    {n: "車用晶片", t: "NXPI", r: "恩智浦、安森美 ON、德儀 TXN"},
    {n: "電池/鋰材", t: "ALB", r: "雅寶(鋰)、電池供應鏈"},
    {n: "零組件系統", t: "APTV", r: "安波福、博格華納 BWA、麥格納 MGA"},
    {n: "鋼鋁材料", t: "X", r: "美國鋼鐵、美鋁 AA"},
  ],
  down: [
    {n: "經銷通路", t: "AN", r: "AutoNation、CarMax KMX"},
    {n: "租車/車隊", t: "CAR", r: "Avis、Hertz HTZ"},
    {n: "共享出行", t: "UBER", r: "Uber/Lyft 平台採購"},
  ],
},
"Auto Components": {
  up: [
    {n: "車用半導體", t: "ON", r: "功率/感測晶片"},
    {n: "塑料/橡膠", t: "DOW", r: "化工原料"},
    {n: "鋼材", t: "NUE", r: "紐柯等鋼廠"},
  ],
  down: [
    {n: "整車廠", t: "GM", r: "GM/福特 F/特斯拉 TSLA/Stellantis STLA"},
    {n: "售後維修市場", t: "ORLY", r: "O'Reilly、AutoZone AZO"},
  ],
},
"Pharmaceuticals": {
  up: [
    {n: "CRO 委託研究", t: "IQV", r: "艾昆緯、查爾斯河 CRL"},
    {n: "實驗儀器/耗材", t: "TMO", r: "賽默飛、丹納赫 DHR"},
    {n: "包材/給藥系統", t: "WST", r: "西氏醫藥包裝"},
    {n: "原料藥 API", r: "多在海外(印度/中國)代工"},
  ],
  down: [
    {n: "藥品批發", t: "MCK", r: "麥克森、Cencora COR、Cardinal CAH"},
    {n: "連鎖藥局", t: "CVS", r: "CVS/Walgreens WBA"},
    {n: "保險給付方", t: "UNH", r: "聯合健康等 PBM/保險"},
  ],
},
"Biotechnology": {
  up: [
    {n: "定序/實驗平台", t: "ILMN", r: "Illumina、安捷倫 A"},
    {n: "儀器試劑", t: "TMO", r: "賽默飛、丹納赫 DHR"},
    {n: "CRO/CDMO", t: "CRL", r: "臨床試驗與代工生產"},
    {n: "創投/資本市場", r: "未獲利階段靠融資(利率敏感)"},
  ],
  down: [
    {n: "大藥廠授權/併購", t: "PFE", r: "輝瑞、默克 MRK、禮來 LLY 補管線"},
    {n: "醫療體系", r: "醫院、專科診所處方"},
  ],
},
"Health Care": {
  up: [
    {n: "醫療器材", t: "MDT", r: "美敦力、史賽克 SYK、波科 BSX"},
    {n: "藥品分銷", t: "MCK", r: "醫院藥品供應"},
    {n: "醫療 IT", t: "VEEV", r: "Veeva、電子病歷系統"},
  ],
  down: [
    {n: "保險/給付", t: "UNH", r: "聯合健康、Elevance ELV、信諾 CI"},
    {n: "病患自付", r: "人口老化長期需求"},
  ],
},
"Life Sciences Tools & Services": {
  up: [
    {n: "精密零件/光學", r: "儀器上游組件"},
    {n: "特用化學試劑", r: "抗體、酶、耗材原料"},
  ],
  down: [
    {n: "藥廠研發", t: "LLY", r: "大藥廠與 Biotech 實驗室"},
    {n: "學研機構", r: "大學、政府實驗室(NIH 預算連動)"},
    {n: "診斷實驗室", t: "DGX", r: "Quest、LabCorp LH"},
  ],
},
"Banking": {
  up: [
    {n: "存款人/貨幣市場", r: "資金成本(利率環境)"},
    {n: "金融科技基建", t: "FI", r: "Fiserv、FIS 核心系統"},
    {n: "信用評級/數據", t: "SPGI", r: "標普全球、穆迪 MCO"},
  ],
  down: [
    {n: "企業放貸", r: "商業貸款、投行業務"},
    {n: "房貸", t: "RKT", r: "住房金融"},
    {n: "信用卡網絡", t: "V", r: "Visa/Mastercard/美運通 AXP"},
  ],
},
"Financial Services": {
  up: [
    {n: "交易所", t: "ICE", r: "洲際交易所、CME、那斯達克 NDAQ"},
    {n: "金融數據", t: "SPGI", r: "指數與數據(標普/MSCI/FactSet FDS)"},
    {n: "清算託管", t: "BK", r: "紐約梅隆等託管行"},
  ],
  down: [
    {n: "資產管理", t: "BLK", r: "貝萊德、黑石 BX"},
    {n: "散戶券商", t: "SCHW", r: "嘉信、Robinhood HOOD"},
    {n: "企業融資需求", r: "IPO/併購/發債循環"},
  ],
},
"Insurance": {
  up: [
    {n: "再保險", t: "RNR", r: "RenaissanceRe、Everest EG 分散風險"},
    {n: "精算/風險數據", t: "VRSK", r: "Verisk 風險模型"},
    {n: "投資市場", r: "浮存金收益(利率連動)"},
  ],
  down: [
    {n: "保險經紀", t: "MMC", r: "威達信、怡安 AON 通路"},
    {n: "個人/企業保戶", r: "保費收入"},
  ],
},
"Energy": {
  up: [
    {n: "油田服務", t: "SLB", r: "斯倫貝謝、哈里伯頓 HAL、貝克休斯 BKR"},
    {n: "鑽井平台/設備", t: "RIG", r: "Transocean 離岸鑽井"},
    {n: "砂石壓裂材料", r: "頁岩開採耗材"},
  ],
  down: [
    {n: "煉油", t: "VLO", r: "瓦萊羅、馬拉松 MPC、菲利普 PSX"},
    {n: "管線運輸", t: "KMI", r: "Kinder Morgan、Williams WMB"},
    {n: "石化", t: "LYB", r: "利安德巴塞爾、陶氏 DOW"},
    {n: "出口 LNG", t: "LNG", r: "Cheniere 液化天然氣"},
  ],
},
"Utilities": {
  up: [
    {n: "天然氣供應", t: "KMI", r: "管線輸氣"},
    {n: "太陽能設備", t: "FSLR", r: "第一太陽能、Enphase ENPH"},
    {n: "風電/電網設備", t: "GEV", r: "GE Vernova 渦輪與電網"},
    {n: "核燃料", t: "CCJ", r: "Cameco 鈾"},
  ],
  down: [
    {n: "資料中心", t: "MSFT", r: "AI 用電需求大戶"},
    {n: "家庭/工商用電", r: "受監管費率收入"},
    {n: "電動車充電", r: "電氣化長期需求"},
  ],
},
"Aerospace & Defense": {
  up: [
    {n: "引擎", t: "GE", r: "GE 航太、RTX 普惠"},
    {n: "航電系統", t: "HON", r: "漢威、Teledyne TDY"},
    {n: "特殊合金/鍛件", t: "HWM", r: "Howmet、ATI"},
    {n: "軍規晶片", r: "抗輻射半導體"},
  ],
  down: [
    {n: "航空公司", t: "DAL", r: "達美、聯合 UAL 機隊採購"},
    {n: "國防預算", r: "美國國防部與盟國軍購"},
    {n: "太空商業化", t: "RKLB", r: "Rocket Lab、衛星星座"},
  ],
},
"Airlines": {
  up: [
    {n: "飛機製造", t: "BA", r: "波音、空中巴士"},
    {n: "引擎維修 MRO", t: "GE", r: "發動機大修合約"},
    {n: "燃油", t: "VLO", r: "航空煤油(油價敏感)"},
    {n: "機場/地勤", r: "起降費、地面服務"},
  ],
  down: [
    {n: "商務/休閒旅客", r: "旅遊景氣"},
    {n: "OTA 訂票平台", t: "BKNG", r: "Booking、Expedia EXPE"},
    {n: "航空貨運", t: "FDX", r: "腹艙與全貨機"},
  ],
},
"Telecommunication": {
  up: [
    {n: "網通設備", t: "CSCO", r: "思科、Arista ANET"},
    {n: "光纖/光學", t: "GLW", r: "康寧光纖"},
    {n: "基頻晶片", t: "QCOM", r: "高通 5G"},
    {n: "基地台鐵塔", t: "AMT", r: "美國鐵塔、Crown Castle CCI(租賃)"},
  ],
  down: [
    {n: "消費者/企業月租", r: "電信服務收入"},
    {n: "串流平台", t: "NFLX", r: "頻寬需求方"},
  ],
},
"Chemicals": {
  up: [
    {n: "油氣原料", t: "XOM", r: "乙烷/石腦油(油價連動)"},
    {n: "工業氣體", t: "LIN", r: "林德、空氣產品 APD"},
    {n: "礦物原料", r: "磷、鉀、鹽"},
  ],
  down: [
    {n: "農業", t: "CTVA", r: "科迪華種子農藥、肥料 MOS/NTR"},
    {n: "塗料", t: "SHW", r: "宣偉、PPG"},
    {n: "包裝", t: "AMCR", r: "Amcor 塑料包材"},
    {n: "營建/汽車", r: "終端工業需求"},
  ],
},
"Metals & Mining": {
  up: [
    {n: "採礦設備", t: "CAT", r: "卡特彼勒、Komatsu"},
    {n: "能源成本", r: "電力/柴油(冶煉大宗)"},
    {n: "炸藥/化學品", r: "採礦耗材"},
  ],
  down: [
    {n: "營建骨材", t: "VMC", r: "Vulcan、Martin Marietta MLM"},
    {n: "汽車/家電用鋼", t: "GM", r: "製造業需求"},
    {n: "電池金屬需求", t: "TSLA", r: "鋰/鎳/銅電氣化"},
  ],
},
"Machinery": {
  up: [
    {n: "鋼材", t: "NUE", r: "紐柯、Steel Dynamics STLD"},
    {n: "液壓/傳動元件", t: "PH", r: "派克漢尼汾、伊頓 ETN"},
    {n: "工業自動化", t: "EMR", r: "艾默生、羅克韋爾 ROK"},
  ],
  down: [
    {n: "營建基建", t: "URI", r: "聯合租賃(設備租賃通路)"},
    {n: "農業", r: "農機需求(穀價連動)"},
    {n: "礦業/能源客戶", r: "資本支出循環"},
  ],
},
"Real Estate": {
  up: [
    {n: "營建商", t: "DHI", r: "霍頓、萊納 LEN、普爾特 PHM"},
    {n: "建材供應", t: "BLDR", r: "Builders FirstSource"},
    {n: "房貸融資", t: "RKT", r: "利率環境決定資金成本"},
  ],
  down: [
    {n: "物流租戶", t: "AMZN", r: "電商倉儲需求"},
    {n: "數據中心租戶", t: "MSFT", r: "雲端/AI 機房"},
    {n: "零售/辦公租戶", r: "租金收入來源"},
  ],
},
"Food Products": {
  up: [
    {n: "農產貿易", t: "ADM", r: "ADM、邦吉 BG 原料"},
    {n: "包裝", t: "BALL", r: "Ball 罐裝、Amcor AMCR"},
    {n: "物流冷鏈", t: "UPS", r: "配送網絡"},
  ],
  down: [
    {n: "超市通路", t: "KR", r: "克羅格、沃爾瑪 WMT、好市多 COST"},
    {n: "餐飲服務", t: "MCD", r: "連鎖餐廳、Sysco SYY 食品配送"},
  ],
},
"Beverages": {
  up: [
    {n: "農產原料", t: "ADM", r: "糖、咖啡豆、大麥"},
    {n: "鋁罐/玻璃瓶", t: "BALL", r: "Ball、O-I 玻璃"},
  ],
  down: [
    {n: "超市/便利店", t: "WMT", r: "零售通路"},
    {n: "餐飲/酒吧", r: "現飲通路"},
  ],
},
"Hotels Restaurants & Leisure": {
  up: [
    {n: "食品供應鏈", t: "SYY", r: "Sysco 餐飲食材配送"},
    {n: "訂房平台", t: "BKNG", r: "OTA 導客(抽佣)"},
    {n: "人力成本", r: "最低工資與勞動市場"},
  ],
  down: [
    {n: "旅遊消費者", r: "可支配所得循環"},
    {n: "商務差旅", r: "企業出差預算"},
  ],
},
"Logistics & Transportation": {
  up: [
    {n: "飛機/卡車", t: "BA", r: "波音、Paccar PCAR"},
    {n: "燃油", t: "VLO", r: "柴油/航油成本"},
    {n: "倉儲自動化", t: "HON", r: "分揀機器人"},
  ],
  down: [
    {n: "電商", t: "AMZN", r: "包裹量最大來源"},
    {n: "零售補貨", t: "WMT", r: "供應鏈運輸"},
    {n: "製造業", r: "B2B 貨運需求"},
  ],
},
"Road & Rail": {
  up: [
    {n: "機車頭/車廂", t: "WAB", r: "Wabtec 鐵路設備"},
    {n: "柴油", r: "燃料成本"},
    {n: "鋼軌基建", t: "NUE", r: "軌道材料"},
  ],
  down: [
    {n: "大宗商品託運", r: "煤炭、穀物、化學品"},
    {n: "多式聯運", t: "JBHT", r: "J.B. Hunt 卡車接駁"},
    {n: "汽車運輸", t: "GM", r: "整車出廠物流"},
  ],
},
"Textiles Apparel & Luxury Goods": {
  up: [
    {n: "面料/代工", r: "亞洲成衣供應鏈(儒鴻/聚陽等)"},
    {n: "棉花/皮革原料", r: "大宗農產"},
  ],
  down: [
    {n: "百貨/電商通路", t: "AMZN", r: "亞馬遜、梅西 M"},
    {n: "運動零售", t: "DKS", r: "Dick's 等專賣店"},
    {n: "消費者品牌力", r: "定價權來自品牌"},
  ],
},
"Electrical Equipment": {
  up: [
    {n: "銅/鋼原料", t: "FCX", r: "自由港銅"},
    {n: "功率半導體", t: "ON", r: "IGBT/SiC 元件"},
  ],
  down: [
    {n: "電網升級", t: "GEV", r: "輸配電投資"},
    {n: "資料中心電力", t: "VRT", r: "Vertiv 機房電源散熱"},
    {n: "營建/工業", r: "自動化與電氣化需求"},
  ],
},
"Communications": {
  up: [
    {n: "晶片", t: "QCOM", r: "通訊半導體"},
    {n: "光模組/元件", t: "COHR", r: "Coherent 光通訊"},
  ],
  down: [
    {n: "電信營運商", t: "VZ", r: "Verizon、AT&T T 設備採購"},
    {n: "雲端資料中心", t: "AMZN", r: "網路架構升級"},
  ],
},
"Packaging": {
  up: [
    {n: "紙漿/樹脂", t: "IP", r: "國際紙業原紙、化工樹脂"},
    {n: "鋁材", t: "AA", r: "罐用鋁"},
  ],
  down: [
    {n: "食品飲料", t: "KO", r: "最大包材需求方"},
    {n: "電商出貨", t: "AMZN", r: "瓦楞紙箱"},
    {n: "醫藥包材", t: "WST", r: "無菌包裝"},
  ],
},
"Tobacco": {
  up: [
    {n: "菸葉農產", r: "契作農戶"},
    {n: "加熱器件", r: "新型菸具電子零件"},
  ],
  down: [
    {n: "便利店通路", r: "零售分銷"},
    {n: "監管環境", r: "FDA 政策決定產品線"},
  ],
},
};
