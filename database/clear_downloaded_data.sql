-- Remove all downloaded and derived data before rebuilding the dataset.
-- The corrected rows in funds are preserved.

SET XACT_ABORT ON;
BEGIN TRANSACTION;

DECLARE @holdings_deleted BIGINT;
DECLARE @filings_deleted INT;
DECLARE @securities_deleted INT;
DECLARE @prices_deleted BIGINT;
DECLARE @snapshots_deleted BIGINT;
DECLARE @backtests_deleted BIGINT;
DECLARE @sync_logs_deleted BIGINT;

IF OBJECT_ID('dbo.fund_quarter_positions', 'U') IS NOT NULL
    DELETE FROM dbo.fund_quarter_positions;

DELETE FROM holdings;
SET @holdings_deleted = @@ROWCOUNT;

DELETE FROM portfolio_snapshots;
SET @snapshots_deleted = @@ROWCOUNT;

DELETE FROM backtest_results;
SET @backtests_deleted = @@ROWCOUNT;

DELETE FROM filings;
SET @filings_deleted = @@ROWCOUNT;

DELETE FROM securities;
SET @securities_deleted = @@ROWCOUNT;

DELETE FROM daily_prices;
SET @prices_deleted = @@ROWCOUNT;

DELETE FROM sync_log;
SET @sync_logs_deleted = @@ROWCOUNT;

COMMIT TRANSACTION;

SELECT
    @holdings_deleted AS holdings_deleted,
    @filings_deleted AS filings_deleted,
    @securities_deleted AS securities_deleted,
    @prices_deleted AS daily_prices_deleted,
    @snapshots_deleted AS portfolio_snapshots_deleted,
    @backtests_deleted AS backtest_results_deleted,
    @sync_logs_deleted AS sync_log_deleted;

SELECT
    (SELECT COUNT(*) FROM funds) AS funds_preserved,
    (SELECT COUNT(*) FROM filings) AS filings_remaining,
    (SELECT COUNT(*) FROM holdings) AS holdings_remaining,
    (SELECT COUNT(*) FROM securities) AS securities_remaining,
    (SELECT COUNT(*) FROM daily_prices) AS daily_prices_remaining;
