# MarketDaily × Seedance 2.0 — 30 秒行銷影片 Prompt 包(定稿)

> 依據:BytePlus 官方《Dreamina Seedance 2.0 series prompt guide》(ModelArk 2222480)+ ByteDance Seed 官方發布文 + 2026-07-09 實戰(Higgsfield/Seedance 2.0,16:9 與 9:16 各一輪全數一次過)。
> 硬限制:單次生成上限 **15 秒**多鏡頭含音訊 → 30 秒 = 兩段 15 秒拼接。
> 官方公式:`精確主體 + 動作細節 + 場景環境 + 光線色調 + 運鏡 + 視覺風格 + 畫質 + 約束條件`。
> 音訊符號:`（）`=音樂、`<>`=音效、`{}`=台詞、`【】`=字幕;台詞單一語言不可中英混。
> 鐵則:每鏡只用一種運鏡;不寫每鏡秒數(官方明說計時不穩);直版亂字幕機率較高,約束句放 prompt 最後一行。
> **⚠️ 一次到位鐵則(2026-07-09 用戶指令)**:送生成前 Preflight(§5)全綠才按;改進意見折進本檔定稿,等下支影片/下期額度才用;額度見底只做零成本後製。

---

## 0. 生成前準備

**資產(上傳順序 = 優先權)**:
| 順序 | 資產 | 要求 |
|------|------|------|
| Image 1 | MarketDaily logo 高清 PNG | `docs/logo.svg` 以 rsvg-convert 黑底渲染 1260w |
| Image 2 | 公版日報 email 截圖 | **必須縮樣到所有價位數字不可辨識**(縮到 12.5% 再放大+GaussianBlur 1.2;原圖滿版進出場價,直接餵=違反「影片絕不上買賣價位」) |

**生成設定(Higgsfield CLI,cost 先估價)**:
- Reels 主戰場:`--aspect_ratio 9:16`;網站/YouTube:`16:9`。**要哪個就原生生成哪個,禁止橫版硬裁直版**
- 15 秒 / `--mode std` / `--generate_audio true`;解析度:1080p=135 credits/段、4K=330/段(720p 減半)
- Clip 1 加 `--genre epic`

---

## 1. 方案 A 定稿:牛熊對撞 → 秩序誕生 → 產品揭示

> 下面是 9:16 直式版(主發行版)。要 16:9 時:首行 `vertical 9:16` 改 `16:9`,並刪去所有「vertical frame / upper two-thirds」構圖句(16:9 已實戰驗證同樣一次過)。

### Clip A-1(0–15s,T2V,不用資產,--genre epic)

```
Epic cinematic financial-market spectacle in vertical 9:16 composition, premium brand-film quality, HD, rich details, cinematic texture, deep-space black palette with electric blue and amber-gold accents, volumetric lighting, dramatic rim light, shot on a cinema camera.

Shot 1: The opening frame is already mid-action: a colossal bull sculpted from molten bronze light fills the lower half of the vertical frame, charging straight toward the camera in a low-angle shot, hooves striking sparks of golden data particles off an obsidian plain etched with glowing candlestick charts; towering columns of K-line light rise like skyscrapers along both edges of the vertical frame. <thunderous hoofbeats and a deep rumbling roar>（dark, driving cinematic percussion at high tempo）

Shot 2: Fast tilt upward: from the top of the frame a monumental bear formed of cold blue glass dives down between the candlestick towers. The instant they collide at the center of the vertical frame, ultra-slow motion: the impact erupts into a spherical shockwave of golden and blue data particles like a supernova, shattered K-line columns suspended mid-air inside the blast. <one deep sub-bass impact, then near-silence with shimmering particle chimes>

Shot 3: The camera slowly pushes forward through the drifting golden particles into the calm eye of the explosion, where the chaotic particles align into clean vertical rows of glowing lines — chaos resolving into order — then drift gently upward like embers.（a clean, confident minimal piano motif emerges from the silence）

Constraints: strict vertical 9:16 composition with main subjects in the upper two-thirds of the frame; keep it subtitle-free, avoid generating any text or subtitles, do not generate a logo, do not generate a watermark, no readable stock tickers, numbers or prices anywhere in the frame.
```

### Clip A-2(15–30s,R2V,Image 1 = logo、Image 2 = 日報截圖)

```
Reference the logo in @Image 1 and the email interface design in @Image 2, keeping both consistent, sharp and undistorted.

Premium fintech brand film in vertical 9:16 composition, HD, rich details, cinematic texture, deep-space black palette with electric blue and amber-gold accents; the mood continues from a calm, confident aftermath.

Shot 1: Macro close-up at the center of the vertical frame: drifting golden data particles spiral together in dark space and assemble into a floating smartphone, screen facing the camera. The screen lights up and displays the email interface from @Image 2, scrolling slowly and elegantly upward; the interface text appears soft and gently out of focus, with no readable numbers. Fine particles orbit the phone like tiny satellites. <a soft, crisp notification chime as the screen lights up>（a calm minimal piano motif joined by warm strings）

Shot 2: The camera slowly pulls back and tilts slightly upward: the phone floats in the lower third of the vertical frame while a warm sunrise breaks across a dark horizon behind it, rays of morning light streaming up the tall frame and rim-lighting the device. Voiceover: a calm, confident young male voice says in Chinese: {每天早上七點，AI 幫你把全球市場讀完。一封信，開盤前就緒。}

Shot 3: Fixed shot. The scene dissolves to a pure black background; the logo from @Image 1 appears centered in the middle of the vertical frame, glowing softly. 【MarketDaily｜marketdaily.ai】 fades in below it in clean white type, synchronized with the final piano note.

Constraints: strict vertical 9:16 composition; the logo from @Image 1 must stay sharp and undistorted; do not invent any other text; do not generate a watermark; the email interface text must stay softly blurred with no readable stock prices or numbers anywhere.
```

---

## 2. 方案 B(備選):資訊焦慮 → 一封信的救贖(敘事共鳴版)
適合再行銷/長尾投放,情緒鉤子是「盯盤焦慮」的自我代入。(16:9 版;直式化比照方案 A 的改法)

### Clip B-1(0–15s,T2V)

```
A cinematic brand-film opening, premium fintech commercial quality, HD, rich details, cinematic texture, moody low-key lighting, deep-space dark palette with electric blue accents, shallow depth of field, shot on a cinema camera.

Shot 1: Fixed wide shot of a dark home office at pre-dawn. A man in his early 30s wearing a charcoal shirt sits before six glowing monitors overflowing with chaotic charts, scrolling headlines and flashing red and green numbers; his face is lit only by screen glow, eyes tired, jaw tense, shoulders hunched. <overlapping muffled news-anchor chatter and frantic keyboard clatter>（a low, anxious pulsing electronic drone）

Shot 2: Slow push-in toward his face as reflections of racing candlestick charts flicker across his eyes; he closes his eyes and rubs his temples, overwhelmed, breathing heavily.

Shot 3: Cut to an extreme close-up of a smartphone lying face-up on the desk. It lights up with a single clean notification, casting calm blue-white light across the dark desk; all the chaotic noise abruptly stops. <a single crisp notification chime, then serene quiet> His hand enters the frame and picks up the phone.（the anxious drone resolves into one clean, calm piano note）

Constraints: keep it subtitle-free, avoid generating any text or subtitles, do not generate a logo, do not generate a watermark, no readable stock tickers, numbers or prices anywhere.
```

### Clip B-2(15–30s,R2V,同樣 Image 1 = logo、Image 2 = 日報截圖)

```
Reference the logo in @Image 1 and the email interface design in @Image 2, keeping both perfectly consistent, sharp and undistorted.

Premium fintech brand film, HD, rich details, cinematic texture; the mood shifts from dark tension into warm, calm morning confidence.

Shot 1: Medium shot on a sunlit apartment balcony at golden-hour sunrise, the city skyline soft in the background. The same man, now relaxed in a clean white shirt, leans on the railing holding his phone, reading calmly with a slight confident smile, steam rising from a coffee cup beside him. <distant morning birdsong and soft city ambience>（warm, optimistic minimal piano with light strings）

Shot 2: Close-up over his shoulder: the phone screen clearly shows the email interface from @Image 2 scrolling slowly and smoothly. Voiceover: a calm, confident young male voice says in Chinese: {別人還在追新聞的時候，你已經看完今天的重點了。}

Shot 3: Fixed shot. The scene fades to a pure black background; the logo from @Image 1 appears centered, glowing softly. 【MarketDaily｜marketdaily.ai】 fades in at the bottom-center in clean white type, synchronized with the final piano chord.

Constraints: the logo from @Image 1 must stay sharp and undistorted; do not invent any other text; do not generate a watermark; no readable stock prices anywhere.
```

---

## 3. 拼接與後製 SOP(全部實戰驗證過)

1. **拼接點**:前段尾剪 6 幀、後段頭剪 1 幀(24fps);音訊接點兩側各 60ms fade(declick)。
2. **端卡(實戰結論)**:AI 畫 logo icon 幾乎必歪 → 一律後製覆蓋。用 `docs/logo.svg` 源碼渲染正版 end card(16:9 標準版/9:16 版底部網址行放 **84% 高度**避 IG 底部 UI)。
3. **端卡切換手法**:`xfade=transition=fadeblack`,**禁用 dissolve**(AI 版文字與正版卡疊影)。切換點必須在 AI 文字成形**之前**——先抽幀定位文字出現時間(兩輪實測:約 10.0–10.5s 開始成形),offset 設在其前 0.3–0.5s,duration 0.8。
4. **結尾爆音 bug**:結尾音軌 fade-out 0.7s。
5. **響度**:成品跑 `loudnorm` 兩段式壓到 **-14 LUFS / TP -1.0**(IG 標準;Seedance 原生輸出實測 -13/-0.6 會被 IG 轉檔削頂)。音軌單獨處理,影像 `-c:v copy` 不重壓。
6. **QC 必做**:抽幀檢查(無亂字幕/浮水印/疊影、logo 正確、4K 下放大驗螢幕假 UI 無真實股名+價位)+ Groq whisper-large-v3 逐字驗旁白。
7. **交付**:4K 母帶存檔;IG 上傳用 1080×1920 版(IG 會壓爛 4K 直傳)。ffmpeg 時基坑:xfade 前所有輸入加 `settb=AVTB`。

## 4. 成本(Higgsfield,2026-07)

| 規格 | credits/15s | 30 秒兩段 |
|---|---|---|
| 1080p | 135 | 270 |
| 4K | 330 | 660 |

Plus 方案每月 1,200 credits。**預算規劃:每支影片一輪過(660 或 270),不留重抽預算——因為根本不重抽。**

## 5. 一次到位 Preflight(送生成前逐項打勾,全綠才按)

- [ ] `higgsfield generate cost` 估價 + `workspace list` 確認餘額足夠**本輪全部段數**
- [ ] 兩張參考圖 QC:logo 渲染正確;日報截圖已縮樣至價位不可辨識(放大親眼驗)
- [ ] Prompt 自檢:每鏡一種運鏡/無每鏡秒數/音訊符號正確/台詞單一語言/約束句在最後/直式版有垂直構圖句
- [ ] 合規預演:prompt 明令無可讀價位代碼、文案無假數字、無付費連結(對照 §6)
- [ ] 版型正確:發行渠道決定 aspect_ratio,原生生成
- [ ] 端卡素材已備好(對應版型的正版 end card PNG)
- [ ] 送出後不論結果,只靠後製收尾(§3);任何「更好」的想法 → 改進本檔定稿,下支影片用

## 6. 合規自檢(發佈前必過)

- [ ] 全片無買賣價位、無個股建議、無可讀報價數字(含 4K 放大驗假 UI)
- [ ] 無假數字:不提勝率/訂戶數/來源數
- [ ] 無任何付費方案文案(2026-07-09 起全面免費化,唯一口徑=限時免費+早鳥,行銷影片乾脆不碰)
- [ ] 螢幕內容 = 公版日報真截圖縮樣,非捏造版面
- [ ] 社群發佈時 caption 依鐵則 `--dry` + 逐字驗
