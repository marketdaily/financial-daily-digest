# local_video — winrig 5080 本地 AI 影片(零元,Tier 0)

- 引擎:ComfyUI portable 0.33.1(Windows 原生,`C:\AI\ComfyUI_windows_portable`),torch 2.11+cu128(驅動 572.83 跑不了預設 cu130,已換);排程任務 `ComfyUI_headless`(登入自啟,`schtasks /Run /TN ComfyUI_headless` 手動起;用 pythonw 無主控台,否則 MCP 呼叫結束會 window-CLOSE 連坐)
- 服務:`http://172.31.144.1:8188`(WSL 打 Windows host IP;NAT 模式 localhost 不通),log `C:\AI\comfy.log`(cp950,讀要 iconv)
- 模型:Wan 2.2 TI2V-5B fp16(10GB)+ umt5_xxl fp8(6.7GB)+ wan2.2_vae → `ComfyUI\models\{diffusion_models,text_encoders,vae}`
- 用法:`python3 run_wan.py "prompt" [--w 1280 --h 704 --len 121 --steps 20 --seed N --prefix name]` → 輸出在 `C:\AI\ComfyUI_windows_portable\ComfyUI\output\<prefix>_0000N_.mp4`
- 實測 2026-08-17:832x480/49f/15步 = 56s(含載模);1280x704/121f(5s@24fps)/20步 = 293s;VRAM 峰值未爆(dynamic VRAM loading),主機 RAM 剩 <9GB(WSL 佔 14GB)是瓶頸,LTX-2.3(22B/46GB)與 Wan 14B 不要在這台試
- 定位:B-roll/背景動態/產品推鏡的零元量產;hero 鏡頭仍走 Higgsfield(畫質高一代)
