# us_congress_trades 連接器 · 上線清單

骨架已產生(us_congress_trades.py + capabilities/tests/us_congress_trades.test.sh),以下才是真正的工作。

## 填空
- [ ] `classify()`:定義真實 red/yellow/plain 門檻+白話理由(參考 intel/tw_margin.py、intel/tw_fsc.py 的 signal 字串寫法)
- [ ] `_fetch()`:接上真實 API/RSS/官網;`.gov`/`.gov.tw` 網域一律先用 `_fetch_curl()`,別浪費一次踩坑循環去試 urllib
- [ ] 確認資料源是否需要 token/API key、免費層額度夠不夠(額度不夠就在 INDEX.md 記一筆,別悶著頭硬做)

## 接線(若是信息差引擎新源,接進 intel/patrol.py;其他領域比照當下 aggregator 結構)
- [ ] `intel/patrol.py` 開頭 import 加上 `us_congress_trades`
- [ ] `patrol.py::run()` 內加一段呼叫 `us_congress_trades.scan(watchlist_codes)`,結果併入 by_code
      (同碼多筆訊號合併時優先序 red > yellow > plain,別讓後面迴圈把更嚴重的蓋掉)
- [ ] 若不受 watchlist codes 限制(如 tw_fsc.py 自成一套金融機構清單),自成一組 loop,別硬塞進 codes 迴圈

## 收尾(mission 規定,缺一不可)
- [ ] 填完 `capabilities/tests/us_congress_trades.test.sh` 的 TODO,`bash capabilities/tests/us_congress_trades.test.sh` 過
- [ ] 不必手動註冊——`capabilities/selftest.sh` 用 glob `tests/*.test.sh` 自動撿到
- [ ] `capabilities/INDEX.md` 新增條目(格式見該檔開頭範本:用途/位置/呼叫/依賴/狀態/建立)
- [ ] `eval/evals.json` 加一題對應考題
- [ ] `capabilities/usage.log` append 一行(首建即實跑算首次使用)
- [ ] 真實資料至少跑一次驗證(合成 fixture 不算數,要看過真實 API 回應長什麼樣)
- [ ] 依 mission VERIFY 標配:若判斷值得,開一個全新 context 子代理只給程式碼+已驗證結果做驗證者分離

## 已知坑(骨架已規避,新填的邏輯若違反這些會重踩舊坑)
- `.gov`/`.gov.tw` 憑證鏈驗證失敗 → 用 curl 不要用 urllib(TDCC/金管會/證交所皆踩過同一顆雷)
- 快取 key 只留「今天」,否則檔案無限長大(骨架的 cache 剪枝那行別刪)
- 台股代碼常混雜 4 碼正股與 6 碼權證/牛熊證,務必用 `len(code) == 4` 過濾(TWSE 監理公告連接器踩過)
- UA 字串別用裸 `"Mozilla/5.0"`,部分 WAF(如 FRED)會把教科書級假瀏覽器特徵當機器人指紋(骨架 `_fetch_urllib` 已用完整版本字串)
- 測試檔的「今天」一律用 `datetime.date.today()`,絕不寫死字面字串(同款 bug 已復發 5 次,見 memory `harness_golden_live_data_drift.md`)
- `classify()` 保持純函式(不呼叫網路/不吃 `datetime.now()`),否則自測無法離線跑
- 需要合併多個 API 判斷是常態(如 tw_margin.py 同時查融資餘額+股價兩支端點對齊日期),
  骨架的 `_fetch()` 只放單一 URL 當起點,不是限制——填空時視需要呼叫兩次
- test.sh 骨架預設 `cd "$HOME/Delvin-agent"`(信息差引擎慣例);若這個連接器放在別的 repo,記得把這行也改掉
