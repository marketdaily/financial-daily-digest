# 券商程式交易 API 整合 Playbook — 永豐 Shioaji（先接）vs 元大 Yuanta

> **背景**：Delvin 老闆（2026-07-13）指示「先接永豐的看一下，因為永豐的證券 API 也是走 Python」。永豐 = SinoPac，官方 Python API = **Shioaji**。這份 playbook 是「先接永豐 paper-trading」的實作規格書，也是 SSF 交易任務 **V4「Shioaji 模擬帳號自動 paper-trading 迴圈」** 的技術地基。
>
> **驗證狀態**：核心事實已對照官方 docs（sinotrade.github.io）＋ PyPI 權威查證＋winrig 本機實測。不能從 docs 證實的一律標 **[UNVERIFIED]**，實作時 runtime 驗。日期 2026-07-13。
>
> **死線**：本任務全程 **paper（simulation=True）**，live 路徑只寫在文件、不寫進運行程式；真金投入是 Delvin 本人的決定。

---

## 0. TL;DR / 決策

| 問題 | 結論 |
|------|------|
| 先接哪家？ | **永豐 Shioaji**（老闆正確）。唯一真 `pip install` 原生 Python 綁定、一行 `simulation=True` paper 模式、免費自助金鑰、完整 SSF 個股期貨、docs/社群最成熟。零業務員摩擦，今天就能 paper-trade 台股期貨。 |
| 元大 Yuanta 有 Python API 嗎？ | 有，**元大 SPARK API**——但 Python 是 **pythonnet/.NET 元件橋接**（非純 pip 套件），UAT 模擬需固定 IP 白名單＋業務員。**legit 的第二目標，不是第一。** 舊的 YuantaOne/EasyWin 是 Windows COM/DLL，避開。 |
| 元大唯一勝過永豐處？ | **國外期貨（international futures）** ＋台灣最大券商流動性/費率（規模大時）。策略擴到海外期貨或要 Tier-1 流動性才加。 |
| winrig 跑得動嗎？ | **能**。base python 3.14.4（regular GIL），shioaji 1.5.6 出 `cp37-abi3` 通用 wheel → pip 裝得上 3.14；但走 venv（PEP 668）。建議 `uv venv --python 3.12` 求重現性＋對齊 cb-desk 現役碼。 |
| 已有現成碼嗎？ | 有。`~/cb-desk/cbdesk/feeds/sinopac.py` 是**已驗證的 STOCKS 行情路徑**（登入/合約解析/snapshot/rate-limit 分批）。SSF/期貨下單這塊是本 playbook 要新建的。 |

---

## 1. 環境與安裝（winrig）

- **版本**：最新 **shioaji 1.5.6**（2026-07-09，PyPI 權威）。**pin `shioaji>=1.5.3`**（1.5.0/1.5.1/1.5.2 已 yanked）。`requires_python: >=3.7`。
- **Wheel 現況（PyPI 權威，2026-07-13 查）**：`cp37-abi3`（通用 stable-ABI，含 `win_amd64`、macOS x86/arm64、manylinux x86/aarch64）＋ `cp314-cp314t`（free-threaded 3.14 專用）。
  - ⚠️ **記憶校正**：舊 memory `reference_shioaji_simulation` 說「無 3.14 wheel，只 3.10–3.12」——那是**舊版 version-specific `cpXY` wheel 時代，現已過時**。1.5.x 改發 `cp37-abi3` 通用 wheel，**3.7→3.14 皆可裝**。
  - winrig base python 3.14.4 = **regular GIL build**（`sysconfig Py_GIL_DISABLED=0`）→ 用 `cp37-abi3` wheel（非 free-threaded 的 cp314t）。
- **安裝（建議 venv，勿污染 base）**：
  ```bash
  cd ~/<trading-project>
  uv venv --python 3.12 .venv        # 3.12 求重現性＋對齊 cb-desk；用 3.14 亦可（abi3）
  uv pip install "shioaji>=1.5.3"
  # base python3 直裝會被 PEP 668「externally-managed」擋，這是預期的 → 用 venv
  ```
- **金鑰自助生成（免費即時，需永豐帳戶）**：https://www.sinotrade.com.tw/newweb/PythonAPIKey/
  1. 進「PythonAPIKey」管理頁 → **新增 API KEY** → 過 2FA（手機/email OTP）。
  2. 設定：到期日、**權限（行情 Market-Data / 帳務 Account / 下單 Trading）**、帳號綁定、正式環境存取、選填 IP allowlist。
  3. 複製 `api_key` + `secret_key`（**secret 只顯示一次**）→ 放 `.env`。
  - **最小權限原則**：純行情 + paper 只需 **行情** 權限就夠；paper 下單要 **下單** 權限但 simulation 不需 CA 憑證。真 live 才需 `api.activate_ca(...)`。降低 blast radius：daemon 用的金鑰不要多給 Trading 除非真要下單。
- **`.env` 慣例**（沿用 cb-desk）：`SINOPAC_API_KEY` / `SINOPAC_SECRET_KEY` / `SINOPAC_SIMULATION=1`（安全預設；只有明確 `0/false/no/off` 才切正式）。

---

## 2. 台灣券商 Python 程式交易 API 對照表

| 券商 / API | 原生 Python SDK | 現股 | 期貨＆**SSF** | 選擇權 | Sim/paper | 行情串流 | 免費自助金鑰 | 上手摩擦 | 成熟度 |
|---|---|---|---|---|---|---|---|---|---|
| **永豐 Shioaji** | ✅ `pip install shioaji`（真原生綁定） | ✅ | ✅ 含 **SSF**（CDF/QFF…） | ✅＋combo | ✅ `simulation=True`（1 flag） | ✅ WS tick/bidask | ✅ 理財網自助，2FA，免費 | **低** | **最佳**：活躍更新、中英文 docs、社群最大 |
| **元大 Yuanta SPARK** | ⚠️ Python 走 **pythonnet/.NET 橋**（Win/Mac/Linux）；PyPI 純套件 [UNVERIFIED] | ✅ | ✅ 含 SSF ＋ **國外期貨** | ✅ | ✅ **UAT** 環境，需固定 IP 白名單＋業務員 | ✅ | ✅ 無財力/量門檻，S/F 分開開通 | **中** | 改善中；Python 持續維護，OSS 少 |
| **富果 Fugle** | ⚠️ `fugle-trade` **已 EOL 停更 2025/11**；`fugle-marketdata` 仍活 | ✅（透過玉山） | ❌ 下單僅現股 | ❌（下單） | [UNVERIFIED] | ✅ 一流免費資料 API | ✅ | 資料低；下單受玉山戶限制 | 資料強；**下單 SDK 已棄用，勿新建** |
| **凱基 KGI SUPER PY** | ✅ `pip install kgisuperpy` | ✅ 台+**美股** | ✅ 期貨；SSF [UNVERIFIED] | ✅ | ✅ `simulation=True`＋內建 backtest | ✅ | ✅ | 中 | 穩健成長 |
| **元富 Masterlink**（→台新） | ✅ Python + C# | ✅ | ✅ 期貨；SSF [UNVERIFIED] | ❌ | ✅ 盤中即時撮合 | ✅ | ✅ | 中；**2026-04-06 併入台新**平台連續性風險 | 尚可，組織變動中 |
| **FinMind**（純資料） | ✅ `pip install FinMind` | 資料 | 資料（含 SSF 價） | 資料 | ❌ 無下單 | ❌ REST 非串流 | ✅ 免費層+token | 極低 | 研究/資料佳，**不能下單** |

**命名坑（別搞混）**：「統一 Masterlink」是誤植——Masterlink = **元富**（非統一）；統一 = President Securities（另一家，無確認的 Python 下單 SDK）。Fugle 執行夥伴是**玉山**（非元大）。

**Bottom line**：純台股 SSF 專案，**Shioaji 一家就夠**。策略擴到國外期貨或要 Tier-1 流動性/費率才加元大 SPARK。`fugle-marketdata` 可當免費資料副源搭配任一券商。

---

## 3. Shioaji SSF/期貨 交易參考（V4 的下單核心）

### 3.1 SSF 合約查找 — **關鍵：每檔個股期各有自己的 TAIFEX 商品代碼，沒有單一「SSF」類別**

```python
list(api.Contracts.Futures)                 # 所有類別碼
api.Contracts.Futures["CDFR1"]              # 直接代碼查找（台積電近月）
api.Contracts.Futures.CDF.CDFR1             # 類別導覽
api.Contracts.Futures.CDF.CDF202607         # 明確交割月
```

- **商品代碼 = TAIFEX 商品代碼**。指數期：`TXF`(大台)/`MXF`(小台)/`TMF`(微台)。**個股期每個標的一個碼**：
  - **2330 台積電 → `CDF`**（已對 TAIFEX/HiStock 核實）；小型台積電期碼可能是 `QFF` 或 `QF` [UNVERIFIED，用 TAIFEX 商品代碼表確認]。Shioaji attr 名 runtime `list(api.Contracts.Futures)` 確認
- **`R1`/`R2` 近月慣例**：`...R1` = 近月（front，連續滾動 alias），`...R2` = 次月；物件的 **`target_code`** 告訴你目前實際對應到哪個交割月合約。
- **Future 物件欄位（1.5.x verbatim 範例）**：`code, symbol, name, category, delivery_month, delivery_date, underlying_kind('I'=指數), unit, limit_up, limit_down, reference, update_date, target_code`。
- **反查 標的→SSF 碼**：優先用**已知商品碼對照**（2330→CDF→CDFR1，最可靠）。迭代過濾 `underlying_code=='2330'` 的路子 **[UNVERIFIED]**（1.5.x 範例只見 `target_code` 不見 `underlying_code`，該欄舊版有、新版未證）。`underlying_kind='S'`（股票期）是**推論**，docs 只示範 `'I'`。→ **建議維護一份 `{stock_id: ssf_product_code}` 對照表**當積木（TAIFEX 商品代碼表為權威源）。

### 3.2 下單（**已對官方 doc 直接核實**）

```python
order = sj.FuturesOrder(                     # 官方 docs 期貨用此構造子（api.Order 是現股形式，
    action=sj.constant.Action.Buy,           #   期貨 api.Order+octype 等價性未證 [UNVERIFIED]）
    price=contract.reference,                # LMT 用限價；MKT/MKP 市價單 → price=0
    quantity=1,
    price_type=sj.constant.FuturesPriceType.LMT,   # LMT | MKT | MKP
    order_type=sj.constant.OrderType.ROD,          # ROD | IOC | FOK
    octype=sj.constant.FuturesOCType.New,          # Auto | New | Cover | DayTrade
    account=api.futopt_account,             # ⚠️ SSF 用 futopt_account（非 stock_account）
)
trade = api.place_order(contract, order)    # 回 Trade 物件
```

- **octype 開倉值＝`"New"`（不是 `"NewPosition"`）** ← 官方 doc 直接確認；`'NewPosition'` 是**狀態/輸出值**非輸入。`Auto`=券商依現有部位自動判開/平。
- **MKT/MKP 市價 → `price=0`**。字串值也可直接當 kwarg（`price_type="LMT"` 等）。
- 字串 enum 也接受；enum class 同時有 `sj.constant.*` 與頂層 `sj.*` alias。

### 3.3 委託/成交 callback 與狀態

```python
def order_cb(stat, msg):                    # stat=OrderState 枚舉, msg=dict
    if stat == sj.constant.OrderState.FuturesDeal:   # 成交（member=FuturesDeal，值='FDEAL'）
        ...  # msg: trade_id, ordno, action, code, price, quantity, ts, ...
    elif stat == sj.constant.OrderState.FuturesOrder:  # 委託回報 ack（member=FuturesOrder，值='FORDER'）
        ...  # msg['operation']['op_code']=='00' 為成功；msg['order']['ordno']
api.set_order_callback(order_cb)
```

> ⚠️ **enum 成員名＝`OrderState.FuturesDeal`/`FuturesOrder`（v1.0 起改名，舊 `FDeal`/`FOrder` 已無此成員→AttributeError）**；其**字串值**才是 `'FDEAL'`/`'FORDER'`（別把字串值當成員名寫）。官方 doc 直接核實。現股對應成員＝`StockDeal`/`StockOrder`。

- **對單**：委託 `order.id` == 成交 `deal.trade_id`；成交 `ordno` 前 5 碼 == 委託 `ordno`。
- **FuturesOrder(ack) payload key**：`operation{op_type('New'|'Cancel'|'UpdatePrice'|'UpdateQty'), op_code('00'=成功), op_msg}` / `order{id, seqno, ordno, action, price, quantity, order_type, price_type, market_type('Day'|'Night'), oc_type('New')}` / `status{id, exchange_ts, modified_price, cancel_quantity}` / `contract{security_type('FUT'), code, exchange, delivery_month, option_right('Future')}`。
- **FuturesDeal(fill) payload key**：`trade_id, seqno, ordno, exchange_seq, broker_id, account_id, action, code, price, quantity, security_type('FUT'), delivery_month, market_type, ts`。
- **輪詢狀態**：`api.update_status(api.futopt_account)` → `api.list_trades()`。**讀 `Trade.status` 前必先 `update_status`**（place_order 回來時是 `PendingSubmit`）。`OrderStatus` 成員：`PendingSubmit, PreSubmitted, Submitted, Filled, PartFilled, Cancelled, Failed, Inactive`。`Trade.status`：`.status/.order_quantity/.deal_quantity/.cancel_quantity/.deals`。

### 3.4 部位與保證金

```python
positions = api.list_positions(api.futopt_account)   # list[FuturePosition]
# FuturePosition(id:int, code:str, direction:Action(Buy/Sell), quantity:int,
#                price:avg進場, last_price:mark, pnl:未實現float)
api.list_position_detail(api.futopt_account, detail_id=0)   # 進場日/seq/手續費/稅

m = api.margin(api.futopt_account)          # Margin 物件
# 關鍵欄位: today_balance, initial_margin, maintenance_margin, risk_indicator,
#          equity, available_margin, future_open_position, future_settle_profitloss ...
```

- **帳號物件**：登入後 `api.stock_account`（現股）＋ `api.futopt_account`（**期＋權共用同一個，SSF 用它**）自動填好。現股/期貨帳號獨立，依 terms 須分開開通/測試。

### 3.5 Simulation（paper）眉角

- `api = sj.Shioaji(simulation=True)` → `api.login(api_key=, secret_key=)`，**paper 不需 CA 憑證**。
- **Sim 伺服器時段：週一–五 08:00–20:00**（官方 terms 頁）；**18:00–20:00 限台灣 IP、08:00–18:00 無限制**（terms 頁載明，非社群傳言）→ daemon 從台灣主機（winrig 在台）跑無虞，海外 IP 傍晚會被擋。簽 API 條款後**等 ≥5 分鐘**再測（terms 頁，語意偏「審核延遲」[UNVERIFIED]）；**現股/期貨 sim 帳號要分開測**。
- doc sim 限制：模擬環境**下單不支援興櫃/零股**（現股 caveat，無 SSF 專屬 caveat）。
- ⚠️ **SSF paper 到底會不會撮合成交？docs 未明說 [UNVERIFIED]**。社群/家裡前例：sim 伺服器給**真實報價＋模擬撮合**且 sim 時段內會回委託/成交 callback，但成交可能延遲/部分、價格真實性有限。**V4 第一件事就是實測**：sim 時段內下一張可成交的 LMT（或 MKT）→ 確認收到 `OrderState.FuturesDeal` 且 `list_positions(futopt_account)` 有更新。時段外只會有 ack 無 fill。
- sim 假撮合**不模擬漲跌停**（用 `contract.limit_up/limit_down` 自己過濾，沿用舊 memory 教訓）。

---

## 4. 行情 + 常駐 daemon 運維（V4 資料層）

### 4.1 即時串流（daemon 首選；**stream 別 poll**）

```python
# 先註冊 callback，再 subscribe
@api.on_tick_fop_v1()                        # 期貨/SSF tick
def on_fop(exchange, tick: sj.TickFOPv1):
    if tick.simtrade: return                 # ⚠️ 濾掉試撮，否則 paper fill 用到假價
    ...
@api.on_tick_stk_v1()                        # 現股 tick
def on_stk(exchange, tick: sj.TickSTKv1):
    if tick.simtrade: return
    ...
api.quote.subscribe(api.Contracts.Futures.CDF.CDFR1,
                    quote_type=sj.constant.QuoteType.Tick,   # docs 用 sj.constant.*
                    version=sj.constant.QuoteVersion.v1)     # 路由到 on_tick_*_v1（近版預設 v1）
# quote_type: QuoteType.Tick | QuoteType.BidAsk；intraday_odd=True 為零股
```
- callback 亦有 setter：`api.quote.set_on_tick_fop_v1_callback(fn)` 等（注意 `.quote.` 命名空間）。signature 恆 `(exchange, obj)`。
- **payload 欄位**：
  - `TickFOPv1`（期/SSF）：`code, datetime, open, underlying_price, avg_price, close, high, low, volume, total_volume, tick_type, price_chg, pct_chg, simtrade`。
  - `TickSTKv1`（現股）：`code, datetime, close, volume, total_volume, tick_type, price_chg, pct_chg, bid/ask_side_total_vol, simtrade, intraday_odd, ...`。
  - `BidAskFOPv1`/`BidAskSTKv1`：五檔 `bid_price/bid_volume/ask_price/ask_volume`（list）＋ `underlying_price`（FOP）＋`simtrade`。
  - `tick_type`：1=外盤/buy aggressor，2=內盤/sell，0=unknown。
- **訂閱上限 200**（tick 與 bidask 各算一個）。

### 4.2 Snapshot / 最新價（週期性對帳用，非 daemon 主行情）

```python
snaps = api.snapshots([c1, c2, ...])         # 單次最多 500 檔；回 list[Snapshot]
```
- 欄位（現股/期/權相同）：`ts(ns int), code, exchange, open, high, low, close, tick_type, change_price, change_rate, average_price, volume, total_volume, amount, total_amount, buy_price, buy_volume, sell_price, sell_volume, volume_ratio`。
- **無 `yesterday_close`**：昨收 = `close - change_price` 推導。
- ⚠️ **cb-desk 現役碼分批 50 檔是保守值**——真實限制是 **市場資料 50 req/10s**（見下），而 `snapshots` **單次可帶 500 檔**。要掃很多檔時，用「單 request 帶 ≤500 檔」比「50 檔一批打多次 request」更省 request 額度。（cb-desk 分批 50 沿用「50 筆/5s」的舊理解，非 bug 但次佳。）
- `Snapshot` 是 MappingMixin 有 `__len__`：空快照 falsy，判空**用 `is None` 非 `or`**（cb-desk 踩過）。

### 4.3 歷史資料

```python
kbars = api.kbars(contract, start="2026-05-17", end="2026-05-18")   # 1 分 K
ticks = api.ticks(contract, date="2026-05-18",
                  query_type=sj.constant.TicksQueryType.AllDay)
```
- kbars 欄位：`ts(ns), Open, High, Low, Close, Volume, Amount`（大寫 OHLCV），**解析度 1 分**（自己聚合成 5m/15m/1h）。轉 df：`pd.DataFrame({**kbars})`。
- 深度回溯到 **2020-03-02**（股/期皆是）。**單次 kbars 日期範圍 ≤30 天**（長區間分窗迴圈）。
- 盤中（當日）`ticks` ≤10 calls/session、`kbars` ≤270 calls/session。
- 期/SSF：個別月合約會到期脫落，長歷史用連續 `...R1`/`...R2` 自動滾動。

### 4.4 Rate limits（現行，官方 limit 頁核實）

| 類別 | 上限 | 視窗 |
|---|---|---|
| **市場資料**（snapshots/ticks/kbars/credit_enquires…） | **50 req** | **每 10s** |
| **帳務**（account_balance/list_positions/margin/list_profit_loss…） | **25 req** | 每 5s |
| **下單**（place_order/cancel_order/update_status/update_qty/update_price） | **250 req** | 每 10s |
| 登入 | 1000 | 每日 |
| 盤中 `ticks`（當日）| 10 calls | per session |
| 盤中 `kbars`（當日）| 270 calls | per session |

- ⚠️ **記憶校正**：舊 memory 表寫「行情 50/5s」——官方 limit 頁現為 **50/10s**（本輪核實；以官方為準，實作照 10s 抓）。
- 最大訂閱 **200**、每 person_id 最大連線 **5**（每次 `login()`=1 連線，**一 process 一 login**，退出 `logout()` 否則洩連線）。
- **每日流量位元組上限**（每交易日 08:00 重置，依前日成交量分級）：0 成交→**500MB/日**；達 100M TWD 股 / 1000 大台 / 4000 小台→2GB；以上→10GB。`api.usage()` → `connections, bytes, limit_bytes, remaining_bytes`，daemon 輪詢並在低量時退避（丟 BidAsk 保 Tick）。
- 超限→約 **1 分鐘停權**；同日重犯→**IP＋帳號停權**。**設計鐵則：stream 不 poll**。

### 4.5 常駐 daemon 陷阱清單（每條配對修法）

| 陷阱 | 修法 |
|---|---|
| **合約非同步下載 race**（早碰 `api.Contracts.Futures...` KeyError） | 登入帶 `contracts_timeout=10000`（阻塞至載完）**或** `contracts_cb=` callback **或** 輪詢 `while api.Contracts.status != sj.constant.FetchStatus.Fetched: sleep(0.3)` |
| **subscribe 後程式秒退**（stream 被殺） | 主執行緒 keep-alive：`threading.Event().wait()` 或 daemon run-loop |
| **callback 執行緒**：串流由 Solace 背景 context thread 派發，**非主執行緒** [Shioaji 是否重派主緒 UNVERIFIED，防禦性處理] | callback **絕不阻塞**：快速 `queue.put()` 丟給 worker thread 做策略/下單；共享狀態加 lock |
| **token 24h 過期**（24/7 daemon 必踩） | 每 ~20–23h 排 `logout()`→`login()`（挑非盤時段），**re-login 後所有 subscribe 要重訂**（訂閱不跨新登入存活）；先 logout 舊 session 免燒掉 5 連線之一 |
| **偵測行情斷線**（無 heartbeat 欄位） | `api.quote.set_event_callback(fn)` 收斷線/重連事件 ＋ **tick 新鮮度看門狗**：追 `last_tick_ts`，盤中某流動標的 N 秒無 tick → 判斷斷線 → re-login+re-subscribe；任何 API call 逾時也當 session 死 |
| **sim 伺服器 18:00–20:00 限台灣 IP**（官方 terms 頁載明；08:00–18:00 無限制） | winrig 在台灣跑無此問題；海外 IP 傍晚登入會被擋 → 從台灣 IP 跑或避開該窗、登入失敗 retry-backoff |
| 流量位元組燒爆（重訂 200 檔 tick 在 500MB 層會逼近） | `api.usage()` 監控，低量丟 BidAsk 保 Tick 或降檔數 |

### 4.6 登入簽章（1.5.x 全參數）

```python
accounts = api.login(
    api_key=os.environ["SINOPAC_API_KEY"],
    secret_key=os.environ["SINOPAC_SECRET_KEY"],
    fetch_contract=True,          # 預設 True
    contracts_timeout=10000,      # ms，阻塞等合約載完（daemon 建議設）
    contracts_cb=None,            # callable(security_type)
    subscribe_trade=True,         # 訂委託/成交事件
    receive_window=30000,
)
```

---

## 5. 「先接永豐 paper」Step-1 Runbook（給 Delvin/主視窗直接照做）

> 目標：最小可跑的 paper 環境，證明「登入→查 SSF 合約→拉行情→下一張 paper 單→收成交→查部位」整條通。這是 V4 daemon 的種子。

1. **金鑰**：到 https://www.sinotrade.com.tw/newweb/PythonAPIKey/ 用**公司永豐帳戶**建 API KEY，勾「行情＋下單」，記下 secret（一次性），寫進專案 `.env`（`SINOPAC_API_KEY`/`SINOPAC_SECRET_KEY`）。`.env` 確認在 `.gitignore`。
2. **環境**：`uv venv --python 3.12 .venv && uv pip install "shioaji>=1.5.3"`。
3. **Smoke（sim 時段 08:00–20:00 內跑）**：照 §6 骨架，先只跑「登入＋等合約 Fetched＋`snapshots([CDFR1])` 印價」——驗證金鑰/連線/合約（**不下單**）。
4. **Paper 下單實測**：跑完整骨架下一張可成交 LMT `octype=New quantity=1` → **觀察是否回 `OrderState.FuturesDeal`＋`list_positions(futopt_account)` 是否更新**（回答 §3.5 的 [UNVERIFIED] SSF 撮合問題）。時段外只有 ack 無 fill 是正常。
5. **沉澱積木**：把「登入+合約解析+SSF 商品碼對照表+snapshot+下單封裝」照 `capability_coldstart_data_connector_archetype`（tests_dir 隔離、fake sj module 注入、`_ensure_login` 惰性登入重用連線）沉澱成 `capabilities/` 積木——**直接 fork `~/cb-desk/cbdesk/feeds/sinopac.py` 的 STOCKS 模式**，加期貨/SSF 分支。

### SSF V4 對接點（承接 backlog SSF 任務）
- SSF 交易任務結論：**taker 套利五類＋方向性 D1/D2 全掃完皆 no_edge**，SSF 定位＝**低成本、可雙向、稅費低的執行工具**，承載未來站得住的方向/擇時訊號（特徵源：intel 信息差引擎紅黃訊號、regime、法人流向）。
- V4 daemon 骨架＝**本 playbook §4.5 的 keep-alive/re-login/看門狗 ＋ §3 的下單/callback/部位對帳**，套家裡「預測→記帳→校準」四步：訊號→paper 下單→成交回報→部位/風險帳本→每日 paper 實績 vs 回測預期對帳，偏離大告警 admin（web push）。
- **死線**：paper-only 絕不真下單；live 切換（simulation=False＋activate_ca）只寫 V5 手冊，不寫進運行程式。

---

## 6. 最小 e2e 骨架（1.5.x，已核實的呼叫）

```python
import os, time, queue, threading
import shioaji as sj

api = sj.Shioaji(simulation=True)                        # paper，不需 CA
api.login(os.environ["SINOPAC_API_KEY"], os.environ["SINOPAC_SECRET_KEY"],
          contracts_timeout=10000)                       # 阻塞等合約
while api.Contracts.status != sj.constant.FetchStatus.Fetched:
    time.sleep(0.3)

# --- 成交/委託 callback：快速丟 queue，別阻塞 ---
fills = queue.Queue()
def on_order(stat, msg):
    if stat == sj.constant.OrderState.FuturesDeal:       # 成交（v1.0 起改名，非 FDeal）
        fills.put(msg); print("FILL", msg["code"], msg["price"], msg["quantity"])
    else:                                                # FuturesOrder ack
        print("ACK", msg["operation"]["op_code"], msg["order"].get("ordno"))
api.set_order_callback(on_order)

# --- 台積電近月 SSF：TAIFEX 商品碼 CDF -> CDFR1 ---
contract = api.Contracts.Futures.CDF.CDFR1               # 或 api.Contracts.Futures["CDFR1"]
print("snap:", api.snapshots([contract])[0].close)

order = sj.FuturesOrder(                                 # 官方期貨構造子（非 api.Order）
    action=sj.constant.Action.Buy, price=contract.reference, quantity=1,
    price_type=sj.constant.FuturesPriceType.LMT,
    order_type=sj.constant.OrderType.ROD,
    octype=sj.constant.FuturesOCType.New,                # 開倉='New'（非 'NewPosition'）
    account=api.futopt_account,
)
trade = api.place_order(contract, order)
print("placed:", trade.status.status)                    # PendingSubmit

time.sleep(3); api.update_status(api.futopt_account)
print("status:", trade.status.status, "dealt:", trade.status.deal_quantity)
for p in api.list_positions(api.futopt_account):
    print("POS", p.code, p.direction, p.quantity, "avg", p.price, "pnl", p.pnl)

api.logout()
```

---

## 7. 實作時要 runtime 驗的 [UNVERIFIED] 清單（別當定論）

1. **`api.Contracts.Futures.CDF` 屬性名** ＋ `underlying_kind='S'`：由 TAIFEX 商品碼推論，Shioaji docs 未逐字示範 → `list(api.Contracts.Futures)` ＋ `dir(...CDFR1)` 確認。
2. **`underlying_code` 反查欄位**在 1.5.x Future 物件存不存在（現範例只見 `target_code`）→ 優先用 `{stock_id: product_code}` 對照表，別靠反查。
3. **SSF simulation 撮合行為**（會不會回 `FuturesDeal`/更新部位）docs 未載 → sim 時段內實測（見 §5 步驟 4）。
4. **callback 執行緒**：Solace docs 證背景 context thread，Shioaji 未載是否重派主緒 → 防禦性（callback 不阻塞、共享狀態加 lock）。
5. **`sj.FuturesOrder` vs `api.Order(...octype=)`** 期貨等價性：docs 只示範 `sj.FuturesOrder`（現股才見 `api.Order`）→ 期貨用 `sj.FuturesOrder`；小型台積電碼 `QFF`/`QF` 與「簽約後等 5 分鐘」語意也待確認。
6. **元大 SPARK 是否有真 pip 套件**（vs 元件下載）→ 真要接元大時查證。

> ✅ **本輪 fresh-context 驗證者已核實正確、無需 runtime 再驗**（原列 UNVERIFIED 但實查為真）：sim 伺服器 **18:00–20:00 限台灣 IP** 是官方 terms 頁載明（非社群傳言）；`OrderState` 成員為 **`FuturesDeal`/`FuturesOrder`**（非 `FDeal`/`FOrder`）；行情 rate limit **50 req/10s**；2330→`CDF`；1.5.6 `cp37-abi3` wheel 可裝 3.14。

---

## 8. 來源

- Shioaji 官方 docs：https://sinotrade.github.io/ （contract / order/FutureOption / order_deal_event/futures / accounting/position / accounting/margin / login / prepare/terms / simulation / limit / market_data/*）
- Shioaji GitHub：https://github.com/Sinotrade/Shioaji ｜ PyPI：https://pypi.org/project/shioaji/（1.5.6 / cp37-abi3+cp314t / requires_python>=3.7，本輪權威查證）
- 金鑰自助頁：https://www.sinotrade.com.tw/newweb/PythonAPIKey/
- 元大 SPARK API：https://www.yuanta.com.tw/file-repository/content/API/page/index.html ｜ 元大期貨 EasyWin（legacy）：https://www.yuantafutures.com.tw/ytf/easywin/api/download.html
- 富果 Fugle（trade EOL 通知）：https://developer.fugle.tw/docs/trading/intro/ ｜ 凱基 KGI SUPER PY：https://superpy.kgieworld.com.tw/ ｜ 元富→台新併購：https://www.tssco.com.tw/TSHOLDINGSMERGE/announcement/index.html
- 現役參考碼（已驗證 STOCKS 路徑）：`~/cb-desk/cbdesk/feeds/sinopac.py`

*（本 playbook 為 research 知識資產，非可執行程式；接元大或建 V4 daemon 時以此為 spec。）*
