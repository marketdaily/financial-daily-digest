# Viral Broadcast 草稿(等你確認 → 我才寄)

> ⚠️ 嚴格遵守「不可手動發信」原則 — 草稿在這裡,你說「寄」我才會 trigger broadcast endpoint。

---

## 寄送對象

**所有現有訂閱者**(目前 9 人,以後增加自動含)— 透過 Brevo Campaign API broadcast,**不是個別 transactional**。

---

## Email 主旨

```
🎁 兩週感謝 — 邀請朋友雙方各得 30 天 Premium
```

## Email body 內容

```
嗨,

過去這段時間謝謝你陪 MarketDaily 一起長大 ☕

如果這個日報對你有用 — 有件事想拜託你:

把它分享給一個朋友。

我們的成長 95% 靠口碑,不靠廣告。每多一個訂閱者,日報就能寫得更深、新聞源能再增加。

【推薦計畫(雙邊各得 30 天 Premium)】

你的專屬推薦連結:
https://marketdaily.ai/?ref={YOUR_REF_CODE}

朋友點這個連結訂閱後:
✅ 朋友:30 天 Premium 試用(LINE Bot AI 對話 + 即時推播)
✅ 你:30 天 Premium 信用,自動延長到帳戶

【分享文案範例(直接複製貼上)】

最近發現一個東西不錯 — marketdaily.ai 每天早上 7 點寄 AI 過濾過的財經日報。
我已經訂閱一陣子,真的省很多時間。
你用我的連結訂閱,我們雙邊都得 30 天 Premium:
{YOUR_REF_LINK}

---

去你的「我的專區」拿推薦連結:
https://marketdaily.ai/dashboard.html#referral

明早 7 點見 💪
— Delvin · MarketDaily
```

⚠️ `{YOUR_REF_CODE}` 和 `{YOUR_REF_LINK}` 會在 Brevo merge tag 處理,每個收件人自動帶自己的 ref code。

---

## LINE Broadcast 內容(給 Premium 綁定 LINE 用戶)

```
⚡ 兩週感謝 — 邀請朋友雙方各得 30 天 Premium

如果 MarketDaily 對你有用,分享給一個朋友 →
雙方各得 30 天 Premium 信用。

去拿你的專屬推薦連結:
https://marketdaily.ai/dashboard.html#referral
```

---

## 預期效益

假設目前 9 個訂閱者,**有效推薦率 30%**(3 人推薦成功):

- 3 個新 free 訂閱
- 3 個推薦人 + 3 個新訂閱 = **6 人獲得 30 天 Premium 試用**
- 30 天後 30% Premium 試用者升正式 = 約 2 個新 Premium 用戶
- ARR 提升:**2 × NT$499 × 12 = NT$11,976/年**

成本:**NT$0**(用 Brevo 既有 quota + 推薦獎勵是延後費用)

---

## 風險

| 項目 | 風險 |
|------|------|
| 太頻繁推銷 | 用戶疲勞 → 退訂 |
| Premium 試用變成負擔 | 推薦獎勵燒太多免費 Premium → 影響營收 |
| 推薦連結被濫用 | 已有防鑽機制(Gmail alias normalize + 月上限 10 人) |

緩解:**這封信只寄一次,不會二寄**。Email 內附明確 unsubscribe link。

---

## 你說「寄」我會做什麼

1. 從 KV 拉所有 `pwd:` keys 的 email list
2. 為每個 email 生 / 拉 ref code(用 grantReferralReward 同邏輯,確保 idempotent)
3. 用 Brevo Campaign API 建 broadcast(merge tag {{REFCODE}} 自動代入)
4. Submit broadcast → Brevo 寄出
5. 同樣 LINE message 給綁定的用戶
6. 寫 KV `viral_broadcast_sent:2026-05-24` 記錄,避免重寄

---

## 我絕對不做的事

- ❌ 沒你的明確「寄」就觸發 broadcast
- ❌ 寄給非訂閱者
- ❌ 寄給已 unsubscribe 的人
- ❌ 一週內 2 寄

---

## 等你回覆

說「**寄 viral broadcast**」我才執行。
說「先不寄」我關掉這 task。
有想改的字也跟我說,我改完再 review。
