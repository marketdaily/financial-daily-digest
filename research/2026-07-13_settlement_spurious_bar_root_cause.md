# 戰績結算「偽 bar 窗口平移」根因定案 + 防線（2026-07-13 深攻輪）

## 一句話
戰績帳本 9 筆 06-29/07-01 建議的 label 凍錯，**不是**先前假設的「美股除息回溯調整」，
而是**首判結算時 Yahoo 在個別檔 feed 塞了偽 bar（美股 07/04 觀察日 07/03），
`fetch_prices` 用 `sorted_dates[ref_idx+N]` 純位置索引取結算價 → 窗口整段早一交易日 →
錯結算價被 judge 首判「凍死」進 label 永不自癒**。Yahoo 事後清掉偽 bar，
2026-07-12 backfill 才拿到正確窗口、發現與凍結 label 不一致（= 帳本標籤新鮮度偵測器的 9 筆 allowlist）。

## 為什麼先前的「除息」假設是錯的
- 9 筆 ticker：NVDA/BE/TSLA/GENB（06-29）、AMZN/META/MU/NOW/PLTR（07-01）——多數不配息，
  位移 0.2~4.1% 遠超任何股息率。驗證者 07-12 已證偽，但當時只留「疑 Yahoo bar 增刪」未定案。

## 決定性證據鏈（皆可重跑，offline 用 scripts/.price_cache.json）
1. **現行 cache 窗口正確**：06-30 存在、無 07-03 偽 bar，06-29→+5=07-07、07-01→+5=07-09（逐日核對）。
2. **backfill chg = 現行 cache 重算 chg（byte-for-byte 全 9 筆 SAME）** → backfill chg 用的是**正確窗口**。
3. **凍結 label 與正確窗口導出的 label 全部不一致** → 錯的是凍結 label，不是 backfill chg。
4. **6/9 恰好匹配「早一交易日」窗口**（06-29→07-06、07-01→07-08）：BE/GENB/TSLA/AMZN/META/NOW ——
   6 檔獨立 ticker 同時命中同一位移 = 巧合機率極低 → 首判時確有一個 +1 位置的偽 bar（07-03）。
5. **3/9（NVDA→07-02、MU→07-01、PLTR→~07-01）結算更早**：個別檔 feed 偽 bar 更多，
   首判窗口平移更大（無法逐位復現，因 Yahoo 已清該檔偽 bar，屬強推論非重現）。
6. **偽 bar「對美股偽、對台股真」的活證據 STILL 在 cache**：07-03 在 40 檔台股 = 100%（台灣 07-03 有開市），
   在真美股 = 0%。這證明**任何 bar 濾網必須分市場**，否則會誤刪台股的合法 07-03。

## 機制（為何會「凍死」）
- `judge()` 在 `close_5d` 第一次可得時把 label 定死；`append_personal_ledger` 對既有 key idempotent，
  **首判後永不重算 label**。所以首判若踩到偽 bar → 錯 label 凍死一輩子。
- 影響面**不只這 9 筆**：任何結算窗跨假期、又碰上 Yahoo 個別檔偽 bar 的建議，都會被凍錯。
  假期每季都有 → 這是會**每季復發**的公開戰績正確性漏洞。

## 修法（已上線，behavior-preserving）
`scripts/build_track_record.py::fetch_prices` 改兩 pass：先集齊全檔歷史 → 算「同市場多檔共識交易日」
→ 濾掉個別髒 feed 的偽 bar 再做位置索引。
- **市場分群 `ticker.isdigit()`**：台股全數字（含 5-6 位 ETF 006208/00878，`yf_symbol` 的 4 位判斷漏掉的）、
  美股全字母。**不寫死假期表**（會過期，harness_golden_live_data_drift 前科），**自更新**。
- **偽 bar 判準**：某日在該市場占比 ≤15% **且夾在兩個「占比 ≥60% 的真交易日」之間**（防誤刪稀疏上市邊界）。
- **安全退回**：市場檔數 <5 不濾（共識不可靠時退回原行為）。
- **可見性**：濾掉時印 `[settle-guard] drop spurious bar {ticker} {date} (market freq X%)`。

## 驗證
- **離線 A/B（HEAD vs 工作樹）**：1032 ledger keys 的 fetch_prices 輸出 **byte-for-byte IDENTICAL**
  （現行 cache 乾淨 → 掉 0 bar → 現行公開數字零變動）。
- **合成自測** `capabilities/tests/settlement_spurious_bar_guard.test.sh`（12 檢查全過）：
  偽 07-03 被濾（06-29+5 從錯的 07-06 修正到 07-07）、台股共享 07-03 保留、<5 檔不濾、稀疏邊界不誤刪、
  fetch_prices 端到端 close_5d 濾後與 clean 檔一致。
- 相依測試無回歸：ledger_label_freshness / test_baseline_regime_conditioning / build_track_record_calibration 全綠。

## 待 Delvin 拍板（未擅自做）
既有 9 筆凍錯 label 是否改寫成 backfill chg 導出的正確值——**動公開戰績勝率**（net ≈ −5 win / 1451 ≈ −0.3pp）
且**反 P1.5「首判凍結、drift 留白可見」設計**。技術上 backfill chg 已驗證權威（正確窗），
但屬對外可見資料變更，不擅自動；共識濾網已擋未來復發，這 9 筆是歷史殘留，可等下次規則 bump 順手遷移。

## 泛化教訓
1. **「純位置索引取第 N 個」對外部序列的完整性是脆弱的**——資料源偶發增刪一個元素，整段語意平移。
   凡「用 index+N 當日曆」都要問：這個序列會不會被上游偷偷改？（同類：off-by-holiday、path_dates 切片）
2. **首判即凍結 + idempotent = 把首次的資料瑕疵永久化**。凍結是對的（防 drift），
   但凍結的東西若可能來自瞬時髒資料，就需要「穩定後才凍」或「凍事實(chg)＋可重導」——後者 P1.5 已做，
   只是這 9 筆凍在 chg 欄存在之前。
3. **跨實體共識是免假期表的日曆校正法**：真交易日全市場近 100%、偽 bar 只在個別 feed；
   分群鍵要選對（isdigit 勝過 yf_symbol 的 4 位 regex）。
