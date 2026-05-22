# MarketDaily 長輩上手引導系統 — 實作計畫

- 日期:2026-05-22
- 對應設計:`docs/superpowers/specs/2026-05-22-elderly-onboarding-design.md`

依相依性排序的階段。每階段附驗收標準。

---

## Phase 0 — 準備截圖

1. Playwright 開啟 `index.html`、`dashboard.html`(登入畫面)、`dashboard.html`(登入後持倉區),各截一張圖
2. 存到 `docs/assets/guide/`:`step1-register.png`、`step3-login.png`、`step4-stocks.png`
3. 步驟 2(設密碼)截 `set-password-form` 畫面 → `step2-password.png`

**驗收**:4 張截圖存在、清晰、可辨識操作位置。

---

## Phase 1 — 互動浮層引導模組 `docs/onboarding-tour.js`

1. 建立 IIFE 模組 `Tour`,對外 `Tour.mount(steps, options)`
2. **遮罩 + spotlight**:全螢幕遮罩,高亮元素用透明定位框 + `box-shadow: 0 0 0 9999px rgba(0,0,0,0.72)`,加 indigo 外框
3. **泡泡**:依 `placement` 定位於高亮元素旁,含標題、白話說明、「上一步 / 下一步 / 跳過教學」按鈕(觸控區 ≥ 44px、字 ≥ 16px)
4. **狀態機**:`start / show / next / prev / finish`;`show()` 找不到 `selector` 元素則自動 `next()`
5. **浮動按鈕**:注入右下角固定「❓ 新手教學」FAB,點擊 `start()`
6. **localStorage**:鍵 `md-tour-done:<tourId>`;`auto:true` 且未播放過 → 載入後延遲 ~600ms 自動啟動,播畢寫入;`localStorage` 不可用時當作未播放
7. **結束**:`Esc` 或「跳過教學」呼叫 `finish()`,清除 DOM、解除 resize 監聽
8. 視窗 resize / scroll 時重算高亮位置
9. 模組自帶 CSS(注入 `<style>` 或同檔字串),不依賴外部樣式

**驗收**:在任一含目標元素的頁面呼叫 `Tour.mount` 能高亮、前進後退、跳過、FAB 重播;缺元素步驟自動跳過不報錯。

---

## Phase 2 — 圖文教學頁 `docs/guide.html`

1. 以 MarketDaily 品牌(深色玻璃卡片、indigo 漸層、Inter)建頁,內文字級放大(內文 ≥ 18px、步驟標題 ≥ 24px、按鈕 ≥ 17px)
2. 頁首:標題「新手教學 — 3 分鐘學會用 MarketDaily」+ 友善開場句
3. 4 張步驟卡(垂直單欄):超大編號徽章 + 對應截圖 `<img>` + 2~3 句白話說明 + CTA 按鈕
   - 步驟 1 →「現在去註冊」`index.html`
   - 步驟 2 →(無按鈕)提醒把密碼寫在紙上
   - 步驟 3 →「前往登入」`dashboard.html`
   - 步驟 4 →「去設定股票」`dashboard.html`
4. 截圖 `<img>` 加 `alt` 文字
5. 頁尾:鼓勵句 + 回首頁連結
6. 手機優先單欄;不加游標特效
7. 保留 `data-i18n` 掛鉤,本期只交付中文

**驗收**:手機與桌機版面正常;4 顆 CTA 連到正確頁面;字級達標;截圖失敗時 `alt` 不破版。

---

## Phase 3 — 各頁掛載引導

1. **`index.html`**:`<script src="onboarding-tour.js">` + 內嵌步驟(`tourId:"index"`,Email→繼續→選方案);nav/footer 加「📖 新手教學」連結
2. **`dashboard.html`**:引入模組;登入畫面掛 `tourId:"dashboard-login"`(Email→密碼→進入按鈕);登入成功後掛 `tourId:"dashboard-stocks"`(搜尋→加入→儲存);加教學頁連結
3. **`preferences.html`**:引入模組;掛 `tourId:"preferences-stocks"`(同持倉步驟);加教學頁連結
4. FAB 按鈕由模組注入,確認三頁皆出現且不擋既有 UI

**驗收**:三頁皆有 FAB 與教學頁連結;首訪自動播一次;原有功能(登入、設密碼、儲存偏好)不受影響。

---

## Phase 4 — 改寫歡迎信

1. 修改 `stripe-webhook/src/index.js` 的 `sendWelcomeEmail()` HTML:
   - 新增「3 步驟開始」區塊(① 設定密碼 ② 登入我的專區 ③ 設定股票)
   - 兩顆大 CTA:「設定密碼並登入 →」`dashboard.html?email=<encoded>`、「看完整圖文教學 →」`guide.html`
   - 字級放大、語句白話;保留「報告包含」「推薦好友」區塊,順序:歡迎→3步驟→報告內容→推薦
2. 同步產出靜態預覽 `marketing/welcome-email.html`(內容與 Worker 版一致)
3. 不改寄送失敗處理行為

**驗收**:預覽檔渲染正常;CTA 連結正確含 email 參數;Worker `wrangler deploy` 無誤。

---

## Phase 5 — 測試

1. Playwright 在 `index.html`、`dashboard.html` 跑導覽:高亮位置、上一步/下一步/跳過、首訪自動播、`localStorage` 記錄、缺元素跳過
2. `guide.html` 手機(375px)與桌機寬度檢視
3. 觸發 `/free-subscribe`(測試 Email + 邀請碼)確認實際收信、CTA 正確
4. 回歸:登入、設密碼、儲存偏好仍正常

**驗收**:上述全部通過。

---

## Phase 6 — 部署

1. 前端:`npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true --branch=main --commit-message="deploy: onboarding guide"`
2. Worker:於 `stripe-webhook/` 執行 `npx wrangler deploy`
3. 線上抽查 `marketdaily.ai/guide.html` 與 FAB

**驗收**:線上頁面與歡迎信皆生效。

---

## 風險與備註

- 部署 commit message 必須 ASCII(見記憶 `project_deploy_gotcha`)
- Playwright 瀏覽器若被佔用需先釋放
- 截圖須在頁面最終樣式定稿後再補拍,避免過期
