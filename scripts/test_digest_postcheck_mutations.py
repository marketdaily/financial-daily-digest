#!/usr/bin/env python3
"""突變測試:確認 test_digest_postcheck_triage.py 真的咬得住(每個突變都必須讓它變紅)。"""
import shutil, subprocess, sys, tempfile
from pathlib import Path

SRC = Path.home() / "Delvin-agent" / "scripts"
MUTS = [
    ("常態判定失效", "CHRONIC_MIN_HITS = 3", "CHRONIC_MIN_HITS = 99"),
    ("交付閘不延後", '    if not deadline_passed:\n        return "defer"',
                     '    if False:\n        return "defer"'),
    ("壞帳本靜音", 'escalate, why = True, f"帳本{ledger_broken}',
                   'escalate, why = False, f"帳本{ledger_broken}'),
    ("週期提醒失效", "CHRONIC_REMIND_DAYS = 7", "CHRONIC_REMIND_DAYS = 999"),
    ("早晚班切段失效", "        seg = seg[:1 + nxt.start()]", "        pass"),
    ("origin 例外當已交付", "    except Exception:\n        return False\n    finally:",
                            "    except Exception:\n        return True\n    finally:"),
    # 驗證者 2026-08-02 findings 的迴歸是否真的咬得住
    ("F1 cwd 不切到 repo", "        os.chdir(REPO)\n        return bool(origin_fn(edition, date))",
                            "        return bool(origin_fn(edition, date))"),
    ("F2 型別漂移不 fail-closed", 'if not isinstance(r.get("slow"), (int, float)) or isinstance(r.get("slow"), bool):\n                    raise TypeError(f"slow 欄型別漂移:{line[:60]!r}")',
                                   'pass'),
    ("F3 帳本不去重", "                rows[d] = {", "                rows[d + str(len(rows))] = {"),
    ("F3 視窗不依日期排序", "    return [rows[k] for k in sorted(rows)], broken",
                            "    return list(rows.values()), broken"),
    ("F8 CLI 不驗班別", 'if edition not in ("tw", "us"):\n        raise SystemExit',
                        'if False:\n        raise SystemExit'),
]
py = str(Path.home() / "Delvin-agent" / ".venv" / "bin" / "python")
bad = []
for name, a, b in MUTS:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        shutil.copy(SRC / "test_digest_postcheck_triage.py", td)
        s = (SRC / "digest_postcheck.py").read_text(encoding="utf-8")
        if a not in s:
            bad.append(f"{name}: 突變錨點找不到")
            continue
        (td / "digest_postcheck.py").write_text(s.replace(a, b, 1), encoding="utf-8")
        r = subprocess.run([py, str(td / "test_digest_postcheck_triage.py")],
                           capture_output=True, text=True, cwd=td)
        status = "咬到✓" if r.returncode != 0 else "沒咬到✗"
        print(f"[{name}] rc={r.returncode} {status}")
        if r.returncode == 0:
            bad.append(name)
sys.exit(1 if bad else 0)
