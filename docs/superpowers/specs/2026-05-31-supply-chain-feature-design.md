# 持股產業鏈 / 供應鏈功能 — 設計文件

日期：2026-05-31
範圍：MarketDaily「我的專區」(`docs/dashboard.html`) story card 內，為每支持股加上「這家公司做什麼 + 所屬產業 + 上中下游供應鏈」。

## 目標

用戶在專區點開任一持股泡泡時，除了現有的 signal / 價位 / 走勢圖，再看到一張**上游 ▲ → 中游 ●（本公司）→ 下游 ▼** 的橫向供應鏈鏈圖，理解這家公司是做什麼的、在產業鏈的哪個位置、上下游關聯哪些公司。

## 權限

**免費開放給所有登入用戶。** 不綁 Premium。

## 資料策略：Hybrid（真資料優先，AI 補洞）

純 AI 生成供應鏈關係有幻覺風險（會把無往來公司講成上下游），且質性資料無法事後 deterministic 驗證 —— 踩 [[feedback_no_fake_numbers]] 鐵則。故採 hybrid：

1. **先查既有人工核實 DB**（`finance_course/system/supply_chain.py`，66 家，含美股科技巨頭 / AI 群 / 無人機國防 / 台股主力，已 Firecrawl 查證）。命中 → 標記 **✓ 已核實**。
2. **未命中才走 AI 生成**（Claude Haiku，KV 快取）。標記 **AI 整理 · 僅供參考**。
3. 視覺上**明確區分兩種來源**，使用者一眼知道哪些查證過、哪些是 AI 推測。

DB 命中（多數熱門持股）完全不呼叫 LLM → 更快、更省、更可信。

## 架構與資料流

```
story card 點開
   │
   ├─ 前端 lazy-load  docs/data/supply_chain.json  (靜態, CDN 快取, 首次開卡才載)
   │     │
   │     ├─ ticker 命中 ──▶ 直接畫鏈圖, 標「✓ 已核實」          [零 LLM]
   │     │
   │     └─ 未命中 ──▶ GET /supply-chain?ticker=XXXX            [AI 路徑]
   │                      worker: 查 KV sc:${ticker}
   │                         ├─ 命中 ─▶ 回快取
   │                         └─ 未命中 ─▶ Claude Haiku 生成 → 存 KV(30d) → 回
   │                      前端畫鏈圖, 標「AI 整理 · 僅供參考」
   │
   └─ session 內再快取一份 (_scCache) 避免重複請求
```

### 元件 1：DB 匯出腳本 `scripts/export_supply_chain.py`

- import `finance_course/system/supply_chain.py` 的 `SUPPLY_CHAIN`
- 轉成前端用的精簡 JSON，寫到 `docs/data/supply_chain.json`
- 映射規則：
  - `company_zh` → 公司中文名
  - `biz_model` → 中游 desc（「做什麼」）
  - `suppliers[]`（取 name_zh/name_en/ticker/category/criticality）→ **上游**
  - `customers[]`（取 name_zh/name_en/ticker/role）→ **下游**
  - `industry`：DB 無此欄，由 `category` 群組或 biz_model 推一句（匯出時若缺則留空，前端不顯示該行）
- 需在 DB 更新後重跑（手動，非自動 cron）。
- key 維持原樣（`AAPL` / `2330.TW` / `8299.TWO`）。

### 元件 2：Worker AI 端點 `GET /supply-chain?ticker=XXXX`

加在 `stripe-webhook/src/index.js`（= `marketdaily-webhook`，與 `/stock-quotes`、`/chat` 同支，已有 `env.ANTHROPIC_API_KEY` + KV `USER_PREFS`）。

- **免登入**（免費功能），但加**輕量 per-IP rate limit**（30 次/分，KV `rl:sc:${ip}`）防 LLM 濫用。
- 流程：查 KV `sc:${ticker}` → 命中回快取；未命中 → 呼叫 `claude-haiku-4-5-20251001`，structured prompt 要求回**嚴格 JSON**（中英雙語）→ 解析成功才存 KV（TTL 30 天）→ 回傳。
- **Prompt 鐵則**：只列真實、公認的供應鏈關係；不確定就回**空陣列**，絕不亂掰；ticker 只在確定是上市公司才附。
- 解析失敗 / LLM 失敗 → 回 `{ error }`，**不回假資料**。

### 元件 3：前端 UI（`docs/dashboard.html` `renderStoryCard`）

- 走勢圖下方新增 `#sc-supplychain` 區塊。
- 開卡時 `loadSupplyChain(sym)`：先查 `_scCache` → 查靜態 JSON → 否則 fetch worker。
- 台股正規化：`2330` → 試 `2330.TW` 再試 `2330.TWO`。
- 渲染：
  - 頂部一行：`【公司名】所屬產業`（有才顯示）
  - 中游 desc（biz_model）
  - 三欄鏈圖：▲ 上游原材料/設備 → ●中游製程【本公司 highlight】← 你追蹤 → ▼ 下游應用/客戶
  - 每欄關聯公司 chip（**v1 純展示、不可點**，避免暗示成推薦）；DB 命中可加 criticality 小標（如「極高—無替代」）
  - 底部來源標籤：`✓ 已核實` 或 `AI 整理 · 僅供參考`，並固定附「非投資建議」
- 載入中 skeleton；失敗或空 → 「暫時無法載入產業鏈」，不塞假資料。
- i18n：隨 `localStorage("md-lang-v2")` 切中英；新增 i18n key（上游/中游/下游/已核實/AI 整理/載入失敗 等）。

## 資料格式（前端統一消費）

```json
{
  "ticker": "2330.TW",
  "source": "verified",            // "verified" | "ai"
  "company_zh": "台積電",
  "industry": "半導體 › 晶圓代工",   // 可空
  "mid": { "name": "台積電", "desc": "全球最大晶圓代工廠，先進製程獨家" },
  "upstream":  [ { "name_zh": "ASML", "name_en": "ASML", "ticker": "ASML", "category": "曝光設備", "criticality": "極高—無替代" } ],
  "downstream":[ { "name_zh": "蘋果", "name_en": "Apple", "ticker": "AAPL", "role": "A/M 系列 SoC" } ]
}
```

AI 路徑回傳同結構（`source:"ai"`，無 criticality 時省略，ticker 不確定時為 `null`）。

## 錯誤處理

| 情況 | 行為 |
|------|------|
| JSON 載入失敗 | 略過 DB，直接走 worker AI |
| worker LLM 失敗 / 回空 / 解析失敗 | 顯示「暫時無法載入產業鏈」，無假資料 |
| rate limit 觸發 | 同上，前端視為暫時無法載入 |
| ticker 兩種市場都查無 | 顯示「暫時無法載入產業鏈」 |

呼應 [[feedback_zero_error_no_miss]]：fallback 只能是誠實的「暫時無法載入」，絕不顯示捏造關係。

## 動到的檔案

| 檔案 | 變更 |
|------|------|
| `scripts/export_supply_chain.py` | 新增：DB → JSON 匯出腳本 |
| `docs/data/supply_chain.json` | 新增：匯出產物（66 家） |
| `stripe-webhook/src/index.js` | 新增 `/supply-chain` 路由 + rate limit |
| `docs/dashboard.html` | 新增 `#sc-supplychain` UI + `loadSupplyChain` + CSS + i18n key |

## 部署

- Worker：`cd stripe-webhook && npx wrangler deploy`
- Pages：`npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true --commit-message "supply-chain"`（ASCII commit message，呼應 [[project_deploy_gotcha]]）
- 改 `docs/data/supply_chain.json` 走靜態檔，無需 cache-bust（每次開卡 fetch）；若擔心 CDN 快取可帶 `?v=` 版本參數。

## 非目標（YAGNI）

- chip 點擊互動 / 一鍵加入持股（v1 不做）
- 供應鏈關係的即時更新 / 自動 cron 重建（手動重跑腳本即可）
- 風險清單 `risks[]` 顯示（v1 不放，避免卡片過長；未來可加）
- 美股 ticker 之外的深度連結
