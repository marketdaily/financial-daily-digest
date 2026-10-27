#!/usr/bin/env python3
"""迴歸:manifest 晚於語音產線落地時,個人音檔不得整班靜默消失(2026-10-27 慢性失分)。

事故形狀:runner 07:20 跑完公版 TTS→personal.py 找不到 manifest 回 0、拿走每日鎖;
main.py 07:22 才寫 manifest ⇒ 24/24 支個人音檔 CDN 驗不到,連續 5 班。"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "audio_brief"))

import audio_brief.manifest as man  # noqa: E402
import personal  # noqa: E402

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


class Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))


with tempfile.TemporaryDirectory() as td:
    out = Path(td)
    man.OUT = out
    os.environ.pop("MD_FAILOVER", None)
    D, ED = "2026-10-27", "tw"

    spy = Spy()
    r = man.kick_personal_if_missed(D, ED, popen=spy)
    check(r == "skip:runner_pending" and not spy.calls, f"runner 還沒跑不該補跑: {r}")

    (out / f"audio_{D}_{ED}.json").write_text("{}")
    spy = Spy()
    r = man.kick_personal_if_missed(D, ED, popen=spy)
    check(r.startswith("kicked:") and len(spy.calls) == 1,
          f"公版已出、個人未出(=事故情境)必須補跑: {r}")
    if spy.calls:
        argv, kw = spy.calls[0]
        check(argv[-3:] == [str(man.HERE / "personal.py"), D, ED], f"補跑參數錯: {argv}")
        check(kw.get("start_new_session") is True, "補跑必須脫離 main.py(不擋寄信)")

    os.environ["MD_FAILOVER"] = "1"
    spy = Spy()
    check(man.kick_personal_if_missed(D, ED, popen=spy) == "skip:failover" and not spy.calls,
          "雲端備援不該補跑")
    os.environ.pop("MD_FAILOVER")

    (out / f"personal_{D}_{ED}.json").write_text("{}")
    spy = Spy()
    check(man.kick_personal_if_missed(D, ED, popen=spy) == "skip:already_done" and not spy.calls,
          "個人音檔已產出不該重跑")

    personal.OUT = out
    lk = personal._acquire_lock(D, ED)
    check(lk is not None, "第一支應拿到鎖")
    check(personal._acquire_lock(D, ED) is None, "同班第二支不得同時跑")
    old = lk.stat().st_mtime - personal.PERSONAL_LOCK_STALE_S - 10
    os.utime(lk, (old, old))
    lk2 = personal._acquire_lock(D, ED)
    check(lk2 is not None, "過期鎖(前一支被砍)要能回收")
    lk2.unlink()

    (out / f"manifest_{D}_{ED}.json").write_text('{"entries": []}')
    personal.VB_OUT = out
    (out / f"brief_{D}_{ED}.json").write_text("{}")
    check(personal.process(D, ED) == 0, "空 manifest 照舊回 0")
    check(not (out / f"personal_{D}_{ED}.lock").exists(), "跑完必須釋放鎖")

main_src = (REPO / "main.py").read_text(encoding="utf-8")
i = main_src.find("write_manifest(audio_entries")
check(i > 0 and "kick_personal_if_missed(data" in main_src[i:i + 600],
      "main.py 寫 manifest 後必須接補跑判定")

if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("OK test_personal_audio_late_manifest")
