-- Add investable 13F trade-copy analysis tables.
-- Safe to run more than once against Azure SQL.

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID('dbo.security_events', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.security_events (
        id INT IDENTITY(1,1) PRIMARY KEY,
        old_ticker NVARCHAR(32) NOT NULL,
        effective_date DATE NOT NULL,
        event_type NVARCHAR(32) NOT NULL,
        successor_ticker NVARCHAR(32) NULL,
        cash_per_share DECIMAL(18,6) NULL,
        exchange_ratio DECIMAL(18,8) NULL,
        notes NVARCHAR(1000) NULL,
        created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_security_events UNIQUE (old_ticker, effective_date),
        CONSTRAINT CK_security_events_type CHECK
            (event_type IN ('ticker_change', 'cash_merger', 'stock_merger', 'liquidation'))
    );
    CREATE INDEX IX_security_events_lookup
        ON dbo.security_events(old_ticker, effective_date);
END;

IF OBJECT_ID('dbo.trade_copy_results', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.trade_copy_results (
        id BIGINT IDENTITY(1,1) PRIMARY KEY,
        fund_id INT NOT NULL REFERENCES dbo.funds(id),
        signal_filing_id INT NOT NULL REFERENCES dbo.filings(id),
        next_filing_id INT NOT NULL REFERENCES dbo.filings(id),
        signal_date DATE NOT NULL,
        entry_date DATE NOT NULL,
        exit_date DATE NOT NULL,
        total_return DECIMAL(12,6) NOT NULL,
        benchmark_return DECIMAL(12,6) NULL,
        alpha DECIMAL(12,6) NULL,
        turnover DECIMAL(12,6) NOT NULL,
        transaction_cost DECIMAL(12,6) NOT NULL,
        price_coverage DECIMAL(12,6) NOT NULL,
        unresolved_policy NVARCHAR(16) NOT NULL,
        num_positions INT NOT NULL,
        no_start_price_positions INT NOT NULL DEFAULT 0,
        delisted_positions INT NOT NULL DEFAULT 0,
        resolved_event_positions INT NOT NULL DEFAULT 0,
        unresolved_positions INT NOT NULL DEFAULT 0,
        computed_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_trade_copy_signal UNIQUE (fund_id, signal_filing_id)
    );
END;

IF OBJECT_ID('dbo.trade_copy_position_results', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.trade_copy_position_results (
        id BIGINT IDENTITY(1,1) PRIMARY KEY,
        trade_copy_result_id BIGINT NOT NULL
            REFERENCES dbo.trade_copy_results(id) ON DELETE CASCADE,
        fund_id INT NOT NULL REFERENCES dbo.funds(id),
        signal_filing_id INT NOT NULL REFERENCES dbo.filings(id),
        ticker NVARCHAR(32) NOT NULL,
        cusip NVARCHAR(16) NULL,
        position_rank INT NOT NULL,
        disclosed_value BIGINT NOT NULL,
        target_weight DECIMAL(18,10) NOT NULL,
        previous_weight DECIMAL(18,10) NOT NULL,
        weight_change DECIMAL(18,10) NOT NULL,
        trade_type NVARCHAR(16) NOT NULL,
        entry_date DATE NULL,
        entry_price DECIMAL(18,6) NULL,
        exit_date DATE NULL,
        exit_value DECIMAL(18,6) NULL,
        total_return DECIMAL(18,8) NULL,
        benchmark_return DECIMAL(18,8) NULL,
        excess_return DECIMAL(18,8) NULL,
        contribution DECIMAL(18,8) NULL,
        resolution_type NVARCHAR(32) NOT NULL,
        is_resolved BIT NOT NULL,
        resolution_note NVARCHAR(1000) NULL
    );
    CREATE INDEX IX_trade_copy_positions_result
        ON dbo.trade_copy_position_results(trade_copy_result_id, position_rank);
    CREATE INDEX IX_trade_copy_positions_fund_trade
        ON dbo.trade_copy_position_results(fund_id, trade_type, is_resolved);
END;

COMMIT TRANSACTION;
