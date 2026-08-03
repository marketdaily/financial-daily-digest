# buy 訊號 setup 條件化 edge 分析 — 精準預判 P1.7

**日期**：2026-07-13（深攻輪 Opus 4.8）
**交辦**：Delvin 2026-07-13 親令「我要你做到精準預判」
**問題**：buy 訊號在**什麼 setup 條件**下才有正 edge？(regime × 超賣/回檔 × 桶級 × 市場別)
**產出性質**：純唯讀分析報告，**不改 analyzer，等 Delvin 拍板**。腳本 `research/2026-07-13_buy_setup_conditional_edge.py`。

---

## 一句話結論（誠實版）

**用目前這 18 個交易日的帳本，「精準預判哪些 buy 會贏」在統計上還做不到——沒有任何 setup 能通過誠實驗收門檻。** 但資料不是零產出：它明確指出**唯一現在就站得住的 buy 閘門是「把追高的 buy 降級成 wait」**（追強勢是 certified 負 edge，且與既有 chase-high 證據互相印證），並留下**一個值得追蹤的正向假設（買回檔/超賣）**，外加**一個對你今天剛上線的 rebuy-bleed 閘門的對帳警訊**。

---

## 方法（為什麼可信）

沿用既有統計積木 + 過去踩過的坑（`feedback_math_rigor` + lessons）：

1. **固定【預先登記】14 個 cut，不掃參**——沒有「挑出最好看的切法」的自由度，避免 overfitting。
2. **基線不是 50%，且必須排除 buy 自身**（`capability_daycluster` 2026-07-12 caveat + 本輪驗證者修正）：buy 的 win 條件是 `chg>0`，這 18 天是**跌勢**，若把 buy 放進自己的虛無假設是 circular。用 **non-buy 宇宙** `P(chg>0)=47.3%`（wait/sell/hold 的 ticker-day）當基線。所以 buy 的 38.7% 勝率要跟 **47.3%** 比、不是 50%——差 8.6 個百分點。
3. **雙獨立透鏡，兩個都過才算 edge**：
   - **(A) hit-rate**：`edge_validator.assess`——正確基線 + day-cluster 90% CI + eff_days 誠實閘 + episode fragility。
   - **(B) EV / 選股力**：`backtest_validator.deflated_sharpe` 跑**day-neutralized 每日 mean chg**（減掉當日 **non-buy** 宇宙 mean chg，剝掉大盤 beta，只留「選股 selection edge」），`n_trials=14`（多重檢定懲罰）。⚠️ DSR 在 T<10 天機械式回傳 0（三四階動差估不出）→ 那些 cut 標 **underpowered(T<10)**，不是「overfit」，該透鏡對它們**無資訊**（不可當第二佐證）。
4. **eff_days≥15 誠實閘**（Herfindahl 有效獨立日，非日期數）：18 天資料一 subset 就塌，這個閘是最後防線。
5. **無 lookahead**：RSI14 / MA20 / 回檔深度都只用 ≤ 訊號日的價格（收盤 anchor 與 label 的 forward return 同錨，屬標準「收盤進場」慣例）。
6. **day-neutralize 揭穿 beta 陷阱**：`regime_down` 是活教材——原始勝率 56%、EV +1.86% 看似強，但 day-neutralized EV 是 **−1.69%/日**（負的）。它「贏」純粹因為跌勢裡的相對，不是選股技巧。

> **驗證者分離（獨立 fresh-context 子代理，統計方法論類）裁 SOUND-WITH-CORRECTIONS，三個可復現修正全採納**（都讓 buy 看起來**更差**，方向誠實）：①day-neutralize 的 benchmark 原本含 buy 自身→circular，改用 non-buy 宇宙（neu-EV 不再被 (1−buy占比) 往零壓）；②基線 44%→non-buy 47.3%；③DSR 對 T<10 的 cut relabel 成 underpowered，不再冒充「第二透鏡也說沒 edge」。修正後 `uptrend_above_ma20` 由 inconclusive **翻成 certified negative_edge**，追高負 edge 的結論更強。

---

## 全部 14 個 cut 結果（buy n=563，基線 47.3%，K=14）

| setup cut | n | eff_days | 勝率% | day-cluster CI | EV%/筆 | 中性EV%/日 | hit 裁決 | DSR裁決 | **PASS** |
|---|--:|--:|--:|---|--:|--:|---|---|:--:|
| all_buy | 563 | 14.3 | 38.7 | [26.4, 51.7] | −2.39 | −1.71 | inconclusive | overfit | — |
| non_rebuy_bleed | 472 | 14.6 | 37.3 | [25.4, 50.9] | −2.95 | −1.82 | inconclusive | overfit | — |
| rebuy_bleed | 91 | 5.9 | 46.2 | [26.7, 61.7] | +0.46 | +0.50 | inconclusive | overfit | — |
| regime_up | 273 | 7.2 | 23.1 | [14.8, 38.1] | −6.40 | −1.68 | **negative_edge** | underpwr(T<10) | — |
| regime_down | 277 | 6.6 | 56.0 | [41.9, 67.3] | +1.86 | **−1.69** | inconclusive | underpwr(T<10) | — |
| prob_hi≥0.8 | 158 | 7.5 | 33.5 | [14.1, 56.8] | −3.50 | −1.48 | inconclusive | underpwr(T<10) | — |
| prob_lo≤0.4 | 104 | 6.2 | 42.3 | [25.5, 57.4] | −2.68 | −1.54 | inconclusive | underpwr(T<10) | — |
| market_tw | 317 | **15.1** | 42.6 | [28.0, 56.9] | −1.12 | −1.16 | inconclusive | overfit | — |
| market_us | 246 | 11.7 | 33.7 | [21.3, 47.3] | −4.04 | −2.72 | inconclusive | overfit | — |
| oversold_rsi<30 | 7 | 2.9 | 71.4 | [50.0,100.0] | +6.28 | +2.99 | real_edge† | underpwr(T<10) | — |
| dip_pullback≥10% | 199 | 9.3 | 54.3 | [41.1, 64.2] | +1.92 | **+0.84** | inconclusive | overfit | — |
| uptrend_above_ma20 | 404 | 13.5 | 31.7 | [20.8, 46.1] | −4.29 | −2.48 | **negative_edge** | overfit | — |
| uptrend_AND_prob≥0.7 | 242 | 6.8 | 23.6 | [11.3, 43.3] | −5.77 | −2.45 | **negative_edge** | underpwr(T<10) | — |
| dip_in_uptrend | 4 | 4.0 | 25.0 | [0.0, 75.0] | −1.33 | +2.06 | inconclusive | underpwr(T<10) | — |

† `oversold_rsi<30` 的 assess 回 real_edge 是 **n=7 的小樣本假象**（day-cluster CI 沒塌到比 naive 窄，退化閘沒攔）——外層 eff_days≥15 閘正確把它擋掉。這是「單一透鏡會被小樣本騙、多層閘互補」的活例。

**沒有任何 cut PASS。** 唯一 eff_days≥15 的是 `market_tw`（15.1），而它是 null（勝率 42.6% < 基線 47.3%，中性 EV −1.16%）。**三個「追強勢」cut（`regime_up` / `uptrend_above_ma20` / `uptrend_AND_prob≥0.7`）全 certified negative_edge**——這是本表最一致的訊號。

---

## 三個可行動的發現（即使無法 certify）

### 1. ✅ 站得住的閘門：**追高的 buy → 降級 wait**
三個「追強勢」cut 全 **certified negative_edge**：`regime_up`（勝率 23.1% vs 基線 47.3%）、`uptrend_above_ma20`（31.7%）、`uptrend_AND_prob≥0.7`（23.6%）。買強勢、買站上 MA20 的高信心票，在這段期間是**系統性賠錢**——中性 EV −1.7 ~ −2.5%/日，是全表最負。
- 這**不是**單一切片的孤證：它與既有 KPI `edge.chase_high_verdict = negative_edge`（在更大的 1451 樣本稽核上算出）**獨立收斂**。三個彼此重疊但不同定義的 cut ＋ 外部稽核同指一件事，可信度來自匯流而非這 18 天。
- **建議**：buy 訊號若「現價>MA20」（尤其同時 regime==up 或高 prob），降級成 wait。`wait` 本身是系統唯一真 edge（64%），把負 edge 的追高 buy 轉成 wait 是**嚴格佔優**的動作。
- ⚠️ 誠實限制：連這些負 edge 的 eff_days（7–13.5）都不到 15；`regime_up`/`uptrend_AND_prob` 的 DSR 透鏡是 underpowered(T<10)、**無資訊**，負 edge 判定只靠 hit-rate 透鏡＋中性 EV，不是「兩個透鏡都同意」。它站得住是靠「效應量大（15–24 個百分點）＋外部證據印證」，不是這片資料獨立達標。`uptrend_above_ma20`（n=404, eff_days 13.5）是三者中最接近門檻、最可信的一個。

### 2. 👀 唯一值得追蹤的正向假設：**買回檔（dip_pullback≥10%）**
全表唯一「選股力為正」的假設：勝率 54.3%（>基線 47.3%）、EV +1.92%、**中性 EV +0.84%/日**（剝掉 circular flatter 後從 +1.55 降到 +0.84，但仍是全表唯一穩定為正的選股力）。
- 但 eff_days 9.3 < 15、DSR overfit——**現在不可 certify，不准當閘門用**。
- **建議**：列為觀察假設。等帳本再累積 2–3 週（此 subset eff_days≥15 時）**重跑本腳本**。若屆時 hit + DSR 雙過，才是第一個有統計證據的「正 edge buy setup」。方向上它與 #1 一致：**買弱勢（回檔）> 買強勢（追高）**。

### 3. ⚠️ 對帳警訊：rebuy-bleed 閘門（commit c00cf3a）的 −6.96% 幾乎確定是 lookahead 假象
我用**你上線閘門的實際 runtime 條件**（同票 5 日曆日內發過 buy、現價較前次訊號 ≤ −8%）忠實重建，在帳本期間命中 91 個事件。這批的報酬是**中性高變異**，完全不重現 commit 說的「−6.96% 單向續跌、fade t=+10.9」：
- mean chg **+0.46%**、勝率 **46.2%**（反而**接近** 47.3% 基線）、median −0.46%。雙尾分布：巨虧（ONDS −19.8%、AMPX −17.2%、QUBT −14.9%）與巨賺（8996 +39.5%、BE +21.7%、8996 +24.2%）並存——典型「接落刀」高變異，不是確定輸家。
- 驗證者獨立暴力掃 {5,7,10,14 日} × {前次/區間峰值/首次} 全部 ref 定義，**每一種 pre-signal 跌幅定義算出的 mean 都是正的（+0.4% ~ +2.2%）**，沒有任何一種重現 −6.96%。而「−6.96%、t=10.9、n=192」對真實 forward return 在統計上幾乎不可能——**那是「挑已經/即將下跌的 buy」這種 circular / lookahead selection 的特徵指紋**。
- **結論傾向**：commit 的 justification 數字（−6.96%）**很可能是有 lookahead 的診斷產生的假象**，不是閘門真正切掉的 cohort 的表現。建議回頭核對你那份 192 筆診斷的算法（是不是用了「事後知道跌了」去選樣本）。
- **但閘門不必拔**：即使 mean ≈ 中性，這批**下行尾巴極重**，砍掉接落刀式 rebuy 能顯著**降變異/尾部風險**——閘門在**風控**上站得住，只是把它的 justification 從「切除 −6.96% 輸家」改成「切除高變異接落刀、降尾部風險」才誠實。

---

## 給 Delvin 的閘門提案（等你拍板，不會自己改 analyzer）

| # | 提案 | 證據等級 | 動作 |
|---|---|---|---|
| A | **追高 buy（regime up + 站上 MA20）降級 wait** | certified negative + 外部印證 | 可做（低風險，wait 是真 edge）——你點頭我出 analyzer patch + golden 凍結 |
| B | **買回檔（dip≥10%）當觀察假設** | 唯一正向但 underpowered | 不動 analyzer；2–3 週後 eff_days≥15 重跑本腳本再議 |
| C | **rebuy-bleed 閘門 justification 對帳** | 重建不重現 −6.96% | 你核對原始 192 筆診斷定義；閘門暫留（風控理由成立） |

**核心誠實訊息**：目前無法「精準預判哪些 buy 會贏」——18 天太少，任何聲稱正 edge 的 buy 規則都沒有統計基礎。能做的是**precision by subtraction**：砍掉 certified 賠錢的追高 buy（→wait），並持續累積資料等回檔假設達標。這比硬湊一個過擬合的「買進訊號」誠實得多，也才是真正的「精準」。

---

## 驗收對照（backlog P1.7 驗收條件）
- 「OOS 勝率/EV 顯著優於 49.3%/−0.03% 基線」→ **無任何 setup 達標**（誠實結論：這 18 天資料不支持任何正 edge buy 閘門）。
- 「walk-forward OOS、固定門檻不掃參、DSR 檢驗」→ ✅ 預先登記固定 cut、day-neutralized DSR、eff_days 閘、episode fragility 全上。
- 「驗證者分離」→ 見本輪 log（統計方法論類，已開獨立驗證者）。
- 「不准直接改 analyzer，先出報告等拍板」→ ✅ 純報告。

---

## 提案 A 上線登記(2026-08-03 補登,Delvin 已拍板)
- **上線日:2026-07-21**(dq-519171bfa5)。實作=`analyzer._pp_uptrend_chase_gate`:
  `regime==risk_on 且 price>MA20` 的 buy 卡降級 wait(chip 換「⚪ 觀望·多頭市況勿追強勢(回檔再進)」,
  帶 `<!--gated:buy:uptrend_chase-->` 反事實標記;holder 卡經 `_pp_holder_wording` 換防守語)。
  無 lookahead:只用訊號日當天 price/MA20/VIX/指數漲跌,口徑同本報告。
- **行為凍結:`scripts/test_uptrend_chase_gate.py`**(8/8 綠,2026-08-03 複驗)——降級語意、
  regime 條件、techs 缺席 fail-open、gated 標記契約全鎖;refactor_harness golden 亦綠。
- **效果驗證機制(rotation_pairs 同款,已自動接線)**:`build_track_record.py` 的
  `gate_effect` 反事實雙軌結算(shown vs blocked 勝率,隨 track-record cron 每日重算,
  見 docs/data/track-record.json stats.gate_effect)。閘門一開火即自動累積樣本,無需人工記帳。
- **2026-08-03 現況(誠實)**:上線至今 **0 次觸發**——查 intel/regime_ledger.jsonl,07-21 起
  無任何一天 risk_on(全 neutral,僅 07-24/07-30 risk_off)。零觸發=市況使然非接線 bug
  (同期 chase/crash/autogate 閘皆有開火紀錄,存檔標記機制正常)。首個 risk_on 日自然生效。
