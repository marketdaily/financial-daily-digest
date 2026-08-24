# 睡前全站 Audit — 2026-06-06(凌晨)

對 marketdaily.ai 前端(docs/)做完整稽核。派 Explore agent 掃描 + 人工依專案史過濾誤判。

## ✅ 已修 + 已部署 + 已推 origin
**pricing.html 比較表殘留 Pro 欄(用戶可見,違反「UI 不可再提 Pro」)**
- tier-card 早已清成「免費 + Premium」,但功能比較表還留一欄 `<th>Pro</th>` + 14 列中間值格,用戶看得到一個買不到的方案。
- 結構化移除整欄:刪表頭 col-pro、14 列 Pro 值格、4 個 group-head `colspan 4→3`;逐列驗證每列剩正好 3 值欄、表頭 3 欄對齊、tag 平衡。
- commit `6535675` 已推 origin;`npx wrangler pages deploy` 已上線;production `marketdaily.ai/pricing.html` 驗證 `col-pro`=0。
- JS 裡 `PRICES.pro=299/239` 與 `pro-price-note` 是**死碼**(無對應 DOM、被 `if(pn)` 擋、setBilling 只寫 premium),用戶不可見,**刻意不動**以免影響 billing 邏輯。

## 🔍 已查證但「刻意不改」(設計如此 / 用戶明令保護 / 已知待辦)
列出讓你知情,不是漏修:
1. **localStorage 明文存密碼**(dashboard `md-saved-pwd`、admin `md-admin-pwd-saved`):是「記住密碼」功能,記憶 `feedback_password_flow_protect` 多次警告**不可動設密碼/登入/重試 flow**。屬已接受的設計取捨,夜間不自行改。
2. **WORKER_URL 嵌帳號名 `delvin-12345678.workers.dev`**(10+ 檔):記憶 `project_privacy_audit` 列為**已知待辦**(待綁自訂網域後一次換),非新問題。
3. **admin.html 前端 ADMIN_EMAIL 常數**:真正權限驗證在 worker 後端,前端 email 只是 UI gate;與 worker URL 同批,待自訂網域。
4. **dashboard LINE `?action=bindLine&token=` 一鍵綁定**:記憶 `feedback_line_bind_setup_lock` 明令此 flow 已鎖**不可改壞**,屬刻意設計。
5. **onboarding-tour.js innerHTML**:插入的是內部靜態 step 資料、非用戶輸入,XSS 風險低。

## ✅ 通過項
- guide 4 張教學圖(step1-4)實體檔案皆存在,無破圖。
- 自訂游標未被加回(符合規定)。
- 無 console.log/debug 殘留、無假數字(統計用「—」)、無重複 id。
- i18n 完整(236 個 data-i18n);RWD 用 clamp/彈性佈局無明顯破版。

## 總評
無會讓用戶當下踩到的高危 bug。唯一用戶可見的退化(Pro 欄)已修並上線驗證。其餘為已知/受保護項,維持現狀。
