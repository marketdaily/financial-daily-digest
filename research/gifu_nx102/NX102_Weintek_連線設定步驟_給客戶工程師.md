# OMRON NX102-1200 ↔ Weintek cMT2166X 連線設定步驟(給客戶 PLC 工程師)

我方已在 EasyBuilder Pro V6.09.02 用同一驅動完成「匯入標籤 → 綁物件 → 編譯 0 錯誤 → 模擬讀寫」驗證。以下是 PLC 端要做的事，照順序做完，把第 3 步產出的 txt 給我們即可。

## 1. Sysmac Studio:建立給 HMI 用的全域變數
1. Global Variables 建立變數(命名建議統一 `HMI_` 開頭，清單見附件 `NX102_GlobalVariables_CX-Designer_sample.txt`)。
2. 每個給 HMI 的變數 **Network Publish 一律選 `Publish Only`**。
   - 選「Do not publish」的變數:匯入 HMI 時會被帶進來，但**通訊不會成功**(Weintek 官方連線指南原文)。請逐一確認，不要漏。
3. 陣列**索引必須從 0 開始**(`ARRAY[0..41] OF ...`)。
4. 不要用 AT 指定絕對位址(用變數名通訊即可)。若一定要用 AT:BOOL 不能對到連續位址，每個 BOOL 要獨占一個 word(%W10.0、%W11.0…)；BOOL 陣列建議對到 %W/%H 的 word 起點。
5. 支援型別:BOOL、SINT、BYTE、USINT、INT、WORD、UINT、DINT、UDINT、DWORD、REAL、LINT、ULINT、LWORD、LREAL、STRING(最長 80，建議長度取偶數)及以上型別的陣列。**不支援 STRING 陣列**；結構體請用「匯入標籤」方式，不要用「取得標籤資訊」。

## 2. PLC 安全通訊(韌體 V1.49 以後；客戶這台需確認韌體版本)
1. 斷電 → CPU 上 **DIP SW 1、2 切到 ON** → **重新上電**。
   - ⚠️ 只切 DIP 不重新上電不會生效(NX102 硬體手冊:「change the DIP switch settings 後再 turn ON power」；V1.64 實例就是卡在這一步)。
2. 若 PLC 有啟用「使用者驗證(User Authentication)」，需依 OMRON 說明關閉或改成允許第三方 HMI 連線；DIP 各位元功能請以貴司 OMRON 窗口確認為準(Weintek 官方表示不同型號 DIP 定義可能不同)。
3. 任務週期 [Task Execution Time / Set Period] 請設合理值，太緊會拖慢 HMI 回應。

## 3. 匯出變數給我們
1. Sysmac Studio:**Tools → Export Global Variables → CX-Designer**(會複製到剪貼簿)。
2. 開記事本貼上 → 另存 `.txt`，**編碼選 ANSI**。
3. 把這個 txt 寄給我們(不需要整個專案檔)。

我們這邊會用 `nx_tags_check.py` 先檢查一遍(陣列下標非 0、不支援型別、TAGLINK 非 TRUE 都會被抓出來)，匯入後核對變數數量。
> 實測發現:EasyBuilder 只認陣列寫成 `UINT[42]` 這種「元素數」格式；若檔案裡是 `ARRAY[0..41] OF UINT`，該行會被**安靜略過**(其他變數照常匯入，不報錯)。檢查工具會自動轉成正確格式並列出變數數量，所以這一步不用貴司處理，只要原樣匯出即可。

## 4. 網路
| 項目 | 設定 |
|---|---|
| 協定/埠 | EtherNet/IP，**TCP 44818**(不是 80) |
| PLC IP | 出廠預設 Port1 = 192.168.250.1(請告知實際值) |
| HMI 驅動 | EasyBuilder Pro「OMRON EtherNet/IP (NJ/NX Series)」，站號 1 |
| HMI LAN1 / LAN2 | **兩個網口要設在不同網段**(例:LAN1 192.168.250.x 接 PLC，LAN2 192.168.20.x 接廠區網路)。同網段會出現「Device No Response」 |
| 排錯 | 先 HMI 直接網路線接 PLC(不經交換器)＋只放一個變數測通；通了再接回交換器 |

## 5. 請貴司提供
- [ ] 第 3 步匯出的 txt(ANSI)
- [ ] PLC IP / 子網路遮罩、HMI 要用的 IP
- [ ] 韌體版本、DIP 已切且已重新上電的確認
- [ ] 是否有使用者驗證、是否已關閉
- [ ] 陣列/BOOL 是否有 AT 絕對位址(有的話請列出)

來源:Weintek PLC Connection Guide「OMRON EtherNet/IP (NJ/NX Series)」(dl.weintek.com/public/PLC_Connect_Guide/OMRON_EtherNet_IP_NJ_NX_Series.pdf)；forum.weintekusa.com/t/omron-plc-via-ethernet/3405(NX102 V1.64、DIP 需重新上電、44818)；forum.weintekusa.com/t/how-to-connect-to-an-omron-nx102-in-eb-pro/3802(Publish Only、LAN1/LAN2 分網段、直連排錯)。
