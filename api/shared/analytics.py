"""Presentation calculations for persisted backtest results."""

from math import isfinite, prod


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
    """Join consecutive eligible filing periods, as in the strategy rankings."""
    episodes = []
    current = {}
    for row in sorted(rows, key=lambda row: (row["seq"], row["ticker"])):
        ticker = row["ticker"]
        episode = current.get(ticker)
        if episode is None or row["seq"] != episode[-1]["seq"] + 1:
            episode = []
            episodes.append(episode)
            current[ticker] = episode
        episode.append(row)

    trades = []
    for episode in episodes:
        first, last = episode[0], episode[-1]
        resolved = all(
            row["is_resolved"] and row["total_return"] is not None
            and isfinite(float(row["total_return"])) and float(row["total_return"]) >= -1
            for row in episode
        )
        pnl = prod(1 + float(row["total_return"]) for row in episode) - 1 if resolved else None
        if pnl is not None and not isfinite(pnl):
            pnl = None
        closed = not last["next_is_eligible"]
        trades.append({
            "ticker": first["ticker"],
            "entry_date": first["entry_date"],
            "entry_price": first["entry_price"],
            "as_of_date": last["exit_date"],
            "is_closed": closed,
            "pnl": pnl,
            "periods": len(episode),
            "resolved": resolved and pnl is not None,
            "_sort_date": first["period_entry_date"],
        })
    trades.sort(key=lambda trade: (trade["_sort_date"], trade["ticker"]), reverse=True)
    return [{key: value for key, value in trade.items() if key != "_sort_date"} for trade in trades[:5]]
