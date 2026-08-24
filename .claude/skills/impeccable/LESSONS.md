### 2026-08-10 「detect」不是 command 是腳本
- 坑:CLAUDE.md 寫 `/impeccable detect`,但 Commands 表沒有 detect;真身是 `scripts/detect.mjs`。
- 修:`node <skill>/scripts/detect.mjs <files...>` 直接跑,`--no-advisory` 靜音進階提示;中文站的「——」破折號會觸發 em-dash advisory,屬正當標點可保留。

### 2026-08-24 驗證跑在資產傳播完成之前 = 對著舊版下結論
- 坑:Cloudflare Pages/Workers assets 部署後有數十秒傳播,`?v=` 換版也擋不住。我連兩次截圖驗證跑在舊資產上,一次判定「改了沒效果」、一次把已修好的版面看成還壞著,差點去改本來就對的程式。
- 修:驗證前先 poll 線上檔案裡的新字串再截圖(`until curl … | grep -q '<新字串>'`),不要用 sleep 猜。
- 另:巢狀網格要從最外層查起 —— 內層 `grid-template-columns` 再對,外層 `.crew` 那個舊的 auto-fit 三欄會先把整組壓進 290px。改版面時先量 `getBoundingClientRect()` 的實際寬度,不要只看自己剛寫的那條規則。
