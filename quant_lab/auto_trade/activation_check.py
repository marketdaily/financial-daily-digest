"""期貨 API 開通自動複檢(一次性,2026-07-28 08:55 winrig cron,跑完 cron 行自清)。
背景:07-27 開戶+測試環境檢核完成,永豐「過檔明天生效」→ 本腳本自動驗收:
  signed=false → 推播「仍未生效」收工(cron 已自清,需人工重排或手動跑)
  signed=true  → 自動跑 test_live_order 掛撤關;過了再跑 fill-close 關(微台,學費~百元)
  結果全部推播到 Delvin 手機。
用法:python3 activation_check.py
"""
import os
import sys
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    from paper_daily import push
    from shioaji_adapter import _load_env
    _load_env()
    import shioaji as sj
    api = sj.Shioaji(simulation=False)
    api.login(api_key=os.environ["SHIOAJI_API_KEY"],
              secret_key=os.environ["SHIOAJI_SECRET_KEY"])
    time.sleep(3)
    acc = api.futopt_account
    signed = bool(getattr(acc, "signed", False))
    try:
        api.logout()
    except Exception:
        pass
    if not signed:
        push("⏳ 期貨API複檢:signed 仍=false,永豐過檔未完成。晚點手動跑 "
             "python3 activation_check.py 或問營業員")
        print("signed=false,收工")
        return

    def run(args):
        r = subprocess.run([sys.executable, os.path.join(HERE, "test_live_order.py")] + args,
                           capture_output=True, text=True, timeout=300, cwd=HERE)
        return r.stdout + r.stderr

    out1 = run(["--yes"])
    ok1 = "掛撤關)通過" in out1
    if not ok1:
        push(f"⚠️ 期貨API已生效但掛撤關失敗,尾段:{out1[-300:]}")
        print(out1)
        return
    out2 = run(["--yes", "--mode", "fill-close"])
    ok2 = "成交關)通過" in out2
    if ok2:
        push("🎉 期貨真單鏈路全通!signed=true+掛撤關+fill-close關(微台)全過,部位歸零。"
             "真錢起跑只剩 paper 裁決閘(魚C 30筆/魚B 10筆)。")
    else:
        push(f"⚠️ 掛撤關過,fill-close 關異常(檢查部位!),尾段:{out2[-300:]}")
    print(out1[-500:], "\n----\n", out2[-500:])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            from paper_daily import push
            push(f"⚠️ activation_check 異常:{type(e).__name__} {e}")
        except Exception:
            pass
        print(f"activation_check 異常:{type(e).__name__} {e}")
