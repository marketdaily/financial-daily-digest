# MarketDaily 管理後台交接筆記

> 更新：2026-07-14。來源：`docs/admin.html`（2086 行，單頁 SPA）+ `docs/dashboard.html` 內嵌管理小工具。
> ⚠️ 本檔放 repo 根目錄，**不可**移進 `docs/`（會隨 Pages 部署公開，洩漏後台結構）。

## 進入方式
- 網址：`https://marketdaily.ai/admin.html`
- 登入：密碼 POST 到 worker（`doLogin`），無硬編碼 token
- 記住 Email：`localStorage("md-admin-email-saved")`，登入自動填入並 focus 密碼欄
- 後端 API host：`WORKER_URL = https://api.marketdaily.ai`（admin.html 頂部常數）
- Watchdog host：`WATCHDOG_URL = https://watchdog.marketdaily.ai`

## 側欄 11 個功能區（`nav(id)` 切換 `.section`）

| 區塊 | 標籤 | 用途 | 主要載入函式 |
|------|------|------|------|
| overview | 總覽 | KPI 磚(訂閱數/30d 事件/啟用新聞源)、系統健康探測、30d 歸因趨勢、近期轉換 | `renderOverviewStatic/Charts`, `runHealth` |
| equity | 模擬跟單 | 內部指標:由 `track-record.json` / `/admin/plan-trades` 畫模擬跟單淨值曲線(轉正才公開) | `renderEquity`, `loadEqTrades`, `drawEquity` |
| analytics | 數據分析 | 流量來源、事件類型、每日事件長條、近 50 筆轉換 | `loadAnalytics` |
| ops | 營運監控 | Watchdog run 狀態、健康、近期推播告警 | `loadOps`, `loadAlerts` |
| email | 寄信成效 | 30 天寄送統計 | `loadEmailStats` |
| audit | 稽核記錄 | 稽核 log 表 | `loadAudit` |
| subscribers | 訂閱者 | 訂閱清單(=Brevo list)、90 天累積成長、CSV 匯出、單一 email 明細 modal | `loadSubscribers`, `renderSubs`, `exportSubsCSV`, `openUserDetail` |
| reactive | 內容審核 | AI 生成內容審核佇列(核准/退回) | `loadReactive`, `rxApprove/rxReject` |
| news | 新聞源 | 分頁:美股 RSS / 台股 RSS / NewsAPI 網域白名單(改 KV 設定) | `switchNewsTab`, `renderFeeds`, `addFeed/removeFeed`, `addDomain/removeDomain` |
| settings | 系統設定 | API key 狀態、健康探測、全域 KV 設定 `admin:global-config` | `loadFromWorker`, `runHealthInto` |
| tools | 工具 | 生命週期測試信;⚠️危險:依 email pattern 清除測試聯絡人 | `lifecycleTest`, `purgeContacts` |

- 全域按鈕：`refreshAll()` 重整全部、`saveAll()` 寫回 KV 設定

## 主要 fetch 端點
- `POST {WORKER_URL}/admin/get-config`、`/admin/plan-trades`、config 存檔走 `api()`
- `GET {WORKER_URL}/stock-quotes?tickers=...`（健康探測）
- `GET /data/track-record.json`、`HEAD /output/digest_{ymd}.html`
- `GET {WATCHDOG_URL}/status`
- `copyDigestLink` 組 `https://marketdaily.ai/output/digest_{today}.html`

## 2026-07-14 整理紀錄
- 刪死碼 CSS `.segbar/.seg-premium/.seg-free/.seg-legend/.seg-leg`（已移除的「方案分布」segment bar 殘留）
- dashboard.html 刪死碼 `.share-btn.line`（LINE 已全面退役的分享鈕樣式殘留）
- **保留**：`plan` 欄位仍串在訂閱者程式(SUBS/CSV/`set-plan` audit label)。依「早鳥永久免費」規則,`s.plan` 可能載 legacy premium/早鳥身分,是有意義資料,CSV 匯出保留,非純死碼

## 已知殘留/注意
- 全站已免費化，訂閱者明細 badge 硬編「訂閱中 · 免費開放」；`plan` 資料仍由後端 KV `plan:${email}` 供應(可能有 legacy 值)
- `.plan-select` CSS class 名稱誤導:實際被 lifecycle-test 與 reactive bias 下拉沿用(是活的,別誤刪)
- admin.html JS 全內嵌(1060–2083 行);唯一外部 JS = `ui-pro.js`
- 無 LINE / Stripe / checkout / paywall / 升級 殘留(admin.html 乾淨)
- 無硬編碼 token/secret/API key
