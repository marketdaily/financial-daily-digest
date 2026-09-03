# Sidekick — 24 小時盯螢幕、用講的教你做事的助理（設計規格）

日期：2026-09-03　狀態：待老闆核可後開工　專案目錄：`~/sidekick`（獨立 repo，不進 Delvin-agent）

## 1. 目標與驗收

**一句話**：只要 winrig 或 Mac 醒著，Sidekick 就在看老闆的螢幕；老闆卡住時（自己問、或它看出來）它用講的告訴他下一步；講了還不懂就在螢幕上圈給他看。全程不花現金。

**驗收（老闆親測）**
1. 在任一台電腦打開一個沒用過的網站設定頁，按熱鍵或講「我卡住了」→ 10 秒內聽到中文語音講下一步。
2. 說「指給我看」→ 畫面上出現圈選框與短字，游標與焦點都沒被動到。
3. 同一畫面來回超過 90 秒沒進展 → 它主動開口問要不要幫忙（不會在正常工作時亂講）。
4. 晚上收到手機推播「今天做了什麼／待辦／沒解決的」。
5. 連續跑 24 小時：Anthropic 帳單 0 元、Claude 訂閱額度沒被撞滿（升級呼叫有上限）。

**不做**：不接管滑鼠鍵盤（winrig 鐵則）、不做手機端、不錄整天對話音檔（第三階段另開）。

## 2. 架構：看＝本機免費、教＝Claude 訂閱

```
Mac (Hammerspoon)  ─┐  截圖(變化才送)/問題/語音    ┌─ watch.py  本機 VLM qwen3.5:9b (Ollama, 5080) → timeline.db
                    ├──HTTPS/token──▶ server.py ────┤
winrig (AHK v2 +    ─┘  8990, FastAPI                └─ teach.py  claude -p --resume (cwd ~/Delvin-agent, 全記憶/技能)
 PowerShell 擷取)        ◀── SSE: say / show / done ──┘         └─ quota guard: 每小時/每日上限, 429 退本機模型
                                                       recap.py 每晚 1 次 Claude → web push + Markdown
```

**分工鐵律**
- 「看」層（每 2 秒、24 小時）只做三件小事：他在做什麼、有沒有錯誤視窗、像不像卡住。實測 qwen3.5:9b 一張 1.6 秒、正確認出「左 Ubuntu 終端機、右 marketdaily.ai/watch」，0 元。
- 「教」層（需要開口時）100% Claude：`claude -p` 走老闆的 Claude 訂閱（不是 API 付現）。實測 haiku 一張 88K token/US$0.04 額度、9 秒，因此**教層每小時最多 20 次、每日 150 次**，超過或 429 → 本機模型代答並明講「Claude 額度滿了，X 點恢復」。
- 現金支出 = 0。唯一「費用」是訂閱額度，且有守衛。

## 3. 元件

### 3.1 server.py（winrig WSL，systemd user service `sidekick.service`，port 8990）
- `POST /frame`：{device, ts, jpg(≤1280px), app_title, idle_s}。存 `data/frames/<device>/<ts>.jpg`（保留 24h 滾動刪除），丟進 watch 佇列。
- `POST /ask`：{device, text? , wav?}。wav → faster-whisper large-v3（沿用 `~/jarvis/core/stt.py` 的 `_pick_lang` 中文偏好）→ text。進 teach。
- `GET /events/<device>`：SSE。事件 `say{text}`、`show{boxes:[{x,y,w,h,label}], text}`、`status{mode}`。
- `POST /mode`：{device, mode: watch|quiet}（老闆說「安靜」就只留熱鍵）。
- 認證：`Authorization: Bearer <SIDEKICK_TOKEN>`（`.env`，不進 git）。

### 3.2 watch.py（本機 VLM tick）
- 只處理「變化」：dhash 與上一張差異 < 3% 直接丟；idle_s > 180 不處理（人不在）。
- 呼叫 Ollama `qwen3.5:9b`（`think:false`，`num_predict:200`），回 JSON `{doing, app, error, stuck}`；壞 JSON 重試一次後記 `parse_fail`。
- 寫 `timeline.db`（sqlite）：ts, device, app, doing, error, stuck, frame_path。
- **卡住偵測**（純程式，不靠模型情緒）：同 device 連續 90 秒內 `doing` 語意相同（nomic-embed 相似 > 0.9）且畫面有小變化（來回點）、或 `error=true` 連續 2 tick → 發 `escalate(reason)`。每個 reason 冷卻 10 分鐘，避免碎唸。
- GPU 預算：qwen3.5:9b 6.6G + whisper 3G + F5 2G ≈ 12G/16G。Tuna 的聊天模型同步改用 qwen3.5:9b（一個模型兩邊用），不再載 qwen2.5:7b。

### 3.3 teach.py（Claude 層）
- 一個「任務 session」= 一條 `claude -p --resume <id>` 對話（`cwd=~/Delvin-agent`，帶全部記憶/技能；模型 `claude_model heavy`＝opus 降 sonnet，來源 `scripts/lib_cron_runner.sh`，不自寫 `--model`）。session 閒置 2 小時自動換新。
- 輸入：最新截圖路徑 + 最近 10 條 timeline + 老闆問題（或 escalate reason）+ `--append-system-prompt` 固定規則：一次只講一步、繁中口語、≤2 句、**只回 JSON** `{say, show:[{x,y,w,h,label}]|null, done, ask_back}`；座標以送入圖的像素為準，server 依 device 原始解析度換算。
- 「幫我查 X／幫我做 X」：同一 session 自己用工具查完再回，但工具白名單排除任何會動老闆滑鼠鍵盤的路徑（pyautogui/SendInput 已被全域 CLAUDE.md 禁止）。
- 額度守衛：sqlite 計數；超限或 stdout 帶 `rate_limit` → 走本機 qwen3.5:9b 用同一 prompt 代答，`say` 前綴「（Claude 額度滿，先用本機模型答）」，並 push 一次告警給老闆。
- 輸出經 `say` 事件先講；`show` 只在老闆說「指給我看／show me」或 `ask_back` 為 true 且 30 秒內沒回應時才推。

### 3.4 嘴巴
- winrig：沿用 `~/jarvis/core/mouth.py`（F5 陳華聲，掛了退 Kokoro），paplay 出喇叭，無視窗。
- Mac：Hammerspoon `hs.speech`（內建 `Meijia` zh_TW），0 元離線。第二版可改成 winrig 合成 wav 傳回播放（同一個聲音）。

### 3.5 耳朵
- winrig：Tuna 已有喚醒詞「Tuna」；在 `~/jarvis/core/brain.py` 加一個 intent：句子含「卡住／怎麼做／下一步／指給我看／幫我看螢幕」→ 轉發 `POST /ask`，由 Sidekick 回答並用 Tuna 嘴巴講。熱鍵 `Ctrl+Alt+/` 也可打字問。
- Mac 第一版：按住 `⌥⌘/` 講話（push-to-talk，`ffmpeg -f avfoundation` 靜態 binary 錄 wav），放開即上傳；短按彈打字框。喚醒詞留第二版。

### 3.6 擷取端
- **winrig**：`agent_win/capture.ps1` 單一常駐 PowerShell 迴圈（隱藏視窗，每 2 秒 `CopyFromScreen` 主螢幕 + 前景視窗標題 + `GetLastInputInfo` 閒置秒數 → 縮 1280 寬 JPEG → POST localhost:8990/frame）。`agent_win/sidekick.ahk`（AutoHotkey v2，winget 安裝）：熱鍵、浮窗（`+E0x20` click-through、`WS_EX_NOACTIVATE` 不搶焦點）、圈選框（同上）、SSE 客戶端。兩者由 Windows 排程「登入時」啟動，不出現任何視窗。
- **Mac**：Hammerspoon（GitHub release zip 直裝 `/Applications`，登入啟動）。`~/.hammerspoon/init.lua`：`hs.timer` 2 秒 `hs.screen.mainScreen():snapshot()` → 縮圖 → POST；`hs.host.idleTime()` 閒置門檻；`hs.hotkey` 熱鍵；`hs.canvas` 浮窗與圈選（`clickActivating(false)`、level overlay、不搶焦點）；`hs.speech` 講話。需老闆一次性允許：螢幕錄製、輔助使用、麥克風。Hammerspoon 用 Login Item 自啟，不新增 LaunchAgents plist；仍在 `~/.mac-guard/allowlist.txt` 註記一行備查（老闆已核可）。
- **傳輸**：Mac → `https://sidekick.marketdaily.ai` → 既有 `cb-tunnel`（`~/.cloudflared/cb-config.yml` 加一條 ingress → 127.0.0.1:8990，`cloudflared tunnel route dns`），winrig 端走 localhost。

### 3.7 記憶與回顧
- `recap.py`（cron 22:30 TW，Claude 1 次/日）：讀當日 timeline → 「做了什麼／待辦／未解問題」→ web push 手機（既有 alert-worker 推播）+ 寫 `~/sidekick/recaps/YYYY-MM-DD.md` 並鏡進 Obsidian vault `Sidekick/`。
- 「我今天做了什麼／答應了誰」：`/ask` 偵測回顧型問題 → teach 帶當日 timeline 全文回答。

## 4. 錯誤處理
- Ollama 掛：watch 停、記 `watch_down`，教層照常（老闆問仍能答）；每 5 分鐘自癒重試；連續 15 分鐘 push 一次。
- Claude 429/逾時：見 3.3 守衛；逾時 40 秒先講「我在看，再等一下」。
- 擷取端斷線：server 60 秒沒收到 frame 標 `device_offline`，不告警（人可能關機）；Mac 隧道死 → Hammerspoon 本地退 `hs.speech` 講「連不到 winrig」。
- 假死防線：`logs/ok/sidekick.ok` 戳記（沿用艦隊 `logs/ok` 契約），夜巡看最後成功時間。

## 5. 測試（老闆不在也能驗）
- `tests/test_watch.py`：3 張固定截圖（設定頁、錯誤對話框、終端機）→ JSON 合法、`error` 判對。
- `tests/test_stuck.py`：合成 timeline（來回 90 秒／正常工作）→ 只有前者觸發，冷卻生效。
- `tests/test_teach_schema.py`：mock claude 輸出 → schema 驗證、座標落在圖內、超限退本機。
- `tests/test_quota.py`：模擬 429 → 代答 + 告警一次。
- 擷取端 dry-run：Windows/Mac 各跑 30 秒，server 收到 ≥ 10 張、SSE 能推一則 `say`。
- e2e：老闆按熱鍵一次（驗收 1-2）。

## 6. 實施計畫
| 階段 | 內容 | 驗 |
|---|---|---|
| P0（今天） | `~/sidekick` repo、server.py、watch.py、timeline、systemd、cb-tunnel ingress | tests 1-2、curl /frame |
| P1 | winrig 擷取（PowerShell 迴圈）+ AHK 熱鍵/浮窗/圈選 + Tuna 嘴巴/intent + teach.py + 額度守衛 | tests 3-4、dry-run、老闆 e2e |
| P2 | Mac Hammerspoon 全套 + 權限引導 + allowlist 註記 | dry-run、老闆 e2e |
| P3 | recap.py + 推播 + Obsidian 鏡像 + 回顧型問答 | 首班實射 |
| P4 | Mac 喚醒詞、winrig 合成聲傳 Mac | — |

## 7. 風險
- Mac 權限沒點 → 截圖全黑：安裝後第一次 tick 偵測全黑即語音提示去點。
- 訂閱額度：守衛在，且看層不碰 Claude；仍要在 status 頁顯示今日用量。
- 隱私：截圖 24 小時滾動刪、timeline 文字長存於本機；只有教層把當下那張圖送 Anthropic。
