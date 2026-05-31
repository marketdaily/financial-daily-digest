# 日報財報/營收影響分析 — 設計文件

日期：2026-05-31
範圍：在 MarketDaily 每日 Email 日報中，為訂閱者持股加入「**事件日個人化財報影響喊話**」——在某持股的月營收/季報真正公布的那天，於持有它的訂閱者日報裡，第二人稱告訴他數字、對其部位的影響、與下一個真實觀察點。

## 目標與非目標

**目標**：把「估值/財報」做成**事件驅動的個人化提醒**，而非天天報估值。當且僅當某持股有新財報數據落地，當天在該訂閱者日報多一段：「今天你追蹤的 X 公布 Y，YoY Z%，對你的部位[偏正/偏負/中性]，接下來留意 [真實下一個事件]」。

**非目標（YAGNI）**：
- 不在日報塞單一「合理價 $XXX」(DCF 假精準,踩 [[feedback_no_fake_numbers]])。完整 DCF 估值區間是後續第二階段,本期只做「財報影響分析」。
- 不天天對每支持股報估值。
- 不做美股 earnings 日曆的盤中即時(本期用最近一期已公布財報)。

## 資料策略（沿用已拍板方向）

| 市場 | 數據 | 來源 | 成本 |
|------|------|------|------|
| 台股月營收 | 每月10號前公告上月 | **FinMind**（免費，已驗證可抓） | 0 |
| 台股季報 | 5/15、8/14、11/14、3/31 | FinMind | 0 |
| 美股季報 | earnings（income/cashflow/ratios） | **FMP stable**（免費層已驗證可抓，key 存 `.env`） | 0 |

台股 DCF/基本面在 FMP 免費層被擋 → 台股一律走 FinMind。

## 核心原則：硬數字程式算，AI 只潤飾

- **YoY / MoM / 累計YoY / 連續成長月數 / beat-miss** 全部 Python deterministic 計算，當作「已核實事實」。
- LLM 只在這些**已驗證數字外圍**做白話解讀與口吻潤飾，**禁止自行產生營收數字或預期**。
- 「下一個觀察點」必須是**真實排程事件**（下一個季報法定申報日）或**數字本身透露的真實隱憂**（如累計YoY轉弱）——不准套漂亮話硬掰（用戶「毛利率被匯率吃掉」僅示意）。算不出根據就只報今天事實。
- 極端值防呆：|YoY|≥100% 標「(低基期)」提示，不裸報嚇人。

## 架構與資料流

```
data_fetcher.fetch_all()
   └─ 既有:行情 + 新聞 + 市場狀態
   └─ 新增: 對每位訂閱者持股,呼叫 valuation.earnings_impact
            └─ 事件日閘門:只有「最近一次公布在 N 天內」才算事件,附 facts
                          (月營收:該月資料 release_date 在近 ~10 天;季報:財報日近 ~10 天)
analyzer.generate_report(...)
   └─ _format_market_data() 注入「📊 財報影響(已核實,必須照數字寫,不可竄改)」區塊
   └─ LLM 依據事實寫出第二人稱喊話段落
   └─ _postprocess / digest_audit 驗證 email 內數字 = 計算值(防幻覺)
generate_deterministic_fallback()
   └─ 同樣附上影響段(數字本就 deterministic,fallback 也能寫)
```

### 元件 1：`valuation/earnings_impact.py`（擴充現有原型）

- `tw_revenue_impact(stock_id, today)` → FinMind 月營收：算 YoY/MoM/累計YoY/連續成長月數 → verdict（偏正/偏負/中性）+ impact（大/中/有限）+ `is_event`（最近公布在 N 天內）+ `base_effect` flag + `next_point`（真實下一季報日）。
- `us_earnings_impact(symbol, today)` → FMP：最近一季 EPS YoY、毛利率/營益率趨勢、（有 estimate 時）beat/miss → 同結構。
- `next_report_point(today)` → 真實季報排程（3/31、5/15、8/14、11/14）。
- **快取**：結果存 `valuation/cache/impact_{market}.json`，月營收每月10號後刷新、季報申報日後刷新；避免每日重打 API。
- 中文名：用既有 `stock_names.py`。

### 元件 2：`data_fetcher.py` 接線

- 既有 per-subscriber 持股流程中，對每支 holding 取 `earnings_impact`，只保留 `is_event=True` 的（當天才喊話）。把事件清單放進 data dict（如 `data["earnings_events"][email]` 或隨持股帶）。

### 元件 3：`analyzer._format_market_data()` 注入

- 新增區塊餵 prompt：
  ```
  📊 財報影響(以下數字已核實,撰寫時必須照寫不可更改;只針對有事件的持股):
  - 你持有 群聯(8299):2026/4 月營收 YoY +236.6%(低基期) MoM +10.3% 連13月正成長 → 偏正面/影響大;下一觀察點 2026-08-14 Q2季報
  ...
  ```
- prompt 指示：當有財報影響事件時，在對應持股的 signal-card 加一句第二人稱影響喊話；無事件不提。

### 元件 4：`digest_audit.py` 守門

- 擴充：抽出 email 內出現的營收/YoY 數字，比對計算值；不符 → 觸發既有 retry/fallback 流程（[[feedback_zero_error_no_miss]]）。寧可不顯示也不顯示錯誤數字。

### 元件 5：deterministic fallback

- `generate_deterministic_fallback()` 對有事件的持股，用純 Python 模板加一行影響句（數字 deterministic，安全）。

## 事件日閘門細節

- **月營收**：FinMind 該筆資料對應「公布日 ≈ 次月10號」。今天若在某持股最新月營收公布後 N 天內（N≈3，涵蓋10號當天到日報），算事件。
- **季報**：最近財報日在 N 天內算事件。
- 同一事件對同一訂閱者只喊一次（避免連續多天重複）：用 `valuation/cache/notified_{email}.json` 或日期比對。

## 錯誤處理

| 情況 | 行為 |
|------|------|
| FinMind/FMP 抓不到 | 該持股不顯示影響段（不報假數字），其餘正常 |
| 數字算不出（缺去年同期） | verdict=資料不足 → 不喊話 |
| audit 發現 email 數字≠計算值 | 走既有 retry → deterministic fallback |
| 無任何事件 | 日報完全不出現財報影響段（不硬塞） |

## 動到的檔案

| 檔案 | 變更 |
|------|------|
| `valuation/earnings_impact.py` | 擴充：TW+US 影響計算、快取、事件閘門、中文名 |
| `valuation/cache/` | 新增：影響快取 + 已通知記錄 |
| `data_fetcher.py` | 對持股取影響事件，放進 data |
| `analyzer.py` | `_format_market_data` 注入已核實影響、prompt 指示、fallback 加影響句 |
| `digest_audit.py` | 數字一致性查核 |
| `.env` | `FMP_API_KEY`（已存，gitignored） |

## 驗證計畫（接進 pipeline 前）

1. 離線用**用戶真實全部持股**跑 `earnings_impact`，把每支事件判讀攤給用戶看準不準（原型已證 8 支台股可行）。
2. 用真實數據跑一次完整 digest（**不寄信**，只產 HTML 存本地），檢查影響段是否只在事件日出現、數字正確、中文名、口吻對。
3. audit 數字一致性測試（故意塞錯數字確認被擋）。
4. 全綠才接上排程；遵守 [[feedback_no_manual_send]]：只由 06:55 UTC cron 自動寄，絕不手動觸發群發。

## 第二階段（本期不做，先記）

完整 DCF 估值區間（用 quant_lab/dcf_valuation.py + FMP/FinMind 基本面），輸出「合理價區間 + 判讀帶 + 關鍵假設」，季度更新。見 [[project_digest_valuation]]。
