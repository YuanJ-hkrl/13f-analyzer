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
