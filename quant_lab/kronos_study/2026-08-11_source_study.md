# Kronos 原始碼研讀＋winrig 實跑筆記(2026-08-11)

> 源:https://github.com/shiyu-coder/Kronos(MIT,清華,AAAI 2026)。起因=IG reel Db3P17nN1Og 拆解(swipe file J 段)。
> winrig 落地:repo clone 在 `~/research/external/Kronos`,專用 venv `.venv`(torch 2.13 CPU,刻意不裝 CUDA 版省空間;要 GPU 再換 jarvis venv 的 cu128 同版路線)。smoke test=`smoke_test.py`。

## 架構(讀 model/kronos.py 662 行+module.py 570 行)

兩件式,類 VQ-VAE + GPT:

1. **KronosTokenizer**(encoder/decoder Transformer + BSQuantizer):
   - 輸入 6 維連續值 `[open, high, low, close, volume, amount]`,linear embed 進 d_model,過 encoder 層,投影到 codebook_dim = s1_bits + s2_bits
   - **BSQ(Binary Spherical Quantization)** 把連續向量量化成二進位球面碼;token 拆成**階層雙碼**:s1(粗)+s2(細),一根 K 棒=一組 (s1, s2) token pair
2. **Kronos**(decoder-only Transformer,自迴歸):
   - 預測下一根 K 棒的 token pair,**兩段式解碼**:`decode_s1` 先出 s1 logits+context → `decode_s2` 用 dependency-aware layer 以 s1 為條件出 s2(粗到細,同一時步內也有依賴結構)
   - 有 time embedding:`[minute, hour, weekday, day, month]` 五維時間戳,x 與 y 的 stamp 都要給(這是它知道「預測的是週幾幾點」的方式)
   - 取樣=標準 LLM 套路:temperature / top-k / top-p(`sample_from_logits`),天生**機率式**輸出

## 使用介面(KronosPredictor.predict)

- 輸入:DataFrame(OHLCV+amount;缺 volume 自動補 0,缺 amount 用 volume×均價補)、x_timestamp、y_timestamp、pred_len
- 前處理:**per-window z-score**(對 lookback 窗每欄減均值除標準差)+ clip ±5;輸出反正規化回原尺度
- `sample_count=N` 跑 N 條軌跡,但 `auto_regressive_inference` **內部直接 np.mean 平均後才回傳**——要拿分布(如數軌跡過 strike 的機率法)得自己改:把 `preds = np.mean(preds, axis=1)` 拿掉或迴圈 N 次 sample_count=1
- max_context=512(Kronos-small/base;mini 用 2k tokenizer),超長自動截尾
- 模型家族:mini 4.1M / small 24.7M / base 102.3M(HF NeoQuasar/*);large 499M 未放出

## winrig 實跑結果(smoke_test.py,Binance 公開 API 真數據)

- BTC/USDT 1h,624 根(2026-07-16→08-11),lookback 480 預測 24,30 條軌跡取平均,CPU 跑完約 3 分鐘
- last close 64,331 → 預測 t+24 = 64,380(UP)/實際 64,908(UP)——方向對
- MAE(24h close):Kronos 264 vs naive 持平基線 280
- **⚠️ 誠實聲明:單一時間窗、單一標的、一次抽樣=軼事,不是 edge 證據**。backtest-validation 鐵則適用:要當訊號源必須走 walk_forward harness+DSR+成本模型,樣本量 N≈1/edge²

## 下一步(要做才開工,不自動排)

1. **當候選訊號源進 edge-pipeline**:方向訊號(pred_close_t+k vs last_close)接 walk_forward,對 BTC/ETH/台指期各跑;對照組=naive+ARIMA
2. **機率輸出**:改 inference 拿全部 N 條軌跡→P(close_t+k > X)——與 reel 中 wincy.eth 的 Polymarket 溫度採樣法同構,可先在 crash_gate/尾險場景試(它天生輸出分布,比點估計有用)
3. fine-tune 台股:repo 附 finetune/(qlib pipeline)與 finetune_csv/(裸 CSV pipeline),5080 可跑 small/base

---

## walk_forward 判決(2026-08-11 當日執行,winrig 5080)

**方法**:`eval_wf.py`——BTC/ETH 1h 各 400 天(2025-07-28→2026-08-10),lookback 480 / horizon 24h / step 24h(非重疊),每點 N=20 條獨立軌跡。**保留軌跡的零改碼技巧**:同一窗 batch 疊 N 份+`sample_count=1` 傳原版 `auto_regressive_inference`,multinomial 逐 row 獨立採樣,mean(axis=1) 對 1=恆等——N 條軌跡完整回來,上游碼一行沒動。成本假設 10bps/日單邊翻倉。

**結果(n=379/標的)**:

| 訊號 | BTC hit | ETH hit | 淨日均(BTC/ETH) |
|---|---|---|---|
| kronos 方向(mean) | .515 CI[.464,.564] | .546 CI[.496,.596] | -0.115% / -0.098% |
| kronos 方向(p_up>.5) | .520 | .536 | -0.095% / -0.157% |
| naive 動能24h | .499 | .483 | -0.005% / -0.058% |
| always-up | .483 | .491 | -0.236% / -0.230% |

**判決**:
1. **無可交易 edge(zero-shot)**——所有 CI 含 50%,扣成本全負。與記憶 `project_structural_edges_found`「daily-bar 全失敗」一致。
2. **機率輸出未校準,raw p_up 禁用**——兩極化嚴重:p_up>0.7 的 200 點平均信心 94%,實現漲率只有 50%;Brier 0.41 vs 常數基線 0.25。20 條軌跡高度同向=模型對 context 的方向偏好幾乎確定性,溫度採樣沒帶來真分散。reel 裡 wincy.eth 的 Polymarket 機率玩法直接套=會被自己的假信心殺死,至少要先做 calibration 映射(Platt/isotonic)。
3. **樣本量誠實聲明**:n=379 依 N≈1/edge² 只能偵測 >5% 的 edge;2-3% 的小 edge 在此樣本下不可見。此判決=「無大 edge」,非「證明零 edge」。

**剩餘活路(都是獨立新研究題,不自動開工)**:fine-tune 台股/加密(repo 附完整 pipeline,5080 可跑)、更短 horizon(1-4h)、改用它當波動度/分布形狀預測器(它的 std 或許比方向有訊息)、calibration 後再驗機率。
