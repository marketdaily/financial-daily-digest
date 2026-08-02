# 工程技術寫作週更線 — 12 週內容日曆

主軸(來自創業分析結論):Delvin 的真資產=「讓 LLM 在高風險、有稽核需求環境下輸出可驗證結果的可靠層」。每篇皆中英雙稿(英文版獨立重寫、HN 風格),所有數字先過 facts_sources 查證,紅線同第一篇(no_fake_numbers / 不提個資、key、營收 / 分析內容永不與付費掛鉤)。

| 週 | 日期(週六) | 題目 | 素材出處(repo 真源) |
|---|---|---|---|
| 1 | 2026-08-02 | LLM council + judge:多模型仲裁系統 75 天實錄(本篇,已完稿) | `analyzer.py` council 區、`digest_audit.py`、`main.py` `_audit_with_retry` |
| 2 | 2026-08-09 | Audit 失效模式分類學:31 項檢查,每項都是一次用戶生氣換來的 | `digest_audit.py` 全檔、memory 事故群、大綱見下 |
| 3 | 2026-08-16 | 資料隔離事故報告:公版觀察清單怎麼混進「你的持股」 | `digest_audit.py:491-508`、大綱見下 |
| 4 | 2026-08-23 | 開源發布文:把 council+judge+audit 抽成可重用的最小可靠層 | 第 1-3 篇的機制彙整;發布 repo 需先過 secret 掃描與老闆拍板 |
| 5 | 2026-08-30 | 免費層 LLM 產能工程:TPM vs TPD、配額桶隔離、晚報保留桶 | `analyzer.py:570-668` `_llm_generate` 註解群(TPD 200,000/197,364、保留桶設計)、memory `capability_free_llm_capacity_sourcing` |
| 6 | 2026-09-06 | 確定性修復層:不靠 LLM 聽話的五道後處理防線 | `main.py:84-260`(`_repair_undefined_classes`、`_escape_stray_lt`、休市措辭、晨間/今晚動作窗口注入) |
| 7 | 2026-09-13 | LLM pipeline 的三層熔斷器:席位級、模型級、系統性 | `analyzer.py` `_COUNCIL_SEAT_DEAD`/`_GEMINI_QUOTA_DEAD`、`main.py` `_push_systemic_alert`、memory `project_council_check_red_fix` |
| 8 | 2026-09-20 | 雙寄事故:當兩個備援系統都盡責地寄了信 | `CLAUDE.md` 雙寄防線段、`scripts/test_dupe_delivery_guard.py`、memory `project_digest_dupe_send_root_fix`(07-30 21 位每人收兩封) |
| 9 | 2026-09-27 | 「格式全對、內容是渣」:幫 LLM 輸出深度做統計基線 | `digest_audit.py:263-283` `signal_reason_shallow` 校準史(median 107–197 vs 48) |
| 10 | 2026-10-04 | 一個 0x11 控制字元,讓我們的 email CSS 從未真正內聯過 | `main.py:73-78` 註解、memory `project_premailer_inlining_fix` |
| 11 | 2026-10-11 | 跨用戶 LLM 快取:理論去重 59%,實測只有 41%,差額去哪了 | `analyzer.py:2626-2642` `_CARD_XUSER_*` 註解(236 欄位/97 標的實測)、memory `project_zero_marginal_cost_digest` |
| 12 | 2026-10-18 | 測試裡寫死「今天」的代價:同一個坑復發六次的完整病歷 | memory `harness_golden_live_data_drift`(六度復發)、`capability_date_literal_lint`(日期字面值掃描器) |

備註:
- 第 4 週開源發布文依賴「開源 repo 已就緒」,若未就緒則與第 5 週對調,發布文順延。
- 每篇動筆前重跑該篇數字的查證指令,facts_sources.md 逐篇追加章節(單一真源檔,不分裂)。

---

## 第 2 篇大綱:〈Audit 失效模式分類學:31 項檢查,每項都是一次用戶生氣換來的〉(約 300 字)

把 `digest_audit.py` 的 31 項檢查按失效模式分五類解剖:(1) **時序紀律**——盤前寄的信不能寫完成式,「今早 9:00 開盤」在休市日是謊言;(2) **編造偵測**——佔位符 XXX、假網址、資料端沒有卻寫出「預期 EPS」的無中生有;(3) **覆蓋契約**——用戶選的每支持股都要有操作卡,漏一支即 HIGH;(4) **結構完整性**——輸出截斷、未定義 CSS class、prompt 指令洩漏進成品;(5) **深度與一致性**——理由塌陷統計檢查、全卡同向卻喊觀望的自相矛盾、超出校準上限的信心數字。核心論點:每項檢查都標注它誕生的那次事故日期,展示「出事 1 次=當場建偵測器」的紀律;並誠實解剖兩個反例——檢查自己引發事故(07-06 undefined_css_class 全員降級)與檢查誤殺(07-24 把年份、指數點位當外來股票代號,逼老闆連吃兩版備援),導出「新增 HIGH 檢查前必問:全員同中會怎樣、誤殺誰來扛」的設計準則。

## 第 3 篇大綱:〈資料隔離事故報告:公版觀察清單怎麼混進「你的持股」〉(約 300 字)

2026-07-21 事故完整還原:「組合透視」區塊掛著「你的」字樣,卻混進公版 default_us 觀察清單 10 檔——市場配置憑空多出美股 10 檔、DCF 偏貴列的全非用戶持股。個人化系統最尷尬的失敗:資料沒外洩給別人,是公版資料洩進了個人視角,用戶對系統「懂我」的信任瞬間歸零。修法三層:鐵則化(掛「你的」的區塊,標的必須完全來自傳入的真實持股)、audit 新增 `portfolio_lens_foreign_ticker` HIGH 檢查、fallback 不准偷偷把通用版當個人化版寄。第二幕講防線自身的代價:該檢查初版把「像代號的 token」一律當外來標的,年份(2026)、指數點位、名詞縮寫(AI/GDP/ETF)全被誤殺,07-24 連 retry 兩版都被殺、整封降備援——最終解是「必須是真實上市證券才算外來」:台股比對 12k 代號表、美股比對名稱庫。結論:個人化區塊的隔離要靠白名單契約,而契約的例外清單要用真實 universe 而非啟發式。
