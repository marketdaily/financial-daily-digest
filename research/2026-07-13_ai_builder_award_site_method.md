# 為什麼 AI 建的網站「醜」——以及得獎站/Lovable/v0 到底怎麼不醜

> 2026-07-13 自主機器（深攻輪 opus）。回應 Delvin 07-12「也他媽太醜了吧」+「去 awwwards 找靈感」+「研究 Lovable 這類公司怎麼用 AI 做」。
> 三平行研究代理（award 站結構 / AI builder 方法 / 現行材料庫稽核）+ 綜合 + 落地實作 + render 親眼驗證 + 獨立驗證者。
> 產出不是報告，是**方法級升級**：見 §4「已落地」。

## TL;DR（一句話）
設計 token（顏色/字型/間距）只修**表面**，把 **composition（版面骨架）留在預設** → 所以即使用了 Lovable/v0，4 個「方向」還是**同一個骨架換皮**（skin-not-bones）＝模板臉＝醜。**修法＝在寫任何頁面碼之前，先為每個方向選一個「LAYOUT ARCHETYPE」（版面原型），讓骨架本身不同，不只換色。**

---

## 1. 根因：為什麼 AI 建的站長一樣（方法層，每條都可改）
1. **統計取平均**：叫 LLM「做一個 landing page」= 拿到它吃過的每一份 Tailwind 教學的中位數。修法：版面**不准 under-specified**，明寫版面概念。
2. **共用同一個 block 庫**（shadcn/Tailwind/Relume 1000+ blocks）：LLM 只是重排同一批模組，不是設計新骨架。修法：強制自訂 section 結構，別直接吐庫存 block。
3. **被訓練成「安全、連貫」不是「冒險」**：模型獎勵 coherence 不獎勵 originality。修法：persona prompt +「選最有主見、還能上線的那個」硬指令。
4. **一個 grid 重複用到底**：預設就是「3 欄 icon 卡」重複整頁，section 節奏永不變。修法：強制 per-section 版面變化（一段滿版、一段非對稱 2+1、一段編號散文）。
5. **prompt 只要 token/氛圍，從不要版面概念**：token pipeline 綁死顏色/字/間距，**結構留給預設**。「v0 will pick something if you don't → defaults to neutral across every design choice」。修法：token spec 旁邊加一個 layout-concept 欄。
6. **置中單欄 stack = 預設 composition**：「AI 模板預設置中標題、置中段落、置中按鈕，讀起來像『我沒做決定』」。修法：禁置中單欄，至少 1 個主 section 左對齊/非對稱。
7. **House-style 預設**：Inter/Roboto、紫→靛漸層、3 icon 卡、圓角+0.1 陰影、玻璃態、Undraw 插畫。這些就是 tell。修法：system prompt 硬 ban。

## 2. 得獎站的「骨架」——7 個 LAYOUT ARCHETYPE（結構配方，非換色）
每個 archetype 的關鍵是**不同的 nav 位置 + hero 構圖 + section 節奏 + 一個結構型招牌動作**（不是顏色/字型）：

| Archetype | nav | hero 構圖 | 招牌結構動作 | 破哪個 cliché |
|---|---|---|---|---|
| **Editorial/Broadsheet** | masthead（rule+dateline，品牌置中） | 滿版超大 display 標 + drop-cap 導言 + 多欄 | pull-quote 破欄到全寬 | 置中單欄部落格 stack |
| **Swiss/Grid** | 貼死 12 欄網格 | 標題按數學網格定位（左對齊，非置中） | 剛性網格內的非對稱張力（內容推到一欄，旁邊留大 void） | 對稱置中 hero |
| **Brutalist** | 裸/可見邊框/mono | 裸大字填滿視口 | 超大 numeral 當 section 錨 + 可見邊框 | 圓角柔卡 16px radius |
| **Techy/Terminal** | mono 索引標（01/02） | 左對齊 mono 標 + 資料 grid | 持久左 gutter 的超大索引數字 | 友善 3-up icon 卡 |
| **Immersive/Cinematic** | 最小持久 overlay | 滿版 canvas，字當建築元素 | scroll-as-timeline（scroll 驅動場景轉換） | 每個元素都 fade-in |
| **Bento/Modular** | 標準 | hero 是第一個大格 | 2×2 錨格 + 大小不一的鑲嵌（**cell span=重要度**） | 等高卡重複 3-up |
| **Asymmetric/Broken-Grid** | 常 offset/側置 | split 一邊明顯較大，或標偏一側+圖 bleed 出對邊 | offset overlap/對角切/圖出血過欄界 | 全對齊單一置中網格 |

**通用原則**：建立網格→**刻意破它**（破得像故意的，網格當參照）；戲劇性 scale 對比（超大 H1 vs 小 body，或 cell span 編碼階層）；whitespace 當**主動構圖**（隔離主元素，不是剩下的 padding）；一個大膽結構主意貫穿全站；type 當建築不是裝飾；編輯層級（kicker/drop-cap/超大 numeral/pull-quote 破欄）；節奏靠對比不靠均勻（拒絕上到下等 padding）；刻意 edge treatment（bleed/overlap）。

## 3. 好工具比 token 多做的三件事（可執行）
- **① 建站前先選 layout CONCEPT/archetype**：v0 的「named design systems」（Base/Mono/Soft Pop/Neo Brutalism/Cosmic Knight）＝控字型/間距/元件/整體美學的完整框架，官方定位「解決 generic AI 網站」。Bolt 有「10 prompt keywords」。Lovable/Framer 沒有內建版面多樣性機制→只能靠外部 art direction。
- **② reference 驅動萃取**（Framer/Lovable/v0 都**不能**從 raw URL clone；要用 UX Pilot Match-a-Brand / Anima / Superdesign 或截圖）：貼截圖當靈感（v0 native）、clone 一個 reference 的 design language、點名 2-3 個競品各取一個屬性（Linear=字型密度 / Vercel=編輯克制 / Rauno=非對稱 mono / Stripe=功能密度）。
- **③ anti-default 約束**：asymmetry 配額（≥50% section 非對稱）、per-section 節奏變化、banned-pattern 清單（禁 Inter/Roboto、禁白底紫漸層、禁三 icon 卡、禁「置中標+副標+2 鈕+手機圖」、禁玻璃態/shimmer、禁 empower/unlock/seamless 廢詞）、左對齊編輯式 hero（標 14-22ch measure）。

**prompt 級指令（可直接貼）**：先命名一個 archetype（"Swiss editorial" / "brutalist" / "Bloomberg terminal density"）；禁置中單欄；每頁一段滿版+一段省略+一段 off-grid；用非對稱 grid（2+1，一格 2× 大）取代 3 卡；persona=有印刷背景的資深前端 +「預設選最有主見、最非對稱、最編輯的、還能上線的；若你的產出能出現在任何 SaaS 站，丟掉重做」。

## 4. 已落地（不只歸檔——直接升級了 website-design-team skill 的材料庫）
現行 `design_intelligence` 材料庫稽核發現：4 個「方向」（graphite/broadsheet/signal/vellum）**DOM skeleton byte-identical**（76/76 行 diff 全同）＝1 layout × 4 換色，**self-test 還結構性強制 sameness**（4 proof 都從同一個 `build()` 重生），無任何閘查 layout variety。這正是 Delvin「太醜」的結構根因（前 6 輪只建 token/lint=floor，從沒碰 composition）。

本輪修法（`build_proof.py` 重構 + `helper.py` 新閘）：
- **ARCHETYPE 軸**：graphite→**terminal**（左索引 gutter + 水平 manifest + 編號 rows）、broadsheet→**editorial**（masthead + 超大 display + drop-cap + pull-quote 破欄）、signal→**brutal**（ink 邊框 slab + offset 破網格）、vellum→**bento**（varied cell span 鑲嵌 + 柔陰影）。4 個結構真的不同（nav/hero/features 全異）。
- **確定性 variety 閘** `helper.check_layout_variety`：hash 每頁 DOM skeleton（tag+class 序列，忽略文字/屬性），**任兩方向同 signature = FAIL**。此閘今日跑會 FAIL 改前的材料（4 signature 全同）。self-test 加 block 8（4/4 distinct + 負控：兩個相同骨架必須被抓 collision）。
- **關鍵設計判斷**：共用的 floor-safe primitive（`.lead-index` 內容元件、proof strip、CTA band、footer、buttons）**刻意保留**——skin-not-bones 的病是**整個骨架**都一樣，不是共用一個好元件；真正的多品牌設計系統就是「共用 primitive + 各異的 hero/feature 構圖」。
- **驗證**：全 floor 閘綠（lint 100×4 / rendered-CTA 全過 / void-card×4 / 3 regression 全 fire）；render 4 桌面+4 手機**親眼看**（教訓：lint 只量 floor，composition 級醜靜態掃不出）——修掉 render 才看得到的 3 個真缺陷（heading UA-margin 不均、bento 大格底部 void、brutal 死掉的隱形 numeral backdrop）。

## 5. 給 Delvin 的一句話
你上次「用 team 建站還是醜」的根因找到了：team 教的是 Lovable 的 **token 方法**（讓站「不破」），但**沒教得獎站的 composition 方法**（讓站「wow」）——所以 4 個方向只是換皮。這輪把「先選版面原型」的方法補進去了，材料庫的 4 個範例現在是 4 個**真的不同的版面**（terminal/editorial/brutal/bento），而且加了一道確定性閘，之後 team 產出「同骨架換皮」會被自動擋下。**下次你真的要建某個站時，跟我說目標，我用這套（archetype→foundation+token→section 組裝→3 道閘→render 親眼）走一遍。**

## 附：資料源（研究代理實讀，非記憶）
prg.sh（purple-gradient）、publishd.app（make-ai-not-look-ai）、superdesign.dev（anti-slop prompts）、sureprompts.com（v0 guide）、nocode.mba（v0 design systems）、axe-web.com（sameness）、shuffle.dev、banani.co（Lovable）、framer.com/wireframer、relume.io、support.bolt.new；awwwards 技術面：publitas（magazine layout）、swissthemes、todaymade/designlab（brutalist）、metabole（immersive）、saasframe/banani（bento）、htmlburger/thehypedge（broken-grid/asymmetric）、925studios（ai-slop tells）。
