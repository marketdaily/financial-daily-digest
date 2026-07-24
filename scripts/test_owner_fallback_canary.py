"""回歸測試:老闆本人掉降級/備援版 → admin 告警必帶紅色 canary + push 具重試韌性。

2026-07-24:delvin 掉 portfolio_lens 誤殺備援,舊告警只說「1 位掉備援」跟其他品質
告警一模一樣 → 淹沒沒被抓到。此測試鎖住:①老闆在名單→最上方 canary;②非老闆→無
canary;③push 間歇失敗會重試,3 次全敗會拋(守衛掛掉也要看得見)。
"""
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MARKETDAILY_ALERT_TOKEN"] = "test-token"
os.environ["MARKETDAILY_OWNER_EMAIL"] = "delvin.12345678@gmail.com"
import main  # noqa: E402

OWNER = "delvin.12345678@gmail.com"
CANARY = "🚨🚨🚨 老闆本人"


class _FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkey_fail=0):
    """回傳 (captured_message, urlopen_call_count)。monkey_fail=前 N 次拋錯。"""
    box = {"msg": None, "calls": 0}

    def fake_urlopen(req, timeout=10):
        box["calls"] += 1
        box["msg"] = req.data.decode("utf-8")
        if box["calls"] <= monkey_fail:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        return _FakeResp()

    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        return box, orig
    finally:
        pass  # 還原在呼叫端做


def run():
    import json

    # 1) 老闆本人掉備援 → 訊息最上方有 canary + 該行標「← 老闆本人」
    box = {"msg": None, "calls": 0}

    def fk(req, timeout=10):
        box["calls"] += 1
        box["msg"] = req.data.decode("utf-8")
        return _FakeResp()
    orig = urllib.request.urlopen
    urllib.request.urlopen = fk
    try:
        main._push_admin_halt_alert("2026-07-24", [OWNER], [], dry_run=False)
        msg = json.loads(box["msg"])["message"]
        assert CANARY in msg, "[FAIL] 老闆掉備援卻無 canary"
        assert msg.splitlines()[0].startswith(CANARY), "[FAIL] canary 不在最上方"
        assert "← 老闆本人" in msg, "[FAIL] 名單未標記老闆本人"

        # 2) 非老闆掉備援 → 無 canary(不製造雜訊)
        box["msg"] = None
        main._push_admin_halt_alert("2026-07-24", ["someone.else@gmail.com"], [], dry_run=False)
        msg2 = json.loads(box["msg"])["message"]
        assert CANARY not in msg2, "[FAIL] 非老闆卻誤觸 canary"

        # 3) 個人化失敗路徑也吃 owner canary
        box["msg"] = None
        main._push_admin_halt_alert("2026-07-24", [], [(OWNER, "prefs_403")], dry_run=False)
        assert CANARY in json.loads(box["msg"])["message"], "[FAIL] perso_fail 老闆未觸 canary"
    finally:
        urllib.request.urlopen = orig

    # 4) push 前 2 次失敗、第 3 次成功 → 仍送達(重試韌性)
    box2 = {"calls": 0, "msg": None}

    def fk_retry(req, timeout=10):
        box2["calls"] += 1
        box2["msg"] = req.data.decode("utf-8")
        if box2["calls"] <= 2:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        return _FakeResp()
    urllib.request.urlopen = fk_retry
    try:
        main._push_admin_halt_alert("2026-07-24", [OWNER], [], dry_run=False)
        assert box2["calls"] == 3, f"[FAIL] 應重試到第3次成功,實際 {box2['calls']}"

        # 5) 3 次全敗 → 拋錯(守衛掛掉也要看得見,不吞)
        box3 = {"calls": 0}

        def fk_allfail(req, timeout=10):
            box3["calls"] += 1
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        urllib.request.urlopen = fk_allfail
        raised = False
        try:
            main._push_admin_halt_alert("2026-07-24", [OWNER], [], dry_run=False)
        except Exception:
            raised = True
        assert raised, "[FAIL] 3 次全敗竟沒拋錯(告警靜默蒸發)"
        assert box3["calls"] == 3, f"[FAIL] 應嘗試 3 次,實際 {box3['calls']}"
    finally:
        urllib.request.urlopen = orig

    print("✅ owner fallback canary 回歸測試全過(5 組)")


if __name__ == "__main__":
    run()
