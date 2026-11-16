# Sysmac Studio:設 Network Publish 後跳警報/要在「工作設定」再填一次 — 排查步驟(給貴司 PLC 工程師)

背景:HMI(Weintek cMT2166X)透過 EtherNet/IP 讀寫 NX102 的全域變數,這些變數要設 **Network Publish = Publish Only**。HMI 端**不需要**在「工作設定(Task Settings)」登記任何東西;如果設了 Publish Only 之後出現警告、而且要到「工作設定 → 工作中變數的排他控制設定」再輸入一次才消失,通常是下面其中一種情況。請依序檢查。

## 第 0 步:先把訊息原文抓下來(最重要)
1. Sysmac Studio 選單 **專案 → 檢查全部程式(Check All Programs)**,或 **建置(Build)**。
2. 下方「建置」頁籤會列出 錯誤/警告。對著那一行 **截圖,或按右鍵複製文字**,連同變數名稱一起傳給我們。
3. 記下:這是**錯誤**(不能下載)還是**警告**(可以下載)。

## 第 1 步:這個變數是不是在「兩個以上的工作」裡被使用?(最常見)
- NX102 若有 Primary Periodic Task 以外的週期工作(例如 Priority-16 Periodic Task),同一個全域變數被 A 工作寫、B 工作讀(或兩個都寫),Sysmac Studio 檢查時會給警告(OMRON W501 5-9-1)。
- 這跟 Network Publish 無關,只是設定 HMI 變數時剛好把它變成「全域變數+多個程式在用」才浮出來。
- 處理方式擇一:
  1. **最簡單(建議)**:給 HMI 用的 `HMI_*` 變數,只在**一個工作**的程式裡讀寫(通常是 Primary Periodic Task)。其他工作要用,就在那個工作裡複製一份。
  2. 必須跨工作使用時:**工作設定 → 工作中變數的排他控制設定**,每個變數指定**一個更新工作(Refreshing Task)=負責寫入的那個工作**,其他只讀的工作設為**存取工作(Accessing Task)**。
     - 存取工作裡不能有寫入該變數的指令,否則檢查會報錯。
     - 陣列/結構只能**整個變數**指定一個更新工作,不能逐元素分開。
     - 這個設定**RUN 模式下不能改**,改完要**下載到 CPU** 才生效。
  3. 必須多個工作都寫:改用 Lock/Unlock(工作排他控制指令)包住寫入的程式段。

## 第 2 步:這個變數有沒有同時被放進 EtherNet/IP 標籤資料連結(Tag Set)?
- Publish Only 的變數**不能用在標籤資料連結**(W501 6-3-8)。若同一個變數也被放進 EtherNet/IP 連線設定的 Tag Set,會出現「未登錄於變數表的網路變數…」之類的錯誤。
- 處理:HMI 用的變數**不要**放進 Tag Set(HMI 走 CIP 訊息,不走標籤資料連結);真的要跟另一台 PLC 做資料連結的變數,改設 Input 或 Output。

## 第 3 步:變數是不是用 AT 指到 I/O(裝置變數)?
- 指到 EtherCAT/NX 單元 I/O 的變數,只能在「I/O 控制工作設定」指定的那個工作裡輸出;在別的工作寫入,檢查時會報錯(W501「Accessing I/O from the User Program」p.5-112)。
- 處理:HMI 變數不要用 AT 指到 I/O;用一般全域變數,在 I/O 工作的程式裡再搬到輸出。

## 第 4 步:確認設定完整
- [ ] 陣列/結構:Network Publish 是針對整個變數設定(所有元素/成員一起)。
- [ ] 改完 Network Publish/工作設定後**重新編譯並下載**到 PLC(不是只存檔)。
- [ ] HMI 變數都沒有選成「Do not publish」(會匯入但通訊失敗)。

## 第 5 步(可選):HMI 反應慢
- 不是警報,但可順便看:工作設定裡每個工作的 **Variable Access Time(%)** 決定 PLC 每個週期給外部(HMI)存取變數的時間;HMI 刷新太慢時可酌量調高(依 OMRON 手冊範圍)。

## 請回傳給我們
- [ ] 第 0 步的警告/錯誤原文截圖
- [ ] 工作清單(有哪些工作、各工作的週期)
- [ ] 出現警告的變數名稱,以及它在哪幾個程式/工作被讀、被寫
- [ ] 是否有 EtherNet/IP Tag Set、是否有 AT 指定

來源:OMRON《NJ/NX-series CPU Unit Software User's Manual》(W501)— 4-2-3 Task Settings「Settings for Exclusive Control of Variables in Tasks」(p.4-12)、5-9-1「Ensuring Concurrency of Variable Values between Tasks」(p.5-123~5-126)、6-3-8「Variable Attributes / Network Publish」(p.6-68)、I/O 控制工作外的輸出(p.5-112)、Primary Periodic Task 處理內容「System common processing 2 / variable access time」(p.5-16)。https://files.omron.eu/downloads/latest/manual/en/w501_nj_nx-series_cpu_unit_software_users_manual_en.pdf
