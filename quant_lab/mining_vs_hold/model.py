import copy

import numpy as np

BLOCKS_PER_DAY = 144.0


class Machine:
    def __init__(self, hashrate_th, power_w, price_usd, name="ASIC"):
        self.hashrate_th = float(hashrate_th)
        self.power_w = float(power_w)
        self.price_usd = float(price_usd)
        self.name = name

    @property
    def j_per_th(self):
        return self.power_w / self.hashrate_th

    @property
    def power_kw(self):
        return self.power_w / 1000.0


class MiningParams:
    def __init__(
        self,
        capital_usd=100_000.0,
        machine=None,
        elec_price=0.05,
        btc_price_0=100_000.0,
        price_cagr=0.0,
        price_vol=0.60,
        net_hashrate_0_eh=850.0,
        difficulty_cagr=0.25,
        difficulty_vol=0.15,
        subsidy=3.125,
        fees_frac=0.02,
        pool_fee=0.01,
        uptime=0.97,
        days=1095,
        residual_frac=0.10,
        risk_free=0.04,
        curtail=True,
    ):
        self.capital_usd = float(capital_usd)
        self.machine = machine or Machine(200, 3500, 3500, "Antminer S21")
        self.elec_price = float(elec_price)
        self.btc_price_0 = float(btc_price_0)
        self.price_cagr = float(price_cagr)
        self.price_vol = float(price_vol)
        self.net_hashrate_0_th = float(net_hashrate_0_eh) * 1e6
        self.difficulty_cagr = float(difficulty_cagr)
        self.difficulty_vol = float(difficulty_vol)
        self.subsidy = float(subsidy)
        self.fees_frac = float(fees_frac)
        self.pool_fee = float(pool_fee)
        self.uptime = float(uptime)
        self.days = int(days)
        self.residual_frac = float(residual_frac)
        self.risk_free = float(risk_free)
        self.curtail = bool(curtail)

    @property
    def n_machines(self):
        return int(self.capital_usd // self.machine.price_usd)

    @property
    def fleet_hashrate_th(self):
        return self.n_machines * self.machine.hashrate_th

    @property
    def block_reward(self):
        return self.subsidy * (1.0 + self.fees_frac)


def _daily_grid(annual_cagr, days):
    t = np.arange(days) / 365.0
    return (1.0 + annual_cagr) ** t


def daily_btc_minted(p, price_path, net_hash_path):
    gross = (p.fleet_hashrate_th / net_hash_path) * BLOCKS_PER_DAY * p.block_reward
    return gross * p.uptime * (1.0 - p.pool_fee)


def daily_elec_cost(p):
    return p.n_machines * p.machine.power_kw * 24.0 * p.elec_price * p.uptime


def simulate(p, price_path=None, net_hash_path=None):
    if price_path is None:
        price_path = p.btc_price_0 * _daily_grid(p.price_cagr, p.days)
    if net_hash_path is None:
        net_hash_path = p.net_hashrate_0_th * _daily_grid(p.difficulty_cagr, p.days)

    minted = daily_btc_minted(p, price_path, net_hash_path)
    elec = np.full(p.days, daily_elec_cost(p))
    if p.curtail:
        run = minted * price_path > elec
        minted = minted * run
        elec = elec * run
    elec_in_btc = elec / price_path

    hodl_stack = np.cumsum(minted)
    net_stack = np.cumsum(minted - elec_in_btc)

    usd_profit = minted * price_path - elec
    cash_pile = np.cumsum(usd_profit)

    n0 = p.capital_usd / p.btc_price_0
    residual = p.n_machines * p.machine.price_usd * p.residual_frac

    hold_value = n0 * price_path
    mine_value_hodl = net_stack * price_path + residual
    mine_value_sell = cash_pile + residual

    return {
        "price_path": price_path,
        "net_hash_path": net_hash_path,
        "minted": minted,
        "elec_daily": elec,
        "hodl_stack": hodl_stack,
        "net_stack": net_stack,
        "cash_pile": cash_pile,
        "hold_value": hold_value,
        "mine_value_hodl": mine_value_hodl,
        "mine_value_sell": mine_value_sell,
        "n0_btc": n0,
        "residual": residual,
    }


def breakeven_elec_price(p, t=0):
    price_path = p.btc_price_0 * _daily_grid(p.price_cagr, p.days)
    net_hash_path = p.net_hashrate_0_th * _daily_grid(p.difficulty_cagr, p.days)
    minted = daily_btc_minted(p, price_path, net_hash_path)
    rev = minted[t] * price_path[t]
    kwh = p.n_machines * p.machine.power_kw * 24.0 * p.uptime
    return rev / kwh if kwh > 0 else float("nan")


def net_btc_vs_hold(p):
    r = simulate(p)
    return r["net_stack"][-1], r["n0_btc"]


def critical_difficulty_cagr(p, lo=-0.5, hi=3.0, tol=1e-4):
    def terminal_gap(g):
        pp = copy.copy(p)
        pp.difficulty_cagr = g
        r = simulate(pp)
        return r["mine_value_hodl"][-1] - r["hold_value"][-1]

    a, b = lo, hi
    fa, fb = terminal_gap(a), terminal_gap(b)
    if fa * fb > 0:
        return None
    for _ in range(60):
        m = 0.5 * (a + b)
        fm = terminal_gap(m)
        if abs(fm) < tol or (b - a) < tol:
            return m
        if fa * fm < 0:
            b, fb = m, fm
        else:
            a, fa = m, fm
    return 0.5 * (a + b)


def monte_carlo(p, n_paths=5000, seed=42):
    rng = np.random.default_rng(seed)
    dt = 1.0 / 365.0
    days = p.days

    mu_p = np.log(1.0 + p.price_cagr)
    mu_d = np.log(1.0 + p.difficulty_cagr)

    z_p = rng.standard_normal((n_paths, days))
    z_d = rng.standard_normal((n_paths, days))

    drift_p = (mu_p - 0.5 * p.price_vol**2) * dt
    drift_d = (mu_d - 0.5 * p.difficulty_vol**2) * dt
    log_price = np.cumsum(drift_p + p.price_vol * np.sqrt(dt) * z_p, axis=1)
    log_diff = np.cumsum(drift_d + p.difficulty_vol * np.sqrt(dt) * z_d, axis=1)

    price_paths = p.btc_price_0 * np.exp(log_price)
    net_hash_paths = np.maximum(p.net_hashrate_0_th * np.exp(log_diff), 1.0)

    elec = daily_elec_cost(p)
    gross = (p.fleet_hashrate_th / net_hash_paths) * BLOCKS_PER_DAY * p.block_reward
    minted = gross * p.uptime * (1.0 - p.pool_fee)
    elec_arr = np.full_like(minted, elec)
    if p.curtail:
        run = minted * price_paths > elec_arr
        minted = minted * run
        elec_arr = elec_arr * run
    net_stack = np.cumsum(minted - elec_arr / price_paths, axis=1)[:, -1]

    n0 = p.capital_usd / p.btc_price_0
    residual = p.n_machines * p.machine.price_usd * p.residual_frac
    pT = price_paths[:, -1]
    mine_val = net_stack * pT + residual
    hold_val = n0 * pT

    diff = mine_val - hold_val
    return {
        "mine_val": mine_val,
        "hold_val": hold_val,
        "diff": diff,
        "p_mine_wins": float(np.mean(diff > 0)),
        "mine_median": float(np.median(mine_val)),
        "hold_median": float(np.median(hold_val)),
        "diff_median": float(np.median(diff)),
        "diff_p05": float(np.percentile(diff, 5)),
        "diff_p95": float(np.percentile(diff, 95)),
    }
