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
  { platform: 'instagram', angle: '痛點切入:資訊焦慮/看不完新聞' },
  { platform: 'threads', angle: '機制差異化:AI 假訊息過濾怎麼運作' },
  { platform: 'x', angle: '產品日常:一封日報長什麼樣(講結構不講當日數字)' },
  { platform: 'facebook', angle: '信任與合規:免費與付費看到完全相同的個股分析' },
  { platform: 'instagram', angle: '新功能:每天 3 分鐘語音快報(marketdaily.ai/audio)' },
  { platform: 'threads', angle: '使用情境:通勤/開盤前的晨間儀式' },
]

phase('研究')
const research = await agent(
  `工作目錄 MarketDaily repo 根。任務:Marketing Agents 週批次「研究」步。
1. 讀 ${SKILLS}/spy/SKILL.md 與 ${SKILLS}/competitive-ads-extractor/SKILL.md 的鐵則。
2. 用 .venv/bin/python(沒有就 python3)跑 ${CAP}/spy.py 的 spy_report(),結果以 JSON 覆寫 ${CAP}/latest_spy_report.json。spy 失敗最多修一次,再失敗就沿用既有檔案並回報 spy_stale=true(不可因 spy 掛掉就整批不產)。
3. 讀 ${CAP}/RUNBOOK.md、marketing/CLAUDE.md、docs/pricing.html、docs/data/track-record.json(當下現值)。
4. 產出給創作代理的研究簡報 brief(競品在打什麼/我們的差異化彈藥/當前方案與排程事實/可用的真實賣點),800 字內。`,
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
    `讀 ${SKILLS}/ads-score/SKILL.md 評分準則,對這則草稿評分(0-100)+兩句筆記(強項/弱點):\n${JSON.stringify(d, null, 2)}`,
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