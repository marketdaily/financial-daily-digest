# 2026-07-30 GitHub 星海挖礦（Delvin 指令：找 top-star 專案，能學的直接搬）

## 已搬入庫（6 skills，皆 MIT，SKILL.md 尾註來源）
來自 **coreyhaines31/marketingskills**（42k★，48 skills，取我們缺口 4 個）：
- `cro` — 單頁轉換率診斷（正接 07-21 conversion funnel 診斷的後續火力）
- `onboarding` — 註冊後活化（訂閱→設偏好→首封日報這段漏斗）
- `programmatic-seo` — 模板×資料規模化 SEO 頁（SEO 文章線升級方向）
- `marketing-psychology` — 行為科學心智模型庫

來自 **mattpocock/skills**（194k★，grill-me 同源）：
- `wayfinder` — 超大工程「決策票地圖」規劃法（我們原本沒有這類積木）
- `domain-modeling` — 詞彙表 + ADR，補工程部 Clean Code 基底

三處同步已完成（CATALOG / CLAUDE.md 速查 / GOVERNANCE 歸群），128→134。

## 評估後不搬（含理由，防未來重挖）
- `caveman`（94k★ 省 token skill）— 與溝通鐵則（可讀性>壓縮）相衝
- `graphify`（98k★ 知識圖譜）— brainsearch + graph.py 已覆蓋
- `ruflo` / swarm 框架 — Workflow harness 已覆蓋
- marketingskills 的 `churn-prevention` — 八成篇幅 Stripe 帳務挽留，全面免費用不上
- mattpocock 的 `to-tickets`（dispatch 骨架重疊）、`git-guardrails`（會擋 git push，與自動化管線相衝；但「PreToolUse 擋 `reset --hard`/`clean -f`/`branch -D`」的點子已記入下方提案）
- ECC 25 skills / anthropics 官方 / trading-skills 11 個 — **2026-05-30 已搬過**，Karpathy CLAUDE.md 模式 07-14 已學

## 情報：public-apis（453k★）金融區新源 → **已當場建成 2 連接器**（07-30 親令：挖到就蓋路，自主學習鋪平）

- ✅ `intel/us_congress_trades.py` — 國會議員交易（CongressInvests 實測免 key）；classify 真實資料開火 18 檔含群聚 red；**內建殭屍源守衛當天就攔下凍結快取**（免費快取凍在 06-01）。patrol/query 已接線，自測過。
- ✅ `intel/gold_macro.py` — 黃金避險溫度計（goldprice.dev 匿名層），ledger 首日入帳 $4,041。patrol 市場級段已接線，自測過。
- 🔜 鋪平工單已進 `~/autonomous/backlog.md`（congress key/官方源、Dino/EconPulse/BriefTape 評估、gold 門檻校準）。

### 原始候選表（存檔）
| API | 內容 | Auth | 對位 |
|---|---|---|---|
| CongressInvests | 美國會議員交易揭露（Senate EFD + House Clerk 即時） | apiKey | 與 us_13f/us_insider 互補的獨立訊號 |
| Dino.markets | Kalshi×Polymarket 配對預測市場+跨場價差 | apiKey | 全新訊號類型 |
| Econdb | 全球總經 | 免key | macro_rates 補源 |
| EconPulse | CPI/PPI/國債/BTC premium 即時 | apiKey | macro 補源 |
| Goldprice.dev | 金銀銅現貨+期貨+30年史 | 免key | 商品新域 |
| Portfolio Optimizer | 投組分析優化 API | 免key | quant_lab 對照驗證 |
| BriefTape | AI 摘要 SEC filings/Fed/FDA，ticker-tagged | apiKey | 事件流補源 |

評估標準照 intel 連接器慣例：免費層額度、資料新鮮度、與現有 24 連接器的獨立性。

## 順手記
- git-guardrails 點子（擋破壞性 git 指令的 PreToolUse hook）→ 併入 `project_engine_security_hardening_proposal` 待 Delvin 審批次。
