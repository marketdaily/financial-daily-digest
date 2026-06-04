# 家用 Windows 24h 主機 — 採購 + Setup 指南

---
## ★ 選定清單(2026-06-03 定案)

### 主機(選定)— 華碩 黑曜之刃 W 水冷機 NT$95,311(折後)
momo 華碩平台 R7 八核 RTX5080 Win11(i_code 15102054/55)
- CPU **Ryzen 7 9800X3D** / GPU **華碩 RTX 5080 16GB** / 32GB DDR5(Kingston FURY)/ **1TB** M.2 Gen4 / B850 / 水冷 / **WiFi 6E** / **Win11 已含** / 1 年保
- **升到 5080 的理由**:頭顯改 Pimax Crystal Light(高解析吃顯卡),5070 Ti 跑 F1 要調設定,5080 才從容
- ⚠️ **只有 1TB SSD** → 遊戲+4K素材+VR 很快滿,之後自加一顆 2TB M.2(~NT$3,500,B850 有第二槽)
- 32GB 之後重度 4K 剪片覺得緊再自加到 64GB(便宜易升)
- (前一候選 MSI 5070Ti NT$84,695 已被這台取代)

### 螢幕 — 2× LG 27G610A-B(27" 1440p, 主 200Hz)約 NT$10,980
### 桌子 — IKEA MITTZON 電動升降桌(160×80 或 140×80)約 NT$11,799
### 音響 — Edifier G1500 MAX 2.1(含重低音)NT$2,690

### F1 VR Sim Racing(一次到位 B 版)≈ NT$88,000
| 部位 | 產品 | 約 NT$ |
|------|------|--------|
| 頭顯 | **Pimax Crystal Light** $899 +(選配 DMAS 離耳音響 $99.90)+ 運 $40 = US$1,038.90 ≈ **NT$33,560**(Pimax 官網進口,有線 DP+USB)。不要 8KX | ~33,560 |
| 力回饋底座 | **MOZA R12 V2**(RS081, 12Nm)— **樂天米特3C 台灣公司貨 7%折 NT$11,151**(在地保固,改不進口了) | 11,151 |
| 方向盤 | **MOZA FSR2**(RS068, F1 方程式造型) | 17,980 |
| 踏板 | **MOZA mBooster 主動踏板**(RS082, 馬達主動回饋模擬ABS/鎖死;比 CRP2 高一階的奢侈升級) | 28,490 |
| 座艙 | **NLR F-GT PRO 圓形鋼管**(GT+F1 雙坐姿可轉換,比 Playseat 更剛性) | 32,900 |

注意:
- 核心三件(R12+GS V2P+SR-P ≈ 33,500)是 F1 手感靈魂、買了不用換;找 MOZA 套裝組有整組優惠;座艙最能省。
- **Crystal Light 是有線(DP+USB),不能無線** → rig 要擺在主機 ~5m 內,或拉光纖 DP 延長;**WiFi 路由器免買**。
- F1 24/25 PC 版內建 VR;**主機已升 RTX 5080** 配 Crystal Light,F1 跑得從容(故主機從 5070Ti 換 5080)。
- rig 上不用裝螢幕(VR 在頭顯裡);桌上 2 螢幕做正事,兩不相干。

---


> 目的:一台永遠開機的 Windows 桌機，當「家裡的大腦」。
> 24h 跑 Claude Code、遠端操控、看盤、偶爾遊戲、4K 剪片、未來 VR sim racing。
> MacBook 帶出門當行動端，原本東西全留著不丟。

---

## 一、採購清單（一次到位版，買完五年不用換主機）

| 零件 | 建議 | 備註 |
|------|------|------|
| 顯卡 GPU | RTX 5080 | VR sim racing + 遊戲 + 4K 剪片全包；5090 CP 值差不用 |
| CPU | Ryzen 7 9800X3D | sim racing/遊戲最強單核+3D快取 |
| 記憶體 | 64GB DDR5 | 剪片+看盤+24h Claude Code 同開永不卡 |
| 系統碟 | 2TB NVMe SSD | 系統+遊戲+素材都放得下 |
| 電源 | 850W 80+ 金牌 | 餵飽 5080 + 24h 常開留餘裕 |
| 散熱 | 360 水冷 或 高階塔散 | 24h 重載壓溫度 |
| 螢幕 | 2 台（可挑高刷新） | 看盤一台、剪片/遊戲一台 |

> 未來唯一會加的只有「放影片的第二顆硬碟」，主機本體不動。

**購買路線**
- 省事：品牌整機（技嘉/微星/ROG）照規格挑
- 省錢：原價屋/欣亞線上估價單填零件請店家組，同規格便宜 2–4 成

---

## 二、Setup 流程總覽

**為什麼分兩段**：Claude 現在跑在 MacBook，跟新機沒連線。要遠端進去，得先有連線管道，
但管道本身要先在新機上裝起來 → 開頭一小段只能人親手做，通了之後 Claude 遠端全接手。

---

## Phase 0 — 你本人坐在新電腦前（約 15 分鐘，照貼）

### 0-1 開 WSL2（Linux 環境）
以系統管理員開 PowerShell，貼：
```powershell
wsl --install
```
裝完重開機，設 Ubuntu 的使用者名稱+密碼。

### 0-2 裝 Tailscale（從外面連回家的加密私網）
- 下載：https://tailscale.com/download/windows
- 安裝後用同一個帳號登入（**delvin.12345678@**，MacBook 已裝同帳號 → 兩台自動互通）
- 記下這台 Windows 在 Tailscale 顯示的 IP（100.x.x.x）

### 0-3 開遠端桌面 RDP
設定 → 系統 → 遠端桌面 → 開啟。

### 0-4 電源永不睡眠
設定 → 系統 → 電源 → 螢幕與睡眠 → 「睡眠」全部設「永不」。

### 0-5 WSL 裡開 SSH（讓 Claude 能進來）
WSL 終端機貼：
```bash
sudo apt update && sudo apt install -y openssh-server
sudo service ssh start
```

### 0-6 回報給我
把這台的 **Tailscale IP** + WSL 使用者名稱告訴我。連線一通，後面我接手。

---

## Phase 1 之後 — Claude 遠端接手（你不用管）

1. WSL2 裝 Node + Python + git + Claude Code
2. 架 tmux 持久階段（斷線/闔蓋任務不停）
3. 搬要常駐的專案 repo / 設定過去
4. 架遠端 MCP tunnel（手機 Claude App 也能指揮）
5. 設開機自動啟動 WSL + ssh + tunnel → 24h 不關
6. 全測：MacBook 連回家 / 闔蓋後任務續跑 / 手機能連

---

## 四、本地 LLM 跑什麼（零 API 成本的 24h 雜活引擎）

> 用 Odysseus（pewdiepie-archdaemon/odysseus）的硬體適配公式算出來的真實落點，不是 spec sheet 嘴砲。
> 生成速度本質是記憶體頻寬瓶頸：`tok/s ≈ GPU頻寬 ÷ 模型大小(GB) × 0.55`。
> 這台：**5080 = 16GB VRAM、960 GB/s**。瓶頸是 VRAM，不是 32GB 系統 RAM。

| 模型級距(Q4) | 大小 | 落點 | 估算速度 | 用途 |
|---|---|---|---|---|
| 7–8B | ~4GB | 全進 GPU ✅ | ~120 t/s | 快任務:分類、抽取、爬蟲後處理 |
| 14B | ~7.5GB | 全進 GPU ✅ | ~70 t/s | 一般雜活、初稿 |
| **24B** | ~13.5GB | 全進 GPU ✅ | **~40 t/s** | **主力甜蜜點** |
| 32B | ~18GB | 溢出到 RAM ⚠️ | ~15–20 t/s | 偶爾要點品質再忍速度 |
| 70B | ~38GB | 大量 offload ❌ | ~5 t/s | 不實用，別跑 |

**真實天花板 = 14–24B 全 GPU 跑。70B 是幻想（VRAM 不夠）。**

### 到貨後裝這三隻（Ollama，一行下載）
```bash
# 主力（雜活/初稿，~40 t/s）
ollama pull qwen2.5:32b-instruct-q4_K_M   # 想穩在全GPU可改 qwen2.5:14b
# 快任務（分類/抽取，~120 t/s）
ollama pull qwen2.5:7b-instruct-q4_K_M
# embedding（本地 RAG/記憶向量，零成本）
ollama pull nomic-embed-text
```

### 把這台當「夜班工廠 + GPU 算力房」的真實用途
- **省現金**：貓咪影片 Seedance 一支 US$3–5、虛擬模特 Flux → 5080 本地跑 SDXL/影片模型 + 本地訓 LoRA，邊際成本歸零
- **轉錄提速**：股癌 666 集 mlx-whisper(Mac 2–3 天) → GPU faster-whisper 快一個量級
- **quant 算力**：交易 bot 萬級參數 sweep + Deflated Sharpe 一晚跑完，不再 28-cell 自欺
- **本地 RAG**：memory 系統/knowledge-ops/股癌詞典上本地向量庫，檢索零 API 成本、不外洩
- **分工原則**：前沿品質(日報明牌/交易決策)走 Claude/Gemini API；不值得花 API 錢的常駐雜活走本地 24B

---

## 三、日常使用心智模型

```
你人在外面
  MacBook（只是遠端視窗）
   │ Tailscale 加密連回家
家裡 Windows（永遠開機）
   └ WSL2 裡的 Claude Code（在 tmux 裡，斷線不停）
        └ 程式建在家裡、跑在家裡
```

- 程式不在 MacBook 上 → 你闔蓋走人，家裡照跑
- 重連（MacBook 或手機 Claude App）→ 接回原進度

---

## 五、到貨後安裝清單（SSH 一通,我照這清單一路裝）

> 圖例:🤖 = 我自動裝好設好 ／ 🧑 = 非我不可(物理校準/帳號登入/UAC 提權)
> Windows 程式我透過 WSL interop 呼叫 `winget` 靜默安裝;winget 沒有的(Pimax/MOZA)我下載官方 installer,提權那下你點。

### A. WSL Linux 側 — 全 🤖
- Node.js + Python3 + git + tmux + **Claude Code**(`npm i -g @anthropic-ai/claude-code`)
- `git clone delvin-claude-brain` → `bash restore.sh /home/<user>/Delvin-agent`(記憶/技能/設定還原)
- clone 各專案 repo(MarketDaily / trading_bot / 各 side project)
- **Ollama + 本地模型**(qwen2.5:32b 主力 / 7b 快任務 / nomic-embed) — 見第四節
- 架 tmux 持久 + 遠端 MCP tunnel + 開機自動啟動 → 24h 常駐

### B. Windows 一般程式 — 🤖(winget 靜默)
| 類別 | 程式 | winget id |
|---|---|---|
| 系統 | PowerToys / 7-Zip / Brave 或 Chrome | `Microsoft.PowerToys` `7zip.7zip` `Brave.Brave` |
| 開發 | VS Code / Git for Windows | `Microsoft.VisualStudioCode` `Git.Git` |
| GPU | **NVIDIA App**(驅動) | `Nvidia.NvidiaApp` 🧑可能要重開機確認 |
| 通訊 | Discord | `Discord.Discord` |

### C. Sim Racing VR
| 步驟 | 誰 |
|---|---|
| 裝 Steam / SteamVR / EA app / F1 24·25 | 🤖 `Valve.Steam` `ElectronicArts.EADesktop`;遊戲帳號登入🧑 |
| 裝 **Pimax Play**(官網 installer) | 🤖 下載+觸發,提權🧑 |
| 裝 **MOZA Pithouse**(官網,方向盤/底座/踏板韌體+校準工具) | 🤖 下載+觸發,提權🧑 |
| 把 F1 的 VR 設定 / 力回饋參數預設檔放好 | 🤖 |
| **頭顯 room setup + IPD 瞳距校準** | 🧑 戴頭顯,我引導 |
| **方向盤定中 / 踏板行程校準 / 韌體更新** | 🧑 接 USB 實體操作,我引導 |

→ 我先把軟體全裝好,硬體接好後一起花 ~20 分鐘校準

### D. 剪片 — 近全 🤖
| 程式 | winget / 來源 |
|---|---|
| **DaVinci Resolve**(主力,免費強) | `BlackmagicDesign.DaVinciResolve` |
| OBS Studio(錄製/串流) | `OBSProject.OBSStudio` |
| HandBrake(轉檔) | `HandBrake.HandBrake` |
| ffmpeg(WSL 側 pipeline) | 🤖 apt |
- 🤖 建好素材庫資料夾結構 + 串好現有影片線(貓咪 TikTok / 太空 YT / 虛擬模特)的本地 GPU 生成→轉檔→剪輯流程
- 🧑 僅:Adobe 才需登入 / 開始剪

### 留給你的總共就三類
**① 戴頭顯接硬體校準 ② 帳號登入 ③ 少數 UAC 點「允許」** —— 每下我即時引導,你不用查任何東西。
