"""回歸測試:digest_selfheal_detect —— 只在『檢查造成』的硬錯備援觸發自癒,
排除 provider 429/503 infra(改碼救不了)。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest_selfheal_detect as D  # noqa: E402

OWNER = "delvin.12345678@gmail.com"
os.environ["MARKETDAILY_OWNER_EMAIL"] = OWNER


def _fixture(tmp, fallbacks, log_lines):
    os.makedirs(os.path.join(tmp, "output"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    json.dump({"deterministic_fallbacks": fallbacks},
              open(os.path.join(tmp, "output", "digest_audit_2026-07-24.json"), "w"))
    open(os.path.join(tmp, "logs", "fallback_2026-07-24.log"), "w").write("\n".join(log_lines))
    D.REPO = tmp


def run():
    with tempfile.TemporaryDirectory() as tmp:
        # 1) 老闆因 audit HIGH 掉備援 → 觸發
        _fixture(tmp, [OWNER],
                 [f"   ⚠️ {OWNER} HIGH audit fail(undefined_css_class),retry 一次",
                  f"   🛡️ retry 仍 HIGH fail(undefined_css_class) → 切 deterministic fallback"])
        r = D.detect("2026-07-24", "tw")
        assert r["trigger"] and r["owner_hit"] and "undefined_css_class" in r["checks"], f"[FAIL] 老闆硬錯應觸發: {r}"

        # 2) 老闆因 provider 429 掉備援(log 無 HIGH audit fail 行)→ 不觸發(改碼救不了)
        _fixture(tmp, [OWNER],
                 ["   🛡️ retry 異常 → deterministic fallback (所有 LLM provider 都失敗:429 配額耗盡)"])
        r = D.detect("2026-07-24", "tw")
        assert not r["trigger"], f"[FAIL] 純 429 infra 不該觸發: {r}"

        # 3) 系統性:同一 check ≥3 位(非老闆)→ 觸發
        vics = ["a@x.com", "b@x.com", "c@x.com"]
        _fixture(tmp, vics,
                 [f"   ⚠️ {e} HIGH audit fail(signal_reason_shallow),retry 一次" for e in vics])
        r = D.detect("2026-07-24", "tw")
        assert r["trigger"] and not r["owner_hit"] and r["checks"] == ["signal_reason_shallow"], f"[FAIL] 系統性≥3 應觸發: {r}"

        # 4) 只 2 位非老闆同 check → 不觸發(未達系統性門檻)
        _fixture(tmp, vics[:2],
                 [f"   ⚠️ {e} HIGH audit fail(signal_reason_shallow),retry 一次" for e in vics[:2]])
        r = D.detect("2026-07-24", "tw")
        assert not r["trigger"], f"[FAIL] 僅 2 位不該觸發: {r}"

        # 5) 完全 clean(無備援)→ 不觸發
        _fixture(tmp, [], [])
        r = D.detect("2026-07-24", "tw")
        assert not r["trigger"] and "clean" in r["reason"], f"[FAIL] clean 不該觸發: {r}"

    print("✅ digest_selfheal_detect 回歸測試全過(5 組)")


if __name__ == "__main__":
    run()
