// 政壇市場訊號 — xAI Grok x_search 抓政治人物 X 貼文,LINE 即時推播版。
// 與 repo 根目錄 grok_political.py(日報注入版)同名單、同 prompt 精神,兩邊改動要同步。
// 無 XAI_API_KEY 時整條 no-op,不影響既有新聞推播管線。

export const WATCH_HANDLES = [
  "realDonaldTrump", "WhiteHouse", "POTUS", "USTreasury", "scottbessent",
  "CommerceGov", "USTradeRep", "federalreserve", "SECGov", "elonmusk",
];

const XAI_URL = "https://api.x.ai/v1/responses";

function extractOutputText(data) {
  if (!data || typeof data !== "object") return "";
  if (typeof data.output_text === "string" && data.output_text.trim()) return data.output_text;
  const chunks = [];
  for (const item of data.output || []) {
    if (item && item.type === "message") {
      for (const c of item.content || []) {
        if (c && (c.type === "output_text" || c.type === "text")) chunks.push(c.text || "");
      }
    }
  }
  return chunks.join("");
}

// 回傳近 windowHours 內會影響市場的政治人物貼文訊號(severity 高→低)。
export async function fetchPoliticalSignals(env, windowHours = 2, maxItems = 6) {
  if (!env.XAI_API_KEY) return { skipped: "no_XAI_API_KEY", signals: [] };
  const now = new Date();
  const fromDate = new Date(now - (windowHours + 12) * 3600 * 1000).toISOString().slice(0, 10);
  const toDate = now.toISOString().slice(0, 10);
  const handleList = WATCH_HANDLES.map(h => "@" + h).join("、");

  const sys = "你是頂尖財經市場分析師,專門盯政治人物的發言對金融市場的衝擊。"
    + "只挑出『可能實質牽動』美股、台股、外匯、利率、原物料或加密貨幣的貼文 —— "
    + "例如關稅、出口管制、利率/Fed、財政與預算、產業補貼、點名特定公司、地緣政治。"
    + "與市場無關的純政治口水、個人攻防、選舉造勢一律忽略。所有文字輸出用繁體中文。";

  const user = `搜尋這些帳號在過去 ${windowHours} 小時內發出的 X 貼文:${handleList}。\n`
    + "從中篩出會影響金融市場的貼文,每則整理成一個物件。受影響標的(affected)填股票代碼:"
    + "美股填 ticker(如 NVDA、TSM),台股填四位數代碼(如 2330);"
    + "若影響大盤/匯率/利率而非單一個股,affected 可留空。\n"
    + 'kind 欄位:已宣布/簽署/生效的具體政策行動填 "action";喊話、批評、暗示、預告這類言論觀點填 "statement"。\n'
    + '只輸出 JSON 物件,格式:\n'
    + '{"signals":[{'
    + '"handle":"發文帳號(不含@)",'
    + '"name_zh":"政治人物中文名(如 川普、Fed、財政部)",'
    + '"posted_at":"ISO 8601 發文時間",'
    + '"post_url":"該貼文的 X 連結",'
    + '"headline_zh":"一句繁中標題:他說了什麼",'
    + '"quote":"原文關鍵摘錄(原文語言)",'
    + '"impact_zh":"一句繁中:對哪些市場/標的的影響與方向",'
    + '"affected":["受影響股票代碼"],'
    + '"direction":"bullish|bearish|mixed",'
    + '"kind":"action|statement",'
    + '"severity":1到10整數}]}\n'
    + '找不到符合的貼文就回 {"signals":[]}。不要杜撰貼文或連結,只用搜尋真實找到的內容。';

  let resp;
  try {
    resp = await fetch(XAI_URL, {
      method: "POST",
      headers: { authorization: `Bearer ${env.XAI_API_KEY}`, "content-type": "application/json" },
      body: JSON.stringify({
        model: env.XAI_MODEL || "grok-4.3",
        instructions: sys,
        input: [{ role: "user", content: user }],
        tools: [{ type: "x_search", allowed_x_handles: WATCH_HANDLES, from_date: fromDate, to_date: toDate }],
      }),
    });
  } catch (e) {
    return { error: `xai fetch: ${String(e).slice(0, 120)}`, signals: [] };
  }
  if (!resp.ok) return { error: `xai ${resp.status}: ${(await resp.text()).slice(0, 160)}`, signals: [] };

  let parsed;
  try {
    const content = extractOutputText(await resp.json());
    const s = content.indexOf("{"), e = content.lastIndexOf("}");
    if (s < 0 || e <= s) return { signals: [] };
    parsed = JSON.parse(content.slice(s, e + 1));
  } catch (e) {
    return { error: `parse: ${String(e).slice(0, 120)}`, signals: [] };
  }

  const out = [];
  for (const s of (parsed && parsed.signals) || []) {
    if (!s || typeof s !== "object") continue;
    const headline = String(s.headline_zh || "").trim();
    if (!headline) continue;
    const handle = String(s.handle || "").replace(/^@/, "").trim();
    let sev = Math.round(Number(s.severity));
    if (!Number.isFinite(sev)) sev = 5;
    sev = Math.max(0, Math.min(10, sev));
    out.push({
      handle,
      name_zh: String(s.name_zh || handle).trim(),
      posted_at: String(s.posted_at || "").trim(),
      post_url: String(s.post_url || (handle ? `https://x.com/${handle}` : "https://x.com")).trim(),
      headline_zh: headline,
      quote: String(s.quote || "").trim().slice(0, 280),
      impact_zh: String(s.impact_zh || "").trim().slice(0, 200),
      affected: (s.affected || []).map(t => String(t).trim().toUpperCase()).filter(Boolean),
      direction: ["bullish", "bearish", "mixed"].includes(s.direction) ? s.direction : "mixed",
      kind: s.kind === "action" ? "action" : "statement",
      severity: sev,
    });
  }
  out.sort((a, b) => b.severity - a.severity);
  return { signals: out.slice(0, maxItems) };
}

// 每則訊息必帶操作立場(2026-05-31 鐵則:回答「我該減倉還是加碼」,不只描述)。
function stanceLine(sig) {
  const tgt = sig.affected.length ? sig.affected.join("、") : "大盤";
  if (sig.direction === "bearish") return `📌 立場:利空 ${tgt} — 持有者先別加碼,守住停損;未持有者觀望等政策落地`;
  if (sig.direction === "bullish") return `📌 立場:利多 ${tgt} — 已持有者續抱;未持有者勿追價,等回檔再評估`;
  return `📌 立場:方向未明 — 先觀望,等 ${tgt} 政策細節或市場反應確認再動作`;
}

export function formatPoliticalMsg(sig, displayName) {
  const tickers = sig.affected.length
    ? "🎯 標的:" + sig.affected.map(t => displayName ? displayName(t) : t).join("、") + "\n"
    : "";
  const tag = sig.kind === "statement" ? "💬 言論觀點(非既成政策)" : "🏛️ 政策行動";
  return `${tag} | 政壇市場訊號\n\n`
    + `${sig.name_zh}(@${sig.handle})\n`
    + `「${sig.headline_zh}」\n\n`
    + `💥 影響:${sig.impact_zh}\n`
    + tickers
    + stanceLine(sig) + "\n\n"
    + `🔗 ${sig.post_url}\n`
    + `— MarketDaily 即時提醒 · AI 解讀僅供參考`;
}
