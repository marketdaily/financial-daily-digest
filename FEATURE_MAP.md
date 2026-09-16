# MarketDaily FEATURE MAP

給 **agent** 用的產品地圖：每個功能在哪、從使用者角度怎麼到得了、要抓哪個選取器、什麼叫做對。

**為什麼有這份檔**(2026-09-16)：我們原本只有 `scripts/site_scan.py` 那種「掃描器說綠」的檢查——
它會載入 5 個頁面看 console error，但**不會走使用者路徑**。凡是掃描器看不見的東西
(存檔頁沒進索引、退訂連結宣稱的機制不存在、偏好存不進去) 都曾經在線上活很久沒人發現。
來源：Lauren Tan「verification 是 agent 的第一技能，而 verification 需要一份 feature map」。

## 怎麼用

- **改前端之前**：先在這裡找到你要動的 F-編號，照「驗收」那行決定要測什麼。
- **改完之後**：`python3 scripts/feature_map_lint.py`(靜態對帳，地圖 vs 程式碼)。
- **新增功能**：必須在這裡加一個 F-區塊，否則 lint 的覆蓋率閘門會紅。
- **欄位是機器讀的**：`檔案 / 選取器 / 函式 / 端點 / 狀態 / 驗收` 六行由 lint 逐項回程式碼驗證，
  格式不要改。`選取器` 只寫 `#id`，`端點` 寫路徑片段，`狀態` 寫 localStorage key。

後端基底：`WORKER_URL = https://api.marketdaily.ai`、`WATCHDOG_URL = https://watchdog.marketdaily.ai`

---

## A. 首頁與入站 (docs/index.html)

### F-01 首頁 Email 進入
- 入口: /
- 路徑: 首頁 hero → 填 email → 按「繼續 →」→ 依是否已訂閱分流
- 檔案: docs/index.html
- 選取器: #hero-email #hero-check-btn #hero-remember #email-step #error-email-msg
- 函式: checkEmail resetEmailStep heroSetPassword
- 端點: (無)
- 狀態: md-hero-email md-email
- 驗收: 空白 email 按繼續要出現 #error-email-msg 且不前進;勾 #hero-remember 後重載，#hero-email 要自動帶回上次的值

### F-02 首頁免費訂閱表單
- 入口: /
- 路徑: 首頁方案區 → 免費方案 → 填 email → 「送出 →」
- 檔案: docs/index.html
- 選取器: #home-free-email #home-free-submit #home-free-form #home-free-msg #home-free-btn
- 函式: openHomeFreeForm submitHomeFree subscribeFree
- 端點: (無)
- 狀態: (無)
- 驗收: 送出後 #home-free-msg 要出現明確結果字串(成功或錯誤)，不得靜默;同一 email 重送不得出現未處理例外

### F-03 語言切換 (全站預設中文)
- 入口: /
- 路徑: 右上角語言鈕
- 檔案: docs/index.html
- 選取器: #lang-toggle
- 函式: applyLang toggleLang
- 端點: (無)
- 狀態: md-lang-v2
- 驗收: 切英文後重載仍是英文;切回中文後 localStorage 值為 zh。**動態渲染出來的節點也要跟著翻**(歷史坑：動態內容繞過 i18n)

### F-04 推薦連結歸因
- 入口: /?ref=CODE
- 路徑: 帶 ref 參數進站 → 記錄首觸來源 → 回報 worker
- 檔案: docs/index.html
- 選取器: #invite-code-section
- 函式: getAttrPayload showReferralPrompt toggleInviteSection subscribeInvite
- 端點: /track-referral-click
- 狀態: md-ref md-attr-first
- 驗收: md-attr-first 一旦寫入不得被後續到訪覆蓋(first-touch 語意);無 ref 參數時不得送出歸因請求

---

## B. 訂閱者專區 (docs/dashboard.html + docs/js/dash-*.js)

### F-05 登入
- 入口: /dashboard
- 路徑: 未登入 → 登入卡 → email + 密碼 → 「進入我的專區 →」
- 檔案: docs/dashboard.html docs/js/dash-stocks-auth.js
- 選取器: #login-email #login-password #login-btn #login-err #login-form #login-screen #dashboard
- 函式: doLogin doLogout showLoginForm showDashboard
- 端點: /check-subscriber
- 狀態: (無)
- 驗收: 密碼錯誤要在 #login-err 顯示訊息且 #dashboard 保持隱藏;成功後 #login-screen 隱藏、#dashboard 顯示、#nav-email 出現該帳號

### F-06 首次設定密碼
- 入口: /dashboard
- 路徑: 已訂閱但未設密碼 → 設定密碼卡 → 兩次輸入 → 「設定並進入 →」
- 檔案: docs/dashboard.html docs/js/dash-stocks-auth.js
- 選取器: #new-password #confirm-password #set-pwd-btn #set-pwd-err #set-password-form
- 函式: doSetPassword
- 端點: /set-password
- 狀態: (無)
- 驗收: 兩次密碼不一致要擋在 #set-pwd-err;少於 6 位要擋。**先設密碼再選方案的順序不可顛倒**(歷史坑)

### F-07 修改密碼
- 入口: /dashboard
- 路徑: 專區 → 「修改密碼」→ 舊密碼 + 新密碼 x2 → 「確認修改 →」
- 檔案: docs/dashboard.html docs/js/dash-init.js docs/js/dash-chart.js docs/js/dash-core.js
- 選取器: #cpwd-old #cpwd-new #cpwd-confirm #cpwd-btn #cpwd-err #cpwd-ok #toggle-pwd-btn #change-pwd-form
- 函式: doChangePassword toggleChangePwd togglePwd
- 端點: /change-password
- 狀態: md-saved-pwd
- 驗收: 舊密碼錯誤要顯示 #cpwd-err 而不是靜默失敗;成功要顯示 #cpwd-ok

### F-08 股票偏好 (合規敏感)
- 入口: /dashboard?focus=stocks
- 路徑: 專區 → 股票偏好卡 → 搜尋 / 加入 / 移除 / 套裝
- 檔案: docs/dashboard.html docs/js/dash-stocks-auth.js
- 選取器: #stocks #stat-tw #stat-tw-list
- 函式: addStock removeStock renderTags renderDD renderQuickRow search addBundle
- 端點: (無)
- 狀態: (無)
- 驗收: 台股 tag 要**同時顯示代碼與公司名**;上限由後端執行(前端無常數，不要在前端假造上限訊息)。
  ⚖️ 合規鐵則：個股相關能力不得因方案差異化數量/深度/速度，任何「升級才有」文案都是違規

### F-09 偏好自動儲存
- 入口: /dashboard
- 路徑: 任何偏好變更 → debounce → 自動存 → 狀態列回報
- 檔案: docs/js/dash-init.js
- 選取器: #save-status
- 函式: doAutoSave scheduleSave setSaveStatus curPayload
- 端點: /save-preferences
- 狀態: (無)
- 驗收: 改一檔股票後 #save-status 必須從「儲存中」走到「已儲存」;重載頁面後改動仍在
  (歷史坑：dashboard 與已廢棄的 preferences 兩份 UI 不同步)

### F-10 日報深度設定
- 入口: /dashboard
- 路徑: 專區 → 日報深度卡 → 選深度
- 檔案: docs/js/dash-init.js
- 選取器: #digest-depth-card #depth-opts #depth-lock
- 函式: selectDepth renderDepth setupDepthCard
- 端點: /save-preferences
- 狀態: (無)
- 驗收: ⚖️ 深度全開，#depth-lock 不得對任何方案顯示鎖定態

### F-11 資金與持倉
- 入口: /dashboard
- 路徑: 專區 → 資金卡 / 持倉編輯 modal
- 檔案: docs/dashboard.html docs/js/dash-stocks-auth.js docs/js/dash-prefs-market.js docs/js/dash-init.js
- 選取器: #capital-input #cap-count #capital-card #pos-modal #pos-price #pos-qty #pos-date #pos-err #pos-title
- 函式: capitalChanged openPosEdit confirmPosEdit clearPosEdit
- 端點: /save-preferences
- 狀態: (無)
- 驗收: 非數字輸入要在 #pos-err 擋下;取消 modal 不得寫入資料

### F-12 批次匯入持股
- 入口: /dashboard
- 路徑: 專區 → 批次匯入 → 貼上清單 → 確認
- 檔案: docs/js/dash-stocks-auth.js
- 選取器: #bulk-modal #bulk-textarea #bulk-confirm #bulk-cancel #bulk-result #bulk-title #bulk-desc
- 函式: openBulk closeBulk confirmBulk parseBulkInput
- 端點: (無)
- 狀態: (無)
- 驗收: 貼入含空行/重複/非法代碼的清單，#bulk-result 要逐筆說明被略過的原因，不得靜默吞掉

### F-13 推播通知
- 入口: /dashboard
- 路徑: 專區 → 推播卡 → 開啟/關閉;iOS 需加入主畫面引導
- 檔案: docs/js/dash-notify-chat.js docs/js/dash-stocks-auth.js
- 選取器: #push-alert-card #ios-guide-overlay #ios-guide-copy-btn #ios-guide-inapp #alerts-feed-card #alerts-feed-list #alerts-feed-empty
- 函式: setupPushCard enablePush disablePush pushSupported openIosGuide closeIosGuide copyGuideLink isInAppBrowser setupAlertsFeed loadAlertHistory
- 端點: /push/subscribe /push/unsubscribe /alerts/list
- 狀態: (無)
- 驗收: 不支援推播的瀏覽器要顯示原因而不是壞掉的按鈕;in-app browser 要走 #ios-guide-inapp 分支。
  ⚖️ 推播全開，不得綁方案

### F-14 AI 對話
- 入口: /dashboard
- 路徑: 專區 → 對話 FAB → 問答
- 檔案: docs/js/dash-notify-chat.js
- 選取器: #chat-fab #chat-popup #chat-box #chat-input #chat-send #chat-messages #chat-meta #chat-locked-box
- 函式: setupChatCard toggleChatPopup sendChat renderChat chatEsc
- 端點: /chat-status
- 狀態: (無)
- 驗收: 額度用盡要顯示 #chat-locked-box 並說明何時恢復;送出中不得可重複送出

### F-15 報價與走勢圖
- 入口: /dashboard
- 路徑: 進入專區自動載入大盤與持股報價;點個股看圖
- 檔案: docs/js/dash-prefs-market.js docs/js/dash-chart.js
- 選取器: #market-overview-section #mo-row #sync-countdown #sync-counter #story-chart-canvas #story-chart-msg
- 函式: loadMarketOverview fetchQuotesChunked refreshQuotes startCountdown loadChart renderChart setChartPeriod
- 端點: /market-overview /stock-quotes /stock-chart
- 狀態: (無)
- 驗收: 報價失敗時要顯示明確錯誤，**不得留下 undefined / NaN% / [object Object]**(site_scan 也會抓)

### F-16 個股故事與供應鏈
- 入口: /dashboard
- 路徑: 專區 → 故事列 → 開個股 → 供應鏈
- 檔案: docs/js/dash-stories-chain.js
- 選取器: #stories-section #stories-row #stories-nav-prev #stories-nav-next #story-overlay #sc-ticker #sc-name #sc-price #sc-change #sc-verdict #sc-supplychain #sc-levels
- 函式: loadStories renderStoryCard openStory closeStories storyNav loadSupplyChain renderSupplyChain renderScUpdates
- 端點: /supply-chain /supply-chain-updates
- 狀態: (無)
- 驗收: 供應鏈內容必須帶公司名(歷史坑：只給產業鏈會幻覺);查無資料要走空狀態而不是空白區塊

### F-17 推薦獎勵
- 入口: /dashboard
- 路徑: 專區 → 推薦卡 → 複製連結 / 分享
- 檔案: docs/js/dash-init.js
- 選取器: #copy-ref-btn #ref-recent-list #ref-bonus-badge
- 函式: copyRefLink loadReferral renderRecentReferrals renderBonusBadge shareText shareToX shareToFacebook
- 端點: /referral-stats
- 狀態: (無)
- 驗收: 文案**不得承諾任何可兌現回報**(全面免費化後已無獎勵可發，只能是純分享)

### F-18 專區語言切換
- 入口: /dashboard
- 路徑: 專區右上語言鈕
- 檔案: docs/js/dash-core.js
- 選取器: #hero-name #plan-badge
- 函式: applyLang toggleLang refreshDynamicLang T
- 端點: (無)
- 狀態: (無)
- 驗收: **動態渲染的股票 tag、報價列、故事卡切語言後也要跟著換**(refreshDynamicLang 的存在理由);title 屬性也要翻

### F-19 舊偏好頁重導
- 入口: /preferences
- 路徑: 任何進到 /preferences 的流量 → 立刻轉往 /dashboard?focus=stocks
- 檔案: docs/preferences.html
- 選取器: (無)
- 函式: (無)
- 端點: (無)
- 狀態: (無)
- 驗收: 這頁**不得再長出任何偏好 UI**;帶 query string 進來要保留原參數再附加 focus=stocks

---

## C. 公開頁

### F-20 戰績頁
- 入口: /track-record
- 路徑: 直接進站 → 篩選市場/方向/期間
- 檔案: docs/track-record.html
- 選取器: #rec-table #rec-more #stat-total #stat-direction #stat-risk #stat-days #data-updated-badge #market-split-card #real-service-note
- 函式: renderRecords applyFilter renderCombinedStats renderMarketStats renderHorizonStats renderDataBadge renderEmptyState tradingDaysSince
- 端點: data/track-record.json
- 狀態: md-attr-first md-lang-v2
- 驗收: 主數字必須與公版存檔頁可對照;#data-updated-badge 要反映真實資料日期(歷史坑：價格快取凍結導致舊建議永遠待結)

### F-21 系統狀態頁
- 入口: /status
- 路徑: 直接進站
- 檔案: docs/status.html
- 選取器: (無)
- 函式: (無)
- 端點: (無)
- 狀態: md-lang-v2
- 驗收: 品質戰情頁，資料來自 quality.json;不得寫死數字

---

## D. 管理後台 (docs/admin.html)

### F-22 Admin 登入
- 入口: /admin
- 路徑: 輸入 admin email + 密碼
- 檔案: docs/admin.html
- 選取器: #auth-email #auth-pw #auth-err #auth-remember #auth-screen #admin-shell
- 函式: doLogin bootAdmin
- 端點: (無)
- 狀態: md-admin-email md-admin-email-saved md-admin-pwd-saved
- 驗收: 記住 email 後重載要自動帶入 #auth-email 並把游標 focus 到 #auth-pw

### F-23 Admin 監控與告警
- 入口: /admin
- 路徑: 後台 → 系統告警 / 稽核 / 營運
- 檔案: docs/admin.html
- 選取器: #alerts-content #audit-content #badge-ops #badge-rx #badge-subs #cfg-json #cfg-updated
- 函式: loadAlerts loadAdminEvents loadAudit loadOps handleAlertDeepLink
- 端點: /status /stock-quotes
- 狀態: md-admin-cfg
- 驗收: 已修復的告警要能看到「✅ 已解決」標記(由 scripts/resolve_admin_alert.sh 寫入)

---

## E. 看盤台 (docs/watch.html + docs/js/watch.js)

### F-24 看盤台
- 入口: /watch
- 路徑: 直接進站 → 選標的 / 切週期 / 看籌碼財報
- 檔案: docs/js/watch.js
- 選取器: (無)
- 函式: (無)
- 端點: /market-news /stock-news /stock-quotes /stock-chart /tw-chips /tw-fin /us-fundamentals /us-ranks /supply-chain-updates
- 狀態: (無)
- 驗收: 這是新版看盤台(不是舊的「AI 看盤台」，舊版才有「別重建」限制);報價橋接不可用時要降級而不是整頁空白
