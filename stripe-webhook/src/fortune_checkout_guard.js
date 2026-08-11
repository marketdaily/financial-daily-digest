// fortune-ai(天機AI)收銀台金額把關 —— 純函式,無 Cloudflare 依賴。
//
// 這裡**不決定價格**。價格唯一真源在 fortune-ai repo 的 `worker/src/pricing.js`
// (定價 list、促銷特惠價、檔期起訖都在那裡),fortune-ai worker 在伺服器端算完金額才送來。
// 本檔只做兩件把關:
//   ① 品項白名單
//   ② **永遠不會多收**:金額不得超過該品項的定價上限 max_amount
// 缺 amount 一律拒絕(不猜、不預設定價):客人畫面上看到的是特惠價,
// 若因欄位漏了就默默照定價收錢 = 收得比標價多,那是公平法上最不能犯的方向。
// 呼叫端收到 400 會 fallback 成「專人聯繫」流程並推播老闆,不會靜默出錯。
//
// ⚠️ max_amount 必須恆等於 pricing.js 的 list × 100(TWD 以「分」計)。
//    fortune-ai `tests/node/pricing.test.mjs` 會跨 repo 逐項對帳,改一邊沒改另一邊會紅。
// 2026-08-11 全品項調價(fortune-ai 老闆拍板)+ 新 SKU 終身詳批:
// 舊 sku(bazi249/tarot99/…)隨舊 id 一起下架 —— fortune-ai worker 的 checkout 已拒收舊 id,
// 不會再送舊 sku 過來;歷史已建立的 Checkout Session 不經過本把關,移除無影響。
export const FORTUNE_SKUS = {
  bazi999: { name: "天機AI 八字詳批(單次)", max_amount: 99900 },
  bazifull1999: { name: "天機AI 八字終身詳批(單次)", max_amount: 199900 },
  tarot199: { name: "天機AI 塔羅單題(單次)", max_amount: 19900 },
  hehun1299: { name: "天機AI 合婚合盤(單次)", max_amount: 129900 },
  liunian1199: { name: "天機AI 2027流年詳批(單次)", max_amount: 119900 },
  tarotlove399: { name: "天機AI 塔羅感情聖壇六張陣(單次)", max_amount: 39900 },
  ziwei999: { name: "天機AI 紫微斗數詳批(單次)", max_amount: 99900 },
  astro999: { name: "天機AI 西洋占星本命盤(單次)", max_amount: 99900 },
};

export function resolveFortuneCheckout(sku, amount) {
  const s = FORTUNE_SKUS[sku];
  if (!s) return { error: "bad_sku", status: 400 };
  if (!Number.isInteger(amount) || amount <= 0 || amount > s.max_amount) {
    return { error: "bad_amount", status: 400, max_amount: s.max_amount };
  }
  return { name: s.name, amount };
}
