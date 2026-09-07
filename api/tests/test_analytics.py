import unittest
from datetime import date
from decimal import Decimal

from api.shared.analytics import rank_alpha, recent_strategy_trades


class AlphaTests(unittest.TestCase):
    def test_signed_rankings_and_common_horizon_annualization(self):
        rows = [
            {"ticker": f"T{i}", "excess_contribution": Decimal(i) / 100, "history_days": 730}
            for i in range(-7, 8)
        ]
        result = rank_alpha(rows)
        self.assertEqual([r["ticker"] for r in result["contributors"]], ["T7", "T6", "T5", "T4", "T3"])
        self.assertEqual([r["ticker"] for r in result["detractors"]], ["T-7", "T-6", "T-5", "T-4", "T-3"])
        self.assertAlmostEqual(result["contributors"][0]["annualized_alpha"], .035)
        self.assertAlmostEqual(result["detractors"][0]["annualized_alpha"], -.035)

    def test_missing_zero_and_invalid_history_do_not_create_rankings(self):
        self.assertEqual(rank_alpha([
            {"ticker": "A", "excess_contribution": None, "history_days": 365},
            {"ticker": "B", "excess_contribution": .1, "history_days": 0},
            {"ticker": "C", "excess_contribution": 0, "history_days": 365},
        ]), {"contributors": [], "detractors": []})


def episode(ticker="ABC", entry_date=date(2025, 1, 2), exit_date=None,
            entry_price=100, exit_price=None, latest_price=150,
            latest_price_date=date(2026, 1, 2)):
    return {
        "ticker": ticker, "entry_date": entry_date, "exit_date": exit_date,
        "entry_price": entry_price, "exit_price": exit_price,
        "latest_price": latest_price, "latest_price_date": latest_price_date,
    }


class RecentTradesTests(unittest.TestCase):
    def test_closed_episode_produces_sell_and_buy_with_realized_pnl(self):
        result = recent_strategy_trades([episode(exit_date=date(2025, 8, 15), exit_price=90)])
        self.assertEqual([r["trade"] for r in result], ["sell", "buy"])
        for row in result:
            self.assertAlmostEqual(row["pnl"], -.1)
            self.assertEqual(row["pnl_type"], "realized")
            self.assertTrue(row["is_closed"])
            self.assertEqual(row["entry_date"], date(2025, 1, 2))
        self.assertEqual(result[0]["trade_date"], date(2025, 8, 15))
        self.assertEqual(result[1]["trade_date"], result[1]["entry_date"])

    def test_open_buy_is_marked_to_latest_price_not_prior_backtest_return(self):
        result = recent_strategy_trades([episode(latest_price=175)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["trade"], "buy")
        self.assertAlmostEqual(result[0]["pnl"], .75)
        self.assertEqual(result[0]["pnl_type"], "mark_to_market")
        self.assertEqual(result[0]["as_of_date"], date(2026, 1, 2))
        self.assertFalse(result[0]["is_closed"])

    def test_missing_sell_price_does_not_use_latest_price_for_realized_pnl(self):
        result = recent_strategy_trades([episode(exit_date=date(2025, 8, 15))])
        self.assertEqual(result[0]["trade"], "sell")
        self.assertEqual(result[0]["pnl_type"], "realized")
        self.assertIsNone(result[0]["pnl"])

    def test_missing_invalid_or_pre_entry_quotes_are_unavailable(self):
        for row in [episode(entry_price=None), episode(entry_price=0),
                    episode(latest_price=None), episode(latest_price=float("nan")),
                    episode(latest_price_date=date(2024, 1, 1))]:
            with self.subTest(row=row):
                self.assertIsNone(recent_strategy_trades([row])[0]["pnl"])

    def test_total_loss_stays_minus_one(self):
        result = recent_strategy_trades([episode(exit_date=date(2025, 8, 15), exit_price=0)])
        self.assertEqual(result[0]["pnl"], -1)

    def test_five_latest_events_include_recent_sell_of_old_position(self):
        rows = [episode(f"T{i}", entry_date=date(2025, i, 1)) for i in range(1, 8)]
        rows.append(episode("OLD", entry_date=date(2020, 1, 1), exit_date=date(2025, 8, 1), exit_price=200))
        result = recent_strategy_trades(rows)
        self.assertEqual([r["ticker"] for r in result], ["OLD", "T7", "T6", "T5", "T4"])
        self.assertEqual(result[0]["trade"], "sell")
        self.assertEqual(result[0]["entry_date"], date(2020, 1, 1))
        self.assertEqual(recent_strategy_trades([]), [])

    def test_reentry_keeps_separate_cost_basis(self):
        result = recent_strategy_trades([
            episode(exit_date=date(2025, 3, 1), exit_price=120),
            episode(entry_date=date(2025, 6, 1), entry_price=200, latest_price=150),
        ])
        self.assertEqual([r["trade"] for r in result], ["buy", "sell", "buy"])
        self.assertAlmostEqual(result[0]["pnl"], -.25)
        self.assertAlmostEqual(result[1]["pnl"], .2)
        self.assertEqual(result[1]["entry_date"], date(2025, 1, 2))

    def test_filing_without_execution_date_is_not_a_trade(self):
        self.assertEqual(recent_strategy_trades([episode(entry_date=None)]), [])


if __name__ == "__main__":
    unittest.main()
