import argparse

from model import Machine, MiningParams, simulate

# name: (hashrate_TH, power_W, approx_new_price_USD)
CATALOG = [
    Machine(473, 5676, 9000, "Antminer S21 XP Hydro"),
    Machine(270, 3645, 6000, "Antminer S21 XP"),
    Machine(298, 5513, 5200, "Whatsminer M66S"),
    Machine(234, 3510, 4700, "Antminer S21 Pro"),
    Machine(200, 3500, 3200, "Antminer S21"),
    Machine(141, 3010, 1700, "Antminer S19 XP"),
    Machine(120, 2760, 1200, "Antminer S19k Pro"),
    Machine(100, 3050, 750, "Antminer S19j Pro (used)"),
]


def evaluate(m, elec_price, btc_price, diff_cagr, days):
    p = MiningParams(capital_usd=m.price_usd, machine=m, elec_price=elec_price,
                     btc_price_0=btc_price, price_cagr=0.0, difficulty_cagr=diff_cagr,
                     days=days, curtail=True)
    r = simulate(p)
    day0_net = r["minted"][0] * btc_price - r["elec_daily"][0]
    mined_btc = r["net_stack"][-1]
    hold_btc = r["n0_btc"]
    payback = m.price_usd / day0_net if day0_net > 0 else float("inf")
    return {
        "name": m.name, "th": m.hashrate_th, "jth": m.j_per_th, "price": m.price_usd,
        "day0_net": day0_net, "payback": payback, "mined_btc": mined_btc,
        "hold_btc": hold_btc, "edge": mined_btc - hold_btc,
    }


def report(elec_price, btc_price, diff_cagr, days, label):
    rows = [evaluate(m, elec_price, btc_price, diff_cagr, days) for m in CATALOG]
    rows.sort(key=lambda x: -x["edge"])
    print("=" * 88)
    print(f"  機種排名 @ {label}  (電價 ${elec_price:.3f}/kWh, BTC ${btc_price:,.0f}, 難度+{diff_cagr:.0%}/yr, {days/365:.0f}yr)")
    print("=" * 88)
    print(f"  {'機種':<26}{'TH/s':>7}{'J/TH':>7}{'機價':>8}{'淨/天':>9}{'回本天':>8}{'挖vs買幣':>12}")
    print("  " + "-" * 82)
    for x in rows:
        pb = "永不" if x["payback"] == float("inf") else f"{x['payback']:.0f}"
        edge = f"{x['edge']:+.3f}"
        star = "  ✅" if x["edge"] > 0 else "  ❌"
        print(f"  {x['name']:<24}{x['th']:>7.0f}{x['jth']:>7.1f}{'$'+format(x['price'],',.0f'):>8}"
              f"{'$'+format(x['day0_net'],',.2f'):>10}{pb:>8}{edge:>10} BTC{star}")
    print("  " + "-" * 82)
    best = rows[0]
    if best["edge"] > 0:
        print(f"  最佳: {best['name']} — {days/365:.0f}年淨挖 {best['mined_btc']:.3f} BTC vs 直接買 {best['hold_btc']:.3f} BTC")
    else:
        print(f"  ⚠️ 此電價下【沒有任何機種】贏過直接買 BTC — 最不虧的是 {best['name']}")
    print()


def main():
    ap = argparse.ArgumentParser(description="Best ASIC for your electricity price")
    ap.add_argument("--elec", type=float, default=0.10)
    ap.add_argument("--btc", type=float, default=100_000)
    ap.add_argument("--diff-cagr", type=float, default=0.25)
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--label", default="custom")
    a = ap.parse_args()
    report(a.elec, a.btc, a.diff_cagr, a.days, a.label)


if __name__ == "__main__":
    main()
