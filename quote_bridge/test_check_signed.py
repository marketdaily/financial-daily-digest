"""check_signed.py 自測(純假物件,不打永豐、不發推播、不碰真 marker)。

守的是 2026-08-03 根治的六個沉默漏洞。核心迴歸兩條:
  · 案 1/合約測試:**分腿判準不可以看類別名稱** —— shioaji 1.5.6 的 StockAccount/
    FutureAccount 都是 `Account` 的 alias,靠名字分腿期貨腿永遠是 None(驗證者 F1)。
    案 15 用**真的 shioaji.Account** 建兩腿驗;沒有 shioaji 就印 SKIP(不靜默通過)。
  · 案 5:**證券解鎖不可以把期貨端的看守一起關掉**。

⚠️ fixture 紀律:假帳號一律帶 `account_type`(真 SDK 的權威欄位)。上一版自刻
`class FutureAccount` 當真理,結果 14/14 全綠卻完全咬不到 F1 —— golden fixture 漂移。

用法:python3 quote_bridge/test_check_signed.py        # 跑測試
      python3 quote_bridge/test_check_signed.py --mutate  # 突變測試(驗這些測試真的咬得住)
"""
import fcntl
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SHIOAJI_PY = os.path.expanduser("~/.venvs/shioaji-bridge/bin/python")
FAILED = []
SKIPPED = []


def load(src=None):
    path = src or os.path.join(HERE, "check_signed.py")
    spec = importlib.util.spec_from_file_location("cs_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Acct:
    """真 SDK 的形狀:類別名稱一律 Account,靠 account_type 欄位分腿。"""

    def __init__(self, account_type, signed):
        self.account_type = account_type
        self.signed = signed


class LegacyFutureAccount:
    """舊版 SDK 的形狀:沒有 account_type,只有類別名稱可用(後備判準)。"""

    def __init__(self, signed):
        self.signed = signed


def stock(signed=True):
    return Acct("S", signed)


def futopt(signed=True):
    return Acct("F", signed)


class FakeApi:
    def __init__(self, positions=3, raise_positions=False):
        self.stock_account = object()
        self._positions = positions
        self._raise = raise_positions
        self.logged_out = False

    def list_positions(self, acct):
        if self._raise:
            raise RuntimeError("no permission")
        return list(range(self._positions))

    def logout(self):
        self.logged_out = True


class FakeDate:
    """讓 main()/overdue_alert 的 date.today() 可控;fromisoformat 沿用真的。"""

    def __init__(self, today):
        self._today = today

    def today(self):
        return self._today

    @staticmethod
    def fromisoformat(s):
        return date.fromisoformat(s)


def harness(tmp, src=None):
    """把模組的所有落地路徑導到 tmp,並攔截 push/wake/login。"""
    m = load(src)
    m.HERE = tmp
    m.MARKER = os.path.join(tmp, ".signed_ok")
    m.LEG_MARKER = {"stock": os.path.join(tmp, ".signed_ok_stock"),
                    "futopt": os.path.join(tmp, ".signed_ok_futopt")}
    m.QUALIFY_MARKER = {"stock": os.path.join(tmp, ".qualify_stock_done"),
                        "futopt": os.path.join(tmp, ".qualify_futopt_done")}
    m.WATCH = os.path.join(tmp, ".signed_watch.json")
    m.AUTO_DIR = os.path.join(tmp, "no_such_autonomous")
    m.pushes = []
    m.wakes = []
    m.logins = 0
    m.push_ok = True
    m._env = lambda p: {"SINOPAC_API_KEY": "k", "SINOPAC_SECRET_KEY": "s",
                        "MARKETDAILY_ALERT_TOKEN": "tok"}

    def _push(msg, tok):
        if m.push_ok is Exception:
            raise OSError("network down")
        if not m.push_ok:
            return False
        m.pushes.append(msg)
        return True
    m.push = _push
    m.wake_machine = lambda note: m.wakes.append(note) or "sent"
    m.SELF_ERR_STAMP = os.path.join(tmp, ".self_err")
    return m


def wire_login(m, states, api=None, exc=None):
    def _login(env):
        m.logins += 1
        if exc:
            raise exc
        return states, (api or FakeApi())
    m.login_states = _login


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        FAILED.append(f"{name} {detail}".strip())
        print(f"  FAIL {name} {detail}")


def run_suite():
    # --- 1. 分腿判準:權威欄位 account_type,不是類別名稱(驗證者 F1) ---
    m = load()
    check("1a 兩腿都掛且已簽",
          m.account_states([stock(True), futopt(True)]) == {"stock": True, "futopt": True},
          m.account_states([stock(True), futopt(True)]))
    check("1b ⭐期貨腿不可蓋掉證券腿",
          m.account_states([stock(True), futopt(False)]) == {"stock": True, "futopt": False},
          m.account_states([stock(True), futopt(False)]))
    check("1c 只掛證券 → futopt 是 None(不是 False)",
          m.account_states([stock(False)]) == {"stock": False, "futopt": None})
    check("1d 同腿多帳號取 OR,不是後寫贏",
          m.account_states([stock(False), stock(True)]) == {"stock": True, "futopt": None})
    # 順序反過來才分得出 OR 與「後寫贏」——只測上面那個方向,兩種實作都會過(突變測試抓到)。
    check("1d2 ⭐已簽署的帳號不可被後面沒簽的蓋掉",
          m.account_states([stock(True), stock(False)]) == {"stock": True, "futopt": None},
          m.account_states([stock(True), stock(False)]))
    check("1e 舊 SDK 類別名稱是後備判準",
          m.account_states([LegacyFutureAccount(True)]) == {"stock": None, "futopt": True})
    try:
        m.account_states([Acct("Z", True)])
        check("1f 未知帳號型別要拋例外(寧可告警不猜)", False, "沒拋")
    except RuntimeError as ex:
        check("1f 未知帳號型別要拋例外(寧可告警不猜)", "Z" in str(ex))
    check("1g 缺 signed 屬性當 False",
          m.account_states([Acct("S", None)]) == {"stock": False, "futopt": None})

    # --- 2. 營業日數學:週末不算,過檔是營業日批次 ---
    check("2a 週四→週一 = 2 個營業日",
          m.biz_days_between(date(2026, 7, 30), date(2026, 8, 3)) == 2,
          f"got {m.biz_days_between(date(2026, 7, 30), date(2026, 8, 3))}")
    check("2b 週五→週六 = 0", m.biz_days_between(date(2026, 7, 31), date(2026, 8, 1)) == 0)
    check("2c 同日 = 0", m.biz_days_between(date(2026, 8, 3), date(2026, 8, 3)) == 0)

    # --- 3. 兩腿生效 + 都通知到 + 已叫醒 → 才停走(cron 變 no-op) ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        for p in m.LEG_MARKER.values():
            open(p, "w").write("x")
        m._save_watch({"announced": ["futopt", "stock"], "woke": True})
        wire_login(m, {"stock": True, "futopt": True})
        check("3a 三件齊 → rc=0 且不登入", m.main() == 0 and m.logins == 0, f"logins={m.logins}")
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        for p in m.LEG_MARKER.values():
            open(p, "w").write("x")
        m._save_watch({"announced": ["stock"], "woke": True})   # 期貨那則從沒送達
        wire_login(m, {"stock": True, "futopt": True})
        m.main()
        check("3b ⭐通知沒送達就不准停走", m.logins == 1, f"logins={m.logins}")

    # --- 4. 兩腿都沒生效 → 不落 marker,走逾期告警 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        wire_login(m, {"stock": False, "futopt": None})
        m._save_watch({"first_seen": "2026-07-30"})
        check("4a rc=0", m.main() == 0)
        check("4b 沒有任何 marker",
              not any(os.path.exists(p) for p in m.LEG_MARKER.values()))
        check("4c 逾期已達 2 營業日 → 推播", len(m.pushes) == 1, m.pushes)
        check("4d 逾期訊息點名兩邊都缺",
              m.pushes and "證券/期貨" in m.pushes[0], m.pushes)

    # --- 5. ⭐核心迴歸:證券生效但期貨沒有 → 期貨端必須繼續被看守 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        m._save_watch({"first_seen": "2026-07-30"})
        wire_login(m, {"stock": True, "futopt": False}, api=FakeApi(positions=4))
        check("5a rc=0", m.main() == 0)
        check("5b 證券腿落 marker", os.path.exists(m.LEG_MARKER["stock"]))
        check("5c ⭐期貨腿【不可】落 marker", not os.path.exists(m.LEG_MARKER["futopt"]))
        check("5d ⭐總停走標記【不可】寫下", not os.path.exists(m.MARKER))
        check("5e 推播講出證券生效+期貨仍缺",
              any("【證券】" in p and "期貨端尚未解鎖" in p for p in m.pushes), m.pushes)
        check("5f 部位數有帶進訊息", any("4 檔部位" in p for p in m.pushes), m.pushes)
        check("5g ⭐剩下那腿仍會被催(不因另一腿生效而閉嘴)",
              any("過檔逾期" in p and "期貨自" in p for p in m.pushes), m.pushes)
        m.pushes.clear()
        wire_login(m, {"stock": True, "futopt": False}, api=FakeApi())
        m.main()
        # logins 跨兩次 main() 累加:1+1=2。舊 bug 的形狀是第二輪直接 return 0,會停在 1。
        check("5h ⭐下一輪仍會登入看期貨", m.logins == 2, f"logins={m.logins}")
        check("5i 證券不會被重複宣告",
              not any("【證券】" in p for p in m.pushes), m.pushes)

    # --- 6. 期貨終於生效 → 推播 + 叫醒機器接手 dry-run ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        open(m.LEG_MARKER["stock"], "w").write("x")
        m._save_watch({"announced": ["stock"], "first_seen": "2026-07-30"})
        wire_login(m, {"stock": True, "futopt": True})
        check("6a rc=0", m.main() == 0)
        check("6b 期貨腿落 marker", os.path.exists(m.LEG_MARKER["futopt"]))
        check("6c 兩腿齊全 → 總停走標記寫下", os.path.exists(m.MARKER))
        check("6d 推播點名期貨+SSF",
              len(m.pushes) == 1 and "【期貨】" in m.pushes[0] and "SSF" in m.pushes[0],
              m.pushes)
        check("6e ⭐叫醒機器接手 dry-run", len(m.wakes) == 1 and "dry-run" in m.wakes[0], m.wakes)
        check("6f 喚醒指令明寫不下實單", m.wakes and "絕不下實單" in m.wakes[0], m.wakes)
        check("6g 喚醒成功記帳(不重複叫)", m._load_watch()[0].get("woke") is True)

    # --- 6b. trigger.sh 永久不存在時不可以卡住停走(否則每小時空登入永豐到天荒地老) ---
    with tempfile.TemporaryDirectory() as tmp:
        m2 = load()                              # 真的 wake_machine,不 stub
        m2.AUTO_DIR = os.path.join(tmp, "no_such_autonomous")
        check("6h trigger.sh 不存在 → 回 absent(三態,不可壓成布林)",
              m2.wake_machine("x") == "absent", m2.wake_machine("x"))

    # --- 7. 兩腿同時生效(冷啟動) ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        wire_login(m, {"stock": True, "futopt": True})
        m.main()
        check("7a 兩腿各推一則", len(m.pushes) == 2, m.pushes)
        check("7b 兩腿 marker 齊", all(os.path.exists(p) for p in m.LEG_MARKER.values()))
        check("7c 文案說兩邊都生效、已停走",
              all("兩邊都已生效" in p for p in m.pushes), m.pushes)
        m.main()
        check("7d 停走後不再登入", m.logins == 1, f"logins={m.logins}")

    # --- 8. login 掛掉 → 告警(不是靜默 traceback),去重鍵含錯誤型別,rc=1 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        wire_login(m, None, exc=RuntimeError("406 Not Allowed"))
        check("8a login 失敗 rc=1", m.main() == 1)
        check("8b 有告警且帶錯誤原文",
              len(m.pushes) == 1 and "登入失敗" in m.pushes[0] and "406" in m.pushes[0], m.pushes)
        m.main()
        check("8c 同一天同型別不重推", len(m.pushes) == 1, m.pushes)
        wire_login(m, None, exc=ValueError("憑證被撤銷"))
        m.main()
        check("8d ⭐同日不同型別的錯誤不可被吃掉", len(m.pushes) == 2, m.pushes)
        m.date = FakeDate(date(2026, 8, 4))
        wire_login(m, None, exc=RuntimeError("406 Not Allowed"))
        m.main()
        check("8e 隔天會再推一次", len(m.pushes) == 3, m.pushes)

    # --- 9. 逾期告警週期性重推(舊版一輩子只推一次) ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m._save_watch({"first_seen": "2026-07-30"})
        states = {"stock": False, "futopt": None}
        seq = [(date(2026, 7, 31), 0, "第 1 個營業日未達門檻"),
               (date(2026, 8, 3), 1, "第 2 個營業日首推"),
               (date(2026, 8, 4), 1, "第 3 天不重推"),
               (date(2026, 8, 7), 1, "第 6 天仍不重推"),
               (date(2026, 8, 10), 2, "第 7 天(距上次 5 營業日)重推")]
        for d, want, label in seq:
            m.overdue_alert(states, d, "tok")
            check(f"9 {label}", len(m.pushes) == want, f"got {len(m.pushes)}")
        check("9f 重推訊息標記持續追蹤",
              "持續追蹤" in m.pushes[-1] and "7 個營業日" in m.pushes[-1], m.pushes[-1])

    # --- 10. 推播送不出去不可以記帳(否則把失敗的告警吃掉) ---
    for label, mode in (("例外", Exception), ("回 False", False)):
        with tempfile.TemporaryDirectory() as tmp:
            m = harness(tmp)
            m._save_watch({"first_seen": "2026-07-30"})
            m.push_ok = mode
            m.overdue_alert({"stock": False, "futopt": None}, date(2026, 8, 3), "tok")
            check(f"10a 推失敗({label}) → 不寫 alerted_at_biz",
                  "alerted_at_biz" not in m._load_watch()[0], m._load_watch()[0])
            m.push_ok = True
            m.overdue_alert({"stock": False, "futopt": None}, date(2026, 8, 3), "tok")
            check(f"10b 下一輪重試成功({label})", len(m.pushes) == 1, m.pushes)
            check(f"10c 成功後才記帳({label})",
                  m._load_watch()[0].get("alerted_at_biz") == 2, m._load_watch()[0])

    # --- 11. ⭐驗證者 F2:單腿宣告推不出去必須重試,不可被 marker 永久吃掉 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        open(m.LEG_MARKER["stock"], "w").write("x")
        m._save_watch({"announced": ["stock"], "woke": True})
        m.push_ok = Exception
        wire_login(m, {"stock": True, "futopt": True})
        check("11a 推播炸掉仍 rc=0", m.main() == 0)
        check("11b marker 已落地", os.path.exists(m.LEG_MARKER["futopt"]))
        check("11c ⭐沒送到就不記帳", "futopt" not in m._load_watch()[0].get("announced", []),
              m._load_watch()[0])
        m.push_ok = True
        m.main()
        check("11d ⭐下一輪重講一次期貨生效",
              any("【期貨】" in p for p in m.pushes), m.pushes)
        check("11e 送到後才記帳", "futopt" in m._load_watch()[0].get("announced", []))

    # --- 12. token 缺席 = 送不到(不是「不用送」) ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        m._env = lambda p: {"SINOPAC_API_KEY": "k", "SINOPAC_SECRET_KEY": "s"}
        wire_login(m, {"stock": True, "futopt": True})
        m.main()
        check("12a ⭐token 缺席不可記成已通知",
              m._load_watch()[0].get("announced", []) == [], m._load_watch()[0])
        ok, why = m._try_push("x", "")
        check("12b _try_push 對空 token 回 False 並說明原因",
              ok is False and "TOKEN" in why, (ok, why))

    # --- 13. list_positions 沒權限 / logout 一定被呼叫 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        api = FakeApi(raise_positions=True)
        wire_login(m, {"stock": True, "futopt": False}, api=api)
        m.main()
        check("13a 仍推播", any("【證券】" in p for p in m.pushes), m.pushes)
        check("13b 不假造部位數", not any("檔部位" in p for p in m.pushes), m.pushes)
        check("13c logout 被呼叫", api.logged_out)

    # --- 14. ⭐驗證者 F3:壞掉的 watch 檔 ---
    bad = [("空檔", ""), ("半截 JSON", "{ not json"), ("整個不是物件", '"hello"'),
           ("first_seen null", '{"first_seen": null}'),
           ("first_seen 數字", '{"first_seen": 20260730}'),
           ("first_seen 非法日期", '{"first_seen": "2026-13-01"}'),
           ("alerted_at_biz 字串", '{"first_seen": "2026-07-30", "alerted_at_biz": "x"}'),
           ("announced 不是 list", '{"announced": "stock"}')]
    for label, raw in bad:
        with tempfile.TemporaryDirectory() as tmp:
            m = harness(tmp)
            m.date = FakeDate(date(2026, 8, 3))
            open(m.WATCH, "w").write(raw)
            wire_login(m, {"stock": False, "futopt": None})
            rc = m.main()
            check(f"14 {label} 不 crash", rc == 0, f"rc={rc}")
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        open(m.WATCH, "w").write('{"first_seen": "2026-13-01"}')
        wire_login(m, {"stock": False, "futopt": None})
        m.main()
        check("14i ⭐壞欄位要出聲(不可靜默把等待天數歸零)",
              any("壞掉的欄位" in p for p in m.pushes), m.pushes)
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m._save_watch({"first_seen": "2026-07-30", "alerted_at_biz": 152})   # 時鐘曾前跳
        m.overdue_alert({"stock": False, "futopt": None}, date(2026, 8, 3), "tok")
        check("14j ⭐時鐘校正回來後不可永久閉嘴", len(m.pushes) == 1, m.pushes)
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        os.mkdir(os.path.join(tmp, "sub"))
        m._save_watch({"first_seen": "2026-07-30"})
        leftovers = [f for f in os.listdir(tmp) if f.startswith(".signed_watch.") and
                     f != ".signed_watch.json"]
        check("14k 原子寫不留暫存檔", leftovers == [], leftovers)

    # --- 15. ⭐驗證者 F6:舊版 .signed_ok 遷移,不可重複宣告 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        open(m.MARKER, "w").write("signed ok (legacy)\n")
        wire_login(m, {"stock": True, "futopt": False})
        m.main()
        check("15a 舊 marker 遷移成證券腿 marker", os.path.exists(m.LEG_MARKER["stock"]))
        check("15b ⭐不重複宣告證券生效",
              not any("【證券】" in p for p in m.pushes), m.pushes)

    # --- 16. 逾期起算日錨在開通測試完成日,不是「第一次跑空的那輪」 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        for p in m.QUALIFY_MARKER.values():
            open(p, "w").write("done")
        os.utime(m.QUALIFY_MARKER["stock"], (1785000000, 1785000000))   # 2026-07-25 前後
        anchor = m.signing_anchor(date(2026, 8, 3))
        check("16a 有 qualify marker → 用它的 mtime 當起算日",
              anchor == date.fromtimestamp(1785000000), anchor)
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        check("16b 沒有 qualify marker → 退回今天",
              m.signing_anchor(date(2026, 8, 3)) == date(2026, 8, 3))

    # --- 17. ⭐第 2 輪 F1:無關的腿(複委託 Intl 'H')不可以把整支偵測器炸掉 ---
    m = load()
    check("17a ⭐複委託帳號被跳過,兩腿照常讀得到",
          m.account_states([stock(True), Acct("H", True), futopt(False)])
          == {"stock": True, "futopt": False},
          m.account_states([stock(True), Acct("H", True), futopt(False)]))
    check("17b 只掛複委託 → 兩腿都是 None(不是誤判成某一腿)",
          m.account_states([Acct("H", True)]) == {"stock": None, "futopt": None})
    check("17c 真正未知的型別仍拋專屬例外", issubclass(m.UnknownLegError, RuntimeError))
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        wire_login(m, None, exc=m.UnknownLegError("未知的永豐帳號型別 account_type='Z'"))
        check("17d 未知型別 rc=1", m.main() == 1)
        check("17e ⭐文案不可冒充『登入失敗』(登入其實成功了)",
              m.pushes and "登入失敗" not in m.pushes[0] and "認不得" in m.pushes[0], m.pushes)
        m.main()
        check("17f 同日不重推", len(m.pushes) == 1, m.pushes)

    # --- 18. ⭐第 2 輪 F2:account_states 拋例外時 session 必須被 logout ---
    holder = {}

    class _FakeApi:
        def __init__(self, simulation=False):
            self.logged_out = False
            holder["api"] = self

        def login(self, **kw):
            return holder["accounts"]

        def logout(self):
            self.logged_out = True
    fake_sj = types.ModuleType("shioaji")
    fake_sj.Shioaji = _FakeApi
    real_sj = sys.modules.get("shioaji")
    sys.modules["shioaji"] = fake_sj
    try:
        m = load()
        holder["accounts"] = [stock(True), Acct("Z", True)]      # Z=判準認不得 → 拋例外
        try:
            m.login_states({"SINOPAC_API_KEY": "k", "SINOPAC_SECRET_KEY": "s"})
            check("18a 未知型別要拋例外", False, "沒拋")
        except m.UnknownLegError:
            check("18a 未知型別要拋例外", True)
        check("18b ⭐拋例外時仍然登出(否則每小時漏一個永豐 session)",
              holder["api"].logged_out, holder["api"].logged_out)
        holder["accounts"] = [stock(True), futopt(True)]
        states, api = m.login_states({"SINOPAC_API_KEY": "k", "SINOPAC_SECRET_KEY": "s"})
        check("18c 正常路徑不自己登出(呼叫端還要用 api)",
              states == {"stock": True, "futopt": True} and not api.logged_out, states)
    finally:
        if real_sj is None:
            sys.modules.pop("shioaji", None)
        else:
            sys.modules["shioaji"] = real_sj

    # --- 19. ⭐第 2 輪 F3:損毀告警推不出去,不可以被下游 _save_watch 洗掉 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        open(m.WATCH, "w").write('{"first_seen": "2026-07-30", "alerted_at_biz": "x"}')
        m.push_ok = Exception
        wire_login(m, {"stock": False, "futopt": None})
        m.main()
        check("19a 推播掛掉時把待講事項記成狀態",
              m._load_watch()[0].get("corrupt_pending") == "alerted_at_biz",
              m._load_watch()[0])
        m.push_ok = True
        m.main()
        check("19b ⭐通道復原後補講損毀告警",
              any("壞掉的欄位" in p and "alerted_at_biz" in p for p in m.pushes), m.pushes)
        check("19c 送達後清掉待講狀態", "corrupt_pending" not in m._load_watch()[0])
        n = len(m.pushes)
        m.main()
        check("19d 不重複洗頻",
              not any("壞掉的欄位" in p for p in m.pushes[n:]), m.pushes[n:])

    # --- 20. ⭐第 2 輪 F4:叫不醒機器不可以無聲,也不可以永遠停不下來 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        m.wake_machine = lambda note: "absent"
        wire_login(m, {"stock": True, "futopt": True})
        m.main()
        check("20a ⭐trigger.sh 不在 → 老闆被告知沒人接手",
              any("叫不醒" in p or "找不到" in p for p in m.pushes), m.pushes)
        check("20b 送達後才放行停走", m._load_watch()[0].get("woke") is True)
        m.main()
        check("20c 停走後不再登入", m.logins == 1, f"logins={m.logins}")
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        m.wake_machine = lambda note: "failed"
        wire_login(m, {"stock": True, "futopt": True})
        for i in range(1, m.WAKE_FAIL_LIMIT):
            m.main()
            check(f"20d 第 {i} 次暫時失敗先重試不吵",
                  not any("叫不醒" in p for p in m.pushes), m.pushes)
        m.main()
        check("20e ⭐連續失敗到門檻 → 出聲",
              any("叫不醒" in p for p in m.pushes), m.pushes)
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        m.wake_machine = lambda note: "absent"
        m.push_ok = False
        wire_login(m, {"stock": True, "futopt": True})
        m.main()
        check("20f ⭐告警沒送到不可以停走(否則沒人知道機器沒接手)",
              m._load_watch()[0].get("woke") is not True, m._load_watch()[0])

    # --- 21. ⭐第 2 輪 F5:null 欄位算損毀,不可靜默重錨 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        open(m.WATCH, "w").write('{"first_seen": null}')
        wire_login(m, {"stock": False, "futopt": None})
        m.main()
        check("21a ⭐first_seen=null 要出聲(和數字/非法日期一致)",
              any("壞掉的欄位" in p and "first_seen" in p for p in m.pushes), m.pushes)
    m = load()
    check("21b 欄位不存在不算損毀", m._sanitize_watch({})[1] == [])
    check("21c woke=false 不算損毀", m._sanitize_watch({"woke": False})[1] == [])
    check("21d woke 是字串算損毀", m._sanitize_watch({"woke": "yes"})[1] == ["woke"])

    # --- 22. ⭐第 2 輪 F6:逾期文案不可誣賴已生效的那一腿 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        open(m.LEG_MARKER["stock"], "w").write("x")
        m._save_watch({"announced": ["stock"], "first_seen": "2026-07-30"})
        wire_login(m, {"stock": False, "futopt": False})      # 證券腿抽風回 False
        m.main()
        od = [p for p in m.pushes if p.startswith("⚠️ 永豐 API 過檔逾期")]
        check("22a ⭐逾期文案不點名已落 marker 的證券腿",
              od and "證券/期貨" not in od[0] and "期貨自" in od[0], od)
        check("22b 曾生效又回 False → 另一則專屬告警",
              any("原本已生效" in p for p in m.pushes), m.pushes)
        n = len(m.pushes)
        m.main()
        check("22c 同日不重推回退告警",
              not any("原本已生效" in p for p in m.pushes[n:]), m.pushes[n:])
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        for p in m.LEG_MARKER.values():
            open(p, "w").write("x")
        m._save_watch({"first_seen": "2026-07-30", "announced": ["stock", "futopt"]})
        m.overdue_alert({"stock": False, "futopt": False}, date(2026, 8, 10), "tok")
        check("22d 兩腿都已 settled → 完全不推逾期",
              not any("過檔逾期" in p for p in m.pushes), m.pushes)

    # --- 23. ⭐第 2 輪 F7:偵測器自己爆掉(唯讀目錄)必須出一次聲,不是每小時無聲暴斃 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        ro = os.path.join(tmp, "ro")
        os.mkdir(ro)
        m.LEG_MARKER = dict(m.LEG_MARKER, futopt=os.path.join(ro, ".signed_ok_futopt"))
        os.chmod(ro, 0o500)
        try:
            wire_login(m, {"stock": True, "futopt": True})
            rc = m.main()
            check("23a 唯讀目錄 → rc=1 而不是 traceback 穿出去", rc == 1, f"rc={rc}")
            check("23b ⭐偵測器自己死了要出聲",
                  any("自己異常結束" in p for p in m.pushes), m.pushes)
            n = len(m.pushes)
            m.main()
            check("23c 同日同型別不洗頻",
                  not any("自己異常結束" in p for p in m.pushes[n:]), m.pushes[n:])
        finally:
            os.chmod(ro, 0o700)

    # --- 24. ⭐第 3 輪 F1:"sent" 必須有實證,不可以只證明 fork 得起來 ---
    with tempfile.TemporaryDirectory() as tmp:
        m2 = load()
        m2.AUTO_DIR = tmp
        trig = os.path.join(tmp, "trigger.sh")
        open(trig, "w").write("#!/bin/bash\nexit 0\n")
        os.chmod(trig, 0o755)
        check("24a 正常 trigger.sh → sent", m2.wake_machine("x") == "sent", m2.wake_machine("x"))
        os.chmod(trig, 0o000)
        check("24b ⭐權限壞掉(bash exit 126)不可回 sent",
              m2.wake_machine("x") == "failed", m2.wake_machine("x"))
        os.chmod(trig, 0o755)
        open(trig, "w").write("#!/bin/bash\nexit 3\n")
        check("24c ⭐trigger.sh 自己失敗也算 failed",
              m2.wake_machine("x") == "failed", m2.wake_machine("x"))
        open(trig, "w").write("#!/bin/bash\nsleep 30\n")
        m2.WAKE_WAIT_SEC = 1
        check("24d 還在跑=已接手,算 sent(不阻塞 cron)",
              m2.wake_machine("x") == "sent")

    # --- 25. ⭐第 3 輪 F2:未來日 first_seen 不可以讓唯一的主動告警永久靜音 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m._save_watch({"first_seen": "2027-01-01"})
        m.overdue_alert({"stock": False, "futopt": None}, date(2026, 8, 3), "tok")
        check("25a ⭐未來錨點被鉗回今天(不是留在 2027 讓 waited 恆為 0)",
              m._load_watch()[0].get("first_seen") == "2026-08-03", m._load_watch()[0])
        m.overdue_alert({"stock": False, "futopt": None}, date(2026, 8, 10), "tok")
        check("25b ⭐鉗回後照常在門檻日出聲",
              any("過檔逾期" in p for p in m.pushes), m.pushes)
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        open(m.QUALIFY_MARKER["stock"], "w").write("x")
        os.utime(m.QUALIFY_MARKER["stock"], (2000000000, 2000000000))   # 2033 年
        check("25c ⭐未來 mtime 不可當起算日",
              m.signing_anchor(date(2026, 8, 3)) == date(2026, 8, 3),
              m.signing_anchor(date(2026, 8, 3)))

    # --- 26. ⭐第 3 輪 F4:程式自己要有鎖(不能只靠 crontab 的 flock) ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.LOCK = os.path.join(tmp, "lock")
        m.date = FakeDate(date(2026, 8, 3))
        wire_login(m, {"stock": True, "futopt": True})
        fd = os.open(m.LOCK, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            rc = m.main()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("26a ⭐鎖被別人拿著就整輪跳過(不重複推播/重複喚醒)",
              rc == 0 and m.logins == 0 and m.pushes == [], (rc, m.logins, m.pushes))
        check("26b 鎖放開後照常跑", m.main() == 0 and m.logins == 1, f"logins={m.logins}")

    # --- 27. ⭐第 3 輪 F5:損毀偵測剩下的兩個靜默缺口 + woke 死鎖 ---
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 3))
        open(m.WATCH, "w").write("null")
        wire_login(m, {"stock": False, "futopt": None})
        m.main()
        check("27a ⭐整份檔案是 null 也要出聲",
              any("壞掉的欄位" in p for p in m.pushes), m.pushes)
    m = load()
    check("27b ⭐announced 元素漂移不可靜默過濾",
          m._sanitize_watch({"announced": [1, 2]})[1] == ["announced"],
          m._sanitize_watch({"announced": [1, 2]}))
    check("27c 正常 announced 不算損毀",
          m._sanitize_watch({"announced": ["stock", "stock"]})[1] == [])
    with tempfile.TemporaryDirectory() as tmp:
        m = harness(tmp)
        m.date = FakeDate(date(2026, 8, 10))
        m.wake_machine = lambda note: "absent"
        m.push_ok = False
        wire_login(m, {"stock": True, "futopt": True})
        m.main()
        m.push_ok = True
        m.main()
        check("27d ⭐第一次沒送到,下一輪要再講一次(不可被 latch 鎖死)",
              any("叫不醒" in p or "找不到" in p for p in m.pushes), m.pushes)


def contract_test():
    """⭐驗證者 F5:用**真的 shioaji.Account** 驗分腿,不用自刻 fixture。

    上一版把「類別名稱含 Fut」這個錯誤前提寫進 fixture 當真理,14/14 全綠卻完全
    咬不到 F1 —— 測試證明的是自己的假設,不是與 SDK 的相容性。
    """
    print("\n[合約測試:真 shioaji.Account]")
    py = SHIOAJI_PY if os.path.exists(SHIOAJI_PY) else sys.executable
    code = (
        "import warnings; warnings.filterwarnings('ignore')\n"
        "import shioaji as sj, importlib.util, json\n"
        "spec=importlib.util.spec_from_file_location('cs', %r)\n"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "mk=lambda t,s: sj.Account(account_type=t, person_id='X', broker_id='B',"
        " account_id='1', signed=s)\n"
        "print(json.dumps({'names': [type(mk(sj.AccountType.Stock,True)).__name__,"
        " type(mk(sj.AccountType.Future,True)).__name__],"
        " 'both': m.account_states([mk(sj.AccountType.Stock,True), mk(sj.AccountType.Future,True)]),"
        " 'fut_false': m.account_states([mk(sj.AccountType.Stock,True),"
        " mk(sj.AccountType.Future,False)])}))\n"
        % os.path.join(HERE, "check_signed.py"))
    r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=90)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not line:
        SKIPPED.append(f"合約測試:跑不到 shioaji({py}) — {r.stderr.strip().splitlines()[-1:]}")
        print(f"  SKIP 沒有可用的 shioaji({py});F1 的真 SDK 保護在本環境未被驗證")
        return
    import json as _json
    got = _json.loads(line[-1])
    check("15c 真 SDK 兩腿類別名稱相同(所以名字判準必敗)",
          got["names"][0] == got["names"][1] == "Account", got["names"])
    check("15d ⭐真 SDK 下兩腿都認得出來",
          got["both"] == {"stock": True, "futopt": True}, got["both"])
    check("15e ⭐真 SDK 下期貨不蓋掉證券",
          got["fut_false"] == {"stock": True, "futopt": False}, got["fut_false"])


MUTATIONS = [
    ("分腿退回看類別名稱(F1 原形)",
     'if code == "F" or code.startswith("FUT") or "Fut" in name:',
     'if "Fut" in name:'),
    ("同腿多帳號後寫贏(蓋掉另一腿)",
     "out[kind] = v if out[kind] is None else (out[kind] or v)",
     "out[kind] = v"),
    ("未知帳號型別默默當證券",
     'raise UnknownLegError(f"未知的永豐帳號型別 account_type={at!r} class={name}")',
     'return "stock"'),
    ("複委託帳號炸掉整包(第2輪F1)",
     "    if code in IGNORED_LEG_CODES:\n        return None",
     "    if False:\n        return None"),
    ("未知型別冒充登入失敗(第2輪F1)",
     "        alert_unknown_leg(ex, today, tok)",
     "        alert_login_failure(ex, today, tok)"),
    ("account_states 拋例外時不登出(第2輪F2)",
     "    try:\n        return account_states(accounts), api\n    except Exception:",
     "    if True:\n        return account_states(accounts), api\n    if False:"),
    ("損毀告警沒送到仍不留重試依據(第2輪F3)",
     '        st["corrupt_pending"] = "、".join(pending)',
     '        st.pop("corrupt_pending", None)'),
    ("叫不醒機器仍靜默停走(第2輪F4)",
     '        if how == "sent":',
     '        if how != "nope":'),
    ("喚醒告警沒送到就放行停走(第2輪F4)",
     '                if ok:\n                    st["woke"] = True     # 送達才放行停走',
     '                if True:\n                    st["woke"] = True     # 送達才放行停走'),
    ("wake 只看 fork 成功不看 trigger.sh 結束碼(第3輪F1)",
     '    if rc != 0:\n        print("wake failed: trigger.sh exit", rc)\n        return "failed"',
     '    if False:\n        print("wake failed: trigger.sh exit", rc)\n        return "failed"'),
    ("未來日 first_seen 不鉗回(逾期告警永久靜音,第3輪F2)",
     "    if first > today:",
     "    if False:"),
    ("signing_anchor 不濾未來 mtime(第3輪F2)",
     "    days = [d for d in (datetime.fromtimestamp(s).date() for s in stamps) if d <= today]",
     "    days = [datetime.fromtimestamp(s).date() for s in stamps]"),
    ("整份檔案是 null 靜默吞掉(第3輪F5)",
     '        return st, ["<整個檔案不是物件>"]',
     '        return st, (["<整個檔案不是物件>"] if raw is not None else [])'),
    ("announced 元素漂移靜默過濾(第3輪F5)",
     '        if len(keep) != len(set(st["announced"])):\n            dropped.append("announced")',
     '        if False:\n            dropped.append("announced")'),
    ("程式自己不上鎖(第3輪F4)",
     "            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)",
     "            pass"),
    ("null 欄位不算損毀(第2輪F5)",
     '        v = raw.get(key, _MISSING)\n        if v is _MISSING:\n            return',
     '        v = raw.get(key, _MISSING)\n        if v is _MISSING or v is None:\n            return'),
    ("逾期文案誣賴已生效的腿(第2輪F6)",
     '                   if states.get(k) is not True and not settled(k)]',
     '                   if states.get(k) is not True]'),
    ("腿回退不另外告警(第2輪F6)",
     "    if regressed:\n        alert_leg_regressed(regressed, today, tok)",
     "    if False:\n        alert_leg_regressed(regressed, today, tok)"),
    ("偵測器自身異常無聲暴斃(第2輪F7)",
     "    except Exception as ex:\n        alert_self_failure(ex, date.today())\n        return 1",
     "    except Exception:\n        raise"),
    ("只看證券就永久停走(舊 bug 原形)",
     'live = [k for k in ("stock", "futopt") if states.get(k) is True]',
     'live = ["stock"] if states.get("stock") is True else []'),
    ("停走條件放寬成只要 marker 齊(通知沒送到也退休)",
     "if all(settled(k) for k in LEG_MARKER) and announced >= set(LEG_MARKER) and st.get(\"woke\"):",
     "if all(settled(k) for k in LEG_MARKER):"),
    ("單腿宣告失敗仍記帳(F2:一次 403 永久靜音)",
     "if ok:\n            announced.add(kind)",
     "if True:\n            announced.add(kind)"),
    ("token 缺席當成不用送",
     'if not tok:\n        return False, "MARKETDAILY_ALERT_TOKEN 缺席,告警無法送出"',
     'if not tok:\n        return True, ""'),
    ("逾期告警退回一輩子只推一次",
     "last is None or waited - last >= OVERDUE_REPEAT_BIZ_DAYS",
     "last is None"),
    ("時鐘倒退不重置(F3:永久閉嘴)",
     "if last is not None and last > waited:",
     "if False:"),
    ("watch 檔壞掉靜默吞掉",
     'if dropped or st.get("corrupt_pending"):\n        alert_corrupt_watch(dropped, today, tok)',
     'if False:\n        alert_corrupt_watch(dropped, today, tok)'),
    ("損毀告警不重試(只看本輪 dropped,第2輪F3)",
     'if dropped or st.get("corrupt_pending"):',
     'if dropped:'),
    ("first_seen 不做型別驗證(每小時 traceback)",
     '    take("first_seen", _date_ok)',
     '    take("first_seen", lambda v: True)'),
    ("login 失敗退回靜默",
     "alert_login_failure(ex, today, tok)\n        return 1",
     "return 1"),
    ("login 去重鍵拿掉錯誤型別",
     'stamp = f"{today.isoformat()}:{type(ex).__name__}"',
     "stamp = today.isoformat()"),
    ("期貨生效不叫醒機器",
     'if "futopt" in live and not st.get("woke"):',
     "if False:"),
    ("另一腿生效後就對剩下那腿閉嘴",
     "if any(states.get(k) is not True for k in LEG_MARKER):\n        overdue_alert(states, today, tok)",
     "if False:\n        overdue_alert(states, today, tok)"),
    ("舊 marker 不遷移(重複宣告)",
     "    if os.path.exists(MARKER) and not os.path.exists(LEG_MARKER[\"stock\"]):",
     "    if False:"),
    ("營業日改成日曆天(週末誤報)",
     "if d.weekday() < 5:\n            n += 1",
     "n += 1"),
]


def run_mutations():
    """突變測試:每個突變都必須讓上面的測試變紅——沒咬到的規則等於沒人守。"""
    src = open(os.path.join(HERE, "check_signed.py"), encoding="utf-8").read()
    base = subprocess.run([sys.executable, os.path.join(HERE, "test_check_signed.py")],
                          capture_output=True, text=True, timeout=180)
    if base.returncode != 0:
        # 沒有這道閘,任何「讓測試永遠紅」的環境問題(例如合約測試 SKIP 現在也回 1)
        # 都會讓每個突變都看似被咬住 → 突變測試自己變成假綠。
        print("BASELINE-RED 未突變的測試就已經失敗,突變結果無意義:")
        print(base.stdout[-1500:])
        return 1
    bad = []
    for label, old, new in MUTATIONS:
        if old not in src:
            bad.append(f"{label}:突變錨點已漂移,對不上原始碼")
            print(f"  ANCHOR-LOST {label}")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "check_signed.py"), "w",
                 encoding="utf-8").write(src.replace(old, new, 1))
            shutil.copy(os.path.join(HERE, "test_check_signed.py"),
                        os.path.join(tmp, "test_check_signed.py"))
            r = subprocess.run([sys.executable, os.path.join(tmp, "test_check_signed.py")],
                               capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                bad.append(f"{label}:突變後測試仍全過=這條規則沒有人守")
                print(f"  NOT-CAUGHT {label}")
            else:
                print(f"  caught     {label}")
    if bad:
        print("\n突變測試失敗:")
        for b in bad:
            print(" -", b)
        return 1
    print(f"\n✅ 突變測試 {len(MUTATIONS)}/{len(MUTATIONS)} 全部被咬住")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(run_mutations())
    run_suite()
    contract_test()
    for s in SKIPPED:
        print("  ⏭️ SKIP:", s)
    if FAILED:
        print(f"\n❌ {len(FAILED)} 項失敗:")
        for f in FAILED:
            print(" -", f)
        sys.exit(1)
    if SKIPPED:
        # ⭐第 3 輪 F3:合約測試是唯一咬得住「真 SDK 分腿」的保護,被 SKIP 掉還回 0
        # = 夜巡每晚照樣綠燈,而最重要的那條保護其實沒在跑(假綠比假紅危險)。
        print(f"\n❌ {len(SKIPPED)} 項被跳過:保護沒有真的執行,不算通過")
        sys.exit(1)
    print("\n✅ check_signed 自測全過")
