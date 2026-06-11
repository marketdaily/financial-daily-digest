# 政壇 X 掃描器 — 遷移到 winrig(主機上線後執行)

目標:把每 15 分鐘掃 X 政治帳號 → LINE 推播的工作,從 Mac(Safari + caffeinate)
搬到 winrig(24/7 常開、headless Chrome 持久 profile)。Mac 那套就退役。

## 為什麼搬
- winrig 24/7 常開,無 Mac 睡眠/闔蓋問題(現在 Safari 線只在 Mac 醒+Safari 開時跑)
- winrig 有 Chrome,Playwright 持久 profile 登入一次 X 就永久 headless,不需 Safari 那套 AppleScript hack
- 用 `watch_x.py`(Playwright Chromium 版,已備好);Mac 的 `watch_safari.py` 是過渡方案

## winrig 上線後步驟(遵守 [[feedback-winrig-background-tasks]]:全背景、不搶前景/實體滑鼠)
1. ssh winrig,在 WSL Ubuntu 內 `pip install playwright && playwright install chromium`
2. 把 `political_watch/watch_x.py` + `.env`(內含 POLITICAL_INGEST_TOKEN)複製到 winrig
   (token 值在 Mac 的 `~/Library/Application Support/MarketDailyPoliticalWatch/.env`)
3. **一次性登入 X**:`python3 watch_x.py --login` —— winrig 無頭環境要嘛用 X11 forwarding/VNC
   開一次視窗登入,要嘛用 headed + RDP;登入後 session 存在 `~/.political_watch_profile`
4. 驗證:`python3 watch_x.py --dry` 能抓到 10 帳號貼文
5. 排程改 **systemd timer**(winrig 用 systemd,非 launchd),每 15 分鐘:
   `~/.config/systemd/user/political-watch.timer` (OnUnitActiveSec=15min) + `.service`
6. 上線後**關掉 Mac 端**:
   - `launchctl unload ~/Library/LaunchAgents/com.marketdaily.politicalwatch.plist`
   - `launchctl unload ~/Library/LaunchAgents/com.marketdaily.caffeinate.plist`(Mac 可恢復睡眠)
   - 兩個 plist 改名 .disabled 留底

## 不變的部分(worker 端零改動)
- `/political-ingest` 端點、`POLITICAL_INGEST_TOKEN`、Claude 判讀、LINE 推播管線全部照舊
- 只是「誰來抓 X + 從哪打這支 endpoint」從 Mac 換成 winrig
- 24/7 新聞政治線(CF worker `political` EVENT_RULES)繼續當保底,不受影響
- Grok x_search 線(需 xAI credits)也照舊保留

## 三套抓取來源關係(遷移後)
| 來源 | 機器 | 觸發 | 狀態 |
|---|---|---|---|
| X headless Chrome | winrig | systemd 15min | 遷移後主力 |
| 新聞政治關鍵字 | CF worker | 2min cron | 24/7 保底 |
| Grok x_search | CF worker | 15min cron | 待 xAI credits |
