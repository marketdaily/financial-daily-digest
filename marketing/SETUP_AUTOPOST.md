# 社群自動發文 — 一次性設定

設定完之後,發文只要一行指令。Meta / Threads / LINE 為必備,X 與 YouTube 為選配,全部填進 `marketing/.env`。
**任何一步卡住,截圖貼給 Claude,會逐步帶你。**

---

## 0. 先複製設定檔

```bash
cd marketing
cp .env.example .env
```
之後把下面拿到的值填進 `.env`。(`.env` 已設定不會被 git 追蹤。)

---

## 1. Meta — Facebook 粉專 + Instagram(同一組權杖)

> 前提:FB 粉專已建、IG 已轉「商業帳號」並與粉專連結。

1. 到 **developers.facebook.com** → 用你的 FB 登入 → **我的應用程式** → **建立應用程式**
2. 類型選 **「企業 / Business」** → 填名稱(如 MarketDaily)→ 建立
3. 應用程式建立後**維持「開發模式」即可** —— 對自己的帳號發文不需要送審查
4. 左側加入產品:**Instagram** 和 **Facebook 登入**
5. 開 **Graph API 測試工具(Graph API Explorer)**:
   - 選你的應用程式
   - 「使用者或粉專」選你的**粉專**
   - 點 **新增權限**,勾選:
     `pages_show_list` `pages_read_engagement` `pages_manage_posts`
     `instagram_basic` `instagram_content_publish` `business_management`
     `ads_management`(← 2026-07-10 新增:解鎖 IG Audio API 的 Sound Collection 推薦曲,Reels 自動配樂用)
   - 點 **產生存取權杖** → 同意授權
6. **換成長期權杖**:把上面拿到的權杖貼到「**存取權杖偵錯工具**」(Access Token Debugger)→ 最下方點 **延長存取權杖** → 再執行一次 `GET /me/accounts`,裡面粉專的 `access_token` 就是**不會過期的粉專權杖** → 這個填入 `META_ACCESS_TOKEN`
7. 拿 ID(在 Graph API Explorer 執行):
   - `GET /me/accounts` → 你的粉專 `id` → 填 `FB_PAGE_ID`
   - `GET /{粉專id}?fields=instagram_business_account` → 回傳的 id → 填 `IG_USER_ID`

---

## 2. Threads(獨立)

1. 同樣在 developers.facebook.com,你的應用程式裡加入 **Threads** 用途
2. 設定 Threads → 把你的 Threads 帳號加為測試者並授權
3. 取得 **Threads 存取權杖**(權限 `threads_basic`、`threads_content_publish`)→ 填 `THREADS_ACCESS_TOKEN`
4. 執行 `GET https://graph.threads.net/v1.0/me?fields=id,username` → 回傳的 id → 填 `THREADS_USER_ID`

---

## 3. LINE 官方帳號

1. 到 **developers.line.biz** → 用 LINE 登入 → 進你 OA 對應的 **Provider → Channel**
2. **Messaging API** 分頁 → 最下方 **Channel access token(long-lived)** → 發行
3. 填入 `LINE_CHANNEL_ACCESS_TOKEN`

> LINE 是「廣播給好友」,初期粉絲少時效果有限,可最後再弄。

---

## 4. 驗證 + 發文

```bash
cd marketing

python auto_post.py check          # 確認 4 組權杖都通過(✅/❌)
python auto_post.py stage          # 貼文圖轉 JPEG、傳上 marketdaily.ai/social/、部署
python auto_post.py list           # 看所有貼文 id

python auto_post.py post teaser    # 發預告貼文(IG + FB + Threads)
python auto_post.py post launch --only instagram,facebook
```

`stage` 跑一次即可(圖片有更新再跑)。之後每天發一篇:`post launch` → 隔天 `post problem` → …

---

## 5. X / Twitter(選配)

1. 到 **developer.x.com** → 申請開發者帳號(免費方案 Free 即可發文)
2. 建立一個 **Project**,底下建一個 **App**
3. App 的 **User authentication settings** → 設定 → **App permissions 改成「Read and write」**(這步沒做不能發文)
4. **Keys and tokens** 分頁,拿 4 個值:
   - 「API Key and Secret」→ 填 `X_API_KEY` / `X_API_SECRET`
   - 「Access Token and Secret」→ 點 **Generate**(產生的權限要顯示 Read and Write)→ 填 `X_ACCESS_TOKEN` / `X_ACCESS_SECRET`
5. 若你是先 Generate token 才改權限 —— Access Token 要**重新 Generate 一次**才會生效

> 免費方案每月約 1,500 則發文,日報自動發綽綽有餘。圖片上傳若被免費層擋,程式會自動退回純文字貼文(文案本身已含連結)。

---

## 6. YouTube(選配,自動發短影音 Shorts)

1. 到 **console.cloud.google.com** → 建立專案 → 「API 和服務」→ 程式庫 → 啟用 **YouTube Data API v3**
2. 「OAuth 同意畫面」→ User Type 選 **外部** → 填基本資訊 → 把自己的 Google 帳號加進 **測試使用者**
3. 「憑證」→ 建立憑證 → **OAuth 用戶端 ID** → 應用程式類型選 **桌面應用程式** → 建立後拿到 `client_id` / `client_secret`
4. 跑一次授權拿 refresh token:
   ```bash
   cd marketing
   python get_youtube_token.py <client_id> <client_secret>
   ```
   瀏覽器跳出 Google 授權 → 同意 → 終端機印出 `YT_CLIENT_ID` / `YT_CLIENT_SECRET` / `YT_REFRESH_TOKEN` 三行 → 貼進 `.env`

> refresh token 不會過期(除非撤銷授權)。影片直式、≤3 分鐘會被 YouTube 自動判定為 Shorts。

---

## 注意

- **TikTok 不在自動發文內** —— 它的發文 API 要通過官方審核,個人過不了。TikTok 用排程器或手動。
- Meta 長期權杖約 60 天會過期(粉專權杖通常不過期,但偶爾要重拿);`check` 顯示 ❌ 就回來重做第 1 步第 6 點。
- 全自動(每天定時自己發)可再用 launchd / cron 排程 `post` 指令 —— 設定好權杖後跟 Claude 說即可。
