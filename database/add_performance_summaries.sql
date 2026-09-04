-- Persisted, API-ready quarterly positions. Run once on an existing database.
-- The refresh procedure is idempotent and may rebuild all periods or only periods
-- at/after @from_period.

IF OBJECT_ID('dbo.fund_quarter_positions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.fund_quarter_positions (
        fund_id          INT NOT NULL REFERENCES dbo.funds(id),
        report_period    DATE NOT NULL,
        filing_id        INT NOT NULL REFERENCES dbo.filings(id),
        filing_date      DATE NOT NULL,
        position_key     NVARCHAR(64) NOT NULL,
        ticker           NVARCHAR(32) NULL,
        cusip            NVARCHAR(16) NULL,
        issuer_name      NVARCHAR(512) NOT NULL,
        put_call         NVARCHAR(8) NULL,
        shares           BIGINT NOT NULL,
        value_usd        BIGINT NOT NULL,
        portfolio_weight DECIMAL(18,10) NOT NULL,
        previous_shares  BIGINT NOT NULL,
        previous_value   BIGINT NOT NULL,
        share_change     BIGINT NOT NULL,
        share_change_pct DECIMAL(18,6) NULL,
        change_type      VARCHAR(12) NOT NULL,
        is_exit          BIT NOT NULL,
        refreshed_at     DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_fund_quarter_positions
            PRIMARY KEY (fund_id, report_period, position_key)
    );
    CREATE INDEX IX_fqp_ticker_period
        ON dbo.fund_quarter_positions(ticker, report_period DESC)
        INCLUDE (fund_id, shares, value_usd, portfolio_weight, change_type, is_exit);
    CREATE INDEX IX_fqp_period_change
        ON dbo.fund_quarter_positions(report_period DESC, change_type)
        INCLUDE (fund_id, ticker, shares, value_usd, previous_value);
END
GO

CREATE OR ALTER PROCEDURE dbo.refresh_fund_quarter_positions
    @from_period DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRANSACTION;
    DELETE FROM dbo.fund_quarter_positions
    WHERE @from_period IS NULL OR report_period >= @from_period;

    ;WITH ranked_filings AS (
        SELECT f.id, f.fund_id, f.report_period, f.filing_date,
               ROW_NUMBER() OVER (
                   PARTITION BY f.fund_id, f.report_period
                   ORDER BY f.filing_date DESC, f.id DESC) AS rn
        FROM dbo.filings f
    ), selected_filings AS (
        SELECT id, fund_id, report_period, filing_date,
               LAG(id) OVER (PARTITION BY fund_id ORDER BY report_period) AS prior_filing_id
        FROM ranked_filings WHERE rn = 1
    ), current_positions AS (
        SELECT sf.fund_id, sf.report_period, sf.id AS filing_id, sf.filing_date,
               sf.prior_filing_id,
               UPPER(TRIM(COALESCE(NULLIF(h.ticker, ''), h.cusip))) AS position_key,
               MAX(UPPER(TRIM(h.ticker))) AS ticker,
               MAX(UPPER(TRIM(h.cusip))) AS cusip,
               MAX(h.issuer_name) AS issuer_name, MAX(h.put_call) AS put_call,
               SUM(h.shares) AS shares, SUM(h.value_usd) AS value_usd
        FROM selected_filings sf
        JOIN dbo.holdings h ON h.filing_id = sf.id
        WHERE (@from_period IS NULL OR sf.report_period >= @from_period)
          AND (h.put_call IS NULL OR TRIM(h.put_call) = '')
          AND COALESCE(NULLIF(TRIM(h.ticker),''),NULLIF(TRIM(h.cusip),'')) IS NOT NULL
        GROUP BY sf.fund_id, sf.report_period, sf.id, sf.filing_date,
                 sf.prior_filing_id,
                 UPPER(TRIM(COALESCE(NULLIF(h.ticker, ''), h.cusip)))
    ), prior_positions AS (
        SELECT sf.fund_id, sf.report_period, sf.id AS filing_id, sf.filing_date,
               UPPER(TRIM(COALESCE(NULLIF(h.ticker, ''), h.cusip))) AS position_key,
               MAX(UPPER(TRIM(h.ticker))) AS ticker,
               MAX(UPPER(TRIM(h.cusip))) AS cusip,
               MAX(h.issuer_name) AS issuer_name, MAX(h.put_call) AS put_call,
               SUM(h.shares) AS shares, SUM(h.value_usd) AS value_usd
        FROM selected_filings sf
        JOIN dbo.holdings h ON h.filing_id = sf.prior_filing_id
        WHERE (@from_period IS NULL OR sf.report_period >= @from_period)
          AND (h.put_call IS NULL OR TRIM(h.put_call) = '')
          AND COALESCE(NULLIF(TRIM(h.ticker),''),NULLIF(TRIM(h.cusip),'')) IS NOT NULL
        GROUP BY sf.fund_id, sf.report_period, sf.id, sf.filing_date,
                 UPPER(TRIM(COALESCE(NULLIF(h.ticker, ''), h.cusip)))
    ), combined AS (
        SELECT COALESCE(c.fund_id,p.fund_id) fund_id,
               COALESCE(c.report_period,p.report_period) report_period,
               COALESCE(c.filing_id,p.filing_id) filing_id,
               COALESCE(c.filing_date,p.filing_date) filing_date,
               COALESCE(c.position_key,p.position_key) position_key,
               COALESCE(c.ticker,p.ticker) ticker, COALESCE(c.cusip,p.cusip) cusip,
               COALESCE(c.issuer_name,p.issuer_name) issuer_name,
               COALESCE(c.put_call,p.put_call) put_call,
               COALESCE(c.shares,0) shares, COALESCE(c.value_usd,0) value_usd,
               COALESCE(p.shares,0) previous_shares,
               COALESCE(p.value_usd,0) previous_value,
               CASE WHEN c.position_key IS NULL THEN 1 ELSE 0 END is_exit
        FROM current_positions c
        FULL OUTER JOIN prior_positions p
          ON p.fund_id=c.fund_id AND p.report_period=c.report_period
         AND p.position_key=c.position_key
    ), weighted AS (
        SELECT *, SUM(CASE WHEN is_exit=0 THEN value_usd ELSE 0 END)
                       OVER(PARTITION BY fund_id,report_period) total_value
        FROM combined
    )
    INSERT dbo.fund_quarter_positions
        (fund_id,report_period,filing_id,filing_date,position_key,ticker,cusip,
         issuer_name,put_call,shares,value_usd,portfolio_weight,previous_shares,
         previous_value,share_change,share_change_pct,change_type,is_exit)
    SELECT fund_id,report_period,filing_id,filing_date,position_key,ticker,cusip,
           issuer_name,put_call,shares,value_usd,
           CAST(COALESCE(
               CASE WHEN is_exit=0 THEN value_usd*1.0/NULLIF(total_value,0) ELSE 0 END,
               0
           ) AS DECIMAL(18,10)),
           previous_shares,previous_value,shares-previous_shares,
           CAST((shares-previous_shares)*1.0/NULLIF(previous_shares,0) AS DECIMAL(18,6)),
           CASE WHEN is_exit=1 THEN 'exit' WHEN previous_shares=0 THEN 'new'
                WHEN shares>previous_shares THEN 'added'
                WHEN shares<previous_shares THEN 'reduced' ELSE 'unchanged' END,
           is_exit
    FROM weighted;
    COMMIT TRANSACTION;
END
GO

CREATE OR ALTER VIEW dbo.latest_fund_positions AS
SELECT p.*
FROM dbo.fund_quarter_positions p
JOIN (SELECT fund_id, MAX(report_period) report_period
      FROM dbo.fund_quarter_positions GROUP BY fund_id) latest
  ON latest.fund_id=p.fund_id AND latest.report_period=p.report_period;
GO
