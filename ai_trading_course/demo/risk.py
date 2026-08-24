"""階段 6：風控 / 部位大小。依停損距離反推張數，讓單筆最大虧損 = 帳戶 * RISK_PER_TRADE。"""
import config


def position_size(entry_price: float, stop_price: float) -> dict:
    """回傳建議股數與該筆風險金額。停損距離越遠 → 買越少（風險固定）。"""
    risk_amt = config.ACCOUNT * config.RISK_PER_TRADE
    per_share_risk = max(entry_price - stop_price, 1e-9)
    raw_shares = int(risk_amt / per_share_risk)
    shares = (raw_shares // 1000) * 1000  # 台股整張（1000 股）
    out = {
        "entry": round(entry_price, 2),
        "stop": round(stop_price, 2),
        "shares": shares,
        "risk_amt": round(shares * per_share_risk, 0),
        "cost": round(shares * entry_price, 0),
    }
    if shares == 0:
        lot_risk = round(1000 * per_share_risk, 0)
        out["note"] = (f"1% 風險({int(risk_amt)})買不起一整張(整張風險 {lot_risk:.0f})"
                       f"→ 放寬風險%、加大帳戶、或改用零股")
    return out
