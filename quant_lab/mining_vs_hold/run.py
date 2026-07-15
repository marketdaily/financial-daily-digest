import argparse

from model import Machine, MiningParams, simulate, breakeven_elec_price, critical_difficulty_cagr, monte_carlo

MACHINES = {
    "s21": Machine(200, 3500, 3500, "Antminer S21"),
    "s21pro": Machine(234, 3531, 5000, "Antminer S21 Pro"),
    "s19xp": Machine(140, 3010, 1800, "Antminer S19 XP"),
    "s19": Machine(95, 3250, 800, "Antminer S19"),
}


def fmt_usd(x):
    return f"${x:,.0f}"


def report(p, mc_paths):
    r = simulate(p)
    m = p.machine
    net_btc, n0 = r["net_stack"][-1], r["n0_btc"]
    be = breakeven_elec_price(p)
    gstar = critical_difficulty_cagr(p)

    print("=" * 68)
    print("  BITCOIN MINING vs HOLDING  —  quant_lab/mining_vs_hold")
    print("=" * 68)
    print(f"  Machine        : {m.name}  ({m.hashrate_th:.0f} TH/s, {m.power_w:.0f} W, {m.j_per_th:.1f} J/TH)")
    print(f"  Capital        : {fmt_usd(p.capital_usd)}  ->  {p.n_machines} units, {p.fleet_hashrate_th:,.0f} TH/s")
    print(f"  Electricity    : ${p.elec_price:.3f}/kWh")
    print(f"  BTC price start: {fmt_usd(p.btc_price_0)}   (assumed CAGR {p.price_cagr:+.0%})")
    print(f"  Net hashrate   : {p.net_hashrate_0_th/1e6:.0f} EH/s   (assumed difficulty CAGR {p.difficulty_cagr:+.0%})")
    print(f"  Horizon        : {p.days} days ({p.days/365:.1f} yr),  uptime {p.uptime:.0%},  residual {p.residual_frac:.0%}")
    print(f"  Curtailment    : {'ON (idle when unprofitable)' if p.curtail else 'OFF (always-on)'}")
    print("-" * 68)

    print("  [1] BTC-DENOMINATED  (price-path-independent verdict)")
    print(f"      Buy & hold gets you        : {n0:.4f} BTC  (fixed)")
    print(f"      Mining nets (after elec)   : {net_btc:.4f} BTC")
    edge = (net_btc / n0 - 1.0) * 100
    verdict = "MINING WINS" if net_btc > n0 else "HOLDING WINS"
    print(f"      -> {verdict}  ({edge:+.1f}% BTC stack)")
    print("-" * 68)

    print("  [2] USD TERMINAL VALUE  (deterministic scenario)")
    print(f"      Hold  : {fmt_usd(r['hold_value'][-1])}")
    print(f"      Mine (hodl coins) : {fmt_usd(r['mine_value_hodl'][-1])}")
    print(f"      Mine (sell daily) : {fmt_usd(r['mine_value_sell'][-1])}")
    print("-" * 68)

    print("  [3] BREAKEVEN / TIPPING POINTS")
    print(f"      Breakeven electricity price (day 0): ${be:.3f}/kWh")
    print(f"      (you pay ${p.elec_price:.3f} -> margin { 'POSITIVE' if p.elec_price < be else 'NEGATIVE'})")
    if gstar is None:
        print("      Critical difficulty CAGR: mining wins across full range tested")
    else:
        print(f"      Critical difficulty CAGR : {gstar:+.1%}  (above this, HOLDING wins)")
        print(f"      (you assumed {p.difficulty_cagr:+.0%})")
    print("-" * 68)

    if mc_paths > 0:
        mc = monte_carlo(p, n_paths=mc_paths)
        print(f"  [4] MONTE CARLO  ({mc_paths} paths, GBM price+difficulty)")
        print(f"      P(mining > holding)  : {mc['p_mine_wins']:.1%}")
        print(f"      Median mine terminal : {fmt_usd(mc['mine_median'])}")
        print(f"      Median hold terminal : {fmt_usd(mc['hold_median'])}")
        print(f"      Median edge (mine-hold): {fmt_usd(mc['diff_median'])}")
        print(f"      5th–95th pct edge    : {fmt_usd(mc['diff_p05'])}  ..  {fmt_usd(mc['diff_p95'])}")
        print("-" * 68)
    print()


def build_params(a):
    return MiningParams(
        capital_usd=a.capital,
        machine=MACHINES[a.machine],
        elec_price=a.elec,
        btc_price_0=a.price,
        price_cagr=a.price_cagr,
        price_vol=a.price_vol,
        net_hashrate_0_eh=a.net_hashrate,
        difficulty_cagr=a.diff_cagr,
        difficulty_vol=a.diff_vol,
        uptime=a.uptime,
        days=a.days,
        residual_frac=a.residual,
        curtail=not a.no_curtail,
    )


def main():
    ap = argparse.ArgumentParser(description="Bitcoin mining vs holding model")
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--machine", choices=MACHINES.keys(), default="s21")
    ap.add_argument("--elec", type=float, default=0.05, help="$/kWh")
    ap.add_argument("--price", type=float, default=100_000, help="BTC price start")
    ap.add_argument("--price-cagr", type=float, default=0.0)
    ap.add_argument("--price-vol", type=float, default=0.60)
    ap.add_argument("--net-hashrate", type=float, default=850, help="EH/s")
    ap.add_argument("--diff-cagr", type=float, default=0.25)
    ap.add_argument("--diff-vol", type=float, default=0.15)
    ap.add_argument("--uptime", type=float, default=0.97)
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--residual", type=float, default=0.10)
    ap.add_argument("--no-curtail", action="store_true", help="force machines to run even at a loss")
    ap.add_argument("--mc", type=int, default=5000, help="Monte Carlo paths (0 to skip)")
    a = ap.parse_args()
    report(build_params(a), a.mc)


if __name__ == "__main__":
    main()
