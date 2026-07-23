/* 美股類股/主題(GICS 11 大類 + 熱門主題)——看盤頁「分類」美股模式用。
   靜態策展表:每類收錄該產業代表性大型股(市值/流動性優先),非全宇宙。 */
const US_INDUSTRY = {
  "科技 Technology": ["AAPL","MSFT","NVDA","AVGO","ORCL","CRM","ADBE","AMD","CSCO","ACN","INTC","IBM","QCOM","TXN","NOW","INTU","AMAT","MU","LRCX","ADI","KLAC","SNPS","CDNS","PANW","ANET"],
  "通訊服務 Communication": ["GOOGL","META","NFLX","DIS","TMUS","VZ","T","CMCSA","CHTR","EA","TTWO","WBD","OMC","LYV","MTCH","PINS","SNAP","RBLX","SPOT"],
  "非必需消費 Consumer Disc.": ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","BKNG","TJX","ORLY","MAR","GM","F","CMG","HLT","ROST","YUM","LULU","AZO","DHI","LEN"],
  "必需消費 Consumer Staples": ["WMT","PG","COST","KO","PEP","PM","MO","MDLZ","CL","TGT","KMB","GIS","KHC","SYY","STZ","KR","HSY","MNST","ADM"],
  "金融 Financials": ["BRK.B","JPM","V","MA","BAC","WFC","GS","MS","AXP","SPGI","BLK","C","SCHW","CB","PGR","MMC","BX","PNC","USB","AON","ICE","CME"],
  "醫療保健 Health Care": ["LLY","UNH","JNJ","MRK","ABBV","TMO","ABT","DHR","PFE","AMGN","ISRG","BSX","SYK","MDT","GILD","VRTX","CVS","REGN","CI","ZTS","BDX","HCA"],
  "工業 Industrials": ["GE","CAT","RTX","HON","UNP","BA","UPS","DE","LMT","ETN","ADP","GD","NOC","MMM","EMR","CSX","ITW","FDX","WM","NSC","PH","TT"],
  "能源 Energy": ["XOM","CVX","COP","EOG","SLB","MPC","PSX","WMB","OKE","VLO","OXY","HES","KMI","BKR","HAL","DVN","FANG","TRGP"],
  "公用事業 Utilities": ["NEE","DUK","SO","D","AEP","SRE","EXC","XEL","PEG","ED","WEC","PCG","ES","AWK","DTE","PPL","AEE","CMS"],
  "房地產 Real Estate": ["PLD","AMT","EQIX","WELL","SPG","PSA","O","CCI","DLR","CBRE","VICI","EXR","AVB","EQR","VTR","IRM","WY","INVH"],
  "原物料 Materials": ["LIN","SHW","APD","ECL","FCX","NEM","CTVA","DOW","NUE","DD","PPG","VMC","MLM","ALB","IFF","LYB","STLD","CF"],
};
const US_THEMES = {
  "AI 概念": ["NVDA","MSFT","GOOGL","META","AMD","AVGO","PLTR","SMCI","MU","TSM","ARM","DELL","ANET","VRT","CRWD","NOW","SNOW"],
  "半導體": ["NVDA","AVGO","AMD","TSM","QCOM","TXN","MU","AMAT","LRCX","KLAC","ADI","INTC","ARM","MRVL","NXPI","MCHW","ON","MPWR"],
  "七巨頭 Magnificent 7": ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA"],
  "電動車 EV": ["TSLA","RIVN","LCID","GM","F","NIO","LI","XPEV","BYDDY"],
  "雲端 SaaS": ["CRM","NOW","SNOW","DDOG","CRWD","PANW","ZS","NET","MDB","TEAM","HUBS","WDAY"],
  "金融科技": ["V","MA","PYPL","SQ","COIN","SOFI","AXP","FIS","FISV","HOOD"],
};
