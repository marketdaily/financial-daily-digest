# VERIFIER REPORT
TASK: check-signed-deadman-desktop-fallback-20260806
DATE: 2026-08-06
VERDICT: UNSOUND
FINDINGS: 2

## F1 [CRITICAL] Desktop-toast fallback is dead on arrival in production — the exact scenario open #67 exists to fix still fails silently
- symptom: `_desktop_fallback()` in `quote_bridge/check_signed.py:293-303` invokes the fallback notifier as `subprocess.run(["python3", NOTIFY_ADMIN, ...])` — a bare `python3` resolved via `$PATH`, not an explicit interpreter. That resolves to `/usr/bin/python3` (no venv), which does not have `python-dotenv` installed. `notify_admin.py` does `from dotenv import dotenv_values` at module import time (line 10), so the subprocess crashes with `ModuleNotFoundError` before it even attempts web_push or desktop_toast, and returns exit code 1. `_desktop_fallback` only checks `r.returncode == 0`, so it returns `False`. Net effect: when webpush is genuinely dead (the open #67 scenario), `_try_push()` still returns `(False, why)` — the detector is exactly as mute as before the fix, just with more code around it.
- evidence:
  - Ran the actual code path (not the test harness, which stubs `_desktop_fallback` — see F2) directly against the real `check_signed.py` and real `~/.marketdaily-fallback/notify_admin.py`:
    ```
    $ cd /home/userdelvin/Delvin-agent/quote_bridge && python3 -c "
    import check_signed as m
    print(m._desktop_fallback('CRITICAL VERIFIER TEST'))
    "
    desktop_fallback returned: False
    ```
  - Reproducing the exact subprocess invocation manually:
    ```
    $ python3 -c "
    import subprocess
    r = subprocess.run(['python3', '/home/userdelvin/.marketdaily-fallback/notify_admin.py', '--help'],
                        timeout=20, capture_output=True, text=True)
    print('rc=', r.returncode); print('stderr=', r.stderr)
    "
    rc= 1
    stderr= Traceback (most recent call last):
      File "/home/userdelvin/.marketdaily-fallback/notify_admin.py", line 10, in <module>
        from dotenv import dotenv_values
    ModuleNotFoundError: No module named 'dotenv'
    ```
  - Confirmed no python on this box's bare `python3` PATH resolution has dotenv: `/usr/bin/python3 -c "import dotenv"` → `ModuleNotFoundError`. Checked every venv under `~/.venvs/*` (`cb-analyzer`, `imgforge`, `imggen`, `ruff`, `shioaji-bridge` — the one that actually runs `check_signed.py` per crontab `23 8-17 * * 1-5 flock ... /home/userdelvin/.venvs/shioaji-bridge/bin/python .../check_signed.py`) — **none** have `dotenv` installed. Only `/home/userdelvin/Delvin-agent/.venv/bin/python` has it (verified: `import dotenv` → OK, `dotenv/__init__.py` present).
  - This exact failure mode is already a **documented, known trap in this same repo, discovered the day before this task**: `/home/userdelvin/.marketdaily-fallback/mingshu_social_runner.sh:19-24` reads `# 告警要用 Delvin-agent 的 venv —— fortune-ai 的 venv 沒有 dotenv, 用它跑 notify_admin.py 會 ModuleNotFoundError 當場死掉:告警管道自己是啞的, 而失敗時唯一會說話的就是它。2026-08-05 自測時抓到。` (2026-08-05, one day before this task's 2026-08-06 date). Every one of the ~25 other call sites across `.marketdaily-fallback/*.sh` and `Delvin-agent/scripts/*` that invoke `notify_admin.py` do so with an explicit `PY="$REPO/.venv/bin/python"` (e.g. `site_scan_runner.sh:13`, `run.sh:12`, `council_check.sh:12`, `digest_postcheck_runner.sh:17`, etc.) — `check_signed.py` is the only caller using a bare `python3`.
  - The unit/mutation test suite never exercises this: `harness()` in `test_check_signed.py:112-126` unconditionally monkeypatches `m._desktop_fallback` to a Python stub (`m.desktop_fallbacks.append(msg); return m.desktop_ok`), so none of the 35/35 "caught" mutations and none of cases 12c-12g touch the real `subprocess.run(["python3", NOTIFY_ADMIN, ...])` line at all. All-green test output and 35/35 mutation coverage are real, but they only validate the *control-flow contract* of `_try_push`/`_desktop_fallback` against a fake, not that the real subprocess call succeeds in this environment.
- fix: don't invoke a bare `"python3"`. Resolve an interpreter that actually has `notify_admin.py`'s dependencies, mirroring the pattern already used everywhere else in the repo, e.g.:
  ```python
  _NOTIFY_PY = os.path.expanduser("~/Delvin-agent/.venv/bin/python")
  if not os.path.exists(_NOTIFY_PY):
      _NOTIFY_PY = "python3"
  ...
  subprocess.run([_NOTIFY_PY, NOTIFY_ADMIN, ...], ...)
  ```
  Then add a real (not stubbed) end-to-end test that shells out to the actual `notify_admin.py` (can still stub `web_push`/`desktop_toast` *inside* notify_admin.py via monkeypatch-through-env or a `--dry-run` mode) to catch import/dependency drift like this automatically, since it has already bitten this codebase once (2026-08-05) and now bites it again in a second call site one day later.

## F2 [MEDIUM] `_desktop_fallback` silently discards the subprocess's stderr, hiding the actual failure reason from `_try_push`'s "why" and from the cron log
- symptom: `_desktop_fallback` (check_signed.py:293-303) calls `subprocess.run(..., capture_output=True, text=True)` but never reads `r.stdout`/`r.stderr` — on failure it just `return False`. In `_try_push` (line 306-329), when both webpush and desktop fail, the returned `why` is only the *webpush* failure reason (e.g. "MARKETDAILY_ALERT_TOKEN 缺席"); the desktop-toast failure reason (e.g. the `ModuleNotFoundError` traceback from F1, or a WSL-interop `powershell.exe rc=1` per the author's own acknowledged open risk) is thrown away entirely. `main()`'s only diagnostic output in this path is `print("push failed:", why)` — which will forever say "MARKETDAILY_ALERT_TOKEN 缺席" or similar, never revealing that the fallback channel itself is broken. This is exactly the kind of failure that turned open #67 into a 3-week-silent Mac-guard-token incident before (per the code's own comment at line 88-89) — a second silent channel failing for an undiagnosed reason is a regression of the same pattern this task is supposed to close.
- evidence: `check_signed.py:293-303` — `_desktop_fallback` body has no `print`/log of `r.stdout`/`r.stderr` on the `r.returncode != 0` or exception branches; confirmed by reading the function body directly (no other reference to `r.stdout`/`r.stderr` anywhere in the file via `grep -n "r\.std" quote_bridge/check_signed.py` → no matches).
- fix: on failure, log `r.stderr`/`r.stdout` (truncated) to stdout (cron log) at minimum, e.g. `print("desktop fallback failed:", r.returncode, (r.stderr or r.stdout)[:300])`, and consider folding a short summary into the `why` string returned by `_try_push` so a human reading a *successfully delivered* "watch file corrupted" alert can also see "and by the way your backup channel is broken" without needing to grep the cron log separately.

## Notes
- Everything else claimed by the author checks out under real execution: `python3 quote_bridge/test_check_signed.py` → all cases pass including the real-`shioaji.Account` contract test (15c/15d/15e all pass, not skipped — `~/.venvs/shioaji-bridge/bin/python` resolved and has `shioaji` importable). `python3 quote_bridge/test_check_signed.py --mutate` → 35/35 mutations caught, none anchor-lost.
- Corrupted-watch-file / dedup-on-rerun requirements from the task brief: independently re-verified outside the test harness (not just trusting the suite) — duplicate JSON keys (`json.loads` keeps last value, standard/expected), and a genuinely truncated/mid-write JSON file (`{"first_seen": "2026-07-30", "announced": ["stock"` with no closing brace) both handled correctly (`_load_watch()` returns `({}, ['<JSON 解析失敗>'])`, which downstream triggers the corrupt-watch alert path rather than crashing). Re-running `main()` twice for dedup is also covered in-suite (cases 3b, 5h, 7d, 26b) and I did not find a gap beyond F1/F2.
- UNVERIFIED (cannot test in this environment): whether `notify_admin.py`'s `desktop_toast()` actually produces a visible Windows toast via the WSL→PowerShell interop path, even once F1 is fixed to use the correct interpreter — this needs a real winrig desktop session and would have side effects (a real toast/push to the admin), which I deliberately did not trigger. The author's own stated caveat (WSL interop failing during a *simultaneous* outage) is a separate, already-acknowledged risk and is not what F1 is about — F1 is a deterministic, always-reproducible failure that fires on every invocation regardless of WSL/interop health, because it never gets past `import dotenv`.
- The `.env` token/`MD_REPO` plumbing inside `notify_admin.py` was not exercised by my tests (I did not want to trigger a real production admin push during verification) — this is consistent with the author's own claims and not something I flagged as broken.
