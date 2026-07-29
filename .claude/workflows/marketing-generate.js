export const meta = {
  name: 'marketing-generate',
  description: 'Marketing Agents 生成階段:研究→6 創作代理平行→評分平行→定稿寫檔(5-skill 鏈語義,順序保留、站內平行)',
  whenToUse: '週批次生成 6 則社群草稿(spy→extract→bulk-creative→ads-score→ads-meta);args 可傳 {outPath} 指到測試副本',
  phases: [
    { title: '研究', detail: 'spy 刷新+競品提取' },
    { title: '創作', detail: '6 個創作代理平行,各一則' },
    { title: '評分', detail: 'ads-score 每則平行評分' },
    { title: '定稿', detail: 'ads-meta 格式+合規自檢+寫檔' },
  ],
}

const ARGS = typeof args === 'string' ? JSON.parse(args) : (args || {})
const OUT = ARGS.outPath || 'marketing/ad_creative_drafts.json'
const SKILLS = '~/.claude/plugins/marketplaces/delvin-custom/plugins/delvin-tools/skills'
const CAP = '~/autonomous/capabilities/marketing_agents_pipeline'

const IRON_RULES = `鐵則(違反=白做,獨立驗證者會駁回):
- 零捏造數字:勝率/訂戶數/來源數/百分比一律不准寫死在 caption(下週重跑數字會變=變假話);講機制不講當下數字
- 唯一例外:「新聞hook型」草稿裡的外部新聞事實數字(非我方產品數據)不但可以寫還必須具體,但 draft 必須帶 source_url 欄位(公開可驗證的原始出處,驗證者會逐字對)
- 只有 Premium 一個付費方案;禁「Pro」「免費試讀」「不綁卡」「邀請碼」「送 Premium」
- 禁「保證/穩賺/絕對/100%/月賺X%」;不喊進喊出個股;個股分析內容不得與付費連結(合規鐵則)
- organic only,不投付費廣告;禁任何 LINE CTA(LINE 已退役)
- 中英 caption 語意必須一致(免費版週日休息→不可寫「每天」)`

const RESEARCH_SCHEMA = {
  type: 'object', required: ['brief', 'spy_stale'],
  properties: { brief: { type: 'string' }, spy_stale: { type: 'boolean' } },
}
const DRAFT_SCHEMA = { type: 'object', required: ['draft'], properties: { draft: { type: 'object' } } }
const SCORE_SCHEMA = {
  type: 'object', required: ['score', 'notes'],
  properties: { score: { type: 'number' }, notes: { type: 'string' } },
}
const FINAL_SCHEMA = {
  type: 'object', required: ['written', 'count'],
  properties: { written: { type: 'boolean' }, count: { type: 'integer' } },
}

const ANGLES = [
  // 觸及軌(源自 @100xengineers 拆解,memory reference_100xengineers_playbook):
  // 第一句 hook=具名主體+具體數字+對比;caption=旁白逐字稿式迷你文章(有獨立收藏價值),
  // 收尾一句自然帶到 MarketDaily;新聞事實必須近 7 天內+可公開驗證,draft 帶 source_url
  { platform: 'instagram', angle: '新聞hook型(觸及軌):挑近7天一則「金融×AI」真實新聞(新工具/新模型/大公司動作),第一句=具名主體+具體數字+對比(範式:「Google 剛把要價 $30,000 的 Bloomberg Terminal 變成免費 App」),caption 寫成完整迷你文章,結尾一句帶 MarketDaily;draft 必須帶 source_url(驗證者會逐字對新聞事實)' },
  // AI 神用法軌(源自三大帳號拆解 reference_big3_ai_ig_accounts:aipagedaily「Claude砍機票8prompts」、getintoai「反諂媚prompt」都是這桶,收藏率極高):
  // 教「一個可照抄的 AI 用法」但落在投資/看盤場景,示範 MarketDaily 用戶怎麼用 AI 更聰明地做功課,不喊個股不給買賣價位
  { platform: 'instagram', angle: 'AI 神用法型(觸及軌):教一個具體可照抄的 AI 用法,場景放「用 AI 更聰明地做投資功課」(範式:一句 prompt 讓 ChatGPT 停止拍你馬屁、逼它列出你持股的三個看空理由;或用 AI 十分鐘讀懂一份財報)。第一句 hook=具體數字+對比;caption 給出可直接複製的 prompt/步驟(迷你教學,高收藏);結尾帶 MarketDaily 每天幫你把功課做好。鐵則:只教方法與體驗,絕不出個別股票買賣價位/建議,個股分析不得與付費連結' },
  { platform: 'threads', angle: '機制差異化:AI 假訊息過濾怎麼運作' },
  { platform: 'x', angle: '產品日常:一封日報長什麼樣(講結構不講當日數字)' },
  { platform: 'facebook', angle: '信任與合規:免費與付費看到完全相同的個股分析' },
  { platform: 'instagram', angle: '新功能:每天 3 分鐘語音快報(marketdaily.ai/audio)' },
  // 轉換軌:留言閘門(comment_funnel.py 自動回連結;caption 絕不放連結,固定關鍵字「早鳥」)
  { platform: 'instagram', angle: '留言閘門轉換型:內容教一個真材實料的投資資訊習慣/方法(教方法,不喊個股不給價位),CTA 固定收尾「留言『早鳥』,我把訂閱連結私訊給你 ✌️」;caption 短(三句內)、不放任何連結;口徑只能是「目前全功能限時免費,早鳥用戶在未來恢復收費後永久保留免費使用權」,禁止暗示未來分析內容收費' },
]

phase('研究')
const research = await agent(
  `工作目錄 MarketDaily repo 根。任務:Marketing Agents 週批次「研究」步。
1. 讀 ${SKILLS}/spy/SKILL.md 與 ${SKILLS}/competitive-ads-extractor/SKILL.md 的鐵則。
2. 用 .venv/bin/python(沒有就 python3)跑 ${CAP}/spy.py 的 spy_report(),結果以 JSON 覆寫 ${CAP}/latest_spy_report.json。spy 失敗最多修一次,再失敗就沿用既有檔案並回報 spy_stale=true(不可因 spy 掛掉就整批不產)。
3. 讀 ${CAP}/RUNBOOK.md、marketing/CLAUDE.md、docs/pricing.html、docs/data/track-record.json(當下現值)。
4. 讀 marketing/COMPETITOR_CONTENT_SWIPE.md(三大 AI IG 帳號 @aipagedaily/@getintoai/@evolving.ai 拆解:選題三桶=錢/工作衝擊·名人擂台·獵奇科技、Hook 公式、可搬 AI 神用法),挑當前最能對接我們金融×AI 利基的角度餵給創作代理。
5. 讀 marketing/social_out/engagement_summary.json(若存在):近 14 天 IG 實際成效(各內容型 n/avg_reach/avg_likes/avg_comments、top/bottom_by_reach)。把「哪類型式實際有人看/全軍覆沒」寫進簡報,給創作代理 1-2 句成效導向指引;檔案不存在或數字全缺就明寫「無成效資料」,不准腦補數字。
6. 產出給創作代理的研究簡報 brief(競品在打什麼/我們的差異化彈藥/當前方案與排程事實/可用的真實賣點),800 字內。`,
  { label: 'research', schema: RESEARCH_SCHEMA }
)

phase('創作')
const twoDigit = (n) => String(n + 1).padStart(2, '0')
const drafts = (await parallel(ANGLES.map((a, i) => () =>
  agent(
    `工作目錄 MarketDaily repo 根。你是創作代理 #${i + 1},產出「恰好一則」社群貼文草稿。
1. 讀 ${CAP}/RUNBOOK.md 的「輸出格式」——你回傳的 draft 物件必須完全符合該格式,status="pending_review",platform="${a.platform}",id 先填 "adcreative_PENDING_${twoDigit(i)}"(日期由定稿代理統一補)。
2. 讀 ${SKILLS}/bulk-creative/SKILL.md 鐵則。
3. 研究簡報:\n${research.brief}\n
4. 你的創作角度(不可跟別人撞):${a.angle}
5. caption_zh 寫完先用 Bash 跑 ${CAP}/compliance_selfcheck.py 的 check_caption() 自檢,任何 false 就改寫到全過,結果填 compliance_self_check。
${IRON_RULES}`,
    { label: `creative:${twoDigit(i)}:${a.platform}`, phase: '創作', schema: DRAFT_SCHEMA }
  )
))).filter(Boolean).map((r) => r.draft)
log(`創作完成 ${drafts.length}/6`)
if (drafts.length < 4) throw new Error(`創作代理只回來 ${drafts.length} 則(<4),批次品質不足,中止`)

phase('評分')
const scored = await parallel(drafts.map((d, i) => () =>
  agent(
    `讀 ${SKILLS}/ads-score/SKILL.md 評分準則,對這則草稿評分(0-100)+兩句筆記(強項/弱點)。
額外硬性加權(源自三大 AI IG 帳號拆解):第一句 hook 是否符合「具名主體+具體數字+對比/衝突」公式(第一句就是全部賭注,弱 hook 直接扣分);觸及軌貼文 caption 是否有獨立收藏/教學價值。這兩點不合格則 score 不得高於 70。\n${JSON.stringify(d, null, 2)}`,
    { label: `score:${twoDigit(i)}`, phase: '評分', schema: SCORE_SCHEMA }
  ).then((s) => ({ ...d, ads_score: s ? s.score : null, ads_score_notes: s ? s.notes : 'scorer 缺席' }))
))

phase('定稿')
const final = await agent(
  `工作目錄 MarketDaily repo 根。任務:Marketing Agents「定稿」步。
1. 讀 ${SKILLS}/ads-meta/SKILL.md(organic 模式)與 ${CAP}/RUNBOOK.md 輸出格式。
2. 以下 ${scored.length} 則草稿:把 id 統一改成 adcreative_<今天TW日期YYYY-MM-DD>_NN(NN=01 起流水號),按 RUNBOOK 格式微調欄位(不改 caption 語意),組成完整檔案結構(頂層 generated_at=現在 TW 時間 ISO 格式${research.spy_stale ? ',加 "spy_stale": true' : ''}),**覆寫** ${OUT}。
3. 寫完用 Bash 重讀驗證:JSON 合法、恰好 ${scored.length} 則、全部 status=pending_review、id 日期正確。
草稿:\n${JSON.stringify(scored, null, 2)}
${IRON_RULES}
- 不碰 social_posts.json、不把任何 status 改成 approved、不 git commit、不 deploy、不發文`,
  { label: 'finalize', schema: FINAL_SCHEMA }
)
log(`GENERATED ${final.count}`)
return { generated: final.count, spy_stale: research.spy_stale }