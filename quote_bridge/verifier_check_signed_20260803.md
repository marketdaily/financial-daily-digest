# VERIFIER REPORT
TASK: check-signed-silent-guard-20260803
DATE: 2026-08-03
VERDICT: SOUND-WITH-CORRECTIONS
FINDINGS: 7

第 2 輪(複驗)。第 1 輪的 6 條我用**自己的腳本、不經作者測試檔**重新復驗,**全部真的修掉了**(逐條證據見 `## Notes` 的「舊 6 條復驗表」)。作者宣稱的 16 組自測 / 17 突變 / 合約測試我也獨立跑過並確認為真。
主線功能現在是對的:分腿判準改看 `account_type` 後,真 SDK 下兩腿都認得出來;推播沒送到不記帳、下輪補講且不重複;watch 檔壞掉不再讓偵測器每小時 traceback。

但**修出了新洞**,其中一條是「良性事件把整支偵測器打死」(F1),另外三條是同一個老病灶換位置復發:**失敗路徑上沒有人被告知**(F2 漏 session、F3 損毀告警被下游洗掉、F4 喚醒永遠失敗沒人知道)。因此裁 SOUND-WITH-CORRECTIONS 而非 SOUND。

```
環境:python3.12 / shioaji 1.5.6 (/home/userdelvin/.venvs/shioaji-bridge)
基準(我自己跑的,不是抄作者的):
  $ ~/.venvs/shioaji-bridge/bin/python quote_bridge/test_check_signed.py      → ✅ 全過 RC=0(含合約測試 15c/15d/15e)
  $ ~/.venvs/shioaji-bridge/bin/python quote_bridge/test_check_signed.py --mutate → ✅ 突變測試 17/17 全部被咬住
  $ bash ~/autonomous/capabilities/tests/check_signed.test.sh                 → PASS check_signed
現況未變:.signed_watch.json = {"first_seen":"2026-07-30"};無任何 .signed_ok*;.qualify_*_done mtime = 07-30 22:23
本輪全程未發任何推播(push 全 stub)、未碰任何真 marker(全部 tempfile / copy2 副本);未 commit、未改任何生產檔。
下週一 08:23 的真實預測(用真檔副本跑):首推「⚠️ 過檔逾期:證券/期貨自 2026-07-30 起已過 2 個營業日」,
08-04 不重推,08-10 重推「(持續追蹤)…7 個營業日」——符合設計。
```

## F1 [HIGH] 開一個複委託帳號(AccountType.Intl='H')就會讓整支偵測器 fail-closed 死掉,而且文案誤報成「登入失敗」
- symptom: `_leg_of()` 對認不得的 `account_type` 一律 `raise RuntimeError`,而 shioaji 的 `AccountType` 除了 Stock('S')/Future('F') **還有 Intl('H')=複委託/海外**。永豐只要把一個複委託帳號掛上同一把 API key,`account_states` 就整包拋例外 → 連證券/期貨那兩個**認得出來的**帳號的 signed 狀態都讀不到 → main 走 except → 每天推一則「登入失敗…偵測器等同失明」→ rc=1 → **期貨過檔的看門人徹底死亡**。一個良性事件(老闆去開複委託,他本來就是做美股的)把 SSF 唯一 blocker 的偵測器打成全損。文案也誤導:login **其實成功了**,錯的是帳號型別,老闆會照字面去查憑證/網路/權限,而不是去看永豐掛了什麼新帳號。
- evidence:
```
$ ~/.venvs/shioaji-bridge/bin/python   (真 shioaji 1.5.6 物件)
AccountType members: ['Future', 'Intl', 'Stock', 'name', 'value']
Stock value= 'S'   Future value= 'F'   Intl value= 'H'
Stock  -> _leg_of = stock
Future -> _leg_of = futopt
Intl   -> RAISES RuntimeError 未知的永豐帳號型別 account_type=<AccountType.Intl: 'H'> class=Account
account_states([stock, intl]) -> RAISES RuntimeError …            ← 證券的 signed 也一起讀不到了

# e2e(注入假 shioaji 模組,回 [stock(S,False), intl(H,True)]):
  main rc: 1
  老闆收到的文案: ⚠️ 永豐 API 簽署偵測器登入失敗(RuntimeError: 未知的永豐帳號型別 account_type='H' …)
                  ——今天起無法確認過檔狀態,偵測器等同失明,請人工確認。
```
  (check_signed.py:72-87 `_leg_of`;複現腳本 /tmp/vcs2/adv3.py 區段 B)
- 我第 1 輪建議「認不得就 raise」是針對**未知**型別;Intl 是**已知且與本任務無關**的第三腿,不該讓它中斷整個讀取。這條算我上一輪的建議沒講清楚,但缺陷是真的。
- fix: 認得的兩腿照舊,無關腿**跳過**,真正未知的才出聲(而且不要冒充登入失敗):
```python
IGNORED_LEG_CODES = {"H"}          # Intl 複委託:與本偵測器無關
def _leg_of(account):
    ...
    if code in IGNORED_LEG_CODES: return None          # 跳過,不影響另外兩腿
    raise UnknownLegError(...)                          # 專屬例外
# account_states: kind = _leg_of(a);  if kind is None: continue
# main: except UnknownLegError → 另一則文案「永豐掛上了未知型別帳號 X,分腿判準需更新」,不要寫「登入失敗」
```

## F2 [MEDIUM] `account_states` 拋例外時永豐 session 沒有被 logout —— 每小時漏一個
- symptom: `login_states()` 是「先 `api.login()` 成功、再算 `account_states(accounts)`、最後才把 api 回給呼叫端」。F1 的 raise(或任何 account_states 例外)發生在 login 之後,`api` 這個物件連回都沒回去,`main` 的 `finally: api.logout()` 根本碰不到它 → 登入成功但**永不登出**,cron 每小時重複一次。券商 session 是有數量/單一登入限制的資源(這支還是「本人專用行情」紅線下的東西),漏一整天 10 個 session 可能讓後續登入或看盤 bridge 一起遭殃。對照組:`api_qualify_test.py:85-91` 的 `live_signed_states` **有** `try/finally` 包住 `account_states`,同一份邏輯兩支寫法不一致。
- evidence:
```
=== B. _leg_of 拋例外時 API session 有沒有被 logout ===
  login_states raised: RuntimeError 未知的永豐帳號型別 account_type='H' class=_Acct
  session logged_out? [False]   <- False = 每小時漏一個永豐 session
```
  (check_signed.py:328-334;/tmp/vcs2/adv3.py 區段 B,用注入的假 shioaji 模組,未打真永豐)
- fix:
```python
api = sj.Shioaji(simulation=False)
accounts = api.login(...)
try:
    return account_states(accounts), api
except Exception:
    try: api.logout()
    except Exception: pass
    raise
```

## F3 [MEDIUM] watch 檔損毀告警推不出去時會被下游的 `_save_watch` 永久洗掉(F2 老病灶換位置復發)
- symptom: `alert_corrupt_watch` 遵守了「送達才記帳」,但它**沒有保住重試的依據**:同一輪稍後的 `overdue_alert`(或宣告流程)無條件 `_save_watch(sanitized_st)`,把壞欄位從檔案裡抹掉。下一輪 `_load_watch` 回報 `dropped=[]` → 損毀告警**永遠不會重試**。等於「推播通道當下剛好掛掉」就把這則告警吃掉了——正是第 1 輪 F2 判 HIGH 的同一個 pattern,只是搬到了 F3 的新程式碼裡。
- evidence:
```
=== A. watch 檔損毀告警在推播失敗時會不會被吃掉 ===
(watch = {"first_seen": "2026-07-30", "alerted_at_biz": "x"};push 通道丟 OSError)
push failed: OSError: CF 403 / network down
⚠️ 永豐簽署偵測器的 .signed_watch.json 有壞掉的欄位並已丟棄:alerted_at_biz。…
  round1 pushes: 0  watch on disk: {"first_seen": "2026-07-30"}      ← 壞欄位已被抹掉
  round2 pushes: ['⚠️ 永豐 API 過檔逾期:…']                          ← 通道已復原,但
  round3 pushes: ['⚠️ 永豐 API 過檔逾期:…']
  >>> 老闆有被告知 watch 檔壞過嗎? False
```
  (check_signed.py:226-240 `alert_corrupt_watch` + 274 / 411 的 `_save_watch`;/tmp/vcs2/adv3.py 區段 A)
- fix: 把「有一則損毀告警還沒送出去」寫成狀態而不是靠原始壞資料還在:`st["corrupt_pending"] = "、".join(dropped)`(送達才清掉),main 每輪看到 `corrupt_pending` 就重試。

## F4 [MEDIUM] 喚醒一直失敗時停走條件永遠達不到,而且沒有任何人被告知機器沒被叫醒
- symptom: 停走三件套裡的 `woke` 只有 `wake_machine()` 回 True 才會寫。若 `~/autonomous/trigger.sh` 不在(換機、目錄改名、autonomous 被搬走)或 Popen 失敗,`woke` 永遠是 False:偵測器**永遠停不下來**,每小時真的登入永豐一次直到天荒地老,而「叫醒自主機器接手 dry-run」這件事失敗了**只 print 一行到沒人讀的 log**——這正是這次要根治的「沉默的守衛」本身。老闆會看到「🎉 期貨生效」以為機器已經接手,實際上沒有。
- evidence:
```
=== C. wake 一直失敗(trigger.sh 不存在)→ 停走條件達得到嗎?有人被告知嗎? ===
  logins after 4 rounds: 4 (0 = 已停走)
  watch: {'announced': ['futopt', 'stock']}        ← 沒有 woke,永遠停不了
  pushes: ['✅ …【證券】簽署生效…', '🎉 …【期貨】簽署生效…']
  >>> 有任何一則告訴老闆『機器沒被叫醒』嗎? False
# 另一次真跑也印出:wake skipped: 找不到 …/noauto/trigger.sh   (只進 log)
```
  (check_signed.py:296-310 `wake_machine`、345-352 停走條件、407-411;/tmp/vcs2/adv3.py 區段 C、/tmp/vcs2/adv4.py 尾段)
- 現況 `~/autonomous/trigger.sh` 存在且介面相符(`trigger.sh "reason"`),所以 winrig 上今天不會踩到;這是「靠環境剛好對」而不是靠設計。
- fix: 喚醒連續失敗 N 輪(或第一次就)推一則告警;或把喚醒失敗記成 `wake_fail_count`,超過門檻改推「請手動跑 trigger.sh」並允許停走,不要無限期掛著每小時登入永豐。

## F5 [MINOR] JSON `null` 欄位不算「損毀」:first_seen 被靜默重錨,和 14i 的保證不一致
- symptom: `_sanitize_watch` 用 `if fs is not None:` 開頭,所以 `"first_seen": null` 走的是「這個欄位不存在」而不是「這個欄位壞了」——**不進 `dropped`、不推損毀告警**,等待天數靜靜重新起算。同一個檔案裡 `"first_seen": 20260730` 會告警、`"first_seen": null` 不會,行為不一致;`alerted_at_biz: null`、`announced: null` 同理。
- evidence:
```
  OK    first_seen int         rc=0 pushes=1 watch={'first_seen': '2026-08-10', 'corrupt_alert_date': …}   ← 有告警
  OK    bad date               rc=0 pushes=1 …                                                            ← 有告警
  OK    first_seen null        rc=0 pushes=0 watch={'first_seen': '2026-08-10'}                            ← 靜默重錨
```
  (check_signed.py:113-119;/tmp/vcs2/regress.py「舊F3 全表」)
- 實務衝擊被 `signing_anchor()` 擋掉大半(生產上 `.qualify_*_done` 還在 → 錨回 07-30,不會歸零);純粹是損毀偵測的一致性缺口。
- fix: 用 `sentinel = object(); raw.get("first_seen", sentinel)` 區分「不存在」與「存在但值是 null」,後者列進 `dropped`。

## F6 [MINOR] 逾期文案會誣賴「已生效且已落 marker」的那一腿
- symptom: `pending` 只看本輪 `states`,不看 `settled(k)`。永豐回一次抽風的 False(或該腿被短暫回收)時,已經落過 marker、已經宣告過生效的證券腿會被寫進逾期文案:「證券/期貨自 2026-07-30 起已過 7 個營業日仍未生效」——老闆拿這句去找營業員 Norris 查一個早就生效的帳號。
- evidence:
```
=== D. 已落 marker 的腿因 API 短暫回 False → 逾期文案會不會誣賴它 ===
(.signed_ok_stock 已存在、announced=["stock"];本輪 states={'stock': False, 'futopt': False})
  push: ⚠️ 永豐 API 過檔逾期:證券/期貨自 2026-07-30 起已過 7 個營業日仍未生效…該找營業員 Norris 查是否卡在系統過檔。
```
  (check_signed.py:262;/tmp/vcs2/adv3.py 區段 D)
- fix: `pending = [LEG_LABEL[k] for k in (...) if states.get(k) is not True and not settled(k)]`;若某腿曾 settled 卻回報 False,那是另一種事故,值得**另一則**告警(帳號被收回)而不是混進過檔逾期。

## F7 [MINOR] 寫入端(marker / watch)失敗仍是裸例外:唯讀或滿磁碟時偵測器每小時無聲暴斃
- symptom: 讀取端這次硬化了(sanitize + 原子寫),但**寫**還是沒有保護:`open(LEG_MARKER[kind],"w")`(377)、`_save_watch`(274/411/323)任何一個丟 OSError 都會直接穿出 `main`,cron 收到 traceback 進 log、零推播。宣告的原則是「偵測器自己死了正是最該出聲的時候」,這條路徑沒做到。
- evidence:
```
=== E. 推播成功但 watch 寫不進去(唯讀目錄)→ 會不會每小時重講一次 ===
  round1 CRASH: PermissionError [Errno 13] Permission denied: '…/.signed_ok_futopt'
  推出去的: []          ← 期貨已生效卻一個字都沒送出去,而且每小時重複同樣的死法
```
  (/tmp/vcs2/adv3.py 區段 E)
- fix: 在 `main` 最外層包一層「偵測器自身異常」告警(同日+錯誤型別去重,沿用 `alert_login_failure` 的記帳法),再 `return 1`。這樣任何沒預料到的例外都至少會出一次聲。

## Notes
- **舊 6 條復驗表(全部用我自己的 /tmp/vcs2/regress.py 跑,不經作者測試檔)**:
```
舊F1 分腿判準  ✅ 修掉:真 shioaji.Account 下 account_states([S,F]) = {'stock':True,'futopt':True};
               [stock(True), fut(False)] = {'stock':True,'futopt':False}(期貨不再蓋掉證券);
               [stock(True), stock(False)] = {'stock':True}(OR 而非後寫贏);舊 SDK 名稱後備仍在。
舊F2 推播永久吃掉 ✅ 修掉:推失敗後 announced=['stock'](不含 futopt)→ 通道復原下一輪補講期貨 → 再一輪不重複。
               token 缺席也算沒送到:兩輪 announced=[],token 回來後兩則各補一次、之後不再重複(adv3 區段 F)。
舊F3 watch 損毀 ✅ 修掉:第 1 輪會 CRASH 的 4 種(first_seen null/int/非法日期、alerted_at_biz 字串)
               現在全部 rc=0;alerted_at_biz=99999(時鐘前跳)不再永久閉嘴,當輪即重推。
舊F4 .env/token ✅ 修掉:.env 不存在 → 印警告後 rc=0(不再 traceback);token 缺席大聲印且算「沒送到」。
舊F5 假 fixture  ✅ 修掉:fixture 帶 account_type;合約測試用真 sj.Account;test.sh 改用 shioaji venv 的 python
               (我實跑 guard = PASS,且合約測試三條 15c/15d/15e 真的有執行,不是 SKIP)。
舊F6 舊 marker   ✅ 修掉:.signed_ok 存在時遷成 .signed_ok_stock 並補進 announced,不再重複宣告證券生效。
```
- 我另外確認採納的兩條 Notes 也真的生效:`signing_anchor()` 對真檔副本回 `2026-07-30`(=`.qualify_*_done` 的 mtime,不是「第一次跑空那輪」);另一腿生效後剩下那腿**仍會**被催。
- 三個狀態(marker / announced / woke)交叉不同步我逐一走過,除上列 F3/F4 外沒有卡死或漏講:marker 在但 announced 缺 → 下輪補講一次即收斂;announced 在但 marker 被人為刪掉 → 重新落 marker 但不重複宣告(合理);token 時有時無 → 恢復後兩則各補一次、之後不再重複(logins 也隨即停在 3)。
- 一個可接受的副作用(不列為缺陷):某一腿剛生效的那一輪,老闆會同時收到「✅ 某腿生效」+「⚠️ 另一腿過檔逾期」兩則。這是採納 Notes 修法的必然結果,噪音可接受。
- `_save_watch` 用 tmp+`os.replace` 是對的,但沒有 `fsync`:ext4 上斷電仍可能得到「replace 生效但內容還沒落地」的零長度檔。零長度會被 F3 的路徑接住(視為 JSON 解析失敗並告警),所以只是理論上的殘留,列此備查。
- `api_qualify_test.py` 本輪未修改(`git diff --stat` 為空),它經由 `check_signed.account_states` 繼承了 F1 的 Intl 缺陷:真的掛上複委託帳號時 `live_signed_states()` 會拋例外並穿出 `main()`,而那支腳本**沒有任何自身異常告警**,只會靜靜寫進 api_qualify.log。目前兩個 `.qualify_*_done` 都在,main 第 105 行就 return,所以暫時不會引爆。
- UNVERIFIED:未對永豐做真實登入(限制下不值得),因此「永豐實際掛上期貨帳號那一刻回傳的物件」仍只由 `_core.pyi` 的 `List[Account]` 型別宣告 + 合約測試的真 `sj.Account` 物件推得;分腿判準改成 `account_type` 後,這個推論的風險比上一輪(靠類別名稱)低很多,但仍不是生產實證。
- UNVERIFIED:未驗證 alert-worker `/internal/admin-line-push` 與現行 token 是否真的回 200(硬性限制禁止發推播)。所有「送達/沒送達」的行為都是用 stub 驗的邏輯,不是通道實證。
