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
