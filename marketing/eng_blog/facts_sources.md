# facts_sources — 稿件所有數字/事實的出處對照表

規則(no_fake_numbers 紅線):文章中每個數字必須在此表有一列「數字 → 出處檔案路徑或可重跑指令」。查證不到的數字不准出現在稿件。
本表涵蓋:`2026-08-02_council_judge_zh.md` / `_en.md`(第 1 篇)與 `2026-08-06_audit_taxonomy_zh.md` / `_en.md`(第 2 篇,章節見文末)。

## 時間軸 / 規模

| 數字/事實 | 出處 |
|---|---|
| 首 commit 2026-05-19「初始化財經日報系統」 | `git log --reverse --format="%ad %s" --date=short \| head -1` |
| 生產 75 天(2026-05-19 → 2026-08-02 含首尾) | 由上列首 commit 日期與本文寫作日(2026-08-02)計算 |
| 1,800+ commits(實際 1,802) | `git log --oneline \| wc -l` → 1802 |
| council 上線 2026-06-30;至 08-02 為 34 天;= 首 commit 後第 42 天 | `git log --reverse` 中 commit「2026-06-30 feat(digest): 個股決策改 AI 委員會(多模型辯論)非純 fallback」 |
| audit 層自 2026-05-26 起 | `git log --format="%ad %s" --date=short -- digest_audit.py \| tail -1` → 「2026-05-26 feat(digest): user-perspective auto-audit before send」 |
| 每天兩班(台股早 07:00 / 美股晚 20:00 整點寄出) | `main.py:19`(tw/us/both 班次註解);`CLAUDE.md`「日報整點寄出」段 |
| 21 位訂閱者 | `analyzer.py:2627` 註解「21 位訂閱者持股高度重疊」 |

## Council / Judge 機制

| 數字/事實 | 出處 |
|---|---|
| 9 個免費席位(gemini×2、groq、local、cf×2、openrouter、cerebras、openai) | `analyzer.py:2653-2682` `_COUNCIL_SEATS` 清單(9 個 tuple) |
| 橫跨 7 家供應商;沒 key 的席位自動跳過 | 同上清單(Google/Groq/本地/Cloudflare/OpenRouter/Cerebras/OpenAI);`analyzer.py:2678`「預接線:沒 key raise→席次自動停用」 |
| 常態約 5 把獨立聲音 | `analyzer.py:2685` 註解「免費席仍有 gemini×2/groq/local/cf 五把獨立聲音」 |
| 另有 2 席付費 Claude 為 opt-in(文中未寫數字,備查) | `analyzer.py:2687-2691` |
| quorum:席位意見 <2 不成會 | `analyzer.py:2781` `if len(opinions) < 2: return None` |
| 方向由結構 prior(價 vs MA20 vs MA50)鎖死;席位違向降 neutral | `analyzer.py:2749-2751, 2769-2773` |
| dissent 分 0/1/2 三級並回饋信心 | `analyzer.py:2783-2790`;`analyzer.py:2618-2619` 註解 |
| judge 鏈:gemini-2.5-flash-lite → groq → 最高信念席位 | `analyzer.py:2694-2700` `_council_judge_call`;`analyzer.py:2804-2806` 最高 conviction fallback |
| 席位熔斷:連敗 3 次停用;402 首刀斃命 | `analyzer.py:2709-2712` `_COUNCIL_DEAD_MARKERS` 註解、`analyzer.py:2725` |
| council fail-safe 絕不擋寄信 | `analyzer.py:2812-2813` docstring |
| 每支股票每輪只跑一次、跨用戶共用快取 | `analyzer.py:2619` 註解、`_COUNCIL_CACHE` |
| Gemini 席位刻意用 lite/2.0,把 2.5-flash 留給卡片 | `analyzer.py:2623-2624` 註解 |
| 本地 GPU 席位零配額零 429、全雲端斷線唯一活口 | `analyzer.py:2666-2668` 註解;`analyzer.py:626-628` |
| 本地模型為 14B(qwen2.5-14b) | `analyzer.py:2668` 席位名 `local:qwen2.5-14b` |
| qwen3.6-27b 把 385.25 改寫成 385.00 → 禁入生卡鏈、只准進 council | `analyzer.py:610-611` 註解;`analyzer.py:2661-2662` 註解 |
| 信心顯示校準上限 75%,>75 = 防線破口 | `digest_audit.py:403-408`(check `confidence_overclaim`) |

## Audit / retry / fallback

| 數字/事實 | 出處 |
|---|---|
| 31 項獨立命名檢查 | `grep -o '"check": "[a-z_0-9]*"' digest_audit.py \| sort -u \| wc -l` → 31 |
| 早上 7 點不准寫「今天台股已漲」;台股 9:00 開盤 | `digest_audit.py:146-155`(check `tw_pre_market_tense`) |
| HIGH fail → 等 60 秒再 retry(TPM 窗口) | `main.py:914-918`(sleep(60) 與 Groq TPM 註解) |
| retry 強制換更強模型(prefer_strong) | `main.py:919-920`;`analyzer.py:574-577` |
| 仍 fail → deterministic fallback,刻意不含價位 | `main.py:943-949`;`digest_audit.py:218-219` 註解「fallback 卡刻意不給價位以免誤導」 |
| 同一 HIGH check 連中 3 位用戶 → 系統性告警 | `main.py:909-912`(`systemic_high_counts[_c] == 3`)、`main.py:1522-1526` `_push_systemic_alert` docstring |
| prompt 指令洩漏檢查(「台股講…美股講…」抄進成品) | `digest_audit.py:285-309`(check `prompt_instruction_leak`) |
| 佔位符 XXX / 假網址 / 編造預期 EPS 檢查 | `digest_audit.py:359-381`(checks `fake_urls`、`placeholder_prices`、`earnings_fabricated_estimates`) |

## 事故一:429(2026-06-11)

| 數字/事實 | 出處 |
|---|---|
| Gemini 429 退避每呼叫白燒 ~100 秒 | memory `project_digest_20260611_429_incident.md`:「原本 429 重試 4 次×睡 12s…每呼叫白燒 ~100s(兩模型)」 |
| 日報遲到 5 小時(09:59 寄出、11/11 全寄) | 同上 memory:「正式班最終 success(09:59 TW,遲 5 小時,11/11 全寄)」 |
| 修法:單模型連續兩次 429 = 配額死亡熔斷 | 同上 memory:「單模型連續兩次 429 = 配額耗盡 → `_GEMINI_QUOTA_DEAD` 熔斷」 |

## 事故二:CSS class(2026-06-29 / 2026-07-06)

| 數字/事實 | 出處 |
|---|---|
| 06-29 版型跑掉、補 16 個 LLM 改名 class | commit「2026-06-29 fix(digest): 補 16 個 LLM 改名 class 的 CSS…」(`git log --date=short`) |
| 06-29 新增 `undefined_css_class` HIGH check | commit「2026-06-29 feat(digest): 版型守門—audit 加 undefined_css_class high check…」 |
| 07-06 週一版 12/12 用戶全中、9 位被打成 fallback | memory `project_digest_monday_css_incident.md`;`main.py:84-86` 註解「12/12 打成 deterministic fallback」(全中 12 位、其中 9 位最終降級,見 memory) |
| 事故間隔一週(06-29 → 07-06) | 上列兩 commit 日期相減 |
| 修法:premailer 前確定性修復層(近似名對映+未知 class 移除) | `main.py:84-111` `_CLASS_ALIASES` / `_repair_undefined_classes` |
| 「逐字骨架才是規格」「HIGH check 全員同中」兩教訓 | memory `project_digest_monday_css_incident.md` Why 段 |

## 事故三:深度塌陷(2026-07-23)

| 數字/事實 | 出處 |
|---|---|
| reason 從 129–165 字塌到 48–64 字(-60%) | `analyzer.py:630-631` 註解「reason 從 129-165 字塌到 48-64 字(-60%)」 |
| 用戶(老闆本人)親自抓到而非機器 | `digest_audit.py:263-265` 註解「用戶親自抓到而非機器」 |
| 校準:正常日(07-20~22,3 天)median 107–197、min≥97;壞日 median 48 | `digest_audit.py:264-266` 註解 |
| 門檻:median <80 或半數 <60 判定塌陷 | `digest_audit.py:279-283`(check `signal_reason_shallow`) |

## 免費層配額工程(EN 版)

| 數字/事實 | 出處 |
|---|---|
| Groq 免費層 TPM 8,000 | `analyzer.py:2656-2657` 註解「免費層 TPM 只有 8000」;memory 索引「council天天紅根治—Groq TPM僅8000」 |
| Groq 每模型每日 TPD 200,000;council 吃掉後剩 197,364 已用 | `analyzer.py:592-594` 註解「TPD 200,000 已用掉 197,364」 |
| 45 次呼叫掉到 openrouter 550b、144s/次、拖 108 分鐘、日報遲到 1h35 | `analyzer.py:594-595` 註解;`analyzer.py:2659-2661` 註解 |
| council 席位與生卡鏈刻意用不同 Groq 模型(配額桶隔離) | `analyzer.py:2659-2663` 註解(07-30 換桶 #18) |

## 刻意不寫進文章的(合規/紅線自查)

- 訂閱者 email、姓名等個資:未出現。
- API key / token / secret 名稱與值:未出現(僅泛稱「沒 key 自動跳過」)。
- 營收 / 金流:未出現。
- 個股分析與付費掛鉤:未出現(文章不提任何付費方案)。
- 原任務標題的「跑了一年」:**查證不成立**(git 首 commit 2026-05-19,僅 75 天),依 no_fake_numbers 紅線改為「75 天實錄」,並於兩稿內文明示 council 層自 06-30 起(34 天)。

---

# 第 2 篇:〈Audit 失效模式分類學〉(2026-08-06_audit_taxonomy_zh/en.md)

## 檢查數量與 severity 分布(本篇核心事實)

| 數字/事實 | 出處 |
|---|---|
| 真實可觸發檢查 = 30 項 | `grep -c 'fails.append' digest_audit.py` → 30 |
| grep 數出 31 = 30 + docstring 幽靈 `tldr_has_tw` | `grep -o '"check": "[a-z_0-9]*"' digest_audit.py \| sort -u \| wc -l` → 31;幽靈在 `digest_audit.py:7`(docstring 用法範例,真名是 `tldr_missing_tw`) |
| 20 項固定 HIGH、6 項固定 MED、2 項 LOW、2 項動態 | `grep -o '"severity": "[a-z]*"' digest_audit.py \| sort \| uniq -c` → high 21/med 7/low 2;其中 `tldr_too_short`(`digest_audit.py:199-200` high↔med)與 `verdict_monoculture`(`digest_audit.py:397-398` med↔low)為動態,各從 high/med 扣 1 |
| severity 語義:HIGH → sleep(60)+換強模型 retry → 仍敗切 deterministic fallback;MED/LOW 照寄 | `main.py:888-889` docstring、`main.py:913-920`(sleep(60)+prefer_strong)、`main.py:942-949` |
| 60 秒=等滿一個 TPM 窗口(5s retry 必再撞 429);07-27 八位掉 deterministic 的共犯 | `main.py:914-917` 註解 |
| fallback 卡刻意不給價位、audit 對 fallback 卡豁免三件套檢查 | `digest_audit.py:218-224` 註解 |
| battle-row 進場/目標/停損「三件套」 | `digest_audit.py:228`(`card.count("battle-row") < 3`) |

## 各檢查誕生日期(表格與內文引用,全部來自 digest_audit.py 檢查旁註解)

| 數字/事實 | 出處 |
|---|---|
| 05-26 holdings_uncovered 創始契約,用戶原話「使用者選擇每一個台股美股都要顯示下一步」 | `digest_audit.py:234-235` 註解;audit 首 commit 2026-05-26(見第 1 篇章節) |
| 06-10 實質稽核三連:AAPL 預期 EPS 3.60 vs 真實 1.86+「iPhone 15 仍是重點」/四張卡全「即刻分批買進」vs 結論「先觀望等 CPI」/標題「油價反彈 1.10%」內文「反而下跌」 | `digest_audit.py:374-375`、`digest_audit.py:383-384`、`digest_audit.py:416` 註解 |
| 06-25 「金額高達 XXX 億元」佔位符洩出 | `digest_audit.py:367` 註解 |
| 07-09 certifi 過期→TPEx SSL 靜默失敗→名稱表全滅→主旨+卡片裸代號寄出 | `digest_audit.py:350-353` 註解 |
| 07-11 一位訂閱者週末版 TLDR 0 條 bullet(區塊全空)實鍋 | `digest_audit.py:198` 註解(稿內不寫訂閱者名) |
| 07-15 TW_MORNING_ACTION_RE 假陽性(「9:00開盤」3 字元間隔吃不下)+價格「以1090開盤」誤認時間(驗證者第14案) | `digest_audit.py:18-22` 註解 |
| 07-22 prompt 指令洩漏:每張卡開頭「白話講『下一步』:台股講…美股講…該做什麼具體動作」 | `digest_audit.py:285-287` 註解 |
| 07-23 深度塌陷校準:正常 3 日 median 107–197/min≥97/零卡<80;壞日 median 48/min 46/5/7 卡<60;門檻 median<80 或半數<60 | `digest_audit.py:263-266` 註解、`digest_audit.py:279-283` |
| 信心校準上限 75%,>75=防線破口 | `digest_audit.py:403-408` |
| 07-21 組合透視混入公版 default_us 觀察清單 10 檔 | `digest_audit.py:491-494` 註解 |
| 07-24 誤殺:年份(2026)/指數點位(23150)/價位(1085)/縮寫(AI/GDP/CPI/ETF)全被當外來標的,老闆連 2 版被誤殺→備援 | `digest_audit.py:30-36` 註解 |
| 誤殺根治=真實 universe:台股 ~12k 代號快取+美股名稱庫 | `digest_audit.py:34-36` 註解(「12k 代號」)、`_is_real_ticker`(`digest_audit.py:59-66`) |

## 07-06 undefined_css_class 事故完整 timeline

| 數字/事實 | 出處 |
|---|---|
| 06-29 補 16 個 LLM 改名 class 的 CSS+同日新增 undefined_css_class HIGH check | commits「2026-06-29 fix(digest): 補 16 個 LLM 改名 class 的 CSS…」「2026-06-29 feat(digest): 版型守門—audit 加 undefined_css_class high check…」(`git log --date=short`) |
| 07-06=檢查上線後第一個週一;週一 prompt 只寫「沿用平日 CSS class」沒逐字骨架,平日 prompt 有骨架所以平日沒事 | memory `project_digest_monday_css_incident.md` 根因鏈 1-2 |
| 12/12 用戶全中;retry 同 prompt 同病;9 位被打成 deterministic fallback | 同上 memory 根因鏈 2;`main.py:84-86` 註解 |
| admin 彙總告警 07:24 送達(寄完才知道) | 同上 memory 根因鏈 3 |
| 05:30 preflight 已隨排程遷移靜默死近一個月 | 同上 memory 根因鏈 4 |
| 修法:premailer 前 `_repair_undefined_classes`(12 個近似名對映+未知 class 移除=視覺 no-op) | `main.py:84-111`;`_CLASS_ALIASES` 12 條對映(`main.py:90-103` 逐行數) |
| 系統性熔斷:同一 HIGH check 連中 3 位→立即推 admin,趕在整點寄出前;寄送不擋 | `main.py:905-912`;修復 commits 7b9735c+9a622cd(memory 同檔) |

## 軟硬錯分級與 MED 修復層

| 數字/事實 | 出處 |
|---|---|
| 07-24 老闆親令「絕對不要再看到閹割版」→ 軟錯={signal_reason_shallow, signal_reason_vague, tldr_too_short} 三項,其餘皆硬錯 | `main.py:866-871`(`_SOFT_HIGH_CHECKS`) |
| #15 tw_morning_action_missing:07-13/17 實鍋 5 封,MED 不觸發 retry→確定性改寫層根治,regex 兩邊共用 | `main.py:159-168` docstring(「07-13/17 實鍋 5 封」「TW_MORNING_ACTION_RE 兩邊共用」) |
| #14 us_tonight_action_missing:07-27 起三天 11/7/11 位失分→07-29 鏡射修 | `main.py:209-218` docstring |

## 刻意不寫進第 2 篇的(合規/紅線自查)

- 訂閱者姓名/email:07-11 TLDR 空區塊與 07-22 洩漏案的源註解含用戶名,稿內一律改「一位訂閱者/用戶」。
- 「31 項」對外口徑:第 1 篇已發布的 31 不改稿,本篇正面更正為 30+1 幽靈並附兩條可重跑指令,標題保留 31 作為敘事鉤。
- 個股買賣建議、付費方案、營收、key/token:未出現。
