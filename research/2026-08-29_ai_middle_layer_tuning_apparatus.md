# AI 金字塔「中間層」= 調校裝置(tuning apparatus)——reel 拆解 + 可開創的事業線

源:https://www.instagram.com/reel/DcgYKgmD10z/(@heystevetan,2026-08-26 發,77 秒英文口播,1,135 讚/12 留言,video-watcher 實看:54 格 + Groq whisper 雙流)
老闆交辦(2026-08-29):「學這支,中間層到底是什麼、我們能做什麼——不必綁現有資產,可以自己創造資產」

## 一、他到底說了什麼(frames + transcript 合併,只報真的看到/聽到的)

| 秒 | 畫面 | 口播 |
|---|---|---|
| 0–3 | Sam Altman 戴白墨鏡對 Bloomberg 麥克風 B-roll,黃字「this BILLIONAIRE just told you / solid ADVICE」 | 「這個億萬富翁剛告訴你怎麼變有錢,而且是真的好建議」 |
| 3–9 | **Greylock 講台**(背板 greylock 字樣,Reid Hoffman 同台)Sam 原聲 | 「會有一整批新創,拿未來一個現成的超大模型去 tune 它」 |
| 10–20 | 黑底金線三層金字塔:Bottom Layer=ChatGPT+Claude logo / Middle Layer(**全片沒放任何品牌**)/ Top Layer=兩個 app icon(綠底波浪 + 白底星芒,**未能辨識,gap**) | 「底層是通用大模型,頂層是 wrapper 與應用,Sam 認為中間層才是大機會」 |
| 21–34 | B-roll:某自動化工具 UI(Instructions「Search the web for competitors of AllDevNeeds.com…輸出表格」/ Runs: All·Scheduled·Manual·API·Webhook)、Claude Research 對話(「best AI model to generate videos」→ Seedance 2.0 / Veo 3.1 / Kling 3.0 / HappyHorse 1.0 / Sora 2 / Gen-4.5 / LTX-2.5 / Wan 2.7)、金字塔頂層 icon 拉線接 API | 「底層模型適合研究/寫作/簡單自動化;頂層 wrapper 用 API 把特定任務做得比通用模型好一點」 |
| 34–40 | 黃字「NOT A GOOD moat」;白紙上一行「**Fable / Opus / Sonnet / Haiku**」;紅方塊吃掉黑圓的動畫 | 「這不是好護城河:下一代更強的底層模型一出,就吃掉原本需要你 wrapper 的任務」 |
| 40–62 | 紅色「Claude」機器人玩具 → 藍色「Tuned」機器人;黃字 MEDICINE;交易室螢幕 B-roll;再一次「Fable/Opus/Sonnet/Haiku」;紅點陣列;紅「Tuned」機器人;黃字 ACCUMULATED;「STRONGER LLM」紅機器人 / 「BETTER RESULTS」藍機器人 | 「別再做 wrapper,做 tuning:把現成 LLM 調向醫療/房地產/資產管理等領域。下一代底層模型出來你要重調,**但你的資產從來不是那顆調好的模型,是你日積月累的 tuning apparatus**。更強的底層=更強的基底,調完更好」 |
| 62–68 | Thinking Machines 官網(標題「**Inkling: Our Open-Weights Models** NEW」)+ CNBC 2025-07-15「Mira Murati raises $2 billion」 | 「Mira Murati 的 Thinking Machines 就在這個角落,已募 20 億美元」 |
| 68–74 | 金字塔全景;換到書桌場景(彩色塗鴉牆) | 「這是 AI 裡唯一還沒擠爆的空間,如果你在找那個黃金機會,可能就是它」 |
| 74–77 | 黃色 FOLLOW 按鈕動畫 | 「追蹤看更多」——**沒有留言閘門**(12 則留言 / 1.06%,對照留言閘門片 J 70%、N 221%) |

caption(全文撈到)比口播嚴謹:把 tuning apparatus 明寫成「**your data, evaluations, workflows, domain expertise, and feedback loops**」,並把口播的「唯一沒擠爆的空間」軟化成「opportunity isn't necessarily another wrapper… a much harder moat to copy」。

### honest-extraction 註(這支片沒說、但看片/查證後必須知道的)
1. **Sam 那段話是 2022-09-13 Greylock「AI for the Next Era」講的**(greylock.com 原文可查),不是「剛說」——快四年前。原句更完整:「tune it, **which is not just fine tuning, all of the things you can do**」——Sam 的中間層比「微調」寬:微調只是其中一種手段,重點是「拿現成大模型做成專用版本 + 自己的 data flywheel」。reel 把它窄化成 tuning。
2. Thinking Machines 事實核對:2025-07 種子輪 $2B(估值 $12B)✅;2025-11 想以 $50B 募 $5B,2026-01 談判破局(未募到);2026-07 發 **Inkling**(開源權重,975B MoE/41B active/1M ctx);主力產品 **Tinker** = LoRA 微調 API,20+ 開源模型(Qwen/Nemotron/DeepSeek/Kimi/GPT-OSS/Inkling,4B–550B),按 token 計價、checkpoint $0.10/GB-月。→ 它同時做底層(自己的模型)與中間層(Tinker),**不是純中間層公司**,拿它當「中間層被驗證」的證據只對一半。
3. 「唯一沒擠爆」是意見不是事實:微調**基礎設施**(OpenAI fine-tune/Together/Fireworks/Predibase/Unsloth/Tinker)已經很擠;沒擠的是「**某一個垂直領域**的資料+評測+回饋迴路」——這才是 caption 那五樣東西。
4. 金字塔頂層兩個 icon 與 B-roll 自動化工具皆未辨識(gap);Claude/Tuned 機器人為道具 B-roll,無產品意義;「Fable/Opus/Sonnet/Haiku」白紙是 Anthropic 現役四階模型名,用來表達「下一代會一直來」。

## 二、中間層到底是什麼(我的綜合,標 inference)

**中間層 = 讓通用模型在一個領域變得「異常好」的那套可重跑的裝置**,由五個零件組成,而且**前三樣與底層模型無關**:

| 零件 | 內容 | 底層換代後還在嗎 |
|---|---|---|
| ① 領域資料 | 私有、有標註、持續更新的 domain 資料(不是網路上抓得到的) | ✅ 還在,而且更多 |
| ② 領域評測(eval) | 「在這個領域什麼叫做好」的量尺——一套題+判準+黃金答案 | ✅ 還在,這是最難抄的一樣 |
| ③ 回饋迴路 | 生產結果→標註→下一輪資料(data flywheel) | ✅ 還在,越跑越厚 |
| ④ 訓練配方 | SFT / LoRA / DPO / RL 的 recipe、超參、資料混比 | 🔁 要重跑,但配方可沿用 |
| ⑤ 領域工作流 | 檢索、工具、守衛、輸出格式 | 🔁 部分重接 |

wrapper 與中間層的分界線只有一條:**你有沒有一份「越用越好、換模型也不歸零」的資料+評測**。有=中間層;沒有=wrapper,再多 prompt 都是 wrapper。

反面(必須誠實寫):frontier 模型 + 長上下文 + RAG 在很多任務上已追平小型微調模型,所以「那顆 LoRA」本身沒有價值,價值只在 ①②③。做這行的人要把自己想成「**資料與評測公司**」,不是「模型公司」。

## 三、我們能做什麼(不綁現有資產,三條可開創的新事業線)

### A. 「台灣垂直評測 + 模型選型」公司(最便宜、最快、先做這個)
- **產品**:每個垂直(台灣法規/合約、台灣製造業 B2B 詢價與規格、繁中客服)一套商用評測集(500–2,000 題,含黃金答案與判準),每月對所有主流模型(Claude/GPT/Gemini/Qwen/Inkling/本地開源)跑一次,出「**你的領域該用哪顆模型、差多少、多少錢**」的榜單與報告。
- **為什麼是中間層**:它就是零件②,而且是別人做微調前一定要先有的東西;學界只有 TMLU/TMMLU+ 這類通識題,**沒有商用垂直題**。
- **商模**:榜單免費(流量/信任)→ 企業客製評測 NT$8–15 萬/套 → 每月重測訂閱 NT$1–3 萬。
- **MVP(2 週)**:選一個垂直,出 300 題,跑 6 顆模型,發一頁榜單。零 GPU 成本。
- **要小心**:題庫外洩=資產歸零(hold-out 永不公開;公開只公開分數)。

### B. 「微調工坊」:幫台灣中小企業建 tuning apparatus 的服務公司(現金流最直接)
- **產品**:客戶有私有資料(客服紀錄、報價信、RFQ、SOP、判決/合約)但沒有 ML 團隊。我們做四件事:資料清整與標註設計 → 評測集(用 A 的方法)→ 在 **Tinker(大模型)或本地 5080(≤14B QLoRA)** 訓 LoRA → 上線後回饋迴路(每月回收生產樣本重訓)。
- **賣的是「迴路」不是「模型」**:月費制(對標 CREW NT$28,000/月那種 retainer),底層換代時「幫你重調」正是續約理由——這是 reel 論點的商業版。
- **MVP(4 週)**:一個客戶、一個任務(例:把 RFQ email 抽成結構化報價單),先用 eval 證明「微調後 vs 純 prompt」差多少,差距不到 10 個百分點就誠實說不用微調(這也是信任來源)。
- **成本**:Tinker 按 token(7B 級 LoRA 幾十美元);5080 本地 0 元;人力是主成本。

### C. 一個自營垂直模型:台灣製造業「圖面/規格→結構化資料」專用模型(資產最厚,最慢)
- **產品**:把 2D 工程圖、datasheet、規格書(中英混排)讀成結構化料號規格的專用模型 + 配套評測(shape_gate 類「讀出來的東西像不像圖上那個」)。通用模型在這件事上實測錯很多(我們 8 月 /kc 抽樣 71% 物種讀錯),是「通用模型明顯不夠好、而且錯了會很貴」的典型中間層題目。
- **資料來源**:公開 datasheet(Molex/TE/Samtec 等原廠 PDF 數十萬份,免費)+ 我們自己標註的黃金集;回饋迴路=客戶修正。
- **商模**:API 按頁計價 + 大客戶授權;或併入 B 當旗艦案例。
- **MVP(6–8 週)**:2,000 頁標註 → 14B 視覺模型 QLoRA(5080 可跑)→ eval 對 frontier 模型,**贏了才對外**,沒贏就回到 B 當服務。

### 三條線的關係
A 是所有線的地基(沒評測就沒有「調好了」這句話),B 靠 A 接案並累積各垂直資料,C 是 B 裡某一個垂直長成產品。**建議順序 A → B → C**;A 兩週內可以有東西給老闆看。

### 附註:現有資產能直接餵進去的(只列,不當主線)
- MarketDaily 兩年多的日報+戰績帳本 = 現成「建議→結果」標註資料,可做台股財經垂直的評測與微調(⚠️ 投顧法:只能 B2B 賣給持牌機構或做內部評測,不能對散戶賣個股建議模型)。
- 皇海/ProtoForge 已有的圖面與料號資料 = C 的冷啟動集。
- eval harness / verifier_harness / DSR 這批統計誠實積木 = A 的引擎。

## 四、三個最高訊號觀察(附時間戳)
1. **52–56s「your asset was never the tuned model, it is the tuning apparatus」**:全片唯一真正的洞見,caption 把它展開成五樣東西——資料/評測/工作流/領域專業/回饋迴路。這句話決定了公司該是「資料與評測公司」而不是「模型公司」。
2. **34–40s「Fable/Opus/Sonnet/Haiku」白紙 + 紅方塊吃黑圓**:用 Anthropic 四階模型名具象化「下一代一直來」,是全片最有效的視覺論證;同一張白紙在 58s 再用一次表達「更強底層=更強基底」——同一道具正反兩用,可搬。
3. **3–9s Greylock 原聲 + 0–3s「just told you」**:權威剪貼是 2022 的素材冒充「剛說」;觀眾不會查,但我們拆解時要查——引用名人語錄一律回原文找日期與下一句(下一句「not just fine tuning」剛好推翻 reel 的窄化)。
