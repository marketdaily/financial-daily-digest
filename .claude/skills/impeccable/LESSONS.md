### 2026-08-10 「detect」不是 command 是腳本
- 坑:CLAUDE.md 寫 `/impeccable detect`,但 Commands 表沒有 detect;真身是 `scripts/detect.mjs`。
- 修:`node <skill>/scripts/detect.mjs <files...>` 直接跑,`--no-advisory` 靜音進階提示;中文站的「——」破折號會觸發 em-dash advisory,屬正當標點可保留。

### 2026-08-24 驗證跑在資產傳播完成之前 = 對著舊版下結論
- 坑:Cloudflare Pages/Workers assets 部署後有數十秒傳播,`?v=` 換版也擋不住。我連兩次截圖驗證跑在舊資產上,一次判定「改了沒效果」、一次把已修好的版面看成還壞著,差點去改本來就對的程式。
- 修:驗證前先 poll 線上檔案裡的新字串再截圖(`until curl … | grep -q '<新字串>'`),不要用 sleep 猜。
- 另:巢狀網格要從最外層查起 —— 內層 `grid-template-columns` 再對,外層 `.crew` 那個舊的 auto-fit 三欄會先把整組壓進 290px。改版面時先量 `getBoundingClientRect()` 的實際寬度,不要只看自己剛寫的那條規則。

### 2026-09-01 animation fill:both 會永久蓋掉同元素後續的動畫與 transition
- 坑:入場動畫 `.rd-enter{animation:... both}` 讓退場 `.rd-out`(transition)與錯誤 `.rd-shake`(animation)全部無效——fill 持續佔住 transform/opacity,且同 specificity 下 stylesheet 較晚的 animation 規則獨佔 animation 屬性。
- 修:切換狀態前先 `classList.remove('rd-enter')` 再加新 class;或入場動畫結束後主動移除該 class。
- 避:凡「入場→互動→退場」同一元素多段動畫,入場一律用完即拆,不留 fill。

### 2026-09-01 html2canvas 的兩個 SVG 沉默丟棄坑(海報匯出)
- 坑:①inline `<svg>` 裡的 `<g transform="rotate(...)">` 整顆不畫(無錯誤);②`<img src="data:image/svg+xml">` 若 svg 根元素沒有明確 width/height 屬性(只有 viewBox),匯出時尺寸算 0 也整顆消失——瀏覽器畫面兩者都正常,只有匯出壞。
- 修:裝飾一律用 `<img>`+data URI,svg 根元素帶 width/height,旋轉改放在 img 的 CSS transform(html2canvas 支援元素級 transform);驗收必須看「匯出成品」不能只看瀏覽器,且對匯出圖做像素抽樣斷言。
- 另:CSS `filter: drop-shadow` 匯出時被整個忽略(僅視覺降級,可接受);conic-gradient 不支援,放射光改 SVG path。

## 2026-09-03 detect 對 docs/ 整目錄會被 docs/output/ 130+ 篇日報存檔淹沒
- 修法:只點名主要頁面 `detect.mjs docs/index.html docs/dashboard.html …`;存檔頁是 email 本體(side-tab 色條是 email 樣式),不算站台設計 tell。全站主要頁命中固定四樣:Inter、codex-grid 格線背景、#6366f1 dark-glow、bounce easing——這就是老闆罵的「同一套模板」在程式碼層的指紋。

### 2026-09-03 無人值守+winrig 禁開視窗時,new-work 的決策頁走不了
- 坑:new-work 的 serve-question 決策頁要開瀏覽器給用戶選;winrig 鐵則禁止搶前景,且 session 無人值守。同時 harness 沒註冊 `impeccable-finish-reviewer` agent type。
- 修:PRODUCT.md 自己代填(推定項逐條標【推定】,收工時揭露)、concept-seed 照擲,指派+挑戰者融合後直接建,收工報告寫明假設;審查者改 spawn general-purpose 並餵 `reference/degraded/finish-reviewer.md` 路徑當角色。
- 另:`overflow-x:clip` 後 playwright `full_page` 截圖仍含溢出寬度(陸塊 bleed 被拍成白邊),要帶 `clip={'width':viewport}` 才是使用者看到的畫面;detect 對過衝 easing 一律報 bounce-easing,挑戰者世界本身要求過衝時屬 brief-earned,交給審查者判用量即可。

### 2026-09-04 皇海站台殼的 CSS 變數不全+固定層會壓內部工具頁
- 坑:在 site.css 殼裡直接用 `var(--accent)`/`var(--page-pad)`(那些只在 styles.css 定義,殼沒載)→ 長條圖全黑、頁面零內距;另外 `#curtain`(過場簾幕)/`#kc-qrail`/`#ck` 這幾個 position:fixed 層在 full_page 截圖與實際畫面都會壓住資料。
- 修:內部頁自訂 token(`.ops{--acc:#d6ac57}`)、內距寫死 clamp;`#curtain,#kc-qrail,#ck{display:none!important}`。用殼之前先 `getComputedStyle` 抓一次真的有沒有這個變數,別看檔名猜。
- 另:flex 容器裡的長文字(`.kpi .d`)在 minmax(0,1fr) 格子裡仍會撐出 scrollWidth,要 `flex-wrap:wrap;min-width:0;overflow-wrap:anywhere`。

### 2026-09-04 自訂 class 與 SVG 標記 class 撞名:DOM 數值全對,只有截圖看得出來
- 坑:頂列 `.bar{height:52px;position:sticky…}` 與圖表長條 `<rect class="bar">` 同名 → SVG2 的 height 是 presentation property,CSS 直接把每根長條改成 52px;`getAttribute`/`outerHTML` 查出來的 height 全對,Playwright 數值斷言零紅,只有截圖裡長條變形。
- 修:結構性 class 一律加前綴(`.topbar`),圖表標記 class 用 `.ck-bar` 之類;dataviz 的「第 7 步 render it and look at it」不可省——數值檢查抓不到 cascade 撞名。

### 2026-09-14 flex 置中容器裡的區塊子元素會縮成 0 寬,DOM 斷言全綠只有截圖看得出來
- 坑:遊戲舞台 `.stage-card{display:flex;flex-direction:column;align-items:center}`,裡面的觸控區 `.finger-zone` 沒寫 `width:100%` ⇒ 寬度塌成一條 1px 虛線;v2.0 上線版就長這樣,QA「開啟遊戲 innerHTML>80」照樣綠。我第一輪截圖也拍到了卻沒看出來(當成裝飾線)。
- 修:`.finger-zone{width:100%}`;QA 加 `getBoundingClientRect().width>250` 斷言,並用 `dispatchEvent(new PointerEvent('pointerdown',{pointerId:...}))` 模擬 5 根手指真的跑完倒數。
- 避:批次截圖回合要「每一款遊戲都拍」,看到任何細線/空白區先量 `getBoundingClientRect()`;多點觸控類遊戲的 QA 要模擬到選出結果,不只開得起來。

### 2026-09-15 圖示系統的「沒對照就刪掉」是會靜默壞掉的退路
- 坑:把 emoji 換成自繪 SVG 的替換層寫成 `return key ? icon(key) : ""` —— 沒建對照的 emoji **直接消失**(骰子規則、牌組選單、規則大全的圖示全變空)。截圖看起來只是「那裡本來就沒圖」,沒人會發現。
- 修:退路改成 `: e`(原樣留著),另建 lint 掃「畫面文字裡出現但沒有對照的 emoji」,並把撲克花色 ♠♥♦♣ 列為永不替換(那是牌面內容不是裝飾)。
- 通則:任何「轉換層」的 fallback 都不要選「丟掉」;選「原樣通過」才會在下次截圖時被看見。
