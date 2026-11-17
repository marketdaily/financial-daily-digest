# 景翔 HMI(cMT2166X)交付前技術風險驗證 — 2026-11-16
## 給老闆的白話結論(11-17)
景翔這台 HMI 設計稿要求的 11 個技術點**全部驗證完成**(在 EasyBuilder 實建、編譯 0 錯誤,能模擬的都在模擬器實跑截圖):三狀態圖、路徑動畫、無效值顯示「--」、環形功率表、42 刀位刀具列表(捲動/高亮/編輯/檢測中鎖定)、中英切換(含警報)、頂欄時鐘/帳號/角色、自訂字型、OMRON NX102 標籤直讀、遠端交付流程;素材容量也量過,全套圖放進去只用掉約兩成,不會爆。客戶給的 Excel 變數表我們現在一鍵就能轉成 HMI 匯入檔(格式錯誤會先擋下來)。**還要客戶給的**:① 正式的 Excel 變數表(變數名稱/資料型態/陣列長度/說明)或 Sysmac 匯出的 txt;② 他們設 Network Publish 後跳的那個警告**原文截圖**+工作(Task)清單——依 OMRON 手冊看,最可能是同一個變數被兩個工作同時用到,不是 HMI 的問題,排查步驟已寫好可直接轉給他們工程師;③ PLC/HMI 的 IP、韌體版本、DIP 開關已切且重新上電的確認;④ 角色權限(幾種角色、誰能改什麼)、警報清單、正式設計稿圖檔。實機上才能確認的(大字級外觀、JPG 畫質、真 PLC 連線)排在第 3 週現場。

**11-17 補(#14,客戶改用 FINS 位址模式)**:客戶說改用 OMRON Ethernet(FINS)讀 PLC 的固定位址(%W/%H/%D),不開 Network Publish ⇒ 之前那個警報在新做法裡不會出現。已在 HMI 實建驗證:W、H 區開關燈、D 區整數與小數、42 刀刀具列表(一刀一組 D 區位址,上下捲動、寫入、捲到底停住都正常),編譯 0 錯誤。給客戶的 Excel 位址表範本做好了(含 PLC 端 15 項設定對照)。**要提醒客戶的兩件事**:① NX102 的 W/H/D 記憶體**預設是關的**,要在 Sysmac 的 Memory Settings 打開;② 放在 H/D 區的變數**一定要勾 Retain**、W 區的**不能勾**,否則 Sysmac 會報錯。真 PLC 連線與 32 位元數值字序排第 3 週現場驗。


內部驗證,非交付物。判定只有兩種終點:✅已做到(建物件→編譯0錯誤→模擬器實跑→截圖)/ 🛠 學習計畫+替代做法+驗證完成。
環境:winrig 原生 EasyBuilder Pro 被 Smart App Control 擋(CodeIntegrity 3118),改用 **Wine 11.22 可攜版 + Xvfb :77 虛擬螢幕**跑 EBPro V6.09.02.608(完全背景,不碰實體螢幕)。工作專案 Wine `C:\work\spike.cmtp`(=`~/gifu_spike/pfx/drive_c/work/`),截圖 `research/gifu_spike_shots/`。

## 總表
| # | 項目 | 狀態 | 結論一句話 | 截圖 |
|---|---|---|---|---|
| 1 | 三狀態圖 LW 0/1/2 | ✅ | 多狀態指示燈(Word Lamp)綁 LW,3 張 PNG 依值切換,無觸控 | 01_strip.png |
| 2 | 路徑動畫 LB 控制 | ✅ | 正式採「流動塊」(15.8fps、單一字組控速/停);客製光點用多幀點陣圖+巨集(9.8fps);LB=0/無效強制停皆實測 | 02_anim_grid.png |
| 3 | 無效值顯示「--」 | ✅ | 數值物件「啟用條件 LB=ON、關閉時隱藏」+同位置位元指示燈 OFF 顯示「--」;實測無效時絕不出現 0 | 03_strip_wine_font.png |
| 4 | 環形功率量規 | ✅ | 棒圖→圓形 + 數值綁同一 LW,0/25/50/75/100 實測同步 | 04_ring_strip.png |
| 5 | 刀具列表 42×8 捲動/高亮/編輯/鎖定 | ✅ | 11 列×10 物件 + 索引暫存器 LW-9200 捲動;選列高亮跟刀走、捲到底停 42、編輯寫入、檢測中 LB 鎖基準刀長皆實測 | 05_*.png |
| 6 | 中英文切換 | ✅ | 文字標籤庫(Excel 匯入)+一顆多狀態開關寫 LW-9134;標題、雙狀態文字、警報訊息(含已發生的)、警報表頭全部即時中↔英;⚠️ 編譯時要勾 Language 2 | 06_*.png |
| 7 | 頂欄時鐘/帳號/角色 | ✅ | 日期/時間物件 YYYY/MM/DD HH:MM:SS;帳號=ASCII 讀 PLW-10754;角色=巨集把 LW-9222 權限位元轉 0–3 → 多狀態指示燈+標籤庫(未登入/操作員/工程師/管理員,中英);登入登出走控制位址 PLW-8950 | 07_*.png |
| 8 | 自訂字型 | ✅ | 可以:安裝到 Windows 字型的 TTF 會在編譯時子集化嵌入 cxob(`mt8000/pub/fonts/`),動態數值也用該字型;Google Fonts 原檔需先過 `hmi_font_prep.py`(去 DSIG/GDEF/GPOS/GSUB)否則「無法產生字型檔案」 | 08_*.png |
| 9 | 素材預算 vs 60.58MB | ✅ | 1920 全頁背景+30 張狀態圖+刀具列表底圖實放編譯:全案 8.52MB、剩 55.48MB;EB **原封不動存 PNG**(不重壓)⇒ 預算=檔案大小;每頁背景用 256 色 PNG 或 JPG 可從 1.86MB 壓到 0.4–0.7MB,10 頁設計稿也只吃 ~1/4 容量 | 09_a_compile_assets_0err.png |
| 10 | 遠端交付 SOP | ✅ | 離線模擬包(專案檔+bat,客戶裝免費 EB 即可雙擊跑)實測;USB 用 `project.cxob` 實際產出;遠端桌面/乙太網路下載流程+埠號;EasyAccess 2.0=每台一次性授權 RZACEA020(官方規格書);SOP+客戶清單 | 10_*.png |
| 11 | OMRON NX102 EtherNet/IP 標籤匯入 | ✅ | 驅動 OMRON_EIP_NJ_SERIES(ID 445 V5.70,44818)匯入 16 標籤含 7 個 42 元素陣列→綁物件→編譯 0 錯誤→模擬讀寫;tag 陣列捲動=`TAG[列 + INDEX n]`,索引值直接=捲動列數 | 11_*.png |
| 12 | 客戶 Excel→EB 標籤 txt | ✅ | `scripts/gifu_tags_excel2eb.py`:四欄 Excel 轉 #11 驗證過的 txt,有錯不出檔;16 標籤往返與實際匯入檔逐位元相同,20 項單元測試 | — |
| 13 | 客戶 Network Publish 警報 | 🛠 | 依 W501 推定=同一全域變數跨工作讀寫的並行性警告(非 HMI 需要);排查步驟給客戶工程師,待回傳警告原文定案 | — |
| 14 | OMRON Ethernet(FINS)+ AT 位址 | ✅ | 驅動 OMRON_ETHERNET(ID 435 V2.00,FINS/UDP 9600);W_Bit 000/H_Bit 5500 位元、D1000 16-bit、D1002 Float 編譯 0 錯誤、模擬讀寫;刀具列「D2000+4×刀+IDX2」(Float+UDINT+D_Bit 旗標)捲動/寫入/停底全實測;位址表 Excel 範本+NX102 設定確認表 | 14_strip_*.png |

## 逐項紀錄

### 1. 三狀態圖(✅ 11-16 15:50)
- 做法:「多狀態指示燈」WL_0 綁 LW-6000,狀態數 3,圖片庫匯入 s1_state0/1/2.png(320×260,含發光邊的亮面版);物件沒有觸控功能(指示燈天生不可點)。
- 測試:畫面放一顆 Set Word「循環遞加 JOG+ 0→2」寫 LW-6000 模擬 PLC。模擬器實測 0→1→2→0 圖片正確切換。
- 編譯:0 錯誤 0 警告(專案 2.98MB,剩餘 61.02MB)。截圖 `gifu_spike_shots/01-04_compile.png`、`01_strip.png`(0/1/2/回 0)、`01_state{0,1,2}.png`。
- 正式版注意:PLC 給的值超過 0–2 時要顯示什麼(建議第 4 張「未知」圖),設計定稿時跟客戶確認。

### 2. 路徑動畫(✅ 11-16 16:05)
三種做法比較(兩種實建實跑,一種依官方說明書規格判斷):
| 做法 | 實測 | 控制方式 | 結論 |
|---|---|---|---|
| **流動塊 Flow Block**(物件→動畫→流動塊,cMT 支援 5° 斜線段) | **15.8 fps,間隔 62–69ms 穩定** | 一個字組 LW-6012 = 速度 −25…25,0=停,負=反向 | ⭐ 正式採用:最順、不吃巨集、PLC 直接寫速度字即可 |
| 多幀點陣圖(13 幀多狀態指示燈 WL_1 LW-6010)+週期巨集 | 9.8 fps(巨集最短週期 100ms,最大間隔 134ms) | 巨集讀 LB-6001(運行)&LB-6000(有效)推進幀 0–11,否則停在第 12 幀(靜止圖) | 客戶要「發光點」這種客製外觀時用;上限 10fps |
| 動畫物件 Animation | 未建(說明書 hidd_setobject_animation_4:速度單位 0.1 秒、位置是點擊定義的離散點) | 自動模式無法用 LB 停,要停需改「取決於暫存器」由巨集推位置 | 不採用:跳格移動、≤10Hz,比上兩者差 |
- 邏輯:巨集 ANIM_R02(週期 1×100ms)= `運行 AND 有效` 才前進,同時把流動塊速度 LW-6012 寫 8 或 0。
- 模擬器實測(02_anim_grid.png 九格):①兩者皆 OFF 靜止 ②–⑥運行中光點/流動塊前進 ⑦運行=1 但「有效」=0 → **強制停** ⑧有效=1 運行=0 → 停。
- 巨集編譯 0 錯誤(4 個「變數未初始化」注意,無害)。
- 正式版:PLC 若能直接給「速度字」,連巨集都不用;若只給 LB,巨集照本範例。

### 3. 無效值顯示「--」(✅ 邏輯 11-16 16:15)
- 做法:數值物件 NE_0(LW-6024,32-bit Float,小數 2 位)在「一般屬性→啟用條件」設 LB-6002=ON 才啟用、行為=**關閉時隱藏**;同位置疊一顆位元指示燈 BL_0(LB-6002),OFF 狀態文字「--」、ON 狀態空白。
- 模擬器實測(03_strip_wine_font.png):LB=0 → 只見「--」;LB=1 → 顯示 12.56;LB=0 → 回到「--」。**沒有任何一格出現 0**。
- 數值格式下拉有 64-bit Double,客戶 TL05 的 LREAL 可直接對應。
- 正式版:兩物件要疊在完全相同座標(測試版放在上下兩處方便看)。
- ⚠️ Wine 模擬器字級:36/60 號字在 Wine 版 cMTViewer 被畫成約 10px(16 號以下正常)。這是本機 Wine 執行環境問題,不是專案設定(EB 編輯器顯示正確、專案存的是 Arial 60);字型/字級的真實呈現在第 8 項處理。

### 4. 環形功率量規(✅ 11-16 16:15)
- 做法:「棒圖」物件型態=圓形(BG_0)+數值物件(NE_1)綁同一 LW-0;測試鈕 Set Word 循環遞加 25。
- 模擬器實測 0→25→50→75→100 環與數字同步(04_ring_strip.png)。1920×1080 專案下編譯 0 錯誤。
- 正式版:環底軌(未填滿部分)用背景圖畫出,環本體用棒圖;尺寸依 P06 放大到設計稿尺寸即可(棒圖是向量,無鋸齒)。

### 5. 刀具列表 42 刀位 × 8 欄(✅ 11-16 17:40)
**架構(正式版沿用)**:每欄一個 42 元素陣列 + 每列物件「位址 = 基底 + 2×列 + 索引暫存器 0(LW-9200)」。捲動只改一個值,110 個物件同時換資料。
| 欄 | 物件 | 位址(LW 測試版,32-bit,步距 2) | 對應 NX102 標籤(正式版) |
|---|---|---|---|
| TL01 刀號 | 數值顯示(無輸入) | LW-7000+ | `HMI_TOOL_NO[0..41]`(或 HMI 自算) |
| TL02/03/04 前洗/後洗/斷刀啟用 | 多狀態切換開關 2 態「●停用/●啟用」循環 | LW-7100/7200/7300+ | `HMI_TOOL_PRE_WASH_ENABLE[]` 等 BOOL 陣列 |
| TL05 基準刀長 | 數值輸入 32-bit Float 2 位小數;**安全→啟用條件 LB-6200=OFF,關閉時灰階** | LW-7400+ | `HMI_BROKEN_BASE_LENGTH_BY_TOOL[]` LREAL→改 64-bit Double |
| TL06 實測刀長 | 數值顯示 | LW-7500+ | 逐刀來源待客戶核 |
| TL07 重量 | 數值輸入 Float | LW-7600+ | REAL 陣列 |
| TL08 壽命 | 數值輸入 32-bit Unsigned | LW-7700+ | UDINT 陣列 |
| 選列高亮 | 多狀態指示燈 2 態(透明/青色框 PNG) | LW-7800+ | HMI 內部 |
| 選列觸控 | 隱形 Set Word 寫 1 | LW-7900+2r(不吃索引) | HMI 內部 |
- 捲動:▲▼ Set Word JOG± 寫 LW-6102(0–31),巨集 TOOL_LIST(週期 100ms)把 LW-9200 = 2×LW-6102、算出所選刀號 LW-6100、重刷高亮陣列。巨集 0 錯誤。
- **Tag PLC 正式版更簡單**:官方說明(indexregister.htm)「Tag PLC 時索引暫存器支援一維陣列標籤,位元陣列不需偏移修正」→ 索引值直接 = 捲動列數,不用 ×2。
- 建法:第一列 10 物件手建,再用「多重複製 Y×11、間距 50、位址間隔 2」逐欄展開(多重複製只吃單一物件,共 10 次)。
- 編譯 0 錯誤 0 警告(整案 3.32MB,剩 60.68MB)。
- 模擬器實測:
  - `05_a_initial.png` 1–11 列、刀 1 高亮
  - `05_b_select5.png` 點刀號 5 → 高亮移到 5
  - `05_c_scroll3.png` ▼×3 → 顯示 4–14,**高亮跟著刀 5 走**(不是黏在第 5 列)
  - `05_d_scroll_end.png` 連按 ▼ 35 次 → 停在 32–42,不會捲過頭
  - `05_e_edit_tap.png` 選刀 40、前洗切換 啟用→停用、點重量格進入編輯 → 輸入 7.25 寫入成功
  - `05_f_measuring_lock.png`+`05_g_lock_unlock_strip.png` 檢測中 LB-6200=1 → 基準刀長整欄灰階,點擊不進編輯、打 999 不變;LB=0 → 可編輯,寫入 160.25
- 待補(都有解法,正式建置時做):
  1. 刀號顯示「01」:數值物件自訂格式 `**` 在模擬器顯示「1」。解法:刀號欄改用 ASCII 顯示物件讀巨集預先產生的 2 字元字串(或 42 態文字指示燈);正式建置第 2 週做並截圖驗證。
  2. 選列觸控目前只在刀號格;正式版把隱形 Set Word 拉滿整列寬(在可編輯格下層)。
  3. 彈出鍵盤:Wine 版模擬器不畫彈出視窗(直接進入格內編輯、鍵盤輸入可寫),09-22 原生 Windows 模擬已實測系統鍵盤會跳出;第 3 週實機再驗一次。
  4. 壽命 0 紅字:數值物件「使用警示色彩」下限設 0 即可(TL09 底欄警報另用事件)。

### 6. 中英文切換(✅ 11-17 01:25)
- **機制**:EB「文字標籤庫」每個標籤有 Language 1–8 欄;物件勾「使用文字標籤庫」後,畫面顯示哪一欄由系統暫存器 **LW-9134**(0=第一個下載的語言、1=第二個…)決定。一個暫存器切全頁。
- **標籤用 Excel 批次匯入(實測)**:標籤庫「匯出為 EXCEL」看出格式=第一欄`文字標籤名稱`,其後`Language n, 狀態 k`(先排滿狀態 0 的 8 種語言,再狀態 1…);中文直接寫 xlsx 可匯入(說明書說「不支援 Unicode」,實測繁中正常)。狀態數由有填的欄自動判斷。**再次匯入是整份取代,但已被物件引用的標籤會依名稱保留連結**(第二次匯入後物件不用重綁)。產生器:`research/gifu_i18n/make_labels.py`;樣本 `gifu_labels_zh_en.xlsx`(10 標籤)。`06_a_label_library_import.png`
- **警報文字多語(實測)**:事件登錄每筆「訊息」頁勾「使用文字標籤庫」選標籤。事件表也能 Excel 匯入/匯出(.xls,179 欄);以匯出檔第 3 列當範本複製改位址/標籤,用 `research/gifu_i18n/make_events.py` 產生 `gifu_alarms_i18n.xls` 匯入 → 2 筆警報(LB-6410 主軸過熱、LB-6411 氣壓不足)一次進(`06_b_event_log_import_2alarms.png`)。⇒ **客戶警報清單若用 Excel 給,同一招可批次轉入**。
- **測試畫面**(視窗 13 I18N_TOPBAR):標題文字 L_TITLE、語言鈕(多狀態切換開關 LW-9134,加+循環,2 態;標籤 L_LANGBTN 狀態 0=「English」、狀態 1=「中文」,顯示要切去的語言)、位元開關 LB-6400(L_PREWASH 停用/啟用 兩態兩語)、警報顯示物件(「標題」頁每欄可各掛標籤:L_HDR_TIME/L_HDR_MSG)、警報框標題文字 L_CAPTION、兩顆觸發鈕。
- **編譯坑(實測)**:編譯對話框「選擇 HMI 需使用的語言」**預設只勾 Language 1**;沒勾的語言不會進 cxob,切 LW-9134 也沒東西可顯示。正式版編譯/建立下載資料都要勾 Language 1+2。勾後 0 錯誤 0 警告(3.83MB,剩 60.17MB)`06_c_compile_2lang_0err.png`。
- **模擬器實測**(`06_d_sim_lang_toggle_strip.png`):①中文:開關「啟用」、觸發主軸過熱 ②按 English → 標題 Tool List、開關 Enabled/Disabled、**已經在清單裡的那筆警報也變 Spindle overheat**、表頭 Time/Message、框標題 Active Alarms、按鈕變「中文」③英文下觸發第 2 筆 → Low air pressure ④按 中文 → 兩筆都回中文。(`06_e_sim_zh.png`/`06_f_sim_en.png` 單張)
- 正式版注意:
  1. 警報顯示物件預設外框的「Caption」是向量圖案內建字,不能翻譯 → 正式版用自己的框圖+L_CAPTION 文字物件(本例已這樣做)。
  2. 只有字型大小能逐語言設定,顏色/對齊跟 Language 1 一樣;英文通常比中文長,按鈕寬度以英文為準。
  3. 語言鈕可放頂欄;要開機記住語言,LW-9134 是系統暫存器、重開機會回預設(下載時「下載工程檔案後所顯示的語言」),需記憶就用 RW/配方存一個值、開機巨集寫回(第 3 週實機驗)。
  4. 系統訊息(系統參數→系統訊息)與鍵盤也有「文字標籤庫」選項,同法翻譯。

### 7. 頂欄:時鐘、目前帳號/角色、未登入(✅ 11-17 01:35)
- **帳號系統**:系統參數→使用者密碼,cMT 預設即「進階安全模式」(最多 11 組+admin,類別 A–L)。測試帳號:`op/111`=類別 A(操作員)、`eng/222`=A+B(工程師)、內建 `admin`(全類別,密碼改 999)`07_a_user_accounts.png`。控制位址預設 **PLW-8950**(P=每台 cMT Viewer 各自登入)。
- **系統暫存器(說明書 spsecurity_14,實測)**:`PLW-10754` = 目前登入的使用者名稱(字串);`LW-9222` = 目前使用者可操作類別(bit0=A…bit11=L,未登入=0)。⚠️ 說明書明講「[使用者權限]無法顯示當前登入者權限,要看 LW-9222」。
- **頂欄物件**(視窗 13):
  1. 日期/時間物件:格式 YYYY/MM/DD + HH:MM:SS,關星期(星期名稱要另做多語標籤)。
  2. 帳號:ASCII 顯示 PLW-10754、**字組數量 8**(=16 字元;此欄藏在位址旁「標籤圖示」的位址設定小窗裡,不在主頁)。安全頁「使用暫存器狀態」LB-6421=ON 才顯示,未登入隱藏。
  3. 角色:巨集 `ROLE_MAP`(週期 200ms,`research/gifu_i18n/ROLE_MAP.mcr.txt`)讀 LW-9222 → LW-6420(0 未登入/1 操作員/2 工程師(≥B)/3 管理員(≥0xFFF))+ LB-6421(已登入)。多狀態指示燈 LW-6420 4 態,掛標籤庫 L_ROLE(中英各 4 態)⇒「未登入」也跟著語言切換。巨集 0 錯誤。
  4. 登入/登出(測試用,正式版做成登入彈窗):ASCII 輸入帳號 PLW-8954、密碼 PLW-8962(勾「密碼」顯示 *),Set Word「登入」寫 PLW-8950=1(用名稱登入)、「登出」寫 3。按鈕文字 L_LOGIN/L_LOGOUT。
- 編譯 0 錯誤 0 警告(3.85MB,剩 60.15MB)`07_b_compile_0err.png`。
- **模擬器實測**(`07_c_sim_login_roles_strip.png`):⓪ 開機:名稱空、角色「未登入」① op/111 → 「op｜操作員」② 登出 → 回「未登入」③ eng/222 → 「eng｜工程師」④ 切 English → Engineer、按鈕 Login/Logout ⑤ admin/999 → 「admin｜管理員」⑥ 登出 → 「未登入」。時鐘每秒走。
- 正式版注意:
  1. 角色外觀用自己的 4 張圖(預設指示燈圖顏色淡,`07_c` 第 3/5 格字色看不清,是預設圖片不是功能問題)。
  2. 角色定義要客戶確認:幾種角色、各能動哪些畫面/欄位(對應類別 A–L,物件「安全→使用者限制」設類別即可自動鎖)。#5 的「檢測中鎖基準刀長」可再疊「只有工程師可改」。
  3. 帳號在離線模擬中修改不會保留;實機帳號下載時有「在 HMI 上使用現有帳號」選項,第 3 週決定要不要保留現場改過的密碼。
  4. 時鐘來源 = HMI 內部 RTC;要跟 NX102 對時可開系統參數「時間同步(NTP)」或由 PLC 寫 LW-9010~(第 3 週現場決定)。

### 11. OMRON NX102-1200 EtherNet/IP 標籤匯入(✅ 11-16 20:45)
- 驅動:系統參數→新增設備→OMRON Corporation→**EtherNet/IP (NJ/NX Series)**(OMRON_EIP_NJ_SERIES.c33,ID 445,V5.70),乙太網路,IP 測試設 192.168.250.1,埠固定 44818。
- 匯入標籤:「匯入標籤」→字串型別處理選預設→Import Files(*.txt)→「SINT/INT/DINT 二進制存取?」選否(INT 速度值要保留正負號)→「成功匯入標籤資訊」(`11_a_import_ok.png`)。
- ⭐ **實測踩到的坑(已解)**:陣列若寫成 `ARRAY[0..41] OF BOOL`,EB 照樣顯示「成功匯入」,但**陣列那幾行被安靜略過**(第一次只進 9 個純量)。用 8 種寫法對照測試,只有 CX-Designer 式 `BOOL[42]`(元素數)被接受。改寫後 **16/16 全進**(`11_b_tags_17.png`,檔名的 17 是把表頭算進去的筆誤,11-17 更正:BOOL/UINT/INT/REAL 純量 + BOOL[42]×3、LREAL[42]×2、REAL[42]、UDINT[42])。另:再次匯入是**整份取代**不是追加。
  - 防呆:`research/gifu_nx102/nx_tags_check.py 原檔 輸出檔` 自動把 `ARRAY[0..N] OF T` 轉 `T[N+1]`、抓下標非 0/不支援型別/TAGLINK≠TRUE、印出變數數。拿上面失敗的 v1 檔跑,輸出與實測成功檔內容逐位元相同(僅 CRLF/LF 差,兩種換行都實測可匯入)。
  - 正確格式範例(cp950/ANSI,可直接匯入):`research/gifu_nx102/NX102_GlobalVariables_CX-Designer_sample.txt`(UTF-8 檢視版 `NX102_sample_utf8_view.txt`)。
- 綁物件(新視窗 12「TAG_NX102」,不動 #1–#5):物件位址欄變成「標籤」,從標籤瀏覽器點進陣列選元素;型別自動帶入(REAL→32-bit Float、**LREAL→64-bit Double**、BOOL 陣列→BitArray)。
  - 數值 ×4:`HMI_TOOL_WEIGHT[0..3 + INDEX 1]`(多重複製「位址間隔 1」= 陣列元素 +1,實測)
  - 切換開關:`HMI_TOOL_PRE_WASH_ENABLE[0 + INDEX 1]`(BOOL 陣列)
  - 數值輸入:`HMI_BROKEN_BASE_LENGTH_BY_TOOL[0 + INDEX 1]`(LREAL,2 位小數)
  - ▲▼ Set Word JOG∓ 寫 LW-9201(0–38)
- 編譯 **0 錯誤 0 警告**(3.32MB,剩 60.68MB;編譯選項「不支援的標籤視為錯誤」= 標籤有問題會擋編譯)`11_e_compile_0err.png`。
- **#5 索引暫存器在 tag 驅動下的做法(實測)**:不再是「基底 + 2×列」,而是 **`VAR://陣列[列號 + INDEX n]`,索引暫存器的值 = 捲動到第幾刀**(不用 ×2,位元陣列也不用 16 位元偏移修正,與官方說明一致)。模擬器(OMRON 設備離線模擬)實測:
  - idx=0 寫入 11/22/33/44、前洗[0]=1、基準刀長 160.25(`11_f`)
  - ▼1 → 顯示 22/33/44/0,前洗/刀長換成第 1 刀的 0(`11_g`);▼▼ → 44/0/0/0(`11_h`)
  - ▲×3 回 idx=0 → 11/22/33/44、前洗=1、160.25 全回來(`11_i`);監看面板確認 tag 型別與值(`11_j_sim_watch.png`,LREAL=64-bit Double 160.25)
- ⚠️ 過程中抓到的設計規則:第一次 ▼ 沒反應,原因是 #5 的 TOOL_LIST 巨集是**全域週期巨集**,每 100ms 把 LW-9200 蓋回去。正式版規則:**每個捲動清單用自己的索引暫存器**(16 組 LW-9200~9215 + 16 組 32-bit;多台 cMT Viewer 要各自捲動時用私有 PLW-9200~),週期巨集不要寫別人在用的索引。改用 INDEX 1 後即正常。
- 小註:索引顯示框 ND_0 一直顯示 0,是我新建時格式沿用了上一個物件的 32-bit Float(LW-9201 整數 3 被當浮點讀成≈0),不是 tag 問題;正式版設 16-bit Unsigned。
- 模擬限制:離線模擬的 OMRON 設備是 EB 自帶的記憶體模擬,**沒有接真 PLC**;真 PLC 的 Publish/安全通訊/網段在第 3 週現場驗(清單見下)。
- 給客戶工程師的設定步驟:`research/gifu_nx102/NX102_Weintek_連線設定步驟_給客戶工程師.md`(Publish Only、ANSI 匯出、韌體 V1.49+ DIP 1/2 ON **必須重新上電**、使用者驗證、44818、LAN1/LAN2 分網段、直連排錯、請客戶提供清單)。
- 暫設:spike.cmtp 起始視窗改為 12(方便模擬),收尾時改回 10。

### 9. 素材預算(✅ 11-17 07:20)
- **做法**:新視窗 14「ASSET_BUDGET」放一個圖片物件 GP_0,圖片庫項目 ST30 共 32 個狀態 = `bg_1920.png`(1920×1080 全頁,P06 設計參考圖)+ 30 張狀態圖(10 個區塊 × 原/執行/異常 3 態,295–455px 寬)+ `tl_bg.png`(刀具列表 1920×1080 底圖)。素材總計 4.78MB(PNG 未量化,刻意取最壞情況)。產生器 `~/gifu_spike/gen_assets.py`。
- **編譯**:0 錯誤 0 警告(`09_a_compile_assets_0err.png`)。
  | 項目 | 加素材前(#7 後) | 加素材後 |
  |---|---|---|
  | 全部大小 | 3.85MB | **8.52MB**(8,933,924 B) |
  | 剩餘空間 | 60.15MB | **55.48MB** |
  | 其中 圖片 / 字型 / 物件 / 巨集 | — | 7.11MB / 1.61MB / 0.19MB / 0.02MB |
  (EB 總容量 = 全部大小 + 剩餘 = 64MB;客戶面板目前回報剩餘 60.58MB,以此為上限計算。)
- **關鍵發現(實測)**:解開 cxob 的 `mt8000/project`,32 張 PNG **32/32 逐位元原樣存在**——EB 不重新壓縮圖片。⇒ 預算 = 匯入檔案大小,壓縮必須在匯入前自己做;cxob 外層 gzip 只影響傳輸大小(6.16MB),不影響面板容量計算。
- **壓縮試算**(同一批素材,PIL 轉檔量測,KB):
  | 素材 | 原 PNG(24-bit) | PNG 256 色(不抖色) | JPG q90 4:4:4 | JPG q85 |
  |---|---|---|---|---|
  | 全頁背景 ×1 | 1,859 | 497 | 671 | 416 |
  | 狀態圖 ×30 | 2,759 | 1,102 | 824 | 523 |
  | 刀具列表底圖 ×1 | 161 | 66 | 275 | 173 |
  | 合計 | 4,779 | 1,665 | 1,770 | 1,112 |
- **整案推估**(假設正式版 10 頁、每頁一張全頁背景、狀態圖/動畫幀 ~100 張):原 PNG ≈ 10×1.9 + 100×0.09 ≈ 28MB;依下列規則處理後 ≈ 5×0.5+5×0.7+100×0.04 ≈ **10MB**,加字型 1.6MB、物件 <1MB ⇒ 約佔 60.58MB 的 20%,餘裕充足。
- **素材規則(給設計/建置)**:
  1. 尺寸一律 1:1 畫面像素(全頁 1920×1080),不要放 2× 圖——EB 不會縮小存檔,只會縮小顯示。
  2. 平面 UI 底圖/框/按鈕/狀態圖 → **PNG 256 色(pngquant 類量化)**,需要透明一定用 PNG。
  3. 有照片/漸層/光暈的全頁背景 → **JPG q85–90**(不需透明時);色帶明顯就退回 PNG 量化。
  4. 動畫優先用 #2 的「流動塊」(向量,零圖片成本);多幀點陣圖只用在客製光點,幀圖裁到最小外框。
  5. 同一張底圖在多頁共用時只匯入一次(圖片庫項目重複引用不重複計)。
  6. 每次大批換圖後重編譯看「圖片大小」一行,超過 30MB 就回頭檢查是否有未量化的大圖。
- 限制:JPG 在面板上的實際畫質未上機看(Wine 模擬器畫質不代表實機);第 3 週實機抽一張 JPG 背景確認色帶。

### 12. 客戶 Excel 變數表 → EB 標籤 txt 轉換器(✅ 11-17 07:40)
- 工具:`scripts/gifu_tags_excel2eb.py 客戶變數表.xlsx 輸出.txt [--crlf] [--sheet 名稱]`。Excel 第一列表頭依名稱比對(欄序不拘,中英皆可):**變數名稱 / 資料型態 / 陣列長度 / 說明**。
- 輸出 = #11 實測匯入成功的格式:cp950、Tab 分隔、表頭 `HOST NAME DATATYPE ADDRESS COMMENT TAGLINK RW POU`、TAGLINK=TRUE、RW=RW、陣列一律寫 `T[N]`。
- 陣列兩種寫法都收:`BOOL` + 陣列長度 42,或資料型態直接寫 `ARRAY[0..41] OF BOOL`(自動轉 `BOOL[42]`,避開 EB「顯示成功但安靜略過」的坑)。
- **有任何問題就不輸出**(避免半套檔被匯入),逐列列出:名稱非英數底線/數字開頭、名稱重複(不分大小寫)、陣列下標不是從 0 開始、型態欄與長度欄元素數不一致、結構/列舉型別(要客戶改匯出成員)、STRING 陣列、說明含 cp950 打不出的字(簡體字會在 EB 變亂碼)。`STRING[20]` 視為字串長度不是陣列。
- **驗證**:把 #11 實際匯入成功的 txt 反向拆成 Excel(`research/gifu_nx102/客戶變數表_範例_16標籤.xlsx`,陣列刻意一半用「長度欄」、一半用 `ARRAY[..] OF` 寫法)→ 轉 txt → 與 `C:\work\nx102_tags.txt`(EB 匯入成功的那一份)**逐位元組相同**(`cmp` 無差異)。依指示不再開 EB 重匯。
- 單元測試:`python3 scripts/test_gifu_tags_excel2eb.py`,20 項全過(往返比對 ×3 含 --crlf、各種錯誤列、表頭英文/亂序、空白列、有錯不出檔)。
- 範例 Excel 可直接當「請客戶填的範本」寄出(由老闆轉交)。

### 13. 客戶回報:設 Network Publish: Publish Only 後跳警報、要在「工作設定的變數設定」再輸入一次(🛠 排查法已備,待客戶回傳訊息原文)
- **判讀**:HMI(CIP 訊息存取)**本身不需要**在 Task Settings 登記任何變數;外部存取是 CPU 每個週期在「System common processing 2」用 *Variable Access Time* 處理的(W501 p.5-16)。客戶說的「工作設定的變數設定」對應 **Task Settings → Settings for Exclusive Control of Variables in Tasks**(W501 p.4-12:指定 refreshing task / accessing task,RUN 中不可改、下載才生效)。在那裡填了警告就消失 ⇒ 最可能是**同一個全域變數被兩個以上的工作讀寫**,Sysmac 檢查程式時給的並行性警告(W501 5-9-1 p.5-124~5-126:「從非 refreshing/accessing 的工作讀寫已設 refreshing task 的變數,檢查時給 warning;accessing task 裡寫入則報 error」)。Publish Only 只是讓這些變數剛好被拉成跨工作使用的全域變數,本身不是原因。
- **常見原因與排除(依可能性)**:
  1. 跨工作讀寫 → 建議 HMI 變數只在一個工作(Primary Periodic Task)讀寫;必須跨工作就照 W501 Method 1 設 refreshing task(=寫的那個工作,整個陣列/結構只能一個),多工作都寫就用 Lock/Unlock(Method 2)。
  2. Publish Only 的變數又被放進 EtherNet/IP Tag Set → W501 p.6-68 明載「Publish Only 不能用於標籤資料連結」;OMRON TN 的症狀是 Tag 變粉紅色+「未登錄於變數表的網路變數」。HMI 變數不要進 Tag Set,真要資料連結就改 Input/Output。
  3. 用 AT 指到 I/O 的裝置變數在非 I/O 控制工作裡寫入 → 檢查報錯(W501 p.5-112)。HMI 變數不要 AT 到 I/O。
  4. 改了 Network Publish/工作設定沒重新下載、陣列只設部分元素、或誤選 Do not publish(能匯入但通訊失敗)。
- **限制**:警告原文沒拿到,OMRON 公開資料查不到這句警告的逐字內容(論壇/OMRON US TN 要登入),以上是依官方手冊機制推定;**拿到客戶截圖後 5 分鐘內可定案**。
- **給客戶工程師的繁中步驟**(可直接轉交):`research/gifu_nx102/NX102_NetworkPublish警報排查_給客戶工程師.md`(第 0 步先抓訊息原文 → 跨工作 → Tag Set → AT → 下載確認 → 回傳清單)。
- 來源:
  - OMRON W501《NJ/NX-series CPU Unit Software User's Manual》https://files.omron.eu/downloads/latest/manual/en/w501_nj_nx-series_cpu_unit_software_users_manual_en.pdf (p.4-12、5-16、5-112、5-123~5-126、6-68)
  - OMRON US TN「NX Built-in EIP Tag Set issue」(需登入,引用搜尋摘要)https://omronelectronicsllc.freshdesk.com/en/support/solutions/articles/150000200529-tn-nx-built-in-eip-tag-set-issue
  - Weintek 連線指南(Publish Only / Do not publish 行為,#11 已引用)https://dl.weintek.com/public/PLC_Connect_Guide/OMRON_EtherNet_IP_NJ_NX_Series.pdf

### 14. OMRON Ethernet(FINS)+ Sysmac AT 位址模式(✅ 11-17 16:40)
客戶確認改走 FINS:NX102 變數用 AT 指到 CJ 記憶體(W/H/D),HMI 用 OMRON Ethernet 驅動直接讀寫位址,**不開 Network Publish**(⇒ #13 的警報在這條路上不會出現)。
- **設備**:系統參數→新增設備→OMRON Corporation→**Ethernet** = `OMRON_ETHERNET.c33`(設備 ID 435,V2.00),乙太網路、預設勾「使用 UDP」、埠 9600;測試 IP 192.168.250.1。另有「Ethernet (FINS/TCP)」與「CJ/CS/CP (Ethernet - FINS/TCP)」兩個 TCP 版驅動,依客戶指定用 UDP 版。專案現在同時有設備 4(EIP,#11)與設備 5(OMRON Ethernet)。
- **位址格式(Weintek 官方指南+EB 位址視窗原文一致)**:位元 `DDDDDdd`,**最後 2 碼是位元 00–15**;字組 `DDDDD`。⇒ Sysmac `%W0.00`→`W_Bit 000`、`%W1.07`→`W_Bit 107`、`%H55.00`→`H_Bit 5500`、`%D1000`→`D 1000`。可用區:CIO/W/H/A/D/T/C/EM0–EMC(位元與字組皆有)。
- **新視窗 15「OMRON_FINS」物件**:BL_0 指示燈+TS_0 切換 = `W_Bit 000`;BL_1+TS_1 = `H_Bit 5500`;NE_0 = `D 1000` 16-bit Unsigned;NE_1 = `D 1002` **32-bit Float** 2 位小數(佔 D1002–1003)。
- **刀具列表(42 刀)換成「裝置位址+索引暫存器」**:每刀一組 4 字組 `D2000+4n`(+0 重量 REAL、+2 壽命 UDINT、+3 旗標字 bit0 前洗/bit1 後洗/bit2 斷刀)。
  - 物件:重量 NE_2–6 = `D 2000/2004/…/2016 + Index 2`(32-bit Float);壽命 NE_7–11 = `D 2002/…/2018 + Index 2`(32-bit Unsigned);旗標 TS_2 = `D_Bit 200300 + Index 2`。建法:第一列設好後「多重複製 Y×5、位址間隔 4」。
  - 位址視窗在 OMRON Ethernet 的 D/D_Bit 上**有「索引暫存器」勾選、可選 Index 0–31**,用 Index 2(LW-9202),避開 #5/#11 已用的 0/1。
  - 捲動不用巨集:Set Word 寫 LW-9202「遞加 JOG+ 4,最大 148」/「遞減 JOG− 4,最小 0」(148 = 37 刀×4 ⇒ 最後一頁顯示刀 38–42)。
  - ⭐ 位元套索引的規則(EB 說明書 indexregister.htm):「位元位址套索引時,以 16 個位元(=1 字組)為單位偏移」⇒ 索引值 4 讓 D_Bit 200300 變成 D2007.00,**和字組物件同一個索引值就對齊同一刀**,不需要另一組索引。(Tag 驅動 #11 則是元素為單位,兩者不同。)
- **編譯**:0 錯誤 0 警告(8.52MB,剩 55.48MB)`14_a_compile_0err.png`。
- **模擬器實測**(OMRON Ethernet 離線模擬=EB 內建記憶體模擬,未接真 PLC):
  - `14_strip_bits_words.png`:初始全 OFF → 切 W0.00、H55.00 兩燈亮 → 輸入 D1000=1234、D1002=3.14,關 W0.00 後 H55.00 仍亮(兩區獨立);監看面板顯示物件位址 `OMRON Ethernet W_Bit-0`。
  - `14_strip_tool_index.png`:IDX=0 寫入刀 1–5(1.10/100…5.50/500)→ ▼ IDX=4 顯示刀 2–6 → 在 IDX=4 第 5 列寫 6.60/600(=寫進刀 6 的 D2020/D2022)→ ▼×45 **停在 148** → ▲ 回 IDX=4 刀 6 仍是 6.60/600 → IDX=0 刀 1–5 全回來。
  - `14_strip_dbit_index.png`:IDX=0 打開 D2003.00 → ▼ IDX=4 顯示 OFF(D2007.00,刀 2)→ ▲ 回 ON。
- **給客戶的位址表 Excel**:`research/gifu_nx102/gifu_FINS_address_table_template.xlsx`
  - 「位址表」欄位:**變數名稱 / AT 位址 / 資料型態 / 陣列長度 / 讀寫 / 說明** + Retain(H/D/EM 必須 ON)+ 灰底兩欄我方填(HMI 位址、佔用範圍)。讀寫/型態/Retain 有下拉選單。預填客戶的實例:`%W0.00` BOOL×24(佔 W0.00–W1.07 → W_Bit 000~107)、`%W2.00` BOOL×16(W_Bit 200~215)、`%W100` 輸出(型態待確認)、`%H55.00` BOOL×37(佔 H55.00–H57.04 → H_Bit 5500~5704)、D1000 UINT、D1002 REAL、刀具組 D2000–D2167。
  - 「NX102 FINS 設定確認」15 項(建議值+客戶填實際值+手冊出處),「填寫說明」頁附 3 個官方 URL。
- **NX102 端要確認的(OMRON 官方手冊原文)**:
  1. FINS 開關:Controller Setup → Built-in EtherNet/IP Port Settings → FINS Settings → FINS/UDP 選 **Use**(選 Do not use 時 FINS 伺服器不回應)。NX102 FINS/UDP、FINS/TCP **都支援,預設埠都是 9600**(可改),TCP 最多 16 連線(W596 1-4、2-1)。HMI 用 UDP 版驅動,TCP 可關。
  2. 節點號:FINS/UDP 的 IP→FINS 位址轉換選 **Automatic generation** ⇒ **IP 最後一碼 = FINS 節點號**(W596 2-3;Weintek 指南步驟 2 同樣要求自動產生)。⇒ HMI 與 NX102 同網段、IP 末碼不可撞其他 FINS 節點。
  3. ⚠️ **CJ 記憶體預設全部停用**:Controller Setup → **Memory Settings**(Memory Settings for CJ-series Units)的 CIO/WR/HR/DM/EM 預設都是 **Disable**;啟用後預設字數 CIO 6,144、WR 512、**HR 512(上限 1,536)**、DM 32,768,下載後生效、RUN 中不可改(W501 4-11-3)。沒啟用的區,AT 指過去會報錯、HMI 讀不到。本案至少要開 WR、HR(≥58 字)、DM(≥2,168 字)。
  4. ⚠️ **Retain 必須跟區域一致**:CIO/WR 用「無 Retain」變數,**HR/DM/EM 用「有 Retain」變數**,不一致會報錯(W501 4-11-3 註 *1/*2、6-3-8)⇒ 客戶 `%H55.00` 那個陣列要勾 Retain。
  5. AT 寫法:位元 `%W0.00`(字組.位元)、字組 `%D100`;**整個陣列只設一個起點 AT**(W501 6-3-8)。客戶口述的「%W000」應是 `%W0.00`,位址表請照這寫法填。
  6. **FINS 寫入保護**(Operation Settings → FINS Settings → Security Settings)開著時,MEMORY AREA WRITE 不執行 ⇒ HMI 只能讀不能寫,要關(W596 2-5、2-6)。有開 Packet Filter 要放行 FINS(W596 2-1)。
- **還沒驗、排第 3 週現場**:真 PLC 的 FINS 回應(離線模擬不經網路);**32-bit REAL/UDINT 的字組順序**(用 PLC 寫一個已知值如 3.14 到 D1002 看 HMI 是否顯示 3.14,錯了就在 EB 該設備開字組交換);Weintek 指南建議 PLC 站號 0,若無回應改填 NX102 的節點號。
- 小註:模擬時把起始視窗改成 15,收尾已改回 13 並存檔。Wine 下 EB 的下拉清單偶爾留下一塊黑色未重繪視窗擋住欄位,用 `mvwin.py <id> 3000 3000` 移開即可(不影響專案)。
- 來源:
  - Weintek OMRON Ethernet 連線指南(格式 DDDDDdd、UDP 9600、站號 0、NJ/NX 設 FINS 9600+自動產生)https://dl.weintek.com/public/PLC_Connect_Guide/OMRON_Ethernet.pdf
  - OMRON W596《NX-series CPU Unit FINS Function User's Manual》https://files.omron.eu/downloads/latest/manual/en/w596_nx-series_-_cpu_unit_fins_function_users_manual_en.pdf (1-4、1-5、2-1、2-3、2-5、2-6、2-7)
  - OMRON W501《NJ/NX-series CPU Unit Software User's Manual》https://files.omron.eu/downloads/latest/manual/en/w501_nj_nx-series_cpu_unit_software_users_manual_en.pdf (4-11 Memory Settings for CJ-series Units、6-3-8 AT Specification)
  - EB 說明書 索引暫存器(EBPro 內建 help `indexregister.htm`)

### 10. 遠端交付(✅ 11-16 21:00)
- **離線模擬包**:cxob 是 gzip→tar,解出 `mt8000/project`;EB 自己模擬時也是把這個檔(逐位元相同)交給 `cMTViewer.exe -fs <檔> -allinone`(另帶 `-mp=` 參數,實測不帶也能跑)。
  - 做法 1(實測可跑,**不外送**):自帶執行檔的精簡包 225MB(用 `WINEDEBUG=+loaddll` 找出 viewer 實際載入的 DLL/外掛/資料檔,驅動只留 OMRON NJ)。只補 DLL 會崩潰,要連資料檔一起帶。因威綸使用條款 §6.2 禁止未經許可複製,只留內部備查(`~/gifu_spike/pfx/drive_c/deliver/_internal_selfcontained_DO_NOT_SEND`)。
  - ⭐ 做法 2(交付用):專案檔 + `run_offline_sim.bat`(呼叫客戶自己安裝的 `C:\EBpro\cMTViewer.exe`,沒裝會提示)。從乾淨路徑雙擊 bat 實測開啟、輸入、捲動正常(`10_a_offline_sim_bat.png`)。實測包 `research/gifu_remote_delivery/GIFU_HMI_spike_delivery_test.zip`(1.4MB)。
- **USB/SD 下載**:「建立下載資料」→「下載資料建立成功」,cMT 系列產出就是根目錄一個 `project.cxob`(1.0MB,`10_b_build_download_usb_ok.png`),解開比對與模擬專案逐位元相同。面板端:插 USB→Download→密碼(對話框可在面板系統設定 Miscellaneous 關掉/打開)。
- **遠端桌面 + 乙太網路**:客戶現場 PC 裝 EB、同網段,我們遠端進去「下載 (PC→HMI)」;跨路由器下載埠 TCP 20248、HMI 通訊 8000、EasyAccess 443(EB 說明書埠號表)。
- **EasyAccess 2.0(cMT)**:官方 Weincloud EasyAccess 2.0 Datasheet(eng 20250305):每台 HMI **一次性授權費**、支援 **All cMT X/cMT Series**、啟用卡 **RZACEA020**、100kB/s / 3GB 每月(加量卡 RZSCEAT05/10)。第 3 週交付不需要;「3 個月試用」屬於 Dashboard 不是 EasyAccess(查證時差點混淆)。
  來源:Weintek 官方規格書 PDF(經銷商鏡像 nnz-ipc.ru/files/documentation/weintek/EasyAccess_2.0_Datasheet_ENG_20250313.pdf;weintek.com 產品頁無授權文字)。
- SOP 7 步 + 客戶準備清單:`research/gifu_remote_delivery/遠端交付SOP_第3週_客戶準備清單.md`。

### 8. 自訂字型(✅ 11-16 21:10)
- **機制(實測)**:EB 文字/數值物件可選任何已安裝到 Windows 的 TTF;編譯勾「建立字型檔案」時,**把用到的字形子集化後直接嵌進 cxob** 的 `mt8000/pub/fonts/fontN.ttf`(例:微軟正黑體只帶 761 字形/116KB,我們的 Anton 只帶 212 字形/31KB)。下載到面板時一起帶過去,面板不用另外裝字型。
- **踩到的坑(已解)**:直接用 Google Fonts 的 Anton-Regular.ttf → 編譯失敗「無法產生字型檔案 (Anton Regular),請選用其他字型…或複製到 C:\EBPro\windows_font」(`08_a_font_error_hint.png`)。照提示放進 Windows Fonts + windows_font、修正登錄路徑、重開 EB 都還是失敗 → 做對照組:改名的 Arial 副本成功、**去掉 DSIG/GDEF/GPOS/GSUB 四張表(fsType 設 8)的 Anton 成功**,編譯 0 錯誤(`08_b_compile_custom_font_ok.png`,cxob 內確認 `GIFU AntonB` 212 字形、0–9 齊)。
  - 結論:EB 的字型子集器吃不下某些現代 OpenType 字型的表格;**正式用字前一律先跑** `research/gifu_fonts/hmi_font_prep.py 原檔.ttf 輸出.ttf "GIFU 字型名"`(去四表+改名;去掉的是字距/連字表,HMI 數字與標籤不受影響)。只接受 TrueType 輪廓(glyf);OTF/CFF 要先轉。
  - 改名同時避開 SIL OFL「保留字型名稱」條款;商用字型要先確認授權允許修改與嵌入到設備。
- **模擬實測**:動態數值物件(LW-6300,字型 GIFU AntonB)輸入 2468 → 顯示為 Anton 窄粗體,旁邊對照 Arial 靜態字(`08_c_sim_custom_font_dynamic.png`)。
- 限制:Wine 版模擬器大字級會縮小(#3 已記),所以本機只驗 16 號;實際字級外觀第 3 週實機確認。若某字型處理後仍失敗,退路=靜態標題出 PNG、動態數值用已驗證可嵌入的字型(本次 GIFU AntonB 已證實可用)。
- 另一個只在 Wine 才有的坑:放在 Linux `~/.fonts` 的字型會被 Wine 登錄成 `Z:\...` 路徑,EB 找不到;真 Windows 上「為所有使用者安裝」即可,不會遇到。
