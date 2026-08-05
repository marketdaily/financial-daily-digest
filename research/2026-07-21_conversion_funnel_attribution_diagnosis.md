# 轉換漏斗 × 歸因帳本診斷（2026-07-21）

> 域③ 成長/轉換輪。KPI 揭：近 7 日 ~132 clean human/日，但總訂閱僅 16 → 這是**轉換問題，不是流量問題**。
> 本輪目標：①排除「signup 漏斗靜默壞掉」（成長殺手級 P1）②用歸因帳本裁決 dq-4ddb3a2855（社群自動發文存廢）。
> 資料源：Cloudflare KV `USER_PREFS`（NS `f5229c5bf86a4f8b88d71995005cd670`），`wrangler kv ... --remote` 直讀，2026-07-21 21:3x TW。
> **⚠️ 事實與解讀分開**：§1–§2 是 KV 原始數字（可複查）；§3 起才是解讀。

---

> **🔬 已過驗證者分離（全新 context，2026-07-21）：SOUND-WITH-CORRECTIONS，3 findings 全數已修入本報告。**
> 驗證者獨立重拉 KV 確認 §1/§1b 原始數字全對，但抓到本報告初版兩個 interpretation over-claim：
> ①「visit 層沒 utm＝盲測」是**錯的**（實際 60/491 visits 帶 campaign utm，56 筆來自社群）；
> ②「決定級證據」在 0/56 的統計零樣本上**過度宣稱**。下文 §3.4/§4/§5 已改寫，結論不翻但理由/強度已修正。
> 驗證者報告：`~/autonomous/research/verifier_conversion_funnel_20260721.md`。

## 0. 一句話結論

- **signup 漏斗健康**，不是 P1（`/check-subscriber` live 200、`/subscribe-free-direct` 源碼完整、`getAttrPayload` 前端接線正確、真實轉換最近一筆 07-20 仍在落地）。⚠️ 非 e2e（真 e2e 會觸發歡迎信，違反 `feedback_no_manual_send`）→ e2e 為 UNVERIFIED-BY-DESIGN，但元件級證據足以支持「不是 P1」。
- **歸因帳本 60 天（05-23 起）共 22 筆轉換事件，但其中 11 筆是 `@example.com` 合成測試資料（全落在 05-25），真實轉換只有 11 筆（10 個不重複 email）。**
- **11 筆真實轉換裡：10 筆 `direct`（無 utm）+ 1 筆 `pricing`（站內 /pricing 頁點擊）。轉換事件層 social / blog / referral utm＝0 筆（此 tally 為真）。**
- **但社群不是零觸及**：visit 層 491 筆裡 60 筆帶 campaign utm、其中 **56 筆來自社群平台（threads 33 / fb 17 / ig 6）+ blog 2**，campaign 名對得上社群自動發文管線 → **社群確實在導入可量測流量，只是這 56 筆 visit 沒有一筆連到轉換。**
- ⟹ dq-4ddb3a2855 的正確裁決：社群自動發文**有觸及、零可證轉換**。但 0/56 在網站 ~0.1% 基準轉換率下與 direct **統計上無法區分**（期望轉換數 ≈0.056），**不是決定級證據**；真正的槓桿是「轉換/landing」，不是「修歸因」（歸因本來就在運作）。

---

## 1. 原始事實 — `attr:daily:*` 每日彙總（8 個有轉換的日子 / 60 天）

| 日期(TW) | by_source | by_event | total |
|---|---|---|---|
| 2026-05-23 | direct:3 | invite_used:3 | 3 |
| 2026-05-24 | direct:1 | invite_used:1 | 1 |
| 2026-05-25 | direct:11 | subscribe_free:11 | 11 |
| 2026-06-01 | direct:1 | subscribe_free:1 | 1 |
| 2026-07-03 | direct:2 | subscribe_free:2 | 2 |
| 2026-07-07 | direct:2 | subscribe_free:2 | 2 |
| 2026-07-16 | direct:1 | subscribe_free:1 | 1 |
| 2026-07-20 | other:1  | subscribe_free:1 | 1 |
| **合計** | **direct:21 · other:1** | **invite_used:4 · subscribe_free:18** | **22** |

其餘 52 天（含最近多日）該日 key 不存在＝零轉換事件。

## 1b. 原始事實 — `attr:convert:*` 逐筆（22 筆，email 已遮蔽）

分桶（依 email 網域 + ts→TW 日期）：

- **測試資料（`@example.com`，RFC 2606 保留網域，不可能是真人）：11 筆，全部 ts 落在 2026-05-25。** email 前綴 `rl***`(×9)、`ra***`(×1)、`e2***`(×1)。event 全為 `subscribe_free`、src 全 None。
- **真實轉換：11 筆（10 個不重複 email，1 個 email 出現兩次）**：
  - `invite_used`：4 筆（05-23 ×3、05-24 ×1；`ma***@hotmail.com`/`ma***@gmail.com`/`ti***@gmail.com` 等早期親友）
  - `subscribe_free`：7 筆（06-01、07-03 ×2、07-07 ×2、07-16、07-20）
  - utm_source：**10 筆 None（direct）+ 1 筆 `pricing`（07-20，normalizeSource→`other`）**
  - visit_id 有值：3 筆（皆為近期 subscribe_free），**但這 3 筆的 visit 記錄本身 utm_source 也是 None**。

> `attr:daily:2026-05-25` 的「11 direct subscribe_free」= 上面 11 筆 `@example.com` 測試 → **05-25 的「量日」是功能/壓力測試，不是真人上線潮或親友推薦。**

---

## 2. signup 漏斗健康度（排除 P1）

- `/check-subscriber` live → HTTP 200（端點活著）。
- `/subscribe-free-direct` 源碼完整（`stripe-webhook/src/index.js`），寫入端 `recordConvert` 正確聚合 `attr:daily` + `attr:convert`。
- 前端 `getAttrPayload` 從 URL 抓 utm 帶進轉換請求；並用 localStorage `md-attr-first`（`docs/index.html:1900,1920`）持久化 first-touch utm 跨回訪。⚠️ **社群貼文的 utm_source 不是字面 `social`**，而是**平台名**（`ATTR_SOURCES` at `src/index.js:346` = `ig/fb/threads/line/x/tiktok/youtube/email/blog/rss...`，**設計上沒有 `social` 這個值**）——本報告初版誤搜字面 `utm_source=social` 才誤判「沒帶 utm」。
- **visit 層歸因確實在運作**：491 筆 `attr:visit:*` 裡 60 筆帶 campaign utm（threads 33 / fb 17 / ig 6 / blog 2 / chatgpt 2），涵蓋 05-2x→07-21、地理分佈 US/TW/IE/SE/AU（真實分散流量非測試爆量）。
- **visit_id → 轉換關聯近期有生效但 join 有損**：11 筆真實轉換中 3 筆帶 visit_id（justinchang 07-07 / angela 07-07 / davidlaid 07-16，是最近 4 筆中的 3 筆；**最新一筆 hfks996 07-20 pricing 反而 visit_id=null**）；其餘 8 筆 visit_id=null → 帶著 social utm 進站又轉換的人，仍可能在帳本記成 `direct`。
- ⟹ **漏斗沒有靜默壞掉**，不是 P1。真正的問題在「進來的人幾乎不轉換」——social 有把人帶進來（56 visits），但這批人沒轉換。

---

## 3. 解讀（明確標示，非原始事實）

1. **「6 週零可證社群轉換」是保守說法；真相是整個 60 天窗口零可證 campaign 轉換。** 22 筆事件裡沒有任何一筆帶 social/blog/referral/email utm。唯一非 direct 的 1 筆是站內 `/pricing` 頁點擊（`pricing`），屬站內導流不是外部 campaign。
2. **invite 機制 05-24 後就死了**（只有 05-23/24 共 4 筆 invite_used，之後歸零）——與「推薦獎勵從未兌現」（memory `project_referral_premium_giveaway_gap`）一致。
3. **真實有機轉換速率極低**：06-01 起 60 天只有 7 筆有機 `subscribe_free`（約 5–6 天 1 筆），對照近 7 日 ~132 clean human/日 → 有機轉換率概略在 ~0.1% 量級（見 §4 侷限：帳本涵蓋完整度為假設）。**流量不是瓶頸，轉換才是。**
4. **社群有觸及，但轉換是 0（visit→convert 斷點）**：visit 層 60/491 帶 utm、56 筆社群（見 §2），證明社群貼文**確實在導入可量測流量**；但這 56 筆沒有一筆連到轉換事件。斷點不在「訪客沒帶 utm 進站」（那是初版的錯誤判斷，已證偽），而在 **visit → conversion 的衰減**（8/11 真實轉換 visit_id=null，utm 沒存活到轉換記錄）。⟹ 槓桿是**轉換/landing 頁**（把已經進來的社群流量接住），不是「修歸因」——歸因本來就在運作。

---

## 4. 假設與侷限（誠實揭露，防過度解讀）

- **帳本涵蓋完整度是假設**：`recordConvert` 只在 `subscribe_free`/`invite_used` 端點被呼叫。若有其他 signup 路徑沒走這條，帳本會低估總轉換數。但對 dq-4ddb3a2855 的結論（social utm 零筆）無影響——那是「有標籤 vs 無標籤」的判斷，不依賴總數。
- **utm 遺失發生在 visit→convert 之間，不是進站前**：驗證者實拉 491 筆 visit 證明 utm 確實有被 capture（60 筆帶標籤）。真正的損失點是 visit_id 沒接上轉換記錄（8/11 真實轉換 visit_id=null），所以帶 social utm 進站的人若轉換，會被記成 direct。**初版誤稱「visit 層都沒 utm＝盲測」是錯的，已於 §2/§3.4 更正。**
- **0/56 不足以否定社群**：11 筆真實轉換本就是小樣本；更關鍵的是 social 的 56 筆 visit 在網站 ~0.1% 基準轉換率下，期望轉換數僅 ≈0.056（即使 0.5% 也只 ≈0.28）——**觀察到 0 筆完全符合「社群與網站平均一樣好」的虛無假設**，統計上無法區分 social 是否比 direct 差。因此只能下二元結論「目前零 linked 轉換」，不能下「social 無效」的統計結論。
- **05-25 測試資料未被 purge**：`attr:convert` TTL 365 天且 append-only，測試訂閱者即使已從訂閱名單移除，事件仍留在帳本 → 這是「22 筆」與「16 訂閱」不相等的原因之一（另含 05-23 前的舊訂閱者、churn）。**教訓：讀歸因帳本必須先濾 `@example.com` 再算真實轉換，否則會像本任務前一輪一樣把 22 全當真轉換。**

---

## 5. 對 dq-4ddb3a2855（社群自動發文存廢）的裁決證據

**證據強度：提示性、樣本受限（非決定級）。** 事實面：整個 60 天窗口，社群帶來 **56 筆可量測 visit** 但 **0 筆 linked 轉換**（`attr:convert` 交叉核對）。但 0/56 在 ~0.1% 基準率下與 direct **統計上無法區分**（§4），且 visit→convert join 有損（8/11 轉換 visit_id=null），所以是「零 **linked** 轉換」不是「零 **實際** 轉換」。**社群自動發文管線（`marketing/daily_run.py` + winrig cron）持續發文，證實有觸及（reach），但轉換未證實。**

**修正後的判斷**：這**不是**「社群沒把人帶進來」的問題（初版誤判）——社群把人帶進來了（56 visits），問題是**這批流量沒被 landing 接住轉換**。所以真正該動的槓桿是**轉換率 / landing 頁**，而非停社群或修歸因（歸因已在運作）。

**建議選項（等 Delvin 拍板，機器不自主停社群線）：**
- **A. 先攻轉換，不動社群**：既然社群有 reach、瓶頸在轉換，優先改 landing→signup 的接住率（社群來的 56 人到底卡在哪一步），比停掉唯一有觸及數據的管道更有價值。
- **B. 若要止血，用「每筆可量測 visit 的成本」判，不要用 0/56 轉換判**：0/56 統計上是 null，不足以判社群無效；若要降頻，理由應是「維護成本 vs top-of-funnel 觸及值」，不是「零轉換」。把資源移向 PTT 1-8-4（dq-6c562fda8b）/ SEO 收錄（dq-591921164c）仍可考慮，但那是資源配置取捨，不是「社群被證明無效」。

---

## 附錄：複查指令

```bash
cd ~/Delvin-agent/stripe-webhook
NS=f5229c5bf86a4f8b88d71995005cd670
npx wrangler kv key list --namespace-id $NS --prefix "attr:daily:"   --remote   # 8 keys
npx wrangler kv key list --namespace-id $NS --prefix "attr:convert:" --remote   # 22 records
# ⚠️ 一定要加 --remote，否則 wrangler 讀本地 miniflare（空的）誤判成 0 keys
```
