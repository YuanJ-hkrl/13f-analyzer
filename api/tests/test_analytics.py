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


def period(seq, ticker="ABC", total_return=.1, next_is_eligible=True, resolved=True):
    return {
        "seq": seq, "ticker": ticker, "total_return": total_return,
        "is_resolved": resolved, "next_is_eligible": next_is_eligible,
        "period_entry_date": date(2020 + seq, 1, 1),
        "entry_date": date(2020 + seq, 1, 2), "exit_date": date(2021 + seq, 1, 2),
        "entry_price": 100 + seq,
    }


class RecentTradesTests(unittest.TestCase):
    def test_contiguous_periods_compound_and_preserve_original_entry(self):
        result = recent_strategy_trades([period(2, total_return=-.1, next_is_eligible=False), period(1)])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["pnl"], -.01)
        self.assertEqual(result[0]["entry_price"], 101)
        self.assertEqual(result[0]["entry_date"], date(2021, 1, 2))
        self.assertTrue(result[0]["is_closed"])
        self.assertEqual(result[0]["periods"], 2)

    def test_gaps_create_new_trade_and_open_status_is_preserved(self):
        result = recent_strategy_trades([period(1, next_is_eligible=False), period(3)])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["entry_price"], 103)
        self.assertFalse(result[0]["is_closed"])
        self.assertTrue(result[1]["is_closed"])

    def test_unresolved_period_never_reports_partial_pnl(self):
        result = recent_strategy_trades([period(1), period(2, total_return=None, resolved=False)])
        self.assertIsNone(result[0]["pnl"])
        self.assertFalse(result[0]["resolved"])

    def test_total_loss_stays_minus_one(self):
        result = recent_strategy_trades([period(1, total_return=-1), period(2)])
        self.assertEqual(result[0]["pnl"], -1)

    def test_only_five_latest_entries_are_returned(self):
        result = recent_strategy_trades([period(i, ticker=f"T{i}") for i in range(1, 8)])
        self.assertEqual([r["ticker"] for r in result], ["T7", "T6", "T5", "T4", "T3"])
        self.assertEqual(recent_strategy_trades([]), [])


if __name__ == "__main__":
    unittest.main()
