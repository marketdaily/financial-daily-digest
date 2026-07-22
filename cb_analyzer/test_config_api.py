"""拆解準則網頁可調 + 郵件狀態檔 單元測試(零網路)。
跑:python3 test_config_api.py  (從 cb_analyzer/)
蓋面:validate_config 各非法案例、save_config 原子寫入/備份/audit、
reload_config_if_changed mtime 生效、tcri_spread 改動 → 理論價方向、
mail status 寫讀、_notify_desk 落帳格式、_mail_freshness_line 容錯。"""
import copy
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cb  # noqa: E402
import cb_core  # noqa: E402
import cb_server  # noqa: E402
import cb_mail_ingest  # noqa: E402

n = 0


def ck(cond, msg):
    global n
    n += 1
    assert cond, f"FAIL: {msg}"


ORIG = copy.deepcopy(cb_core.ASSUMPTIONS)


def good():
    return {"rf": 0.013, "asset_swap_spread": 0.020,
            "vol_w_short": 0.35, "vol_w_long": 0.65,
            "elig_tcri": [3, 4], "elig_min_size": 10,
            "tcri_spread": {"1": 0.008, "2": 0.010, "3": 0.015, "4": 0.020, "5": 0.028,
                            "6": 0.038, "7": 0.052, "8": 0.066, "9": 0.082}}


# ── validate_config ──────────────────────────────────────────────
clean, errs = cb_server.validate_config(good())
ck(not errs and clean["rf"] == 0.013, "合法整包應通過")
ck(clean["tcri_spread"]["9"] == 0.082, "tcri_spread 正規化為字串鍵")

for mut, why in [
    ({"rf": 0.6}, "rf 超界 0.6"),
    ({"rf": "0.013"}, "rf 字串"),
    ({"rf": True}, "rf 布林"),
    ({"asset_swap_spread": -0.01}, "spread 負值"),
    ({"vol_w_short": 0.5}, "權重和 1.15 超容差"),
    ({"elig_tcri": []}, "elig_tcri 空"),
    ({"elig_tcri": [3, 10]}, "elig_tcri 含 10"),
    ({"elig_tcri": "34"}, "elig_tcri 非清單"),
    ({"elig_min_size": 100000}, "min_size 超界"),
    ({"tcri_spread": {str(i): 0.01 for i in range(1, 9)}}, "tcri_spread 缺 9"),
    ({"tcri_spread": {**good()["tcri_spread"], "5": 0.001}}, "tcri_spread 反轉"),
    ({"tcri_spread": [0.01] * 9}, "tcri_spread 非物件"),
]:
    c, e = cb_server.validate_config({**good(), **mut})
    ck(c is None and e, f"非法案例應整包拒絕:{why}")
    ck(any(k.split("[")[0] in "".join(e) for k in mut), f"錯誤要點名欄位:{why} → {e}")

c, e = cb_server.validate_config({k: v for k, v in good().items() if k != "rf"})
ck(c is None and any("rf" in x for x in e), "缺欄位要點名 rf")
c, e = cb_server.validate_config({**good(), "elig_tcri": [4, 3, 3]})
ck(c and c["elig_tcri"] == [3, 4], "elig_tcri 去重排序")
sp_eq = {**good()["tcri_spread"], "2": 0.008}
c, e = cb_server.validate_config({**good(), "tcri_spread": sp_eq})
ck(c is not None, "tcri_spread 相鄰相等(非遞減)放行,只擋反轉")

# ── save_config:原子寫入 + 備份 + audit ─────────────────────────
with tempfile.TemporaryDirectory() as td:
    cfgp = os.path.join(td, "cb_config.json")
    hist = os.path.join(td, "hist.jsonl")
    with open(cfgp, "w", encoding="utf-8") as f:
        json.dump({"_說明": "測試", **good()}, f, ensure_ascii=False)
    newcfg = {**good(), "rf": 0.02}
    changes = cb_server.save_config(cb_server.validate_config(newcfg)[0], cfgp, hist)
    ck(set(changes) == {"rf"}, f"diff 只該有 rf,得到 {set(changes)}")
    ck(changes["rf"]["old"] == 0.013 and changes["rf"]["new"] == 0.02, "audit old→new 值")
    with open(cfgp, encoding="utf-8") as f:
        saved = json.load(f)
    ck(saved["rf"] == 0.02 and saved["_說明"] == "測試", "寫入生效且保留 _說明")
    ck(list(saved["tcri_spread"]) == [str(i) for i in range(1, 10)], "利差表 1..9 排序")
    baks = [x for x in os.listdir(td) if ".bak-" in x]
    ck(len(baks) == 1, "有當日備份")
    with open(os.path.join(td, baks[0]), encoding="utf-8") as f:
        ck(json.load(f)["rf"] == 0.013, "備份是改前內容")
    with open(hist, encoding="utf-8") as f:
        row = json.loads(f.read().strip())
    ck(row["changes"]["rf"]["new"] == 0.02 and row["ts"], "audit 落 history")
    ck(not [x for x in os.listdir(td) if ".tmp" in x], "沒有殘留 tmp 檔(原子寫入)")
    ck(cb_server.save_config(cb_server.validate_config(newcfg)[0], cfgp, hist) == {},
       "無變更不重寫不追加")

# ── reload_config_if_changed:mtime 生效 ─────────────────────────
with tempfile.TemporaryDirectory() as td:
    cfgp = os.path.join(td, "cb_config.json")
    with open(cfgp, "w", encoding="utf-8") as f:
        json.dump({**good(), "rf": 0.031}, f)
    old_path, old_m = cb.CONFIG_PATH, cb._CONFIG_MTIME
    try:
        cb.CONFIG_PATH, cb._CONFIG_MTIME = cfgp, None
        ck(cb.reload_config_if_changed() is True, "首讀應 reload")
        ck(cb_core.ASSUMPTIONS["rf"] == 0.031, "reload 後 rf 生效")
        ck(cb.reload_config_if_changed() is False, "mtime 沒變不重讀")
        with open(cfgp, "w", encoding="utf-8") as f:
            json.dump({**good(), "rf": 0.042}, f)
        os.utime(cfgp, (os.stat(cfgp).st_atime, os.stat(cfgp).st_mtime + 2))
        ck(cb.reload_config_if_changed() is True and cb_core.ASSUMPTIONS["rf"] == 0.042,
           "mtime 變了 → 新值生效")
    finally:
        cb.CONFIG_PATH, cb._CONFIG_MTIME = old_path, old_m
        cb_core.ASSUMPTIONS.clear()
        cb_core.ASSUMPTIONS.update(copy.deepcopy(ORIG))

# ── tcri_spread 調升 → 債券底/理論價下降(方向驗證,對應 e2e①)──
item = {"conv_price": 100.0, "tcri": 3, "size_yi": 20, "tenor_year": 3,
        "put": {"year": 3, "redeem_price": 100.0}}
a1 = copy.deepcopy(ORIG)
a2 = copy.deepcopy(ORIG)
a2["tcri_spread"][3] = a2["tcri_spread"][3] + 0.01
r1 = cb_core.analyze(item, 100.0, 0.35, a=a1)
r2 = cb_core.analyze(item, 100.0, 0.35, a=a2)
ck(r1["ok"] and r2["ok"], "analyze 兩組假設都要成功")
ck(r2["bond_floor"] < r1["bond_floor"], "利差調升 → 債券底變低")
ck(r2["theoretical"] < r1["theoretical"], "利差調升 → 理論價變低")

# ── mail status 寫讀 + brief 新鮮度行 ────────────────────────────
import datetime
import zoneinfo
with tempfile.TemporaryDirectory() as td:
    sp = os.path.join(td, "mail_ingest_status.json")
    dt = datetime.datetime(2026, 7, 22, 9, 30, tzinfo=zoneinfo.ZoneInfo("Asia/Taipei"))
    cb_mail_ingest._write_status(2, (dt, "選擇權報價表0722"), 15, "event_log:2", path=sp)
    with open(sp, encoding="utf-8") as f:
        st = json.load(f)
    ck(st["new_items"] == 2 and st["latest_mail"]["subject"] == "選擇權報價表0722", "status 寫讀 roundtrip")
    ck(st["latest_mail"]["date"] == "2026-07-22 09:30", "日期轉台北牆鐘格式")
    line = cb_server._mail_freshness_line(sp)
    ck("📬" in line and "選擇權報價表0722" in line and "本輪新入 2 封" in line, f"brief 行內容:{line}")
    cb_mail_ingest._write_status(0, None, 0, path=sp)
    line = cb_server._mail_freshness_line(sp)
    ck("📬" in line and "本輪新入" not in line and "最新" not in line, "無新件/無最新郵件時行要縮")
    ck(cb_server._mail_freshness_line(os.path.join(td, "nope.json")) == "", "檔不存在 → 空字串不炸")
    with open(sp, "w", encoding="utf-8") as f:
        f.write("{broken")
    ck(cb_server._mail_freshness_line(sp) == "", "壞 JSON → 空字串不炸")

# ── _notify_desk 落帳格式(push_notifier/event_alert 契約)────────
with tempfile.TemporaryDirectory() as td:
    lg = os.path.join(td, "data", "event_notifications.jsonl")
    ck(cb_mail_ingest._notify_desk(["主旨A"], lg).startswith("skipped"), "cb-desk 不在 → 降級不炸")
    os.makedirs(os.path.dirname(lg))
    ck(cb_mail_ingest._notify_desk(["主旨A", ""], lg) == "event_log:2", "寫入回報筆數")
    rows = [json.loads(x) for x in open(lg, encoding="utf-8")]
    ck(len(rows) == 2 and rows[0]["signal"] == "主旨A" and rows[1]["signal"] == "新 CB 郵件",
       "signal=主旨,空主旨有佔位")
    ck(all(set(r) >= {"code", "source", "level", "signal", "notified_at"} for r in rows),
       "行格式含 event_alert 契約鍵")
    sys.path.insert(0, os.path.expanduser("~/cb-desk"))
    try:
        from cbdesk import push as desk_push
        msg = desk_push.build_event_message(rows[0])
        ck("主旨A" in msg["title"] and msg["data"]["url"], f"push_notifier 能組訊息:{msg['title']}")
        ck(desk_push.is_fresh(rows[0]["notified_at"], 12 * 3600), "notified_at 過新鮮度濾網")
    except ImportError:
        print("  (cb-desk 不在,跳過跨庫契約 2 檢)")

print(f"OK test_config_api:{n} 檢查全過")
