"""資金管理 demo:用本週真實回測損益餵 sizing,證明「驗證與資金管理是同一套數學」。
- SuperTrend(lockbox 負)→ Kelly 應給 0 口
- 裸賣跨式(lockbox 小正但肥尾)→ 應被 worst-case 風險閘壓到極小
- 若有人硬凹大口數 → ruin_check 顯示破產機率
用法:python3 sizing_demo.py(權益假設 NT$300 萬=用戶實際資金)
"""
import tx_data
import txo_data
from supertrend_wf import bt as st_bt
from txo_vol_wf import simulate as straddle_sim, ewma_vol_by_date, POINT as TXO_POINT
from engine import split_lockbox
from sizing import kelly_contracts, ruin_check, DrawdownBrake

EQUITY = 3_000_000
TX_POINT = 200


def show(name, pnls_ntd):
    n, why = kelly_contracts(pnls_ntd, EQUITY)
    print(f"\n【{name}】{len(pnls_ntd)}筆,總損益 {sum(pnls_ntd):+,.0f} 元/口")
    print(f"  給口數:{n} —— {why}")
    if n > 0:
        p_ruin = ruin_check(pnls_ntd, n, EQUITY)
        print(f"  壓力測試(bootstrap 250筆):P(回撤>50%) = {p_ruin:.1%}")
        p_ruin_3x = ruin_check(pnls_ntd, n * 4, EQUITY)
        print(f"  若硬凹 4 倍口數({n*4}口):P(回撤>50%) = {p_ruin_3x:.1%} ← 同一個edge,倉位錯=破產")


def main():
    print(f"權益假設:NT${EQUITY:,}(全部口數/風險以此計算)")

    rows = tx_data.load("2020-01-01")
    _, oos, lockbox = split_lockbox(rows)
    st_pnls = [x * TX_POINT for x in st_bt(oos[-60:] + lockbox, 7, 1.5)]
    show("SuperTrend 日線(lockbox,已判無edge)", st_pnls)

    days = txo_data.load("2023-01-01")
    vols = ewma_vol_by_date()
    dates = sorted(days)
    _, oos_d, lb_d = split_lockbox(dates)
    sd_pnls = [x * TXO_POINT for x in straddle_sim(oos_d[-15:] + lb_d, days, vols, 0.03, 0.01, 5, 1.5)]
    show("裸賣跨式(lockbox,小正但肥尾)", sd_pnls)

    print("\n【回撤煞車行為(所有策略上線都掛這道)】")
    brake = DrawdownBrake(soft=0.10, hard=0.20)
    for eq, tag in [(3_000_000, "起始"), (3_150_000, "+5%"), (2_900_000, "回撤8%"),
                    (2_800_000, "回撤11%→減半"), (2_500_000, "回撤21%→全停"),
                    (3_200_000, "反彈也不自動重啟")]:
        s, dd = brake.scale(eq)
        print(f"  權益 {eq:,}({tag}):口數係數 x{s}(回撤 {dd:.0%})")

    print("\n結論:驗證決定「能不能下」(μ≤0→0口),資金管理決定「下多少」(Kelly/風險閘)、")
    print("      「什麼時候必須停」(回撤煞車)。三道閘已可直接掛進 paper/live。")


if __name__ == "__main__":
    main()
