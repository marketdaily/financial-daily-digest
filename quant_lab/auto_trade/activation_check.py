"""期貨 API 開通自動複檢(winrig cron 平日 08:56,全關通過即自我移除 cron)。
歷程:07-27 開戶+測試環境檢核;07-28 signed=true 生效但 99Q9 可委託金額不足(未入金)。
現行為:每天開盤後驗 signed+保證金——
  未入金(可用<2萬) → 推播提醒入金,明天再試
  入金到位 → 自動跑掛撤關+fill-close 關(微台,學費~百元),全過推播 🎉 並移除 cron
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
    avail = None
    try:
        m = api.margin(acc)
        avail = float(getattr(m, "available_margin", 0) or 0)
    except Exception as e:
        print(f"margin 查詢失敗:{e}")
    try:
        api.logout()
    except Exception:
        pass
    if not signed:
        push("⏳ 期貨API複檢:signed 仍=false,永豐過檔未完成,明天自動再試")
        print("signed=false,收工")
        return
    if avail is not None and avail < 20_000:
        push(f"💰 期貨API已生效,等入金:可用保證金 {avail:,.0f} 元(體檢需≥2萬;"
             f"魚C 起跑 2-3 口小台建議 30-50 萬)。入金後隔天早上自動跑完體檢")
        print(f"可用保證金 {avail:,.0f} 不足,收工")
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
        os.system("crontab -l | grep -v activation_check | crontab -")
        print("全關通過,cron 已自我移除")
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
