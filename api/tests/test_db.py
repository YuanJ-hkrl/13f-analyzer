"""Database resilience regression tests; no live database required."""

import unittest
from unittest.mock import MagicMock, patch

import pyodbc
from sqlalchemy.exc import DBAPIError, OperationalError

from api.shared import db


def unavailable():
    return DBAPIError.instance(
        None, None,
        pyodbc.Error("HY000", "[SQL Server]Database is not currently available. (40613) (SQLDriverConnect)"),
        pyodbc.Error,
    )


class DatabaseResilienceTests(unittest.TestCase):
    def setUp(self):
        db._cache.clear()
        self.addCleanup(db._cache.clear)
        env = patch.dict("os.environ", {"DB_CONNECT_ATTEMPTS": "3"})
        env.start()
        self.addCleanup(env.stop)

    @patch.object(db, "get_engine")
    def test_timings_separate_connection_read_and_close(self, get_engine):
        connection = get_engine.return_value.connect.return_value
        with db.capture_read_timings() as timings:
            with patch.object(db.time, "perf_counter", side_effect=[0, .1, 1, 1.2, 2, 2.5, 3, 3.3]):
                self.assertEqual(db._run_read(lambda conn: "result"), "result")
        for phase, expected in {"engine": 100, "connect": 200, "read": 500, "close": 300}.items():
            self.assertAlmostEqual(timings[phase], expected)
        connection.close.assert_called_once()
        self.assertIsNone(db._read_timings.get())

    @patch.object(db, "get_engine")
    def test_failed_read_closes_connection_and_restores_timing_context(self, get_engine):
        connection = get_engine.return_value.connect.return_value
        with self.assertRaises(ValueError):
            with db.capture_read_timings() as timings:
                db._run_read(MagicMock(side_effect=ValueError("invalid result")))
        self.assertIn("read", timings)
        self.assertIn("close", timings)
        connection.close.assert_called_once()
        self.assertIsNone(db._read_timings.get())

    def test_nested_timing_contexts_are_isolated(self):
        with db.capture_read_timings() as outer:
            with db.capture_read_timings() as inner:
                with db._time_read_phase("read"):
                    pass
            self.assertIs(db._read_timings.get(), outer)
            self.assertEqual(outer, {})
            self.assertIn("read", inner)
        self.assertIsNone(db._read_timings.get())

    @patch.object(db.time, "sleep")
    @patch.object(db, "_discard_engine")
    @patch.object(db, "get_engine")
    def test_generic_40613_reconnects(self, get_engine, discard, sleep):
        error = unavailable()
        self.assertNotIsInstance(error, OperationalError)
        engine = get_engine.return_value
        connected = MagicMock()
        engine.connect.side_effect = [error, connected]
        operation = MagicMock(return_value=[{"ok": 1}])
        self.assertEqual(db._run_read(operation), [{"ok": 1}])
        self.assertEqual(engine.connect.call_count, 2)
        operation.assert_called_once_with(connected)
        connected.close.assert_called_once()
        discard.assert_called_once_with(engine)
        sleep.assert_called_once_with(5)

    @patch.object(db.time, "sleep")
    @patch.object(db, "_discard_engine")
    @patch.object(db, "get_engine")
    def test_exhaustion_returns_stale_cache(self, get_engine, discard, sleep):
        get_engine.return_value.connect.side_effect = unavailable()
        db._cache["funds"] = (0, ["previous result"])
        self.assertEqual(db.cached("funds", lambda: db._run_read(lambda conn: [])), ["previous result"])
        self.assertEqual(get_engine.return_value.connect.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10])
        self.assertEqual(db._cache["funds"][0], 0)

    @patch.object(db.time, "sleep")
    @patch.object(db, "_discard_engine")
    @patch.object(db, "get_engine")
    def test_exhaustion_without_cache_raises(self, get_engine, discard, sleep):
        error = unavailable()
        get_engine.return_value.connect.side_effect = error
        with self.assertRaises(DBAPIError) as caught:
            db.cached("missing", lambda: db._run_read(lambda conn: []))
        self.assertIs(caught.exception, error)
        self.assertEqual(get_engine.return_value.connect.call_count, 3)
        self.assertNotIn("missing", db._cache)

    @patch.object(db.time, "sleep")
    @patch.object(db, "_discard_engine")
    @patch.object(db, "get_engine")
    def test_unrelated_hy000_is_not_retried_or_hidden(self, get_engine, discard, sleep):
        error = DBAPIError(None, None, pyodbc.Error("HY000", "Unrelated error (99999)"))
        get_engine.return_value.connect.side_effect = error
        db._cache["funds"] = (0, ["old"])
        with self.assertRaises(DBAPIError):
            db.cached("funds", lambda: db._run_read(lambda conn: []))
        discard.assert_not_called()
        sleep.assert_not_called()

    def test_native_code_does_not_match_statement_text(self):
        error = DBAPIError("SELECT '(40613)'", None, pyodbc.Error("HY000", "Other failure"))
        self.assertFalse(db._is_transient_error(error))


if __name__ == "__main__":
    unittest.main()
