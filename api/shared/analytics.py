"""Presentation calculations for persisted backtest results."""

from math import isfinite


def rank_alpha(rows):
    """Arithmetic annualization of weighted excess returns on a common horizon."""
    ranked = []
    for row in rows:
        days = row.get("history_days")
        contribution = row.get("excess_contribution")
        if not days or days <= 0 or contribution is None:
            continue
        annualized = float(contribution) * 365.0 / days
        if isfinite(annualized):
            ranked.append({**row, "annualized_alpha": annualized})
    ranked.sort(key=lambda row: (-row["annualized_alpha"], row["ticker"]))
    return {
        "contributors": [row for row in ranked if row["annualized_alpha"] > 0][:5],
        "detractors": sorted(
            (row for row in ranked if row["annualized_alpha"] < 0),
            key=lambda row: (row["annualized_alpha"], row["ticker"]),
        )[:5],
    }


def recent_strategy_trades(rows):
    """Expand holding episodes into buy/sell events and rank by execution date.

    All prices come from the same current adjusted-price series. A closed
    episode's buy and sell events both show its final realized return.
    """
    trades = []
    for row in rows:
        entry_date = row["entry_date"]
        if entry_date is None:
            # A filing signal without a subsequent trading session is not a trade.
            continue
        closed = row["exit_date"] is not None
        valuation_date = row["exit_date"] if closed else row["latest_price_date"]
        value = row["exit_price"] if closed else row["latest_price"]
        entry_price = row["entry_price"]
        pnl = None
        if (entry_price is not None and value is not None and valuation_date is not None
                and valuation_date >= entry_date):
            entry_price, value = float(entry_price), float(value)
            if isfinite(entry_price) and entry_price > 0 and isfinite(value) and value >= 0:
                pnl = value / entry_price - 1
                if not isfinite(pnl):
                    pnl = None
        common = {
            "ticker": row["ticker"],
            "entry_date": entry_date,
            "as_of_date": valuation_date,
            "is_closed": closed,
            "pnl": pnl,
            "pnl_type": "realized" if closed else "mark_to_market",
        }
        trades.append({**common, "trade": "buy", "trade_date": entry_date})
        if closed:
            trades.append({**common, "trade": "sell", "trade_date": row["exit_date"]})
    trades.sort(key=lambda trade: (trade["trade_date"], trade["ticker"], trade["trade"]), reverse=True)
    return trades[:5]
