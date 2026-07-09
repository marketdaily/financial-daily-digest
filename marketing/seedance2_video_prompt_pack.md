# MarketDaily × Seedance 2.0 — 30 秒行銷影片 Prompt 包

> 依據:BytePlus 官方《Dreamina Seedance 2.0 series prompt guide》(ModelArk 2222480,2026-07-07 版)+ ByteDance Seed 官方發布文。
> 硬限制:單次生成上限 **15 秒**多鏡頭含音訊 → 30 秒 = 兩段 15 秒拼接。
> 官方公式:`精確主體 + 動作細節 + 場景環境 + 光線色調 + 運鏡 + 視覺風格 + 畫質 + 約束條件`。
> 音訊符號:`（）`=音樂、`<>`=音效、`{}`=台詞、`【】`=字幕;台詞單一語言不可中英混。
> 鐵則:每個鏡頭只用一種運鏡;不要寫每鏡秒數(官方明說計時不穩);橫版比直版少亂字幕。

---

## 0. 生成前準備(資產上傳順序 = 優先權順序)

| 順序 | 資產 | 用途 |
|------|------|------|
| Image 1 | MarketDaily logo 高清 PNG(深色底版) | 品牌 logo 精確渲染(官方:品牌字體一律用 logo 參考圖,不要用文字描述) |
| Image 2 | 公版日報 email 截圖(手機視窗寬度、高清) | 產品畫面真實呈現——用真截圖,不捏造數字 |

設定:**1080p、15 秒、16:9 橫版母帶**(需要 Reels 再原生 9:16 重生一版,見 §4)。
每段生成 3–4 個 take 挑最佳——這是 AI 影片業界標準作法,不是浪費。

---

## 方案 A(主推):牛熊對撞 → 秩序誕生 → 產品揭示
第一眼即抓人(spectacle hook),且與現有官網牛熊 hero 品牌資產同語彙。

### Clip A-1(0–15s,純文生影片 T2V,不用資產)

```
Epic cinematic financial-market spectacle, premium brand-film quality, HD, rich details, cinematic texture, deep-space black palette with electric blue and amber-gold accents, volumetric lighting, shot on a cinema camera.

Shot 1: Low-angle wide shot. On an endless obsidian plain whose surface glows with faint golden candlestick charts, a colossal bull sculpted from molten bronze light charges in from the left, hooves striking sparks of data particles, while a monumental bear formed of cold blue glass charges in from the right. Dust and streaking light particles trail behind them. <thunderous hoofbeats and a deep rumbling roar>（dark, driving cinematic percussion building tension）

Shot 2: Slow-motion close-up at center frame at the instant they collide: the impact erupts into a shockwave of golden and blue data particles rippling outward like a supernova, columns of glowing candlesticks rising from the ground inside the blast wave. <one deep sub-bass impact, then near-silence with shimmering particle chimes>

Shot 3: The camera slowly pushes forward through the drifting golden particles into the calm eye of the explosion, where the chaotic particles align themselves into clean, orderly rows of glowing lines — chaos resolving into order.（a clean, confident minimal piano motif emerges from the silence）

Constraints: keep it subtitle-free, avoid generating any text or subtitles, do not generate a logo, do not generate a watermark, no readable stock tickers, numbers or prices anywhere in the frame.
```

### Clip A-2(15–30s,R2V,上傳 Image 1 = logo、Image 2 = 日報截圖)

```
R2V: Reference the logo in @Image 1 and the email interface design in @Image 2, keeping both perfectly consistent, sharp and undistorted.

Premium fintech brand film, HD, rich details, cinematic texture, deep-space black palette with electric blue and amber-gold accents; the mood continues from a calm, confident aftermath.

Shot 1: Macro close-up. Drifting golden data particles converge in dark space and assemble into a floating, softly glowing smartphone. The screen lights up and displays the email interface from @Image 2, scrolling slowly and elegantly upward with its cards clearly visible. <a soft, crisp notification chime as the screen lights up>（the same calm minimal piano motif continues, now joined by warm strings）

Shot 2: Slow pull-back. The phone recedes to center frame against deep space as warm morning sunlight rises behind it, rim-lighting the device. Voiceover: a calm, confident young male voice says in Chinese: {每天早上七點，AI 幫你把全球市場讀完。一封信，開盤前就緒。}

Shot 3: Fixed shot. The screen content dissolves into the logo from @Image 1, centered and glowing softly against the pure black background. 【MarketDaily｜marketdaily.ai】 appears at the bottom-center in clean white type, fading in gently, perfectly synchronized with the final piano note.

Constraints: the logo from @Image 1 must stay sharp and undistorted; do not invent any other text; do not generate a watermark; no readable stock prices anywhere.
```

---

## 方案 B(備選):資訊焦慮 → 一封信的救贖(敘事共鳴版)
適合再行銷/長尾投放,情緒鉤子是「盯盤焦慮」的自我代入。

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
R2V: Reference the logo in @Image 1 and the email interface design in @Image 2, keeping both perfectly consistent, sharp and undistorted.

Premium fintech brand film, HD, rich details, cinematic texture; the mood shifts from dark tension into warm, calm morning confidence.

Shot 1: Medium shot on a sunlit apartment balcony at golden-hour sunrise, the city skyline soft in the background. The same man, now relaxed in a clean white shirt, leans on the railing holding his phone, reading calmly with a slight confident smile, steam rising from a coffee cup beside him. <distant morning birdsong and soft city ambience>（warm, optimistic minimal piano with light strings）

Shot 2: Close-up over his shoulder: the phone screen clearly shows the email interface from @Image 2 scrolling slowly and smoothly. Voiceover: a calm, confident young male voice says in Chinese: {別人還在追新聞的時候，你已經看完今天的重點了。}

Shot 3: Fixed shot. The scene fades to a pure black background; the logo from @Image 1 appears centered, glowing softly. 【MarketDaily｜marketdaily.ai】 fades in at the bottom-center in clean white type, synchronized with the final piano chord.

Constraints: the logo from @Image 1 must stay sharp and undistorted; do not invent any other text; do not generate a watermark; no readable stock prices anywhere.
```

---

## 4. 拼接與後製 SOP(官方指南 + 已知 bug 對策)

1. **拼接點**:前段結尾剪 6 幀、後段開頭剪 1 幀(官方 CapCut 建議值,消 jump-cut)。
2. **音樂銜接**:兩段 prompt 已寫成同一個 piano motif(A-1 結尾誕生 → A-2 開頭延續),拼接處加 0.3s crossfade。
3. **結尾爆音 bug**:Seedance 已知結尾偶有 click/切斷音 → 後製對結尾音軌做 fade-out。
4. **Logo/文字保險**:若生成的 logo 或【MarketDaily｜marketdaily.ai】有任何變形錯字 → 後製用真 logo PNG 直接蓋上(位置已在 prompt 固定為 center / bottom-center,好對位)。要零錯字,最穩做法是最後 2 秒改用後製 end-card。
5. **螢幕文字**:@Image 2 的日報截圖若在動態中糊掉 → 改後製把真截圖 screen-replace,或接受「微距淺景深、重點卡片清晰」的呈現。
6. **直版 Reels**:官方明說直版亂字幕機率較高。要 9:16 就原生重生一版(不要橫版硬裁),並把 anti-subtitle 約束句放在 prompt 最後一行加重;亂字幕仍可能出現,挑 take 解決。

## 5. 合規自檢(發佈前必過)

- [ ] 全片無買賣價位、無個股建議、無可讀報價數字(prompt 已明令)
- [ ] 無假數字:不提勝率/訂戶數/來源數,文案只說「AI 幫你讀完市場」
- [ ] 不把個股功能與付費連結:全片不出現價格方案
- [ ] 螢幕內容 = 公版日報真截圖,非捏造
- [ ] 社群發佈時 caption 依鐵則 `--dry` + 逐字驗

---

## 方案 A v2(Reels 直式加強版,2026-07-09 下午)
9:16 專用重寫:第 1 秒即主體衝臉 hook、垂直構圖引導(主體上 2/3)、K 線光柱沿直式畫框兩側。

### Clip A-1 v2(9:16)
```
Epic cinematic financial-market spectacle in vertical 9:16 composition, premium brand-film quality, HD, rich details, cinematic texture, deep-space black palette with electric blue and amber-gold accents, volumetric lighting, dramatic rim light, shot on a cinema camera.

Shot 1: The opening frame is already mid-action: a colossal bull sculpted from molten bronze light fills the lower half of the vertical frame, charging straight toward the camera in a low-angle shot, hooves striking sparks of golden data particles off an obsidian plain etched with glowing candlestick charts; towering columns of K-line light rise like skyscrapers along both edges of the vertical frame. <thunderous hoofbeats and a deep rumbling roar>（dark, driving cinematic percussion at high tempo）

Shot 2: Fast tilt upward: from the top of the frame a monumental bear formed of cold blue glass dives down between the candlestick towers. The instant they collide at the center of the vertical frame, ultra-slow motion: the impact erupts into a spherical shockwave of golden and blue data particles like a supernova, shattered K-line columns suspended mid-air inside the blast. <one deep sub-bass impact, then near-silence with shimmering particle chimes>

Shot 3: The camera slowly pushes forward through the drifting golden particles into the calm eye of the explosion, where the chaotic particles align into clean vertical rows of glowing lines — chaos resolving into order — then drift gently upward like embers.（a clean, confident minimal piano motif emerges from the silence）

Constraints: strict vertical 9:16 composition with main subjects in the upper two-thirds of the frame; keep it subtitle-free, avoid generating any text or subtitles, do not generate a logo, do not generate a watermark, no readable stock tickers, numbers or prices anywhere in the frame.
```

### Clip A-2 v2(9:16)
```
Reference the logo in @Image 1 and the email interface design in @Image 2, keeping both consistent, sharp and undistorted.

Premium fintech brand film in vertical 9:16 composition, HD, rich details, cinematic texture, deep-space black palette with electric blue and amber-gold accents; the mood continues from a calm, confident aftermath.

Shot 1: Macro close-up at the center of the vertical frame: drifting golden data particles spiral together in dark space and assemble into a floating smartphone, screen facing the camera. The screen lights up and displays the email interface from @Image 2, scrolling slowly and elegantly upward; the interface text appears soft and gently out of focus, with no readable numbers. Fine particles orbit the phone like tiny satellites. <a soft, crisp notification chime as the screen lights up>（a calm minimal piano motif joined by warm strings）

Shot 2: The camera slowly pulls back and tilts slightly upward: the phone floats in the lower third of the vertical frame while a warm sunrise breaks across a dark horizon behind it, rays of morning light streaming up the tall frame and rim-lighting the device. Voiceover: a calm, confident young male voice says in Chinese: {每天早上七點，AI 幫你把全球市場讀完。一封信，開盤前就緒。}

Shot 3: Fixed shot. The scene dissolves to a pure black background; the logo from @Image 1 appears centered in the middle of the vertical frame, glowing softly. 【MarketDaily｜marketdaily.ai】 fades in below it in clean white type, synchronized with the final piano note.

Constraints: strict vertical 9:16 composition; the logo from @Image 1 must stay sharp and undistorted; do not invent any other text; do not generate a watermark; the email interface text must stay softly blurred with no readable stock prices or numbers anywhere.
```
