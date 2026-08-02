# 工程文章自動發布 Playbook(週三 cron 的 claude -p 執行)

你在 /home/userdelvin/Delvin-agent。任務:把 `marketing/eng_blog/` 裡「已完稿未發布」的下一篇工程文章發布上線。全程照本 playbook,不需人工確認;回覆語言繁體中文。

## 步驟
1. **找目標**:讀 `marketing/eng_blog/content_calendar.md` 與 `published.log`。目標=日曆順序中第一篇「有 `_zh.md` 完稿、且標題不在 published.log」的文章(同名 `_en.md` 若存在則一起發)。找不到 → 推播「本週無完稿可發,請寫稿」後結束(推播方式見步驟 7)。
2. **品質閘**:對 zh/en 稿跑 `python3 ~/autonomous/capabilities/ai_slop_lint/logic.py <檔>`,CLEAN 才續;抽驗 `facts_sources.md` 中該篇 3 個最重的數字(用登記的指令/行號重跑),對不上 → 不發布,推播告警並列出對不上的項目。
3. **建網頁**:完全沿用既有工程文章模板 `docs/blog/eng-llm-council-judge-202608.html`(讀它照抄 head 結構/CSS/CTA/免責/hreflang;CTA 口徑必含「限時免費+早鳥永久保留」)。slug 規則:`eng-<英文短slug>-<YYYYMM>.html`,英文版加 `-en`。mermaid 一律轉 ASCII `<pre>`。og 圖用 `python3 scripts/og_card.py`(慣例輸出 docs/blog/og/<slug>.png)。
4. **掛列表**:`docs/blog/index.html` 依既有卡片格式插到 grid 最上方(`data-cat="eng"`),「全部 N」與副標篇數 +2(中英各一)。
5. **feed/sitemap**:`python3 scripts/blog_feed.py` 與 `python3 scripts/gen_sitemap.py`。
6. **發布**:git add(只准動 docs/blog/、docs/feed.xml、docs/sitemap.xml、marketing/eng_blog/)→ commit(訊息含 [eng-blog auto])→ push → `npx wrangler pages deploy docs --project-name marketdaily --commit-dirty=true` → `python3 scripts/site_scan.py` 必須 exit 0(fail → 立即 `git revert` 該 commit、重新 deploy、推播告警)。上線後 curl 兩頁(**不帶 .html** 的 canonical URL)確認 200。
7. **社群佇列**:把宣傳貼文插入 `marketing/social_posts.json`(參考既有 `eng_article_council_202608` 那筆的格式與插入位置=第一篇未發布之前;圖=og 圖轉 jpg 放 `docs/social/`,要再 deploy 一次;caption 內數字只准用文章內已查證數字;platforms 含 x)。
8. **收尾**:`echo '<中文標題>' >> marketing/eng_blog/published.log`;content_calendar 該週標「已發布」;推播老闆:兩頁 URL+「明 14:00 社群自動發」。推播方式:
   `TOK=$(grep '^MARKETDAILY_ALERT_TOKEN=' .env | cut -d= -f2- | tr -d '"');訊息 JSON {"message":...} POST https://marketdaily-alert-worker.delvin-12345678.workers.dev/internal/admin-line-push,header Authorization: Bearer $TOK + 自訂 User-Agent`。

## 紅線
- 數字查證不過=不發布,寧缺勿錯(no_fake_numbers)。
- 不碰 docs/ 其他頁面;不動 main.py/analyzer.py;絕不寄 email。
- site_scan 不過絕不留在線上。
