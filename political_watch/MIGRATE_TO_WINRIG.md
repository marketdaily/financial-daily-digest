# 政壇 X 掃描器 — 已遷移到 winrig(2026-06-24 完成)

每 15 分鐘掃 X 政治帳號 → /political-ingest → Claude 判讀 → LINE/web push,
已從 Mac(Safari + launchd)搬到 winrig(24/7 常開、headless google-chrome)。

## 現況(winrig)
- 程式:`watch_x.py`(Playwright + storage_state),用系統 google-chrome(channel="chrome",fallback chromium)
- 登入 session:`auth_state.json`(Playwright storage_state,明文 JSON,gitignore 不進版控)
  在有顯示器的機器(Mac)`python3 watch_x.py --login` 登入一次匯出 → 搬到 winrig 即可,跨平台通用
- 排程:systemd user timer `~/.config/systemd/user/political-watch.{timer,service}`(OnUnitActiveSec=15min)
  Linger=yes,免登入 24/7 跑。診斷:`systemctl --user list-timers political-watch.timer`
- 手動測:`cd political_watch && python3 watch_x.py --dry`

## session 失效時(X 登出/cookie 過期)
1. 在 Mac:`python3 watch_x.py --login` 重登 → 產新 auth_state.json
2. base64 搬到 winrig 同目錄(秘密檔走 MCP/ssh,不進 git)

## worker 端零改動
- `/political-ingest`、`POLITICAL_INGEST_TOKEN`、Claude 判讀、LINE/web push 管線全照舊
- CF worker 新聞政治關鍵字線(2min cron)繼續當 24/7 保底
- Grok x_search 線(需 xAI credits)照舊

## Mac 端已退役
- launchd `com.marketdaily.politicalwatch.plist` → unload + 改名 `.disabled-winrig-takeover`
- watch_safari.py / scrape_safari.applescript 留檔當歷史,不再跑
