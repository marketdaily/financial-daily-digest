# MarketDaily 長輩上手引導系統 — 設計文件

- 日期:2026-05-22
- 狀態:已核准設計,待寫實作計畫

## 1. 背景與問題

MarketDaily 已具備完整帳號系統:

- **註冊**:`docs/index.html` 輸入 Email → 選方案(免費需邀請碼 / Pro 走 Stripe)
- **設密碼**:第一次登入時自動跳「設定密碼」表單,呼叫 Worker `/set-password`
- **登入**:`docs/dashboard.html` 登入畫面(Email + 密碼)

問題不在功能缺漏,而在**年長、不熟科技的使用者找不到、看不懂這些步驟**。本專案新增一層「引導系統」,不改動既有帳號邏輯。

## 2. 目標 / 非目標

### 目標
- 用三種方式引導長輩走完:**註冊 → 設密碼 → 登入 → 設定股票偏好**
- 文字白話、字級放大、步驟清楚、可重複查看

### 非目標(明確不做)
- 不更動登入機制,維持 Email + 密碼(不導入驗證碼/魔法連結)
- 不做 FAQ / 客服求助頁
- 不重寫既有 `index.html` / `dashboard.html` / `preferences.html` 的核心流程,只新增引導元素

## 3. 系統總覽

三個互相獨立、各有單一職責的元件:

| 元件 | 職責 | 形式 |
|------|------|------|
| ① 圖文教學頁 | 完整上手的靜態圖文說明 | 新頁面 `docs/guide.html` |
| ② 歡迎信 | 訂閱後主動觸達,把人導回教學頁與登入 | 改寫既有 `sendWelcomeEmail()` |
| ③ 互動浮層引導 | 在真實畫面上一步步 spotlight 帶操作 | 新模組 `docs/onboarding-tour.js` |

三者皆指向同一份內容(4 步驟上手流程),彼此可獨立開發與測試。

---

## 4. 元件一:圖文教學頁 `docs/guide.html`

### 4.1 定位
獨立、長輩友善的大字頁面,沿用 MarketDaily 品牌(深色玻璃卡片、indigo 漸層、Inter 字體、scene-reveal 動畫),但內文字級放大到約 19px、編號徽章超大、語句白話。

### 4.2 版面結構
- **頁首**:標題「新手教學 — 3 分鐘學會用 MarketDaily」+ 一句友善開場
- **4 個步驟卡**,由上而下垂直排列,每張卡含:
  1. 超大圓形編號徽章(1/2/3/4)
  2. 該步驟對應畫面的**真實截圖**
  3. 2~3 句白話說明
  4. 一顆大的「現在就做 →」行動按鈕(步驟 2 無按鈕)
- **頁尾**:一句鼓勵 + 回首頁連結

| 步驟 | 標題 | 說明重點 | 按鈕 → 目標 |
|------|------|----------|-------------|
| 1 | 怎麼註冊 | 到首頁輸入 Email、選免費或 Pro 方案 | 現在去註冊 → `index.html` |
| 2 | 怎麼設定密碼 | 第一次登入會自動跳出設密碼欄;**提醒把密碼寫在紙上保存** | （無) |
| 3 | 在哪裡登入 | 點網站上的「我的專區」,輸入 Email + 密碼 | 前往登入 → `dashboard.html` |
| 4 | 設定你的股票 | 在持倉區搜尋股票代號或名稱 → 點一下加入 → 按「儲存設定」 | 去設定股票 → `dashboard.html` |

### 4.3 視覺/無障礙規範
- 內文最小字級 18px,步驟標題 ≥ 24px,按鈕字級 ≥ 17px、觸控區 ≥ 48px 高
- 色彩對比符合 WCAG AA
- 單欄排版,手機優先;不使用游標特效(專案慣例)

### 4.4 截圖來源
實作階段用 Playwright 對 `index.html`、`dashboard.html` 登入畫面、`dashboard.html` 持倉區各截一張圖,存到 `docs/assets/guide/`,於頁面以 `<img>` 引用。

### 4.5 語言
中文為主(目標族群為台灣長輩)。保留 `data-i18n` 掛鉤以便日後補英文,但本期只交付中文內容。

### 4.6 進入點
於 `index.html`、`dashboard.html`、`preferences.html` 的導覽列或頁尾加上明顯連結「📖 新手教學」指向 `guide.html`。歡迎信亦連到此頁。

---

## 5. 元件二:歡迎信(改寫既有 `sendWelcomeEmail()`)

### 5.1 現況
`stripe-webhook/src/index.js` 已有 `async function sendWelcomeEmail(email, apiKey, isPaid)`(約第 709 行),透過 Brevo 交易信 API(`https://api.brevo.com/v3/smtp/email`,金鑰 `env.BREVO_API_KEY`)寄出。三個訂閱路徑皆已呼叫它:
- `/free-subscribe`(約第 240 行)
- `/subscribe-free-direct`(約第 392 行)
- Stripe 付費成功(約第 478 行,`isPaid = true`)

因此本元件**只需修改這一個函式的 HTML 內容**,不需新增呼叫點。

### 5.2 修改內容
在現有歡迎信中加入並調整:
- 新增「3 步驟開始」區塊,清楚寫出:① 設定密碼 ② 登入我的專區 ③ 設定你的股票
- 兩顆大型 CTA 按鈕:
  - **「設定密碼並登入 →」** → `https://marketdaily.ai/dashboard.html?email=<urlencoded email>`(該頁偵測無密碼會自動顯示設密碼表單)
  - **「看完整圖文教學 →」** → `https://marketdaily.ai/guide.html`
- 整體字級放大(內文 ≥ 15px、按鈕 ≥ 16px)、語句白話化
- 既有「推薦好友」「每日報告包含」區塊保留,順序調整為:歡迎 → 3 步驟 CTA → 報告內容 → 推薦好友

### 5.3 預覽檔
另存一份對應的靜態預覽 `marketing/welcome-email.html` 供檢視;Worker 內的版本為實際寄送來源,兩者內容須一致(實作時以 Worker 版為準,預覽檔同步)。

### 5.4 錯誤處理
沿用既有作法:寄信失敗不阻擋訂閱流程(現有呼叫即為 `await` 後繼續)。不改動此行為。

---

## 6. 元件三:互動浮層引導 `docs/onboarding-tour.js`

### 6.1 定位
可重用的 coach-mark / spotlight 導覽模組。在真實畫面上以遮罩高亮單一元素,旁邊浮出大字泡泡(例:「在這裡輸入你的 Email」),逐步帶操作。

### 6.2 模組介面
`onboarding-tour.js` 對外提供:

```
Tour.mount(steps, options)
```

- `steps`:步驟陣列,每個元素為
  ```
  { selector: "#hero-email",          // 要高亮的元素
    title: "輸入你的 Email",            // 大字標題
    body: "在這個框框打上你的電子信箱", // 白話說明
    placement: "bottom" }              // 泡泡相對位置
  ```
- `options`:`{ tourId: "index-v1", auto: true }`
  - `tourId`:用於 `localStorage` 記錄是否已自動播放過(鍵 `md-tour-done:<tourId>`)
  - `auto`:首次造訪是否自動啟動

模組行為:
- 注入右下角固定的「❓ 新手教學」浮動按鈕(所有掛載頁面皆有),點擊隨時重播
- `auto:true` 且該 `tourId` 未播放過 → 頁面載入後自動啟動一次,播畢寫入 `localStorage`
- 泡泡含「上一步」「下一步」「跳過教學」按鈕;高亮元素被點擊或步驟完成可前進
- 若某步 `selector` 在頁面找不到元素 → 跳過該步並繼續(不中斷)

### 6.3 各頁步驟設定
步驟陣列定義於各頁內嵌 script(非寫死在模組內),模組保持泛用。

- **`index.html`**(`tourId: "index"`):①「輸入 Email」→②「按繼續」→③「選擇方案」→ 結尾提示「訂閱後記得去設定密碼」
- **`dashboard.html` 登入畫面**(`tourId: "dashboard-login"`):①「輸入訂閱 Email」→②「輸入密碼(第一次會請你設定)」→③「按進入我的專區」
- **`dashboard.html` 進入後 / 持倉區**(`tourId: "dashboard-stocks"`):①「在這裡搜尋股票」→②「點一下加入清單」→③「按儲存設定」
- **`preferences.html`**:此頁亦含持倉設定 UI,掛「❓ 新手教學」按鈕 + 教學頁連結,並套用與 `dashboard-stocks` 相同的步驟設定(`tourId: "preferences-stocks"`)

### 6.4 視覺/無障礙
- 泡泡內文 ≥ 16px,按鈕觸控區 ≥ 44px
- 遮罩半透明深色,高亮元素加 indigo 外框
- 不使用游標特效
- `Esc` 或「跳過教學」可隨時結束

### 6.5 載入方式
各頁以 `<script src="onboarding-tour.js">` 引入,再以內嵌 script 呼叫 `Tour.mount(...)`。模組無外部相依,只操作 DOM。

---

## 7. 檔案異動清單

| 檔案 | 動作 | 說明 |
|------|------|------|
| `docs/guide.html` | 新增 | 圖文教學頁 |
| `docs/onboarding-tour.js` | 新增 | 互動浮層引導模組 |
| `docs/assets/guide/*.png` | 新增 | 教學頁用截圖 |
| `marketing/welcome-email.html` | 新增 | 歡迎信靜態預覽 |
| `stripe-webhook/src/index.js` | 修改 | 改寫 `sendWelcomeEmail()` HTML |
| `docs/index.html` | 修改 | 引入並掛載 Tour、nav/footer 加教學頁連結 |
| `docs/dashboard.html` | 修改 | 引入並掛載 Tour(登入 + 持倉兩段)、加教學頁連結 |
| `docs/preferences.html` | 修改 | 引入並掛載 Tour、加教學頁連結 |

## 8. 資料流

- **歡迎信**:使用者訂閱 → Worker 訂閱路徑 → `addToBrevo()` → `sendWelcomeEmail()` → Brevo 交易信 API → 使用者收到信 → 點 CTA 回到 `dashboard.html` / `guide.html`
- **互動引導**:頁面載入 → 內嵌 script 呼叫 `Tour.mount(steps,{auto})` → 讀 `localStorage` 判斷是否自動播 → 使用者操作浮層 → 播畢寫回 `localStorage`
- **教學頁**:純靜態,無資料流;按鈕為一般超連結

## 9. 錯誤處理

- Tour 找不到目標元素 → 跳過該步,不中斷
- Tour `localStorage` 不可用(隱私模式)→ 視為「未播放過」,每次自動播一次,功能不壞
- 歡迎信寄送失敗 → 沿用既有行為,不阻擋訂閱
- 教學頁截圖載入失敗 → 加 `alt` 文字說明,版面不破

## 10. 測試計畫

- **互動引導**:用 Playwright 在 `index.html`、`dashboard.html` 跑導覽,驗證高亮位置、上一步/下一步/跳過、首次自動播放、`localStorage` 記錄、缺元素時跳過
- **教學頁**:手機與桌機寬度檢視版面;確認每顆 CTA 連到正確頁面;字級符合規範
- **歡迎信**:本機渲染 `marketing/welcome-email.html` 檢查版面;以測試 Email 觸發 `/free-subscribe` 確認實際收信、CTA 連結正確
- **回歸**:確認 `index.html` / `dashboard.html` / `preferences.html` 原有功能(登入、設密碼、儲存偏好)不受影響

## 11. 部署

- 前端:`npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true --branch=main --commit-message="..."`(commit message 須為 ASCII)
- Worker:`npx wrangler deploy`(於 `stripe-webhook/`)
