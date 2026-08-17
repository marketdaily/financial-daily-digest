# 手勢遙控機械臂 → 示範學習:SO-101 + LeRobot 執行計畫(2026-08-17)

> 拍板:Delvin 2026-08-17 選定方向 2(AI×硬體主線)。本檔=查證後的可執行計畫,不是概念。
> 一句話:**攝影機看你的手 → SO-101 從動臂同步 → 錄幾十次示範 → winrig 5080 訓 ACT → 手臂自己做**。每個里程碑=一支片。

## 0. 為什麼是 SO-101(查證 2026-08)
- 現在最便宜、社群最大的開源模仿學習入口:6 軸、Feetech STS3215 匯流排伺服、Hugging Face LeRobot 原生支援(校正/遙操作/錄資料/ACT/SmolVLA 一條龍)
- 海外套件價 ~US$199/臂(leader+follower 要兩臂);台灣三家有現貨(機器人王國/ICShop/PlayRobot),不必等海運
- 手勢遙操作已有人做通(見 §3),但**沒有中文創作者在做「手勢遙操作 + 教它自學」系列**——bilibili 只有組裝教學,台灣 YouTube 零

## 1. BOM(三選一;推薦 A)
| 方案 | 內容 | 價格 | 到手 |
|---|---|---|---|
| **A 全組好+校正+雙鏡頭**(機器人王國) | leader+follower 兩臂組好校正、12 顆 STS3215(follower 12V C018×6、leader 7.4V 三種齒比)、2 控制板、電源、**2 台 AVerMedia PW315 FHD 鏡頭**(1 台已裝在 follower)、收納箱、4 個 C 夾 | **NT$18,060 含稅** | 庫存 1(可無庫存下單),3–5 工作天 |
| B Pro 套件不含 3D 列印件(機器人王國) | 同上馬達/板/電源,**沒殼沒鏡頭**;殼要自己印(GitHub TheRobotStudio/SO-ARM100 STL)或找代印(估 NT$1.5–3k) | NT$9,975 含稅 | 庫存 2 |
| C 海外(Seeed/WowRobo/Amazon) | ~US$199–260/臂,運費+關稅+2–4 週 | 兩臂 ≈ NT$14–18k | 慢 |

**推薦 A**:目標是內容節奏與學到「示範學習」,不是學組裝;省下的 3–4 小時組裝+校正踩坑=多一支片。B 只在想要「組裝過程」當第一支片時才選。
另外要準備:USB hub、桌面 60×60cm 白色/素色工作面(鏡頭辨識穩)、幾個練習物件(積木/高爾夫球/馬克杯——**高爾夫球=第一個任務物件,跟你的人設接得上**)。

## 2. 系統架構(誰跑什麼)
```
[Mac]  USB 直連 leader/follower + 鏡頭 ── LeRobot(校正/遙操作/錄資料/推論)
  │            ▲
  │ 資料集(HF Hub 或 rsync)   │ 訓好的 policy 拉回來跑
  ▼            │
[winrig RTX 5080 16GB] ── 訓練 ACT / 微調 SmolVLA(WSL2 CUDA 可用,已驗 nvidia-smi 5080)
```
- **機器人主機=Mac**:LeRobot 官方支援 macOS,USB 序列埠直接看得到;不違反「Mac 純視窗」鐵則(那條管的是大腦/git/排程,不是互動式硬體 session;而且不加 launchd)
- **winrig 只做訓練**:理由①WSL2 要吃 USB 得裝 usbipd-win(現在沒裝,實測 `/mnt/c/Program Files/usbipd-win` 不存在),多一層不穩②WSL 記憶體上限 14GB(`.wslconfig`),訓練夠、跑即時控制迴路+鏡頭沒必要擠這裡
- ⚠️ winrig 系統 Python 是 3.14——LeRobot 要 3.10–3.12,**開獨立 venv/uv 環境**;RTX 5080 是 Blackwell(sm_120),PyTorch 要 ≥2.7 + cu128 輪子,舊版會 `no kernel image`
- 手勢引擎(MediaPipe/WiLoR)在 Mac 端跑即可(MediaPipe CPU 30fps 夠;WiLoR 要 CUDA,先不用)

## 3. 手勢 → 手臂映射(兩條路,先走 ①)
① **直接關節映射(零 IK,兩天做完)**:MediaPipe Hands 21 點 → 手腕 (x,y) 控肩 pan/lift、手到鏡頭距離(手掌大小)控 elbow、手腕角控 wrist、**拇指-食指捏合距離控夾爪**。加 Kalman/EMA 平滑、死區、限速。這是 IG 上「手一動臂就動」的效果,足夠拍片,也足夠當「錄示範」的輸入裝置。
② **IK 映射(第二版)**:手腕 3D 位置 → 末端目標 → IK 解 6 軸(pinocchio/pyroki)。姿態自然但要調很久;Joeclinton1/hand-teleop 走的是直接關節輸出+WiLoR,fork 對新版 LeRobot 已過期(作者自述),只當參考不直接用。
③ 備案:leader 臂本來就是最好的示範輸入(這也是套件附兩臂的原因)。**手勢版=內容;leader 版=生產**。錄 50 集示範時哪個順手用哪個。

## 4. 里程碑 × 內容(每一格=一支片)
| # | 里程碑 | 技術驗收 | 片(hook 借 swipe M 段公式:實體物+一句話+一畫面) |
|---|---|---|---|
| 0 | 到貨前:手勢引擎 | Mac webcam → 6 個關節值即時輸出到螢幕虛擬臂(matplotlib/three.js) | 「我先教電腦看懂我的手」(手在鏡頭前,螢幕上的線框臂跟著動)|
| 1 | 開箱→校正→leader/follower 遙操作 | `lerobot-calibrate` 兩臂、`lerobot-teleop` 跟手 <100ms | 「200 美金的機器手臂,開箱 30 分鐘就會跟我的手」|
| 2 | 手勢遙操作 | 手勢引擎 → follower;夾爪捏合可抓起高爾夫球 | **這就是你看到的那種片**:手隔空一捏,手臂夾起球 |
| 3 | 錄示範 → 訓 ACT → 自主執行 | 50 集(單一任務、位置微變)→ winrig ACT ~100k steps(5080 估 2–4h)→ 回 Mac 推論,成功率 ≥7/10 | 「我教它 50 次,它自己學會了」(左畫面示範/右畫面自主)|
| 4 | 語言指令 | SmolVLA 微調(450M,5080 可訓)→「把球放到杯子裡」 | 「我用講的,它聽得懂」|
| 5+ | 任務系列 | 每支片一個新任務(擺 tee/收球/分色/遞東西) | 「我在家花 200 美金教機器人幫我___」系列 |

拍法固定:三機位——俯視(工作面)、側面(臂+手)、手機錄螢幕(訓練 loss/推論畫面);每支片必有「失敗片段」(掉球、抖動)——這類內容失敗比成功留言多。

## 5. 週計畫(以 A 方案下單日為 D0)
- D0:下單 A;Mac 建 LeRobot 環境(`uv venv -p 3.12`、`pip install lerobot[feetech]`);winrig 建訓練環境(3.12 + torch cu128,跑一次 LeRobot 官方 aloha 小資料集訓練 smoke test 確認 5080 kernel OK)
- D0–D3:手勢引擎(里程碑 0)+ 拍片 0
- D3–D5:到貨,校正、teleop、拍片 1;同天開始用 leader 錄第一個任務(高爾夫球→杯)
- D5–D8:手勢版接上 follower(里程碑 2)、拍片 2
- D8–D12:錄滿 50 集、winrig 訓 ACT、Mac 推論、拍片 3
- 第 3 週起:SmolVLA + 任務系列

## 6. 已知的坑(先寫下來)
- LeRobot API 改版頻繁(hand-teleop 就是這樣壞的)——**釘版本**,requirements 鎖 commit
- 伺服過熱/堵轉:follower 撞到桌面會燒馬達,先加軟體關節限位與扭力上限;12V 電源別接到 7.4V leader
- 校正一次就好,但換 USB 埠會換 port 名(`lerobot-find-port`)
- 錄資料的「位置微變」要刻意做(每 10 集換球的位置),不然 ACT 只會背一條軌跡
- 鏡頭:自主推論時的鏡頭位置必須跟錄示範時**一模一樣**,用 C 夾固定,拍片時別動它
- Blackwell:`pip install torch --index-url https://download.pytorch.org/whl/cu128`,否則卡在 sm_120

## 7. 需要 Delvin 決定的兩件事
1. 買 A(NT$18,060,全組好)還是 B(NT$9,975+自印殼)——我建議 A
2. 手臂放哪:建議放你 Mac 桌上(USB 直插),winrig 只負責訓練

## 來源
- 機器人王國 Pro 套件 NT$9,975:https://robotkingdom.com.tw/product/so-arm101-ai-arm-kit-pro/
- 機器人王國 全組好+PW315×2 NT$18,060:https://robotkingdom.com.tw/product/so-arm101-ai-arm-kit-pro-3d-assembly-pw315/
- ICShop / PlayRobot 亦有 SO-ARM101 Pro
- 海外價 ~US$199/臂:https://www.roboticscenter.ai/hardware/so-101 、Seeed/WowRobo/Hiwonder
- 手勢遙操作先例:https://github.com/Joeclinton1/hand-teleop (LeRobot fork 過期)、https://thinkrobotics.com/blogs/learn/lerobot-so101-hand-tracking (RPi5+MediaPipe)、VR 版 https://github.com/Oasis-Uniandes/lerobot_teleoperator_so101_vuer
- LeRobot SO-101 官方/Seeed wiki:https://wiki.seeedstudio.com/cn/lerobot_so100m_new/ ;NVIDIA sim-to-real 課:https://docs.nvidia.com/learning/physical-ai/sim-to-real-so-101/latest/04-lerobot.html
- SmolVLA 450M:https://learnopencv.com/smolvla-lerobot-vision-language-action-model/
