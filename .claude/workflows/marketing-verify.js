export const meta = {
  name: 'marketing-verify',
  description: 'Marketing Agents 驗證階段:每則草稿一個全新 context 獨立驗證者,平行裁決後統一寫回',
  whenToUse: '週批次驗證 ad_creative_drafts.json 的 pending_review 草稿(取代單一驗證者,隔離更徹底);args 可傳 {draftsPath} 指到測試副本',
  phases: [
    { title: '讀取', detail: '列出 pending_review 草稿' },
    { title: '驗證', detail: '每則一個獨立驗證者(平行)' },
    { title: '寫回', detail: '確定性套用裁決+終檢' },
  ],
}

const DRAFTS = (args && args.draftsPath) || 'marketing/ad_creative_drafts.json'

const LIST_SCHEMA = {
  type: 'object', required: ['read_ok', 'drafts'],
  properties: {
    read_ok: { type: 'boolean' },
    drafts: { type: 'array', items: { type: 'object' } },
  },
}
const VERDICT_SCHEMA = {
  type: 'object', required: ['id', 'action'],
  properties: {
    id: { type: 'string' },
    action: { type: 'string', enum: ['approve', 'reject'] },
    fixed_caption_zh: { type: 'string' },
    fixed_caption_en: { type: 'string' },
    verifier_edits: { type: 'string' },
    reject_reason: { type: 'string' },
  },
}
const APPLY_SCHEMA = {
  type: 'object', required: ['approved', 'rejected'],
  properties: { approved: { type: 'integer' }, rejected: { type: 'integer' } },
}

const RULES = `你是「獨立驗證者」,全新 context,工作目錄是 MarketDaily repo 根。上游草稿是另一個 agent 產的,預設不可信;你的裁決直接決定會不會自動發文,你後面沒有人工把關。寧可錯殺,不可錯放。

檢查這一則草稿:
1. 逐字事實查核 caption_zh 與 caption_en,對照真相來源當下現值:
   - docs/pricing.html(方案名稱只有 Premium、價格、免費版寄送排程——注意免費版週日休息)
   - docs/data/track-record.json(任何戰績/勝率相關描述)
   - marketing/CLAUDE.md 鐵則 + COMPLIANCE_STRUCTURE.md(個股分析內容不得與付費連結)
2. 中英一致性:caption_zh 與 caption_en 語意必須一致(歷史教訓:中文寫「每天」英文寫 Mon-Sat,中文是錯的)
3. 合規字眼:不准出現寫死的勝率/訂戶數/百分比、「Pro」、免費試讀、邀請碼、送 Premium、保證/穩賺/絕對/100%、喊進喊出個股、AI 自稱老師/大師/神算、任何 LINE CTA(LINE 已退役)
4. 品牌距離:對照 ~/autonomous/capabilities/marketing_agents_pipeline/latest_spy_report.json,語句不得與競品 creative 貼太近(近乎照抄=駁回)
5. 用 Bash 跑 ~/autonomous/capabilities/marketing_agents_pipeline/compliance_selfcheck.py 的 check_caption() 重掃 caption_zh,任何一項 false=駁回

裁決規則:
- 小型事實錯誤(日期/星期寫法/明顯錯字)可修正:回傳 fixed_caption_zh / fixed_caption_en(完整改寫後全文)+verifier_edits(改了什麼+為什麼);修正後必須重跑上述全部檢查,全過才可 approve
- 通過 → action=approve;不過 → action=reject + reject_reason(具體原因,引用對不上的原文)
- 你只裁決這一則,不碰任何檔案、不 git commit、不 deploy、不發文`

phase('讀取')
const listed = await agent(
  `讀 ${DRAFTS},回傳所有 status=="pending_review" 的草稿完整物件陣列(欄位原樣保留)。
- 檔案成功讀到且 JSON 合法 → read_ok=true(真的沒有 pending 才回空陣列)
- 檔案讀不到/JSON 壞掉 → read_ok=false + 空陣列(絕不把讀取失敗偽裝成沒有草稿)
不要改任何檔案。`,
  { label: 'list-pending', schema: LIST_SCHEMA }
)
if (!listed || !listed.read_ok) throw new Error(`讀不到 ${DRAFTS}(read_ok=false),fail-closed 中止`)
const pending = listed.drafts || []
log(`pending_review ${pending.length} 則`)
if (!pending.length) return { approved: 0, rejected: 0, note: 'no pending drafts' }

phase('驗證')
const verdicts = (await parallel(pending.map((d) => () =>
  agent(`${RULES}\n\n草稿(id=${d.id}):\n${JSON.stringify(d, null, 2)}`,
    { label: `verify:${d.id}`, phase: '驗證', schema: VERDICT_SCHEMA })
))).filter(Boolean)

if (verdicts.length !== pending.length) {
  log(`⚠️ ${pending.length - verdicts.length} 則驗證者沒回來——缺席者一律 reject(fail-closed)`)
}
const byId = Object.fromEntries(verdicts.map((v) => [v.id, v]))
const finalVerdicts = pending.map((d) => byId[d.id] || {
  id: d.id, action: 'reject', reject_reason: '獨立驗證者執行失敗(缺席),fail-closed 駁回',
})

phase('寫回')
const applied = await agent(
  `把以下裁決確定性套用到 ${DRAFTS}(用 Bash 跑 python,不要用自己的判斷改內容):
${JSON.stringify(finalVerdicts, null, 2)}

規則:
- action=approve → 該 id 的 status="approved";有 fixed_caption_zh/fixed_caption_en 就先替換 caption 欄位,並寫入 verifier_edits
- action=reject → status="rejected" + reject_reason
- 只動列出的 id,不新增/刪除草稿、不改其他欄位、不碰 social_posts.json、不 git commit、不 deploy
- 寫完重新讀檔驗證:不得殘留任何 pending_review;統計 approved/rejected 數量回報`,
  { label: 'apply-verdicts', schema: APPLY_SCHEMA }
)
log(`approved=${applied.approved} rejected=${applied.rejected}`)
return applied