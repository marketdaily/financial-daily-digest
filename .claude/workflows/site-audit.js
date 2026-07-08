export const meta = {
  name: 'site-audit',
  description: 'MarketDaily 全站多代理深度巡檢:每頁平行審+對抗式驗證',
  whenToUse: '要對 marketdaily.ai 做超越 site_scan.py 確定性檢查的深度品質巡檢時(視覺/文案/i18n/console/連結/鐵則合規)',
  phases: [
    { title: '巡檢', detail: '每頁一個代理:console/連結/i18n/視覺/文案鐵則' },
    { title: '驗證', detail: '每個 finding 兩個獨立反駁者' },
  ],
}

const PAGES = [
  'index.html', 'pricing.html', 'guide.html', 'audio.html', 'track-record.html',
  'vs.html', 'vs-chatgpt.html', 'about.html', 'contact.html', 'agents.html',
  'filter.html', 'status.html', 'privacy.html', 'terms.html', 'testimonials.html',
  'analytics.html', 'dashboard.html',
]

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['page', 'findings'],
  properties: {
    page: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'category', 'issue', 'evidence'],
        properties: {
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          category: { type: 'string' },
          issue: { type: 'string' },
          evidence: { type: 'string' },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['refuted', 'reason'],
  properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } },
}

const auditPrompt = (page) => `你是 MarketDaily(marketdaily.ai)的網站品質稽核員。深度審查這一頁:https://marketdaily.ai/${page}

工具做法(不要用 MCP 瀏覽器,它被佔用):
1. 用 Bash 寫一個臨時 python playwright 腳本(chromium headless,args=["--disable-gpu"]),載入該頁(viewport 1280x900),收集:console error/warning、載入失敗的資源、頁面全頁截圖存到 scratchpad。
2. 用 Read 看截圖,親眼檢查視覺(破版/重疊/溢出/對比不足/空白區塊/未載入圖片)。
3. 再截一張 iPhone 尺寸(390x844)的,檢查手機版。
4. 用同一腳本抓頁面所有 <a href> 與 <img src>,對站內連結與圖片 curl -sI 驗 HTTP 狀態(外部連結跳過)。
5. 檢查 i18n:localStorage md-lang-v2 設 en 後 reload,截圖看是否有殘留中文(header/footer/按鈕);再設回 zh。
6. 文案鐵則掃描(讀 HTML 源碼):
   - 不得出現「LINE」相關 CTA(LINE 已全面退役)
   - 不得出現「Pro 方案」(只有 Premium)
   - 不得有看起來捏造的數字/見證(placeholder 應為「—」)
   - 個股分析功能不得與付費綁定的暗示
   - 不得有假即時報價

只回報「真的存在、有證據」的問題,寧缺勿濫;每個 finding 附具體證據(console 原文/截圖觀察/HTTP 狀態碼/HTML 片段)。頁面正常就回空 findings。`

phase('巡檢')
const results = await pipeline(
  PAGES,
  (page) => agent(auditPrompt(page), { label: `audit:${page}`, phase: '巡檢', schema: FINDINGS_SCHEMA }),
  (report, page) => {
    if (!report || !report.findings.length) return []
    return parallel(report.findings.map((f) => () =>
      parallel([1, 2].map((i) => () =>
        agent(
          `對抗式驗證(你是懷疑者#${i},立場=這個 finding 是假的/誇大的,去找反證):\n頁面 https://marketdaily.ai/${page}\nfinding: [${f.severity}] ${f.category} — ${f.issue}\n證據: ${f.evidence}\n\n用 Bash(curl / 臨時 python playwright headless 腳本)實際重現驗證。重現得了=refuted:false,重現不了或證據站不住=refuted:true。不確定時傾向 refuted:true。`,
          { label: `verify:${page}:${f.category}`, phase: '驗證', schema: VERDICT_SCHEMA }
        )
      )).then((votes) => {
        const ok = votes.filter(Boolean).filter((v) => !v.refuted).length >= 2
        return ok ? { page, ...f, confirmed: true } : null
      })
    ))
  }
)

const confirmed = results.flat(2).filter(Boolean)
log(`確認 ${confirmed.length} 個問題`)
return { confirmed }