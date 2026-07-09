# 下一支影片企劃 —「開盤前的兩種人」(等額度刷新,一次過)

> 2026-07-09 研究定稿。生成執行照 `seedance2_video_prompt_pack.md` §5 Preflight,4K 9:16 兩段 = 660 credits(下期額度)。

## 一、IG/TikTok 爆紅 AI 行銷影片研究結論(2026-07)

| 發現 | 數據/出處 | 對我們的意義 |
|---|---|---|
| **UGC/原生感 >> 精緻大片** | UGC 風 CTR 比棚拍高 +400%,creator 風 +70%(Creatify/Virvid 2026 案例);金融品牌第一大錯=「過度精緻的企業風內容」(Vested 金融 TikTok 指南) | 第一支牛熊對撞是品牌大片,對;**下一支必須走「真實生活場景」路線**,兩條腿走路 |
| **前 3 秒三重 hook** | 63% 高 CTR 影片在 3 秒內完成 hook;爆量門檻≈70% 完播(Conbersa 2026);hook 三層=視覺+文字+聲音,多數人只用一層 | 第 1 幀就要:衝擊畫面+燒錄文字 hook+聲音 pattern interrupt |
| **80% Reels 靜音播放** | Metricool/Virvid 2026 | **全程燒錄字幕**(後製上,零錯字、順便解決 AI 生字問題);旁白只是加分不是載體 |
| **最佳長度 21–34 秒** | TikTok 完播率最高區間(Virvid) | 30 秒 ✓ 維持 |
| **金融品牌能打的格式** | 教育型短片、迷思破解、真實生活情境、清楚對比(NerdWallet/Chime 玩法) | 「情境對比」是我們的最佳切入:不賣產品,演一個人人有感的早晨 |
| **明顯 AI 感會反噬;假用戶見證是紅線** | 「obvious AI」觸發負面觀感(Virvid);Guardian 2026-06 調查報導點名 AI 假顧客,輿論要求揭露 | 走 Seedance 2.0 最強的**照片級真實日常人物**(非 CG 特效);**絕不做假用戶見證/假數據**(本來就是我們鐵則) |

**一句話總結**:第一支解決「品牌氣勢」,下一支解決「轉換」——原生感、情境共鳴、靜音可看、教育調性。

## 二、定稿概念:「開盤前的兩種人」(對比敘事,30 秒)

兩個不同人物 = 天然免跨段一致性風險。教育調性+情境共鳴,符合金融品牌最佳實踐;不碰假見證、不碰價位、不碰付費。

**分鏡**:
- **0–2s(hook)**:混亂者的臉被紅綠 K 線光轟炸,通知音疊成噪音牆;燒錄大字 hook:「開盤前 10 分鐘,兩種人」
- **2–15s(Clip 1|混亂者)**:06:50,亂桌、三台裝置、無限刷新聞、咖啡沒動,鬧鐘跳 07:00 他還在資訊海裡;字幕:「一種人:8 個視窗、300 條新聞、越看越慌」
- **15–25s(Clip 2|從容者)**:另一個人,晨光廚房/陽台,一杯咖啡,打開**一封信**滑完(日報介面柔焦捲動),微笑收起手機出門;字幕:「同一個早上,有人已經把全球市場讀完了」(**全片無人聲——用戶 2026-07-09 指令:不用 AI 語音,資訊由燒錄字幕承載,聲音全靠震撼音效設計**)
- **25–30s(正版 end card)**:logo+「每天 07:00,一封信讀完全球市場」+「marketdaily.ai」(可加現行口徑「限時免費」,發佈前照口徑鐵則再驗)

## 三、素材清單(生成前備齊 = Preflight 第 2、6 項)

| 素材 | 來源 | 狀態 |
|---|---|---|
| 日報截圖(價位不可辨識版) | 既有 `digest_ref.png` 作法重做一張最新公版 | 生成日重做(內容要新) |
| logo 參考圖 | `logo_ref.png` 既有 | ✅ |
| 9:16 正版 end card(84% 安全區) | `endcard_916.png` 既有,標語行改「每天 07:00,一封信讀完全球市場」 | 改字即可 |
| 燒錄字幕樣式 | IBM Plex Mono / 思源黑體,白字黑描邊,上 1/3 區 | 後製時做 |
| 兩段 prompt | 下方 §四,已按官方公式寫好 | ✅ 待 preflight |

## 四、兩段 prompt(定稿草案,生成日過 preflight 後直接用)

### Clip 1 混亂者(T2V,9:16,15s,--genre drama)

```
Photorealistic cinematic slice-of-life scene in vertical 9:16 composition, handheld documentary energy, HD, rich skin and fabric detail, moody mixed lighting from screens, shot on a cinema camera.

Shot 1: The opening frame is an extreme close-up of a young East Asian man's tired face at 6:50 AM, lit only by flashing red and green light from off-screen monitors, eyes darting rapidly; reflections of racing candlestick charts flicker across his glasses. <a chaotic wall of overlapping notification dings stacking louder and louder, layered over a deep sub-bass heartbeat that keeps accelerating>（a tense rising drone builds underneath, no vocals）

Shot 2: Quick handheld pull-back: a cluttered desk in a dim bedroom — laptop, tablet and phone all glowing with dense scrolling feeds and charts, sticky notes everywhere, an untouched cup of coffee gone cold, cables tangled. He frantically swipes between devices, jaw tight, one hand gripping his hair.

Shot 3: Fixed close-up on a phone alarm flipping to 7:00 AM on the desk; behind it, out of focus, the man is still hunched and swiping, drowning in feeds. The notification noise keeps stacking, almost suffocating, then hard-cuts to silence on the final frame. <alert dings and the racing heartbeat crescendo into a suffocating wall of noise, one final deep sub-bass slam, then absolute dead silence>

Constraints: strict vertical 9:16 composition; all screen content must be abstract blurred glow with no readable text, tickers, numbers or prices; keep it subtitle-free, avoid generating any text or subtitles, do not generate a logo, do not generate a watermark.
```

### Clip 2 從容者(R2V,9:16,15s;Image 1 = logo、Image 2 = 日報截圖)

```
Reference the logo in @Image 1 and the email interface design in @Image 2, keeping both consistent, sharp and undistorted.

Photorealistic cinematic slice-of-life scene in vertical 9:16 composition, warm golden morning light, airy and calm, HD, rich detail, gentle depth of field, shot on a cinema camera.

Shot 1: Medium shot in a bright modern kitchen at sunrise: a young East Asian woman in a crisp shirt leans against the counter with a warm cup of coffee, steam rising through a beam of morning sunlight. She picks up her phone with one relaxed hand. <soft kitchen ambience, a single crisp notification chime>（no vocals anywhere; a sparse, confident minimal piano motif over deep quiet）

Shot 2: Close-up over her shoulder: the phone screen shows the email interface from @Image 2 scrolling slowly and elegantly upward; the interface text appears soft and gently out of focus, with no readable numbers. She reads with a slight, assured smile and takes an unhurried sip of coffee. <one deep, satisfying resonant chime as the email opens — like a struck temple bell with a long warm tail; the silence around it feels vast>

Shot 3: Medium-wide shot: she locks the phone, slips it into her bag, and walks toward the sunlit door with light, confident steps; the camera holds as she exits the frame, leaving the bright, calm kitchen. <soft footsteps, door opening, birdsong outside>（the piano motif resolves warmly）

Constraints: strict vertical 9:16 composition; do not invent any other text; do not generate a watermark; the email interface text must stay softly blurred with no readable stock prices or numbers anywhere; keep it subtitle-free except the referenced screen content.
```

> 端卡不靠 AI:24–25s 起 `xfade=fadeblack` 切正版 end card(SOP §3)。**端卡進場配一記 cinematic impact hit(deep boom + sub drop),用免版稅 SFX 素材後製疊上,不靠 AI 生成——這是全片最後的震撼記憶點。**
>
> **聲音設計總則(2026-07-09 用戶指令)**:全片零人聲;混亂段=通知音牆+加速心跳+riser 到窒息再驟停(對比式震撼);從容段=巨大留白+一記鐘鳴;端卡=impact hit。響度照 SOP 壓 -14 LUFS,但保留 SFX 瞬態衝擊力(TP -1.0 限幅,不過度壓縮)。

## 五、發佈計畫

- 主發 IG Reels(現有 14:00 產線口徑);TikTok 若開帳號同素材直發
- Caption 發佈前照鐵則 `--dry` + 逐字驗;「限時免費/早鳥」口徑對照 `project_marketdaily_free_earlybird`
- 上線後追蹤:3 秒續看率(hook 成敗)、完播率(70% 門檻)、profile 點擊 → 與第一支牛熊版 A/B 對照,數據決定第三支路線
