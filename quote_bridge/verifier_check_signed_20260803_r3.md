# VERIFIER REPORT
TASK: check-signed-silent-guard-20260803
DATE: 2026-08-03
VERDICT: SOUND-WITH-CORRECTIONS
FINDINGS: 6

第 3 輪(獨立複驗)。第 2 輪的 F1–F7 我用**自己寫的 harness**(`/tmp/vcs3/h.py`,不載入作者的
`test_check_signed.py`、不沿用它的 fixture 假設)逐條重跑,**七條全部真的修掉了**(逐條證據見
`## Notes` 的「第 2 輪 F1–F7 獨立復驗表」)。作者宣稱的「自測 23 組全過 / 突變 28/28 / test.sh PASS」
我也各自實跑確認為真,不是抄他的輸出。真永豐登入 e2e 我自己跑了一次(全部落地路徑導 tmp、push 全 stub)。

但**還有殘留**,其中最重要的一條是**第 2 輪 F4 的修法只修到一半**:`wake_machine` 的 `"sent"`
只證明「fork 出了一個 bash」,不證明 trigger.sh 真的跑起來——而 `"sent"` 正是讓偵測器**永久停走**
的閘門。trigger.sh 存在但讀不到/壞掉時,`wake_machine` 回 `"sent"` → `woke=True` → 偵測器退休,
沒有任何人被告知機器其實沒接手。這正是本次要根治的「沉默的守衛」自己換了一層皮復發。
另有兩條 MEDIUM(逾期告警可被未來日期 first_seen 永久靜音;夜巡守衛在合約測試 SKIP 時仍報 PASS =假綠)
與三條 MINOR。沒有 CRITICAL/HIGH,主線功能是對的,因此裁 SOUND-WITH-CORRECTIONS。

```
環境:shioaji 1.5.6 (/home/userdelvin/.venvs/shioaji-bridge) / 另驗 /usr/bin/python3 的 shioaji 1.7.0
基準(我自己跑的):
  $ ~/.venvs/shioaji-bridge/bin/python quote_bridge/test_check_signed.py
      → ✅ check_signed 自測全過(含合約測試 15c/15d/15e 真的執行,非 SKIP)
  $ ~/.venvs/shioaji-bridge/bin/python quote_bridge/test_check_signed.py --mutate
      → ✅ 突變測試 28/28 全部被咬住
  $ bash ~/autonomous/capabilities/tests/check_signed.test.sh
      → PASS check_signed
真永豐 e2e(我自己跑,fetch_contract=False,push 全 stub,marker/watch 全部指到 tmp 副本):
  REAL states = {'stock': False, 'futopt': None}
  原始帳號 = [(<AccountType.Stock: 'S'>, signed=False, class='Account')]   ← 期貨帳號目前根本沒掛上
  logout ok
  用真狀態跑 2026-08-03 → rc=0,今天 08:23 老闆會收到:
    「⚠️ 永豐 API 過檔逾期:證券/期貨自 2026-07-30 起已過 2 個營業日仍未生效…」
  真檔案 mtime 未變(.qualify_*_done Jul 30 22:23 / .signed_watch.json Jul 31 17:23)
cron 接線已確認存在:
  23 8-17 * * 1-5 flock -n /tmp/qb_check_signed.lock ~/.venvs/shioaji-bridge/bin/python …/check_signed.py
本輪全程:未發任何真實推播(push 一律 stub)、未 commit、未碰 quote_bridge/ 下任何真 marker 與
.signed_watch.json(全部走 tempfile / shutil.copy2 副本);唯一對外行為是一次唯讀的永豐登入+logout。
```

## F1 [MEDIUM] `wake_machine` 的 "sent" 只代表 fork 成功,不代表 trigger.sh 跑起來——而它是**永久停走**的閘門
- symptom: 第 2 輪 F4 的修法把「已叫醒自主機器」定義成 `subprocess.Popen(...)` 沒丟例外。
  `Popen` 是非同步的,`start_new_session=True` 且 stdout/stderr 全導 `DEVNULL`,**從不檢查子行程結束碼**。
  只要 `/bin/bash` 這個 executable 本身 spawn 得起來就回 `"sent"`。於是 trigger.sh 存在但**讀不到 /
  權限壞掉 / 內容壞掉 / 一開頭就 exit 1** 時,`wake_machine` 一律回 `"sent"` → `st["woke"]=True` →
  `_run` 下一輪在第 512 行直接 `return 0`,**偵測器就此永久退休**,而「沒有人接手 SSF dry-run」這件事
  一個字都沒送出去。這正是 F4 宣稱要根治的東西(`"absent" 當成功 → 老闆以為機器接手了,其實沒有,
  而這件事只 print 進沒人讀的 log`),只是失敗點從「檔案不存在」下移到「檔案存在但跑不動」。
  副作用:`"failed"` 這條腿實際上近乎死碼(要 fork 失敗/ENOMEM 才走得到),`WAKE_FAIL_LIMIT`、
  `wake_fail` 計數器與對應告警在真實故障模式下永遠不會被觸發。
- evidence: check_signed.py:407-418(`wake_machine`)、check_signed.py:578-604(`woke` 寫入)、
  check_signed.py:512(停走閘門)
```
$ /home/userdelvin/.venvs/shioaji-bridge/bin/python /tmp/vcs3/r2.py
  trigger.sh 不存在 ->            absent          ← 這條 F4 有修對
  trigger.sh 存在(chmod 000)->  sent            ← ⚠️ 回報成功
  trigger.sh 存在(chmod 000)且真的跑起來了嗎? NO

# 同一份 trigger.sh 直接用 check_signed 的呼叫法跑:
$ /bin/bash /tmp/tmp.aIeHPuk1gD/trigger.sh note
/bin/bash: /tmp/tmp.aIeHPuk1gD/trigger.sh: Permission denied
  bash exit=126  ran檔存在=NO        ← 子行程 126 失敗,wake_machine 仍回 "sent"
```
  補充(不是本身的 bug,但放大這條的後果):真 `~/autonomous/trigger.sh` 自己的註解寫著
  「所有閘門(DISABLED/熔斷/本人在場/用量/輪數上限)照常生效」——**即使 spawn 成功,自主機器也可能
  當場被閘門擋掉什麼都不做**。也就是說 `woke=True` 這個「可以退休了」的訊號,和「SSF dry-run 真的
  有人接手」之間,現在完全沒有任何實證關係。
- fix: 讓 `"sent"` 有實證支撐,而不是靠 Popen 沒丟例外。最小改法(仍不阻塞 cron):
```python
p = subprocess.Popen([...])
try:
    rc = p.wait(timeout=10)          # trigger.sh 只寫兩個檔就 exec driver.sh,10s 綽綽有餘
except subprocess.TimeoutExpired:
    return "sent"                    # 已經在跑了,算送出
return "sent" if rc == 0 else "failed"
```
  更強的做法:改看 trigger.sh 的落地證據(`~/autonomous/state/driver.log` 尾端出現本次 REASON)才記
  `woke=True`——與本檔「送達才記帳」的既有紀律一致(`announced` 就是這樣做的)。

## F2 [MEDIUM] `first_seen` 若落在未來,逾期告警**永久靜音且零輸出**——時鐘前跳保護只做了一半
- symptom: `overdue_alert` 對 `alerted_at_biz` 特地做了時鐘前跳保護(第 333-336 行,註解明寫
  「winrig 有 41h 斷電史」),但對 `first_seen` **完全沒有同樣的保護**。`first_seen` 一旦是未來日期,
  `biz_days_between(first, today)` 的 while 迴圈一次都不跑 → `waited=0` → `due=False` → 這支偵測器
  **唯一的主動告警**從此不再出聲,而且連 log 都不會多印一個字(`print(msg)` 在 `due` 分支內)。
  可達路徑(兩條都對得上作者自己引用的 winrig 時鐘史):①`.signed_watch.json` 遺失 +
  `.qualify_*_done` 也不在(兩者都是未追蹤檔)+ 當下時鐘前跳 → `signing_anchor` 退回 `today`(未來)
  並被 `setdefault` 寫死;②`.qualify_*_done` 的 mtime 在時鐘前跳期間被寫出 → `signing_anchor` 回未來日。
  一旦寫進去就自己好不了(`setdefault` 永不覆寫)。
- evidence: check_signed.py:329-338(`first`/`waited`/`due`)vs check_signed.py:333-336(只保護 `alerted_at_biz`)
```
$ /home/userdelvin/.venvs/shioaji-bridge/bin/python /tmp/vcs3/c.py
=== C2. 未來日 first_seen → 逾期告警永久靜音? ===
  (watch = {"first_seen":"2027-01-01"};states={'stock':False,'futopt':None};跑 08-03 / 09-01 / 11-02)
  三個月後 pushes: [] | watch: b'{"first_seen": "2027-01-01"}'
```
  對照組(同一份表,`/tmp/vcs3/b.py`):`first_seen` 是 bool/數字/`2026-13-01`/null 都會出「壞掉的欄位」
  告警,唯獨「合法但在未來」靜悄悄。
- fix: 在 `overdue_alert` 把未來錨點鉗回今天並當成損毀出聲:
```python
first = date.fromisoformat(st.get("first_seen") or signing_anchor(today).isoformat())
if first > today:                       # 時鐘曾前跳,和 alerted_at_biz 用同一套判準
    first = today
    st["first_seen"] = first.isoformat()
    dropped_hint = "first_seen(未來日期,已鉗回今天)"   # 併入損毀告警管道
```
  同理 `signing_anchor` 應該把未來 mtime 過濾掉:`if d <= today`。

## F3 [MEDIUM] 夜巡守衛在「合約測試被 SKIP」時仍然報 PASS——假綠比假紅危險
- symptom: `contract_test()` 是唯一咬得住 F1(真 SDK 下靠類別名稱分腿必敗)的保護。它在拿不到
  shioaji 時走 `SKIPPED` 分支,但 `__main__` 只在 `FAILED` 非空時 `sys.exit(1)`,**SKIPPED 不影響
  結束碼**;`check_signed.test.sh` 第 22 行只看結束碼,第 23 行雖然 grep 出 SKIP 字樣印在畫面上,
  卻照樣往下走並在第 30 行印 `PASS check_signed`。夜巡是無人看畫面的 cron
  (`50 4 * * * … selftest.sh`),沒有人會讀那行 SKIP。結果:venv 壞掉/搬走的那天起,守衛每晚
  照樣綠燈,而它最重要的那條保護其實沒有在跑。
  附帶:`check_signed.test.sh` 第 11-13 行的註解**描述錯了自己的行為**——它說「用裸 python3 →
  合約測試 SKIP」,但 `contract_test()` 第 596 行是 `py = SHIOAJI_PY if os.path.exists(SHIOAJI_PY)
  else sys.executable`,**永遠優先用 venv 的 python,和 test.sh 選的 `PY` 無關**。照註解去改 test.sh
  的 `PY` 不會有任何效果,真正的觸發條件是 venv 路徑消失。
- evidence: test_check_signed.py:596、611-614、751-755;check_signed.test.sh:18,22-23,30
```
# 模擬 venv 消失(SHIOAJI_PY 指到 /nonexistent)且執行環境沒有 shioaji:
$ python3 -m venv --without-pip /tmp/vcs3/clean
$ /tmp/vcs3/clean/bin/python -c "import shioaji"
ModuleNotFoundError: No module named 'shioaji'
$ /tmp/vcs3/clean/bin/python /tmp/vcs3/t_noshio.py ; echo "exit=$?"
  SKIP 沒有可用的 shioaji(/tmp/vcs3/clean/bin/python);F1 的真 SDK 保護在本環境未被驗證
  ⏭️ SKIP: 合約測試:跑不到 shioaji(…) — ["ModuleNotFoundError: No module named 'shioaji'"]
✅ check_signed 自測全過
測試 exit code = 0            ← ⚠️ 守衛據此判 PASS
```
- fix: 兩處二選一(建議都做)——①`test_check_signed.py`:`if FAILED or SKIPPED: sys.exit(1)`
  (或加 `--require-contract` 旗標,夜巡用它);②`check_signed.test.sh`:
  `echo "$out" | grep -q "SKIP" && { echo "FAIL 合約測試被跳過(shioaji 不可用)"; exit 1; }`。
  順便把第 11-13 行的註解改成描述真正的觸發條件(`SHIOAJI_PY` 路徑存在與否)。

## F4 [MINOR] 程式本身沒有鎖:唯一的併發保護在 crontab 的 `flock`,實測併發會重複推播+重複喚醒+吃掉已送達紀錄
- symptom: `check_signed.py` 對 `.signed_watch.json` 與 marker 沒有任何檔案鎖;`_save_watch` 只保證
  單次寫入是原子的(tmp+`os.replace`),不保證 read-modify-write 不被覆蓋。兩個實例併發時:
  ①老闆收到**重複**的「🎉 期貨生效」與「✅ 證券生效」;②`trigger.sh` 被叫醒**兩次**;
  ③後寫的行程會把先寫行程「已送達」的 `announced` 直接抹掉(lost update)——也就是說,
  這支檔案花最多力氣建立的「送達才記帳」帳本,在併發下會被靜默清零,下一輪再對老闆講一次。
  保護存在但**不在被審的產出物裡**:它在 crontab 的 `flock -n /tmp/qb_check_signed.lock`。
  也就是說 cron vs cron 是安全的,但**手動執行 / runbook / 另一支腳本呼叫**完全不受保護,
  而且這個保護沒有被 `check_signed.test.sh` 守著——改掉 crontab 寫法就會無聲失去它。
- evidence: check_signed.py:204-219(`_save_watch`,無鎖)、508/562/605(read-modify-write 窗口)
```
# 真 OS 行程(multiprocessing fork + Barrier 同步,無 sleep):
$ /home/userdelvin/.venvs/shioaji-bridge/bin/python /tmp/vcs3/e.py
=== E1. 兩個 check_signed 同時跑(程式本身無鎖) ===
  老闆收到的推播則數: 4
    重複『期貨生效』則數: 2
    重複『證券生效』則數: 2
  trigger.sh 被叫醒次數: 2

$ /home/userdelvin/.venvs/shioaji-bridge/bin/python /tmp/vcs3/f.py
=== E3. 兩行程狀態分歧 → 已送達的通知記錄被覆蓋(lost update) ===
   A送達: rc=0 送出 2 則
   B失敗: rc=0 送出 0 則
   最終 watch: {"announced": [], "woke": true}
   >>> A 真的送達了 2 則,但帳本記得嗎? announced = []

# guard mutation(把保護拿掉,確認測試會變紅):
=== E4. crontab 的 flock -n 是否真的擋得住 ===
   有 flock -n:實際執行次數 = 1 (1=擋住)
   拿掉 flock:實際執行次數 = 2 (2=會併發)
```
- fix: 把鎖搬進程式(不要只靠呼叫端):`main()` 開頭 `fd=os.open(LOCK,O_CREAT|O_RDWR)`,
  `fcntl.flock(fd, LOCK_EX|LOCK_NB)`,拿不到就 `return 0`。這樣手動執行也安全,且鎖的存在可以被
  `check_signed.test.sh` 用兩個真行程守住(照 E1 的寫法即可)。

## F5 [MINOR] 損毀偵測仍有兩個「靜默吞掉狀態」的缺口:整份檔案是 `null`、`announced` 元素型別漂移
- symptom: 第 2 輪 F5 的 sentinel 修法只做到**欄位層**。同一個「null 不等於不存在」的問題在另外兩個
  位置還在:
  ①`_sanitize_watch` 第 163 行 `(["<整個檔案不是物件>"] if raw is not None else [])` ——
  整份檔案內容是 `null` 時**刻意不算損毀**,於是 `first_seen`/`announced`/`woke` 全部靜默歸零、
  零告警;而同樣是壞檔的空檔 / `[]` / `"hello"` 都會告警,行為自相矛盾(和 F5 當初判 MINOR 的理由一模一樣)。
  ②第 179-181 行:`announced` 只驗「是不是 list」,元素型別漂移(`[1,2]`)會被**靜默過濾成 `[]`**,
  不進 `dropped`、不告警 → 老闆會被重講一次已經講過的「生效」通知。
  ③衍生死鎖:`woke` 被判損毀丟掉、`wake_fail_alerted` 還在時,第 595 行 `if loud and not
  st.get("wake_fail_alerted")` 讓告警不再發、`woke` 也永遠寫不回去 → 偵測器每小時空登入永豐、
  且再也不出聲。
- evidence: check_signed.py:163、179-181、595
```
$ /home/userdelvin/.venvs/shioaji-bridge/bin/python /tmp/vcs3/b.py
案例                     rc   推播數  有損毀告警  有逾期告警  檔案殘留
只有 null                0    0      False      False      b'{"first_seen": "2026-08-03"}'   ← 靜默重錨
空檔                     0    1      True       False      …                                 ← 有告警
空陣列                    0    1      True       False      …                                 ← 有告警
整份是字串                  0    1      True       False      …                                 ← 有告警
announced 全是數字         0    1      False      True       b'…"announced": [], "woke": true…' ← 靜默清空

$ /home/userdelvin/.venvs/shioaji-bridge/bin/python /tmp/vcs3/c.py
=== C3. woke 被損毀丟掉但 wake_fail_alerted 還在 ===
  pushes: ['⚠️ …有壞掉的欄位…']         (跑 4 輪)
  >>> 有人被告知機器沒接手嗎? False
  watch: {"corrupt_alert_date":…, "announced":[…], "wake_fail_alerted": true}   ← woke 永遠寫不回去
```
- fix: ①第 163 行拿掉 `if raw is not None` 的豁免(`null` 也算 `<整個檔案不是物件>`);
  ②`announced` 過濾時把被丟掉的元素併進 `dropped`:
  `bad=[x for x in v if x not in LEG_MARKER]; if bad: dropped.append("announced")`;
  ③`wake_fail_alerted` 不要當永久 latch,改成和 `woke` 綁在一起判斷(`if loud and not st.get("woke")`)。

## F6 [MINOR] 取代舊 `.signed_ok` 的新狀態檔全都沒進 `.gitignore`,舊的那個反而有
- symptom: `.gitignore:108` 只擋 `quote_bridge/.signed_ok`。這次新增的
  `.signed_ok_stock` / `.signed_ok_futopt`(取代它的兩腿 marker)、`.signed_watch.json`(整個等待
  天數與「已通知」帳本)、以及 `signing_anchor` 依賴的 `.qualify_stock_done` / `.qualify_futopt_done`
  **全都是未追蹤檔**。後果有兩面:①它們永遠出現在 `git status` 的 `??` 噪音裡(本 repo 有
  dirty_tree_watch 類守衛在看);②任何一次 `git add -A` 會把老闆的券商帳號狀態檔 commit 進 repo,
  任何一次 `git clean -fd` 會把整個等待天數與「已通知」帳本刪光(marker 一沒,老闆會被**重講**
  所有已經講過的生效通知;`.qualify_*_done` 一沒,`signing_anchor` 退回今天,等待天數靜默歸零)。
- evidence:
```
$ git check-ignore -q <path> && echo YES || echo NO
quote_bridge/.signed_ok                ignored=YES
quote_bridge/.signed_ok_stock          ignored=NO
quote_bridge/.signed_ok_futopt         ignored=NO
quote_bridge/.signed_watch.json        ignored=NO
quote_bridge/.qualify_stock_done       ignored=NO
$ git status --short quote_bridge/
?? quote_bridge/.qualify_futopt_done
?? quote_bridge/.qualify_stock_done
?? quote_bridge/.signed_watch.json
```
  緩解事實(所以只判 MINOR):我 grep 過 `scripts/`、`~/.marketdaily-fallback/`、整份 crontab,
  **目前沒有任何排程會跑 `git clean` / `git stash -u` / `git add -A`**,而 `lib_cron_runner.sh:147,188`
  還明寫「絕不 --autostash」。也就是說今天不會引爆,是「靠環境剛好對」而不是靠設計。
- fix: `.gitignore` 第 108 行改成 `quote_bridge/.signed_ok*` 並補上
  `quote_bridge/.signed_watch.json`、`quote_bridge/.qualify_*_done`。

## Notes
- **第 2 輪 F1–F7 獨立復驗表**(全部用我自己的 `/tmp/vcs3/h.py` + `r.py` + `r2.py`,不載入作者的測試檔):
```
F1 Intl 跳過+專屬文案 ✅ 真 shioaji 1.5.6:AccountType 只有 {Stock:'S', Future:'F', Intl:'H'};
                       _leg_of(Intl)=None、_leg_of(Stock)=stock、_leg_of(Future)=futopt(三者 class 都是 'Account');
                       account_states([S(T),Intl(T),F(F)]) = {'stock':True,'futopt':False}(Intl 不再炸整包);
                       main(UnknownLegError) → rc=1、文案含「認不得」、**不含**「登入失敗」、同日不重推、隔日重推。
                       另用 /usr/bin/python3 的 shioaji **1.7.0** 重跑同一份探針:結果逐字相同(前向相容)。
F2 例外路徑自己 logout ✅ 注入假 shioaji 模組:account_states 拋 UnknownLegError 時 logged_out=True;
                       正常路徑不自行 logout(呼叫端還要用 api)。
F3 corrupt_pending    ✅ push 丟 OSError → watch 落 {"corrupt_pending":"alerted_at_biz"}(壞欄位已清但重試依據還在)
                       → 通道復原下一輪補講「壞掉的欄位…alerted_at_biz」→ corrupt_pending 被清 → 第三輪不洗頻。
F4 wake 三態          ⚠️ **只修一半**:absent 即刻出聲、failed 累到 3 才出聲、告警沒送到 woke 保持 None(這些都對),
                       但 "sent" 的判準是壞的 → 見 F1(本輪)。
F5 null sentinel      ✅ {"first_seen":null} / {"alerted_at_biz":null} / {"announced":null} 三者都出損毀告警;
                       {} 不算損毀。⚠️ 但整份檔案是 null、以及 announced 元素型別漂移仍靜默 → 見 F5(本輪)。
F6 逾期排除 settled   ✅ .signed_ok_stock 已在 + states={'stock':False,'futopt':False} →
                       逾期文案只寫「期貨自 2026-07-30 起…」(不含「證券/期貨」),另發一則
                       「⚠️ 永豐 API【證券】原本已生效,現在回報未簽署…」,同日不重推。
F7 自身異常兜底       ✅ 唯讀目錄 → rc=1(traceback 不穿出去)+ 一則「偵測器自己異常結束(PermissionError…)」,
                       同日同型別不洗頻(戳記落 tmp,不依賴寫不進去的那個目錄)。
```
- **冪等/去重在真重跑下守得住**:同條件連跑 3 次 → pushes 停在 2、wakes 停在 1、watch 不變
  (`/tmp/vcs3/c.py` C1)。損毀告警、回退告警、自身異常告警的同日去重也都各自實跑過兩輪確認。
- **惡意/畸形 watch 檔 19 種全表**(`/tmp/vcs3/b.py`):空檔、截斷、NUL 位元組、非 UTF-8、`[]`、`"hello"`、
  200 層巢狀、重複鍵、bool/負數/浮點型別漂移 —— **rc 全部是 0,沒有一種讓偵測器 crash**,
  型別漂移該告警的都有告警。只有 F5(本輪)列的兩種會靜默。
- `signed` 欄位型別漂移在真 SDK 下不可達:`sj.Account(signed='N'/'Y'/0/1)` 一律被 C 擴充擋掉
  (`TypeError: argument 'signed': 'str' object is not an instance of 'bool'`),只有 `None` 建得起來
  且會被正規化成 `False`。所以 `bool(getattr(a,"signed",False))` 對 `'N'` 回 True 這個理論風險
  (我實測過確實會)在真 SDK 路徑上碰不到,只在舊 SDK 後備判準上存在,不列為缺陷。
- 帳號清單為空(login 成功但 accounts=[])時 `states` 三腿皆 None;若此時某腿已落 marker,
  會觸發「原本已生效,現在回報未簽署」告警。沒有「連續兩輪確認」的要求,單次 API 抽風即可觸發一則
  嚇人的告警(同日去重,最多一則/天)。噪音可接受,列此備查。
- `_env()` 用 `for line in open(path)` 不關檔(每輪最多洩兩個 fd,行程秒退,無實害);
  真 `.env` 的三把 key 我確認過沒有引號 / 沒有 CRLF / 沒有 export 前綴,`_env` 的簡易解析對它是正確的。
- `_save_watch` 的 `mkstemp` 若行程在 `mkstemp` 與 `os.replace` 之間被 SIGKILL,會在 quote_bridge/
  留下 `.signed_watch.XXXXXX` 殘骸並持續累積(正常路徑不留,作者的 14k 有守)。低優先。
- UNVERIFIED:alert-worker `/internal/admin-line-push` 對現行 token 是否真的回 200 —— 硬性限制禁止發
  任何真實推播,所以本輪所有「送達/沒送達」都是 stub 驗的邏輯,不是通道實證。
- UNVERIFIED:期貨腿翻 True 的那一刻。真登入證實**期貨帳號目前根本沒掛在這把 API key 上**
  (accounts 只回一個 Stock,`futopt=None`),所以 futopt=True 的整條路徑仍只由假物件 + 合約測試的
  真 `sj.Account` 推得,不是生產實證。
- UNVERIFIED:`trigger.sh` 被叫醒後自主機器是否真的接手 SSF dry-run。trigger.sh 自己的註解寫明
  「所有閘門(DISABLED/熔斷/本人在場/用量/輪數上限)照常生效」,我沒有(也不該)在本輪去觸發它。
