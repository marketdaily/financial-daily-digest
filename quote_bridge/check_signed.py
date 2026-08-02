"""永豐 API 簽署生效偵測器(cron 每小時 08-17 平日)。

判準=登入後帳號物件的 `signed` 欄位(永豐權威回報),不是猜 406——406 只說「不給你」,
signed 欄位才分得出證券/期貨各自的狀態,也才能在只解鎖一半時講清楚缺哪一邊。

2026-08-03 根治(原版寫在期貨戶存在之前,設計前提已被 07-29 開戶推翻;獨立驗證者裁 UNSOUND/6):
  ①**分腿判準是壞的(CRITICAL)**:舊 `account_states` 用 `"Fut" in type(a).__name__` 分腿,
    但 shioaji 1.5.6 只有**單一 `Account` 類別**(`StockAccount`/`FutureAccount` 都是它的
    deprecated alias,`is sj.Account` 為 True)→ 期貨腿**永遠**是 None,而且兩個帳號一起回來時
    後者會直接蓋掉前者的真值。改用權威欄位 `account_type`('S'/'F');同腿多帳號取 OR 而非後寫贏。
    ⚠️ 第 2 輪驗證者修正:**與本偵測器無關的腿(Intl 複委託 'H')要跳過,不可拋例外**——
    老闆做美股,哪天掛上一個複委託帳號就會讓整包 account_states 炸掉,連認得出來的
    證券/期貨都讀不到,把 SSF blocker 的看門人打成全損,而且文案還誤報成「登入失敗」。
    真正未知的型別才出聲,且走專屬文案(登入其實是成功的,錯的是分腿判準)。
  ②**只看證券就自殺**:舊版證券一解鎖就寫 `.signed_ok`,下一輪 `exists(MARKER)` 直接 return——
    期貨端(SSF 執行迴路唯一 blocker)從此永不被檢查。現在兩腿各自 marker,兩腿都生效才停走。
  ③**推播失敗被永久吃掉(HIGH)**:舊版先落 marker 再推播,推失敗只 print,而 marker 一在就
    不再進 `newly` → 一次 CF 403 就能讓「SSF blocker 解除」這則通知永遠不出現。現在「講給
    老闆聽」記在 watch 的 `announced`,**送達才記帳**,沒送到下個整點照樣重試。
  ④**逾期告警一輩子只推一次**→ 改每 OVERDUE_REPEAT_BIZ_DAYS 個營業日重推(帶已等待天數)。
  ⑤**login 例外只噴 traceback 進沒人讀的 log** → 走推播告警,去重鍵含錯誤型別(暫時性網路錯
    不可以把同日稍晚的「憑證被撤銷」一起吃掉)。
  ⑥**watch 檔內容零驗證**:值型別漂移會讓偵測器每小時 traceback、`alerted_at_biz` 因時鐘前跳
    衝高後永久靜音、非原子寫在斷電時把 first_seen 靜默重錨到今天。現在載入即 sanitize、
    倒退視同沒推過、tmp+os.replace 原子寫,並對損毀出聲。

期貨腿轉 True 時額外叫醒自主機器接手 dry-run(trigger.sh),免得「API 生效了但沒人知道要
開工」變成下一個沉默的守衛;喚醒同樣是成功才記帳,連續叫不醒會改推「請手動跑 trigger.sh」
並放行停走(否則每小時空登入永豐到天荒地老)。

第 2 輪驗證者(SOUND-WITH-CORRECTIONS/7)另抓到的全數已修,主軸是同一個老病灶換位置復發
**——失敗路徑上沒有人被告知**:
  F1 複委託帳號(Intl 'H')會讓整包 account_states 炸掉 → 無關腿跳過,未知型別走專屬文案。
  F2 account_states 拋例外時漏 logout(每小時漏一個永豐 session)→ login_states 自己收乾淨。
  F3 損毀告警推不出去會被下游 `_save_watch` 把壞欄位抹掉而永遠不重試 → 記 `corrupt_pending`。
  F4 喚醒失敗只 print:absent/failed/sent 三態分流,出聲且**送達才**放行停走。
  F5 `"first_seen": null` 不算損毀(靜默重錨)→ sentinel 分「不存在」與「值是 null」。
  F6 逾期文案會誣賴已落 marker 的那一腿 → pending 排除 settled;曾生效又回 False 另推一則。
  F7 寫入端(marker/watch)失敗仍是裸例外 → main 外層兜底告警(戳記落 tmp,因為
     「那個目錄寫不進去」正是要告警的情境)。

第 3 輪驗證者(SOUND-WITH-CORRECTIONS/6)——**同一個病灶第三次換皮**,全數已修:
  F1 `wake_machine` 的 "sent" 只證明 fork 得起來、不證明 trigger.sh 跑得動,而它是**永久停走**
     的閘門(chmod 000 時 bash 回 126,舊版照樣退休)→ 改看子行程結束碼,逾 WAKE_WAIT_SEC 才算送出。
  F2 `first_seen` 落在未來(時鐘前跳)→ waited 恆為 0 → 唯一的主動告警永久靜音**且零輸出**;
     `alerted_at_biz` 早有同樣的保護,這欄漏了 → 鉗回今天並出聲;signing_anchor 也濾掉未來 mtime。
  F3 夜巡守衛在合約測試被 SKIP 時仍報 PASS(假綠)→ SKIP 即 exit 1,test.sh 補一道 grep。
  F4 程式本身無鎖,併發保護只在 crontab 的 `flock`(手動執行不受保護,實測會重複推播/重複喚醒/
     把已送達的 announced 洗掉)→ 鎖搬進 main()。
  F5 損毀偵測剩下的靜默缺口:整份檔案是 `null`、`announced` 元素型別漂移;`wake_fail_alerted`
     latch 在 woke 被判損毀時會死鎖 → 前兩者列入 dropped,latch 拿掉(條件已在 `not woke` 內)。
  F6 新狀態檔(.signed_ok_*/.signed_watch.json/.qualify_*_done)沒進 .gitignore → 補上。

自測:`python3 quote_bridge/test_check_signed.py`(純假物件 + 真 shioaji.Account 合約測試)。
"""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(HERE, ".signed_ok")            # 兩腿都生效才寫(保留給人看/舊習慣)
LEG_MARKER = {"stock": os.path.join(HERE, ".signed_ok_stock"),
              "futopt": os.path.join(HERE, ".signed_ok_futopt")}
LEG_LABEL = {"stock": "證券", "futopt": "期貨"}
QUALIFY_MARKER = {"stock": os.path.join(HERE, ".qualify_stock_done"),
                  "futopt": os.path.join(HERE, ".qualify_futopt_done")}
WATCH = os.path.join(HERE, ".signed_watch.json")
# 偵測器自身異常的去重戳記:刻意**不放** HERE——那個目錄唯讀/滿磁碟正是要告警的情境之一。
SELF_ERR_STAMP = os.path.join(tempfile.gettempdir(), ".check_signed_self_err")
AUTO_DIR = os.path.expanduser("~/autonomous")
OVERDUE_BIZ_DAYS = 2
OVERDUE_REPEAT_BIZ_DAYS = 5
WAKE_FAIL_LIMIT = 3
WAKE_WAIT_SEC = 10
# 程式自己的鎖(第 3 輪 F4):唯一的併發保護原本只在 crontab 的 `flock -n`,手動執行/別的
# 腳本呼叫完全不受保護,實測併發會重複推播、重複喚醒,還會把「已送達」的 announced 洗掉。
LOCK = os.path.join(tempfile.gettempdir(), ".check_signed.lock")
# AccountType.Intl('H')=複委託/海外。認得、但與「證券/期貨過檔」這件事無關 → 跳過而非拋例外。
IGNORED_LEG_CODES = {"H"}
ALERT_WORKER = "https://marketdaily-alert-worker.delvin-12345678.workers.dev"


def _env(path):
    d = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def push(msg, token):
    req = urllib.request.Request(
        f"{ALERT_WORKER}/internal/admin-line-push",
        data=json.dumps({"message": msg}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                 "User-Agent": "marketdaily-internal/1.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status == 200


class UnknownLegError(RuntimeError):
    """永豐掛上了分腿判準認不得的帳號型別。與「登入失敗」是兩件事,文案不可混用。"""


def _leg_of(account):
    """權威分腿:看 `account_type`('S'/'F'),不是看類別名稱;無關的腿回 None。

    shioaji 1.5.6 起 StockAccount/FutureAccount 都只是 `Account` 的 alias,
    類別名稱一律 'Account' —— 靠名字分腿等於永遠分不出期貨(驗證者第 1 輪 F1 實測)。
    類別名稱只留作舊版 SDK 的後備判準。

    ⚠️ `AccountType` 還有 `Intl`('H')=複委託/海外。老闆做美股,哪天掛上一個就會讓
    整包 account_states 炸掉、連認得出來的兩腿都讀不到(驗證者第 2 輪 F1)。
    無關的腿**跳過**;只有真正未知的才拋 UnknownLegError,讓上層用**專屬文案**出聲
    (登入其實成功了,錯的是判準需要更新)。
    """
    at = getattr(account, "account_type", None)
    code = str(getattr(at, "value", None) or at or "").upper()
    name = type(account).__name__
    if code == "F" or code.startswith("FUT") or "Fut" in name:
        return "futopt"
    if code == "S" or code.startswith("STOCK") or "Stock" in name:
        return "stock"
    if code in IGNORED_LEG_CODES:
        return None
    raise UnknownLegError(f"未知的永豐帳號型別 account_type={at!r} class={name}")


def account_states(accounts):
    """{'stock': True/False/None, 'futopt': True/False/None} —— None=永豐根本沒掛這個帳號。

    同一腿有多個帳號時取 OR(任一個已簽署就算這一腿可用),不可以後寫贏——
    舊版 dict 直接覆寫,期貨帳號會把證券腿的真值蓋掉(驗證者第 1 輪 F1)。
    """
    out = {"stock": None, "futopt": None}
    for a in accounts:
        kind = _leg_of(a)
        if kind is None:
            continue
        v = bool(getattr(a, "signed", False))
        out[kind] = v if out[kind] is None else (out[kind] or v)
    return out


_MISSING = object()


def _date_ok(v):
    try:
        date.fromisoformat(v)
        return True
    except (TypeError, ValueError):
        return False


def _nonneg_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _sanitize_watch(raw):
    """(乾淨的 st, 被丟掉的欄位名) —— JSON 合法不代表值合法。

    舊版只擋「解不開」,於是 first_seen=null / 數字 / 2026-13-01 都會讓 overdue_alert
    在 main 裡裸奔丟例外,整支偵測器每小時 traceback 進沒人讀的 log(驗證者 F3)。

    ⚠️ 第 2 輪 F5:用 sentinel 分「欄位不存在」與「存在但值是 null」。舊版 `is not None`
    把後者當成前者 → `{"first_seen": null}` **不算損毀**、不出聲,等待天數靜靜重新起算,
    而同一個檔案裡 `"first_seen": 20260730` 卻會告警,行為自相矛盾。
    """
    st, dropped = {}, []
    if not isinstance(raw, dict):
        # `null` 也算壞檔(第 3 輪 F5):豁免它等於讓 first_seen/announced/woke 全部靜默歸零,
        # 而空檔 / [] / "hello" 都會告警——同一個檔案兩套標準。
        return st, ["<整個檔案不是物件>"]

    def take(key, ok):
        v = raw.get(key, _MISSING)
        if v is _MISSING:
            return
        if ok(v):
            st[key] = v
        else:
            dropped.append(key)

    take("first_seen", _date_ok)
    take("alerted_at_biz", _nonneg_int)
    take("wake_fail", _nonneg_int)
    for key in ("login_err", "corrupt_alert_date", "corrupt_pending", "leg_regressed"):
        take(key, lambda v: isinstance(v, str))
    take("announced", lambda v: isinstance(v, list))
    if "announced" in st:
        keep = sorted({x for x in st["announced"] if x in LEG_MARKER})
        if len(keep) != len(set(st["announced"])):
            dropped.append("announced")   # 元素漂移靜默過濾=老闆會被重講已講過的生效通知
        st["announced"] = keep
    for key in ("woke",):
        v = raw.get(key, _MISSING)
        if v is _MISSING or v is False:
            continue
        if v is True:
            st[key] = True
        else:
            dropped.append(key)
    return st, dropped


def _load_watch():
    try:
        with open(WATCH) as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}, []
    except Exception:
        return {}, ["<JSON 解析失敗>"]
    return _sanitize_watch(raw)


def _save_watch(st):
    """原子寫:斷電/OOM 落在寫入中間會產生空檔或半截 JSON,下一輪 first_seen 就靜默
    重錨到今天,「已等待 N 個營業日」歸零而沒有人看得出來(驗證者 F3)。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(WATCH) or ".", prefix=".signed_watch.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(st, f)
            f.flush()
            os.fsync(f.fileno())   # 沒 fsync 的 replace 在斷電時會留下零長度檔
        os.replace(tmp, WATCH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def settled(kind):
    """這一腿已經確認生效過(marker 落地)——只有 True 算數,None/False 都還要繼續看。"""
    return os.path.exists(LEG_MARKER[kind])


def signing_anchor(today):
    """逾期天數的起算日:優先用「開通測試完成」的實際日期(.qualify_*_done 的 mtime),
    而不是「偵測器第一次跑空的那一輪」——後者在 watch 檔遺失時會把已等待天數靜默歸零,
    拿去跟營業員對話的數字會被打臉(驗證者 Notes)。"""
    stamps = [os.path.getmtime(p) for p in QUALIFY_MARKER.values() if os.path.exists(p)]
    days = [d for d in (datetime.fromtimestamp(s).date() for s in stamps) if d <= today]
    if not days:
        return today       # 未來的 mtime(時鐘前跳期間寫出的)不可當起算日,否則永遠等不到門檻
    return min(days)


def leg_message(kind, states, n_pos):
    """單腿生效的推播文案。n_pos=None 代表沒查部位(期貨腿或查失敗)。"""
    if kind == "stock":
        msg = "✅ 永豐 API【證券】簽署生效!帳務已解鎖"
        if n_pos is not None:
            msg += f"(現有 {n_pos} 檔部位)"
        msg += ",看盤頁「我的部位」會自動顯示。"
    else:
        msg = ("🎉 永豐 API【期貨】簽署生效!SSF 執行迴路的 blocker 解除——"
               "dry-run(simulation=True)可以開跑,首次真單仍照鐵則等你同席。")
    other = "futopt" if kind == "stock" else "stock"
    if states.get(other) is not True:
        msg += f"\n⚠️ {LEG_LABEL[other]}端尚未解鎖(證券/期貨分開簽署+分開過檔),偵測器繼續看守。"
    else:
        msg += "\n兩邊都已生效,此偵測器已自動停走。"
    return msg


def biz_days_between(a, b):
    """a→b 之間的工作日數(不含 a 當天)。過檔是營業日批次,用日曆天會在週末誤報。"""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _try_push(msg, tok):
    """(送達了嗎, 說明)。token 缺席一律當**沒送到**——不可以當成「不用送」:
    token 遺失/改名時三個告警點會全部退化成 print 進沒人讀的 log,偵測器看起來活著
    實際上啞了(Mac 守衛前例:旋轉後成舊值,啞了三週沒人發現)。"""
    if not tok:
        return False, "MARKETDAILY_ALERT_TOKEN 缺席,告警無法送出"
    try:
        return bool(push(msg, tok)), ""
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"


def alert_corrupt_watch(dropped, today, tok):
    """watch 檔壞掉不可以靜默修好就算了——那等於偷偷把等待天數歸零。

    ⚠️ 第 2 輪 F3:重試的依據不可以是「壞欄位還在檔案裡」——同一輪稍後的 `_save_watch`
    會把壞欄位一併抹掉,下一輪 dropped 就變空,這則告警等於被推播故障吃掉(=第 1 輪 F2
    判 HIGH 的同一個 pattern 換位置復發)。改成把「還有一則損毀告警沒送出去」寫成
    `corrupt_pending` 狀態,送達才清掉。
    """
    st, _ = _load_watch()
    pending = sorted(set(dropped) | {x for x in (st.get("corrupt_pending") or "").split("、") if x})
    if not pending:
        return
    msg = (f"⚠️ 永豐簽署偵測器的 .signed_watch.json 有壞掉的欄位並已丟棄:{'、'.join(pending)}。"
           "逾期天數可能被重新起算,請確認是否有斷電/半截寫入。")
    ok, why = _try_push(msg, tok)
    if ok:
        st.pop("corrupt_pending", None)
        st["corrupt_alert_date"] = today.isoformat()
    else:
        st["corrupt_pending"] = "、".join(pending)
        print("push failed:", why)
    _save_watch(st)
    print(msg)


def alert_leg_regressed(legs, today, tok):
    """已落 marker 的腿又回報未生效——帳號被收回/永豐端出包,是**另一種事故**,
    不可以混進「過檔逾期」文案裡叫老闆去找營業員查一個早就生效的帳號(第 2 輪 F6)。"""
    st, _ = _load_watch()
    stamp = f"{today.isoformat()}:{'/'.join(legs)}"
    if st.get("leg_regressed") == stamp:
        return
    names = "/".join(LEG_LABEL[k] for k in legs)
    msg = (f"⚠️ 永豐 API【{names}】原本已生效,現在回報未簽署——可能是帳號被收回、"
           "憑證換發或永豐端出包。這不是過檔逾期,請直接確認帳號狀態。")
    ok, why = _try_push(msg, tok)
    if ok:
        st["leg_regressed"] = stamp
        _save_watch(st)
    else:
        print("push failed:", why)
    print(msg)


def overdue_alert(states, today, tok):
    """過檔逾期主動告警——沒生效就靜默 = 沉默的守衛 = 沒有守衛。

    舊版一旦推過就把 alerted 寫死成 True,之後**永遠**不再出聲:卡在永豐系統兩週、
    兩個月都一樣安靜。改成每 OVERDUE_REPEAT_BIZ_DAYS 個營業日重推一次並帶上已等待天數,
    催得動也不洗頻(同一個營業日至多一則)。
    """
    st, _ = _load_watch()
    first = date.fromisoformat(st.get("first_seen") or signing_anchor(today).isoformat())
    if first > today:
        # 未來錨點 = 時鐘曾前跳(winrig 有 41h 斷電史)。waited 會恆為 0 → 這支偵測器
        # **唯一**的主動告警從此永久靜音,而且連 log 都不會多印一個字(第 3 輪 F2)。
        # `alerted_at_biz` 早就有同樣的保護,first_seen 漏掉了。
        print(f"⚠️ first_seen={first} 在未來,已鉗回 {today}(時鐘曾前跳?)")
        first = today
        st["first_seen"] = first.isoformat()
    st.setdefault("first_seen", first.isoformat())
    waited = biz_days_between(first, today)
    last = st.get("alerted_at_biz")
    # last > waited = 時鐘曾前跳後被校正(winrig 有 41h 斷電史),否則逾期告警會永久閉嘴。
    if last is not None and last > waited:
        last = None
        st.pop("alerted_at_biz", None)
    due = waited >= OVERDUE_BIZ_DAYS and (
        last is None or waited - last >= OVERDUE_REPEAT_BIZ_DAYS)
    if due:
        # 已落 marker 的腿不進逾期文案:永豐回一次抽風的 False 就會讓老闆拿著
        # 「證券自 07-30 起未生效」去找營業員查一個早就生效的帳號(第 2 輪 F6)。
        pending = [LEG_LABEL[k] for k in ("stock", "futopt")
                   if states.get(k) is not True and not settled(k)]
        if not pending:
            _save_watch(st)
            return
        again = "(持續追蹤)" if last is not None else ""
        msg = (f"⚠️ 永豐 API 過檔逾期{again}:{'/'.join(pending)}自 {first} 起已過 "
               f"{waited} 個營業日仍未生效(簽署+測試皆已完成)。"
               "該找營業員 Norris 查是否卡在系統過檔。")
        ok, why = _try_push(msg, tok)
        # 送不出去就不記帳,下一輪照樣重試——記了帳視同已通知,等於把送不出去的告警吃掉。
        if ok:
            st["alerted_at_biz"] = waited
        else:
            print("push failed:", why)
        print(msg)
    _save_watch(st)


def alert_unknown_leg(ex, today, tok):
    """永豐掛上分腿判準認不得的帳號型別。**不可以冒充「登入失敗」**(第 2 輪 F1):
    登入其實是成功的,錯的是這支程式的判準,老闆照字面去查憑證/網路只會白忙,
    真正要看的是永豐那邊多掛了什麼帳號。"""
    st, _ = _load_watch()
    stamp = f"{today.isoformat()}:unknown_leg"
    if st.get("login_err") == stamp:
        return
    msg = (f"⚠️ 永豐帳號出現偵測器認不得的型別({ex})——登入是成功的,是分腿判準需要更新。"
           "在期貨過檔狀態確認之前,這支偵測器暫時失明,請告訴 Claude 補上這個型別。")
    ok, why = _try_push(msg, tok)
    if ok:
        st["login_err"] = stamp
        _save_watch(st)
    else:
        print("push failed:", why)
    print(msg)


def alert_login_failure(ex, today, tok):
    """login 掛掉(權限/憑證/網路/shioaji 版本)不可以只噴 traceback 進沒人讀的 log:
    偵測器自己死了正是最該出聲的時候。去重鍵含錯誤型別——同日稍晚出現的質變錯誤
    (例如憑證被撤銷)不可以被早上的暫時性網路錯誤吃掉。"""
    st, _ = _load_watch()
    stamp = f"{today.isoformat()}:{type(ex).__name__}"
    if st.get("login_err") == stamp:
        return
    msg = (f"⚠️ 永豐 API 簽署偵測器登入失敗({type(ex).__name__}: {ex})——"
           "今天起無法確認過檔狀態,偵測器等同失明,請人工確認。")
    ok, why = _try_push(msg, tok)
    if ok:
        st["login_err"] = stamp
        _save_watch(st)
    else:
        print("push failed:", why)
    print(msg)


def wake_machine(note):
    """期貨腿生效 → 叫醒自主機器接手(沿用 selftest.sh 的既有喚醒路徑)。

    回 "sent"=已送出;"absent"=**永久**條件(這台沒有 trigger.sh);"failed"=暫時失敗。
    三態不可以壓成兩態(第 2 輪 F4):absent 當失敗 → 停走條件永遠達不到、每小時空登入
    永豐到天荒地老;absent 當成功 → 老闆看到「🎉 期貨生效」以為機器接手了,其實沒有,
    而這件事只 print 進沒人讀的 log——正是這次要根治的「沉默的守衛」本身。
    """
    trigger = os.path.join(AUTO_DIR, "trigger.sh")
    if not os.path.exists(trigger):
        print("wake absent: 找不到", trigger)
        return "absent"
    try:
        p = subprocess.Popen(["/bin/bash", trigger, note],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception as ex:
        print("wake failed:", ex)
        return "failed"
    # ⚠️ 第 3 輪 F1:`Popen 沒丟例外` 只證明 fork 得起來,不證明 trigger.sh 跑得動
    # (權限壞掉時 bash 回 126,舊版照樣回 "sent" → woke=True → 偵測器永久退休而沒人接手)。
    # trigger.sh 只寫兩個檔就轉手,10 秒綽綽有餘;真的還在跑=已經接手了,算送出。
    try:
        rc = p.wait(timeout=WAKE_WAIT_SEC)
    except subprocess.TimeoutExpired:
        return "sent"
    if rc != 0:
        print("wake failed: trigger.sh exit", rc)
        return "failed"
    return "sent"


def migrate_legacy_marker():
    """舊版單一 `.signed_ok` 只代表「證券已生效」(舊碼在 stock=True 時才寫)。
    存在而新版證券腿 marker 不在 → 補上,免得新版把證券當成剛生效再宣告一次(驗證者 F6)。"""
    if os.path.exists(MARKER) and not os.path.exists(LEG_MARKER["stock"]):
        with open(LEG_MARKER["stock"], "w") as f:
            f.write("migrated from legacy .signed_ok\n")
        # 舊碼是「寫 MARKER 之後才推播」,所以這個檔存在就代表老闆當時已被通知過證券生效;
        # 不一併補進 announced 的話,新版會把同一件事再宣告一次。
        st, _ = _load_watch()
        st["announced"] = sorted(set(st.get("announced", [])) | {"stock"})
        _save_watch(st)
        return True
    return False


def login_states(env):
    """正式模式登入回查權威狀態。回傳 (states, api);呼叫端負責 logout。

    ⚠️ 第 2 輪 F2:`account_states` 拋例外時 api 連回都沒回去,呼叫端的 finally 碰不到它
    → 登入成功但**永不登出**,cron 每小時漏一個永豐 session(券商 session 是有上限的資源,
    漏一整天可能連看盤 bridge 一起遭殃)。失敗路徑要自己收乾淨。
    """
    import shioaji as sj
    api = sj.Shioaji(simulation=False)
    accounts = api.login(api_key=env["SINOPAC_API_KEY"], secret_key=env["SINOPAC_SECRET_KEY"],
                         fetch_contract=False)
    try:
        return account_states(accounts), api
    except Exception:
        try:
            api.logout()
        except Exception:
            pass
        raise


def stock_position_count(api):
    try:
        return len(api.list_positions(api.stock_account))
    except Exception as ex:
        print("list_positions failed:", ex)
        return None


def alert_self_failure(ex, today):
    """偵測器自己爆掉(唯讀目錄/滿磁碟/沒預料到的例外)——正是最該出聲的時候,
    但這條路徑不能依賴 watch 檔(它自己可能就是寫不進去的那個),所以去重戳記
    落在 tmp,拿不到 token 也照印(第 2 輪 F7)。"""
    stamp = f"{today.isoformat()}:{type(ex).__name__}"
    try:
        with open(SELF_ERR_STAMP) as f:
            seen = f.read().strip()
    except Exception:
        seen = ""
    msg = (f"⚠️ 永豐簽署偵測器自己異常結束({type(ex).__name__}: {ex})——"
           "期貨過檔狀態今天無人看守,請人工確認(常見原因:目錄唯讀/磁碟滿)。")
    if seen != stamp:
        tok = ""
        try:
            tok = _env(os.path.join(os.path.dirname(HERE), ".env")).get(
                "MARKETDAILY_ALERT_TOKEN", "") or os.environ.get("MARKETDAILY_ALERT_TOKEN", "")
        except Exception:
            tok = os.environ.get("MARKETDAILY_ALERT_TOKEN", "")
        ok, why = _try_push(msg, tok)
        if ok:
            try:
                with open(SELF_ERR_STAMP, "w") as f:
                    f.write(stamp)
            except Exception:
                pass
        else:
            print("push failed:", why)
    print(msg)


def main():
    """外層兜底:任何沒被上面接住的例外(寫 marker / 寫 watch 失敗等)都要出一次聲,
    不可以只留 traceback 在沒人讀的 cron log 裡每小時重演一次(第 2 輪 F7)。"""
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        fd = None            # 拿不到鎖檔不該讓偵測器停擺,退回無鎖行為(cron 端仍有 flock)
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            print("另一個 check_signed 正在跑,本輪跳過(避免重複推播/重複喚醒)")
            return 0
    try:
        return _run()
    except Exception as ex:
        alert_self_failure(ex, date.today())
        return 1
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _run():
    migrate_legacy_marker()
    st, dropped = _load_watch()
    announced = set(st.get("announced", []))
    # 停走條件三件齊:兩腿都生效 + 兩腿都真的通知到老闆 + 期貨那次喚醒真的送出去了。
    # 少了後兩者,推播通道壞掉的那一小時就能讓偵測器帶著「沒人知道」的狀態退休。
    if all(settled(k) for k in LEG_MARKER) and announced >= set(LEG_MARKER) and st.get("woke"):
        return 0

    today = date.today()
    try:
        E = _env(os.path.join(os.path.dirname(HERE), ".env"))
    except Exception as ex:
        # .env 讀不到 = 連 token 都拿不到,唯一還能做的是走環境變數並大聲說出來。
        print(f"⚠️ 讀不到 .env({type(ex).__name__}: {ex}),偵測器無法登入")
        E = dict(os.environ)
    tok = E.get("MARKETDAILY_ALERT_TOKEN", "")
    if not tok:
        print("⚠️ MARKETDAILY_ALERT_TOKEN 缺席:本輪所有告警都送不出去(偵測器等同啞掉)")
    # corrupt_pending = 上一輪推不出去的損毀告警;沒有這個條件,dropped 在檔案被清乾淨後
    # 就永遠是空的,那則告警等於被一次推播故障吃掉(第 2 輪 F3)。
    if dropped or st.get("corrupt_pending"):
        alert_corrupt_watch(dropped, today, tok)

    try:
        states, api = login_states(E)
    except UnknownLegError as ex:
        # 登入成功、只是判準認不得某個帳號型別:專屬文案,不可冒充登入失敗(第 2 輪 F1)。
        alert_unknown_leg(ex, today, tok)
        return 1
    except Exception as ex:
        alert_login_failure(ex, today, tok)
        return 1

    regressed = [k for k in ("stock", "futopt") if settled(k) and states.get(k) is not True]
    if regressed:
        alert_leg_regressed(regressed, today, tok)

    try:
        live = [k for k in ("stock", "futopt") if states.get(k) is True]
        for kind in live:
            if not settled(kind):
                with open(LEG_MARKER[kind], "w") as f:
                    f.write(f"{today.isoformat()} signed ok states={states}\n")
        n_pos = stock_position_count(api) if "stock" in live and "stock" not in announced else None
    finally:
        try:
            api.logout()
        except Exception:
            pass

    if not live:
        print(f"尚未生效 states={states}")
        overdue_alert(states, today, tok)
        return 0

    st, _ = _load_watch()
    announced = set(st.get("announced", []))
    for kind in live:
        if kind in announced:
            continue
        msg = leg_message(kind, states, n_pos if kind == "stock" else None)
        ok, why = _try_push(msg, tok)
        if ok:
            announced.add(kind)
        else:
            # 送不到就不記帳:下個整點原封不動再講一次。全系統最重要的一則通知
            # (SSF blocker 解除)不可以被一次 CF 403 永久靜音(驗證者 F2)。
            print("push failed:", why)
        print(msg)
    st["announced"] = sorted(announced)

    if "futopt" in live and not st.get("woke"):
        # 叫不醒機器 → 停走條件永遠達不到(每小時空登入永豐到天荒地老),而且老闆看到
        # 「🎉 期貨生效」會以為機器接手了、其實沒有(第 2 輪 F4)。永久缺席即刻出聲,
        # 暫時失敗累積到門檻才出聲;兩者都是**送達**才放行停走。
        how = wake_machine("永豐期貨 API 已生效:SSF 執行迴路 dry-run(simulation=True)可以開跑,"
                           "照 backlog 域① 步驟①,絕不下實單")
        if how == "sent":
            st["woke"] = True
            st.pop("wake_fail", None)
        else:
            if how == "failed":
                st["wake_fail"] = int(st.get("wake_fail") or 0) + 1
                why_txt = f"連續 {st['wake_fail']} 次叫不醒自主機器"
                loud = st["wake_fail"] >= WAKE_FAIL_LIMIT
            else:
                why_txt = f"找不到 {AUTO_DIR}/trigger.sh"
                loud = True
            if loud:
                ok, why = _try_push(
                    f"⚠️ 永豐期貨已生效,但{why_txt}——沒有人接手 SSF dry-run,"
                    "請手動跑一次 trigger.sh(或直接叫 Claude 接手)。"
                    "偵測器本身任務已完成,就此停走。", tok)
                if ok:
                    st["woke"] = True     # 送達才放行停走(沒送到=沒人知道,繼續重試)
                else:
                    print("push failed:", why)
    _save_watch(st)

    # 還缺一腿就繼續催——不可以因為另一腿生效了就對剩下那腿閉嘴
    # (證券先過檔、期貨卡三週的情境正是本次要防的)。
    if any(states.get(k) is not True for k in LEG_MARKER):
        overdue_alert(states, today, tok)

    if all(settled(k) for k in LEG_MARKER) and not os.path.exists(MARKER):
        with open(MARKER, "w") as f:
            f.write(f"signed ok {states}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
