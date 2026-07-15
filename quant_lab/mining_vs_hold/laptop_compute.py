import argparse

HOURS_YR = 8760.0
DAYS_YR = 365.0


class Assumptions:
    def __init__(self, **kw):
        self.n_laptops = kw.get("n_laptops", 100)
        self.elec_price = kw.get("elec_price", 0.10)          # $/kWh
        self.wear_per_yr = kw.get("wear_per_yr", 60.0)        # $/laptop/yr when run 24/7

        # --- GPU rental (Vast.ai / Salad style) ---
        self.rent_rate = kw.get("rent_rate", 0.06)           # $/hr realized, after platform cut
        self.rent_util = kw.get("rent_util", 0.40)           # fraction of time actually rented
        self.rent_power_on = kw.get("rent_power_on", 160.0)  # W while serving a job
        self.rent_power_idle = kw.get("rent_power_idle", 35.0)

        # --- Monero (RandomX, CPU) ---
        self.xmr_hs = kw.get("xmr_hs", 2000.0)               # H/s per laptop CPU
        self.xmr_net_hs = kw.get("xmr_net_hs", 5.5e9)        # network hashrate H/s
        self.xmr_reward = kw.get("xmr_reward", 0.6)          # XMR per block (tail emission)
        self.xmr_blocks_day = kw.get("xmr_blocks_day", 720)  # 2-min blocks
        self.xmr_price = kw.get("xmr_price", 160.0)
        self.xmr_power = kw.get("xmr_power", 65.0)           # W CPU-only load

        # --- Profit-switching / multi-mining (NiceHash style) ---
        self.nh_gross_day = kw.get("nh_gross_day", 0.30)     # $/day/laptop realized, auto-switch best algo
        self.nh_power = kw.get("nh_power", 150.0)            # W GPU load

        # --- Bitcoin (SHA-256d, GPU) ---
        self.btc_hs = kw.get("btc_hs", 1e9)                  # H/s per laptop GPU (generous)
        self.btc_net_hs = kw.get("btc_net_hs", 8.5e20)       # 850 EH/s
        self.btc_reward = kw.get("btc_reward", 3.1875)       # subsidy + ~2% fees
        self.btc_blocks_day = kw.get("btc_blocks_day", 144)
        self.btc_price = kw.get("btc_price", 100_000.0)
        self.btc_power = kw.get("btc_power", 150.0)


def elec_cost_yr(a, avg_watts):
    return a.n_laptops * (avg_watts / 1000.0) * HOURS_YR * a.elec_price


def scenario_rent(a):
    rev = a.n_laptops * a.rent_rate * HOURS_YR * a.rent_util
    avg_w = a.rent_util * a.rent_power_on + (1 - a.rent_util) * a.rent_power_idle
    elec = elec_cost_yr(a, avg_w)
    wear = a.n_laptops * a.wear_per_yr
    return {"name": "Rent GPU compute", "rev": rev, "elec": elec, "wear": wear,
            "net": rev - elec - wear, "note": f"util {a.rent_util:.0%} @ ${a.rent_rate:.2f}/hr"}


def _pow_mining(a, hs_per, net_hs, reward, blocks_day, price, power):
    share = (a.n_laptops * hs_per) / net_hs
    coins_day = share * blocks_day * reward
    rev = coins_day * price * DAYS_YR
    elec = elec_cost_yr(a, power)
    wear = a.n_laptops * a.wear_per_yr
    return rev, elec, wear, coins_day


def scenario_monero(a):
    rev, elec, wear, cd = _pow_mining(a, a.xmr_hs, a.xmr_net_hs, a.xmr_reward,
                                      a.xmr_blocks_day, a.xmr_price, a.xmr_power)
    return {"name": "Mine Monero (CPU)", "rev": rev, "elec": elec, "wear": wear,
            "net": rev - elec - wear, "note": f"{cd*365:.3f} XMR/yr @ ${a.xmr_price:.0f}"}


def scenario_bitcoin(a):
    rev, elec, wear, cd = _pow_mining(a, a.btc_hs, a.btc_net_hs, a.btc_reward,
                                      a.btc_blocks_day, a.btc_price, a.btc_power)
    return {"name": "Mine Bitcoin (GPU)", "rev": rev, "elec": elec, "wear": wear,
            "net": rev - elec - wear, "note": f"{cd*365:.2e} BTC/yr"}


def scenario_multimine(a):
    rev = a.n_laptops * a.nh_gross_day * DAYS_YR
    elec = elec_cost_yr(a, a.nh_power)
    wear = a.n_laptops * a.wear_per_yr
    return {"name": "Multi-mine (NiceHash)", "rev": rev, "elec": elec, "wear": wear,
            "net": rev - elec - wear, "note": f"${a.nh_gross_day:.2f}/day/laptop auto-switch"}


def scenario_nothing(a):
    return {"name": "Do nothing", "rev": 0.0, "elec": 0.0, "wear": 0.0,
            "net": 0.0, "note": "hardware preserved, $0 risk"}


def breakeven_elec(s, a, avg_watts):
    kwh_yr = a.n_laptops * (avg_watts / 1000.0) * HOURS_YR
    return (s["rev"] - s["wear"]) / kwh_yr if kwh_yr > 0 else float("inf")


def report(a):
    rent = scenario_rent(a)
    multi = scenario_multimine(a)
    xmr = scenario_monero(a)
    btc = scenario_bitcoin(a)
    nothing = scenario_nothing(a)
    rows = sorted([rent, multi, xmr, btc, nothing], key=lambda s: -s["net"])

    print("=" * 74)
    print(f"  {a.n_laptops} LAPTOPS — WHAT TO DO WITH THEM   (electricity ${a.elec_price:.3f}/kWh)")
    print("=" * 74)
    print(f"  {'Strategy':<20}{'Revenue':>12}{'Elec':>11}{'Wear':>9}{'NET/yr':>12}")
    print("  " + "-" * 62)
    for s in rows:
        print(f"  {s['name']:<20}{'$'+format(s['rev'],',.0f'):>12}"
              f"{'-$'+format(s['elec'],',.0f'):>11}{'-$'+format(s['wear'],',.0f'):>9}"
              f"{('$'+format(s['net'],',.0f')) if s['net']>=0 else ('-$'+format(-s['net'],',.0f')):>12}")
    print("  " + "-" * 62)
    print(f"  Winner: {rows[0]['name']}  (net ${rows[0]['net']:,.0f}/yr)")
    print()
    print("  Notes / assumptions:")
    for s in [rent, multi, xmr, btc]:
        print(f"    - {s['name']:<20}: {s['note']}")
    avg_w = a.rent_util * a.rent_power_on + (1 - a.rent_util) * a.rent_power_idle
    print(f"    - Rent breakeven elec : ${breakeven_elec(rent, a, avg_w):.3f}/kWh")
    print(f"    - Monero breakeven elec: ${breakeven_elec(xmr, a, a.xmr_power):.3f}/kWh")
    print("  ALL rental/coin figures are demand- & price-dependent — tune the flags.")
    print("=" * 74)


def main():
    ap = argparse.ArgumentParser(description="100 laptops: rent vs Monero vs BTC vs nothing")
    ap.add_argument("--laptops", type=int, default=100)
    ap.add_argument("--elec", type=float, default=0.10)
    ap.add_argument("--rent-rate", type=float, default=0.06, help="$/hr realized after platform cut")
    ap.add_argument("--rent-util", type=float, default=0.40)
    ap.add_argument("--xmr-price", type=float, default=160.0)
    ap.add_argument("--btc-price", type=float, default=100_000.0)
    ap.add_argument("--wear", type=float, default=60.0, help="$/laptop/yr hardware wear when run 24/7")
    a = ap.parse_args()
    report(Assumptions(n_laptops=a.laptops, elec_price=a.elec, rent_rate=a.rent_rate,
                       rent_util=a.rent_util, xmr_price=a.xmr_price, btc_price=a.btc_price,
                       wear_per_yr=a.wear))


if __name__ == "__main__":
    main()
