# 景翔 HMI 遠端交付 SOP(第 3 週)+ 客戶準備清單

前提:cMT2166X 面板、OMRON NX102-1200 乙太網路。以下每條路都已在本機用 EasyBuilder Pro V6.09.02 實際產出檔案並驗證(截圖 `research/gifu_spike_shots/10_*.png`)。

## A. 離線模擬檔(交機前給客戶先看畫面、點操作)
**交付內容**(實測包 `GIFU_HMI_spike_delivery_test.zip`,1.4MB):
```
GIFU_HMI_OfflineSim/
  run_offline_sim.bat      ← 雙擊執行
  project/project          ← 編譯後專案(由 .cxob 解出)
```
**客戶端需要**:安裝官方免費 EasyBuilder Pro(weintek.com 下載，預設裝在 C:\EBpro)。批次檔會呼叫 `C:\EBpro\cMTViewer.exe -fs project -allinone`(Weintek 說明書「cMT Viewer 離線模擬」官方用法);沒裝會提示去下載。
- 實測:從乾淨資料夾雙擊 bat → 模擬器開啟、可輸入、可捲動(`10_a_offline_sim_bat.png`)。
- 為什麼不把模擬器整包附上:我們實測過 225MB 自帶執行檔的包也能跑，但威綸軟體使用條款 §6.2「未經威綸明確許可禁止複製」，所以**不外送威綸的執行檔**，讓客戶自己裝官方版。
- 離線模擬沒有接 PLC:PLC 數值由模擬器內部記憶體代替，可手動輸入看畫面反應。

## B. 正式下載到面板 — 兩條路(擇一)
### B1. USB 隨身碟 / SD 卡(最穩，不需網路)
1. 我方:EasyBuilder「建立下載資料」→ 產出 **`project.cxob`**(cMT 系列就是這一個檔，實測 1.0MB,`10_b_build_download_usb_ok.png`;內容與模擬用專案逐位元相同)。
2. 用雲端硬碟/Email 附件傳給客戶。
3. 客戶:把 `project.cxob` 放在隨身碟**根目錄** → 插面板 USB → 面板跳出 Upload/Download 視窗 → 選 **Download** → 輸入下載密碼。
   - 若沒跳視窗:面板系統設定 → Miscellaneous 頁籤把該對話框打開。
4. 下載完面板自動重啟，回報畫面照片給我們。

### B2. 遠端桌面 + 乙太網路下載
1. 客戶現場準備一台 Windows 電腦，跟面板同一網段、裝好 EasyBuilder Pro。
2. 客戶開遠端桌面軟體(TeamViewer / AnyDesk / Chrome 遠端桌面，客戶 IT 允許哪個用哪個)讓我們連入。
3. 我方把 `.cxob` 傳到那台電腦 → EasyBuilder「下載 (PC→HMI)」→ 填面板 IP + 下載密碼 → 下載。
   - 若要跨路由器下載:TCP **20248**(可改，面板端要同步改);面板一般通訊 8000。
4. 下載後在同一台電腦開「連線模擬」或直接看面板，跟客戶一起逐頁驗收。

### (選配)C. EasyAccess 2.0 — 之後要長期遠端維護才需要
- 官方規格書(Weincloud EasyAccess 2.0 Datasheet eng 20250305):**每台 HMI 一次性授權費**(One-time license fee required for each HMI);**cMT / cMT X 全系列支援**;啟用卡料號 **RZACEA020**;流量 100 kB/s、每月 3GB(超過可能限速，可買 RZSCEAT05/10 加量卡);面板需能連外 **TCP 443**。
- 好處:不用客戶開遠端桌面，我們直接連到面板與後面的 PLC(含乙太網路穿透)。
- 第 3 週交付**不需要**它(B1/B2 就能完成);是否購買由客戶決定，向威綸經銷商訂。
- 注意:網路上「3 個月免費試用」那條寫的是 Weincloud **Dashboard**，不是 EasyAccess 2.0，不要混用。

## 第 3 週 SOP(依序)
| 步驟 | 誰 | 內容 | 驗收 |
|---|---|---|---|
| 1 | 我方 | 交離線模擬包(A),客戶看畫面 | 客戶回覆「畫面 OK」或修改清單 |
| 2 | 客戶 | 依《NX102 連線設定步驟》做 PLC 端(Publish Only、DIP+重新上電、匯出 txt) | 收到 txt;我方檢查工具跑過、變數數正確 |
| 3 | 我方 | 匯入正式標籤、編譯 0 錯誤、做 `project.cxob` | 編譯截圖 |
| 4 | 客戶+我方 | B1 或 B2 下載到面板 | 面板開機進主畫面 |
| 5 | 客戶+我方 | 視訊/遠端逐頁驗收:站點狀態、刀具列表捲動/編輯、檢測中鎖定、功率環、路徑動畫 | 逐項打勾 |
| 6 | 我方 | 依問題修正 → 重複 3–5 | 全勾 |
| 7 | 我方 | 交付最終 `.cmtp` 原始檔 + `.cxob` + 密碼清單 | 客戶簽收 |

## 客戶準備清單(請客戶在第 3 週前備妥)
- [ ] 面板型號確認 cMT2166X、OS 版本(面板系統設定可看)
- [ ] 面板 IP / 遮罩 / LAN1 給 PLC、LAN2 給廠網(兩個要不同網段)
- [ ] 面板**下載密碼**(若有設定)
- [ ] PLC 端:NX102 匯出的變數 txt(ANSI)、PLC IP、韌體版本、DIP 1/2 已 ON 且**已重新上電**
- [ ] 走 B1:一支 USB 隨身碟(FAT32)
- [ ] 走 B2:現場一台 Windows 電腦(同網段、已裝 EasyBuilder Pro、可開遠端桌面)
- [ ] 驗收當天能操作面板的人 + 手機視訊
- [ ] (選配)是否購買 EasyAccess 2.0 啟用卡 RZACEA020
