"""Refresh persisted analytics used by latency-sensitive API endpoints."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text

from db import get_connection

logger = logging.getLogger(__name__)


def refresh_position_summaries(from_period: date | None = None) -> dict:
    with get_connection() as conn:
        if from_period is None:
            state = conn.execute(
                text(
                    """
                    SELECT COUNT(*) row_count, MAX(refreshed_at) last_refresh
                    FROM dbo.fund_quarter_positions
                    """
                )
            ).mappings().one()
            if state["row_count"]:
                from_period = conn.execute(
                    text(
                        """
                        DECLARE @last DATETIME2=:last_refresh;
                        SELECT MIN(report_period) FROM (
                            SELECT f.report_period FROM dbo.filings f
                            WHERE f.created_at>@last
                            UNION ALL
                            SELECT f.report_period FROM dbo.holdings h
                            JOIN dbo.filings f ON f.id=h.filing_id
                            WHERE h.created_at>@last
                        ) changed
                        """
                    ),
                    {"last_refresh": state["last_refresh"]},
                ).scalar_one_or_none()
                if from_period is None:
                    result = {"from_period": None, "rows_available": 0, "skipped": True}
                    logger.info("Position summaries are already current")
                    return result
        conn.execute(
            text("EXEC dbo.refresh_fund_quarter_positions @from_period=:from_period"),
            {"from_period": from_period},
        )
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM dbo.fund_quarter_positions "
                "WHERE :from_period IS NULL OR report_period>=:from_period"
            ),
            {"from_period": from_period},
        ).scalar_one()
        conn.commit()
    result = {"from_period": from_period, "rows_available": count}
    logger.info("Position summary refresh complete: %s", result)
    return result
