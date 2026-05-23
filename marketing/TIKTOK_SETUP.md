# TikTok 自動發布設置(Content Posting API)

把 MarketDaily reel 自動發到 TikTok。發法用 **Direct Post + PULL_FROM_URL**
(讓 TikTok 從 marketdaily.ai/social/*.mp4 拉影片,不用上傳 binary)。

設置完之後,把 `tiktok` 加進 `social_posts.json` 對應 reel 的 `platforms`,
GH Actions cron 06:00 TWT 就會自動帶上。

---

## 1. 註冊 TikTok for Developers app

1. 開 https://developers.tiktok.com/ 用品牌帳號(@marketdailyhq)登入。
2. 右上 **Manage apps** → **Connect an app**:
   - **App name**:`MarketDaily Auto Post`
   - **Category**:`News & Information`
   - **Description**:`Daily financial news digest posts (auto-publish reels from marketdaily.ai)`
   - **Website**:`https://marketdaily.ai`
   - **Terms of Service URL**:`https://marketdaily.ai/terms`(若無就先填首頁)
   - **Privacy Policy URL**:`https://marketdaily.ai/privacy`
3. **Products → Login Kit**:加上,Redirect URI 填 `http://localhost:8724/`
   (本機取 token 用;之後線上不需要 redirect,只靠 refresh_token)。
4. **Products → Content Posting API**:加上,選 **Direct Post**(不是 Sandbox upload)。
5. **Scopes** 勾:
   - `user.info.basic`
   - `video.upload`
   - `video.publish`
6. **Submit for review**。Sandbox 模式只能發給 self,正式發給粉絲要過審
   (通常 1–7 個工作天)。送審前先用 sandbox 確認 token 流程 ok。

審核期間,sandbox app 還是能正常發影片到自己帳號 —— 對我們夠用,
不用等審核就可以開始排自動發布。

---

## 2. 拿 client_key / client_secret

App 進到 Live 或 Sandbox 後,在 app 詳細頁的 **App Info** 頁籤:
- **Client key**(以前叫 Client ID)
- **Client secret**

複製下來,別貼到 git。

---

## 3. 本機取 access_token + refresh_token

```bash
python3 marketing/get_tiktok_token.py <client_key> <client_secret>
```

腳本會:
1. 開瀏覽器走 OAuth 授權(登入 @marketdailyhq、勾同意)。
2. 在 localhost:8724 接收 code。
3. 換成 `access_token` + `refresh_token` 印在終端。

把這四行貼到 `marketing/.env`:

```
TIKTOK_CLIENT_KEY=xxx
TIKTOK_CLIENT_SECRET=xxx
TIKTOK_ACCESS_TOKEN=xxx
TIKTOK_REFRESH_TOKEN=xxx
```

`access_token` 24 小時過期,`refresh_token` ~365 天;`auto_post.py` 會
在發文當下用 `refresh_token` 換新 access,GH Actions 不必每天重設。

---

## 4. 驗證

```bash
python3 marketing/auto_post.py check
```

應該看到:

```
TikTok:       ✅ @marketdailyhq
```

---

## 5. 設 GH Actions secrets

到 GitHub repo → Settings → Secrets and variables → Actions → New secret:

| Secret 名稱 | 內容 |
| --- | --- |
| `TIKTOK_CLIENT_KEY` | 上面 client_key |
| `TIKTOK_CLIENT_SECRET` | 上面 client_secret |
| `TIKTOK_ACCESS_TOKEN` | 上面 access_token |
| `TIKTOK_REFRESH_TOKEN` | 上面 refresh_token |

然後在 `.github/workflows/social_post.yml` 的 `env:` 區塊補上:

```yaml
TIKTOK_CLIENT_KEY: ${{ secrets.TIKTOK_CLIENT_KEY }}
TIKTOK_CLIENT_SECRET: ${{ secrets.TIKTOK_CLIENT_SECRET }}
TIKTOK_ACCESS_TOKEN: ${{ secrets.TIKTOK_ACCESS_TOKEN }}
TIKTOK_REFRESH_TOKEN: ${{ secrets.TIKTOK_REFRESH_TOKEN }}
```

---

## 6. 開啟發布

編輯 `marketing/social_posts.json`,把 `tiktok` 加進 reel 貼文的 platforms:

```jsonc
{
  "id": "explainer",
  "type": "reel",
  "platforms": ["instagram", "facebook", "youtube", "x", "tiktok"],
  ...
}
```

下一次 GH Actions cron(每天 06:00 TWT)就會自動發到 TikTok。

---

## 排錯

| 症狀 | 原因 / 解法 |
| --- | --- |
| `access_token_invalid` | refresh_token 過期或撤銷 → 重跑 `get_tiktok_token.py` |
| `url_ownership_unverified` | TikTok 要驗證 video_url 的 domain → 在 app 設定 → **URL Properties** 加 `marketdaily.ai` 並驗證(放 .well-known meta tag) |
| `video_pull_failed` | 影片 URL 不公開、>500MB、或 codec 不支援 → 確認 mp4 (h264 + aac, ≤4K, ≤10min) 可在無認證下載 |
| `spam_risk_too_many_posts` | 同 IP/帳號短時間發太多 → 拉開間隔(每天 1 篇最安全) |
| Sandbox 發出去看不到 | Sandbox 影片只有發布者本人 + 加入 sandbox 的 test user 看得到;正式上架需通過 app review |

---

## 我們目前狀態

- `post_tiktok()`:已實作(`auto_post.py`),PULL_FROM_URL 模式 + 安全跳過。
- 沒設 secrets → 自動 skip,不打斷其他平台。
- `social_posts.json` 暫不含 `tiktok`,等用戶設好 secrets 再加。
