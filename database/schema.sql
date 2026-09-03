-- 13F Analyzer - Azure SQL Database Schema
-- Run this script against your Azure SQL Database to initialize tables.

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'funds')
BEGIN
    CREATE TABLE funds (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        name            NVARCHAR(256) NOT NULL,
        fund_type       NVARCHAR(64)  NOT NULL,  -- 'Long Only' | 'Hedge Core'
        cik             NVARCHAR(20)  NULL,
        is_active       BIT           NOT NULL DEFAULT 1,
        created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_funds_name UNIQUE (name)
    );
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'filings')
BEGIN
    CREATE TABLE filings (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        fund_id         INT           NOT NULL REFERENCES funds(id),
        accession_no    NVARCHAR(32)  NOT NULL,
        form_type       NVARCHAR(16)  NOT NULL DEFAULT '13F-HR',
        report_period   DATE          NOT NULL,
        filing_date     DATE          NOT NULL,
        total_value     BIGINT        NULL,  -- reported in thousands USD
        total_holdings  INT           NULL,
        created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_filings_accession UNIQUE (accession_no)
    );
    CREATE INDEX IX_filings_fund_period ON filings(fund_id, report_period DESC);
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'holdings')
BEGIN
    CREATE TABLE holdings (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        filing_id       INT           NOT NULL REFERENCES filings(id),
        fund_id         INT           NOT NULL REFERENCES funds(id),
        cusip           NVARCHAR(16)  NULL,
        ticker          NVARCHAR(32)  NULL,
        issuer_name     NVARCHAR(512) NOT NULL,
        security_class  NVARCHAR(128) NULL,
        shares          BIGINT        NOT NULL,
        value_usd       BIGINT        NOT NULL,  -- thousands USD per SEC 13F
        put_call        NVARCHAR(8)   NULL,      -- PUT | CALL | NULL
        investment_discretion NVARCHAR(32) NULL,
        created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
    );
    CREATE INDEX IX_holdings_filing ON holdings(filing_id);
    CREATE INDEX IX_holdings_fund_ticker ON holdings(fund_id, ticker);
    CREATE INDEX IX_holdings_cusip ON holdings(cusip);
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'securities')
BEGIN
    CREATE TABLE securities (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        cusip           NVARCHAR(16)  NULL,
        ticker          NVARCHAR(32)  NOT NULL,
        issuer_name     NVARCHAR(512) NULL,
        first_appearance_date DATE     NULL,
        created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_securities_ticker UNIQUE (ticker)
    );
    CREATE INDEX IX_securities_cusip ON securities(cusip);
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'daily_prices')
BEGIN
    CREATE TABLE daily_prices (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        ticker          NVARCHAR(32)  NOT NULL,
        price_date      DATE          NOT NULL,
        open_price      DECIMAL(18,4) NULL,
        high_price      DECIMAL(18,4) NULL,
        low_price       DECIMAL(18,4) NULL,
        close_price     DECIMAL(18,4) NOT NULL,
        adj_close       DECIMAL(18,4) NULL,
        volume          BIGINT        NULL,
        created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_daily_prices_ticker_date UNIQUE (ticker, price_date)
    );
    CREATE INDEX IX_daily_prices_ticker ON daily_prices(ticker, price_date DESC);
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'security_events')
BEGIN
    CREATE TABLE security_events (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        old_ticker          NVARCHAR(32) NOT NULL,
        effective_date      DATE         NOT NULL,
        event_type          NVARCHAR(32) NOT NULL,
        successor_ticker    NVARCHAR(32) NULL,
        cash_per_share      DECIMAL(18,6) NULL,
        exchange_ratio      DECIMAL(18,8) NULL,
        notes               NVARCHAR(1000) NULL,
        created_at          DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at          DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_security_events UNIQUE (old_ticker, effective_date),
        CONSTRAINT CK_security_events_type CHECK (
            event_type IN ('ticker_change', 'cash_merger', 'stock_merger', 'liquidation')
        )
    );
    CREATE INDEX IX_security_events_lookup
        ON security_events(old_ticker, effective_date);
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'portfolio_snapshots')
BEGIN
    -- Pre-computed portfolio weights per fund per quarter
    CREATE TABLE portfolio_snapshots (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        fund_id         INT           NOT NULL REFERENCES funds(id),
        report_period   DATE          NOT NULL,
        ticker          NVARCHAR(32)  NOT NULL,
        weight          DECIMAL(12,6) NOT NULL,  -- fraction of total portfolio
        shares          BIGINT        NOT NULL,
        value_usd       BIGINT        NOT NULL,
        created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_portfolio_snap UNIQUE (fund_id, report_period, ticker)
    );
    CREATE INDEX IX_portfolio_snap_fund ON portfolio_snapshots(fund_id, report_period DESC);
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'backtest_results')
BEGIN
    CREATE TABLE backtest_results (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        fund_id         INT           NOT NULL REFERENCES funds(id),
        period_start    DATE          NOT NULL,
        period_end      DATE          NOT NULL,
        total_return    DECIMAL(12,6) NOT NULL,
        benchmark_return DECIMAL(12,6) NULL,  -- e.g. SPY
        alpha           DECIMAL(12,6) NULL,
        num_positions   INT           NOT NULL,
        computed_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_backtest_fund_period UNIQUE (fund_id, period_start, period_end)
    );
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'trade_copy_results')
BEGIN
    CREATE TABLE trade_copy_results (
        id                  BIGINT IDENTITY(1,1) PRIMARY KEY,
        fund_id             INT NOT NULL REFERENCES funds(id),
        signal_filing_id    INT NOT NULL REFERENCES filings(id),
        next_filing_id      INT NOT NULL REFERENCES filings(id),
        signal_date         DATE NOT NULL,
        entry_date          DATE NOT NULL,
        exit_date           DATE NOT NULL,
        total_return        DECIMAL(12,6) NOT NULL,
        benchmark_return    DECIMAL(12,6) NULL,
        alpha               DECIMAL(12,6) NULL,
        turnover            DECIMAL(12,6) NOT NULL,
        transaction_cost    DECIMAL(12,6) NOT NULL,
        price_coverage      DECIMAL(12,6) NOT NULL,
        unresolved_policy   NVARCHAR(16) NOT NULL,
        num_positions       INT NOT NULL,
        no_start_price_positions INT NOT NULL DEFAULT 0,
        delisted_positions  INT NOT NULL DEFAULT 0,
        resolved_event_positions INT NOT NULL DEFAULT 0,
        unresolved_positions INT NOT NULL DEFAULT 0,
        computed_at         DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_trade_copy_signal UNIQUE (fund_id, signal_filing_id)
    );
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'trade_copy_position_results')
BEGIN
    CREATE TABLE trade_copy_position_results (
        id                  BIGINT IDENTITY(1,1) PRIMARY KEY,
        trade_copy_result_id BIGINT NOT NULL REFERENCES trade_copy_results(id) ON DELETE CASCADE,
        fund_id             INT NOT NULL REFERENCES funds(id),
        signal_filing_id    INT NOT NULL REFERENCES filings(id),
        ticker              NVARCHAR(32) NOT NULL,
        cusip               NVARCHAR(16) NULL,
        position_rank       INT NOT NULL,
        disclosed_value     BIGINT NOT NULL,
        target_weight       DECIMAL(18,10) NOT NULL,
        previous_weight     DECIMAL(18,10) NOT NULL,
        weight_change       DECIMAL(18,10) NOT NULL,
        trade_type          NVARCHAR(16) NOT NULL,
        entry_date          DATE NULL,
        entry_price         DECIMAL(18,6) NULL,
        exit_date           DATE NULL,
        exit_value          DECIMAL(18,6) NULL,
        total_return        DECIMAL(18,8) NULL,
        benchmark_return    DECIMAL(18,8) NULL,
        excess_return       DECIMAL(18,8) NULL,
        contribution        DECIMAL(18,8) NULL,
        resolution_type     NVARCHAR(32) NOT NULL,
        is_resolved         BIT NOT NULL,
        resolution_note     NVARCHAR(1000) NULL
    );
    CREATE INDEX IX_trade_copy_positions_result
        ON trade_copy_position_results(trade_copy_result_id, position_rank);
    CREATE INDEX IX_trade_copy_positions_fund_trade
        ON trade_copy_position_results(fund_id, trade_type, is_resolved);
END
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sync_log')
BEGIN
    CREATE TABLE sync_log (
        id              BIGINT IDENTITY(1,1) PRIMARY KEY,
        job_type        NVARCHAR(64)  NOT NULL,  -- 'edgar_13f' | 'price_data' | 'backtest'
        status          NVARCHAR(16)  NOT NULL,  -- 'started' | 'success' | 'failed'
        message         NVARCHAR(MAX) NULL,
        records_affected INT          NULL,
        started_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        finished_at     DATETIME2     NULL
    );
END
GO
