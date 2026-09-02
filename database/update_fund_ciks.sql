-- Replace fund CIK values from edgar_13f_cik_corrected.csv.
-- Run in Azure SQL, review the validation result, then commit.

SET XACT_ABORT ON;
BEGIN TRANSACTION;

DECLARE @CorrectedCiks TABLE (
    fund_name NVARCHAR(256) NOT NULL PRIMARY KEY,
    cik NVARCHAR(20) NOT NULL
);

INSERT INTO @CorrectedCiks (fund_name, cik)
VALUES
    (N'Anatole Investment Management Ltd.', N'1693745'),
    (N'Aspex Management (HK) Ltd.', N'1768375'),
    (N'Baker Bros. Advisors LP', N'1263508'),
    (N'Cat Rock Capital Management LP', N'1654648'),
    (N'CloudAlpha Capital Management Limited', N'1745907'),
    (N'Coatue Management LLC', N'1135730'),
    (N'D1 Capital Partners L.P.', N'1747057'),
    (N'Dragoneer Investment Group, LLC', N'1602189'),
    (N'Durable Capital Partners LP', N'1798849'),
    (N'Franchise Capital Ltd.', N'1859388'),
    (N'Fundsmith LLP', N'1569205'),
    (N'Greenwoods Asset Management Hong Kong Ltd.', N'1848138'),
    (N'HHLR Advisors, Ltd.', N'1762304'),
    (N'Honeycomb Asset Management LP', N'1675688'),
    (N'Immersion Capital LLP', N'1636441'),
    (N'Kontiki Capital Management (HK) Ltd.', N'1713390'),
    (N'Kora Management LP', N'1659815'),
    (N'Light Street Capital Management, LLC', N'1569049'),
    (N'Lone Pine Capital LLC', N'1061165'),
    (N'OLP Capital Management Ltd.', N'1738126'),
    (N'RV Capital AG', N'1766596'),
    (N'Shawspring Partners LLC', N'1766908'),
    (N'Soma Equity Partners LP', N'1680964'),
    (N'Tairen Capital Ltd.', N'1652062'),
    (N'TCI Fund Management Ltd.', N'1647251'),
    (N'Theleme Partners LLP', N'1511881'),
    (N'Tiger Global Management LLC', N'1167483'),
    (N'Two Creeks Capital Management, LP', N'1606430'),
    (N'Tybourne Capital Management (HK) Ltd.', N'1553936'),
    (N'Viking Global Investors LP', N'1103804'),
    (N'Whale Rock Capital Management LLC', N'1387322'),
    (N'Windacre Partnership LLC', N'1599383');

-- Stop before changing data if any CSV fund name is not in Azure.
IF EXISTS (
    SELECT 1
    FROM @CorrectedCiks AS c
    LEFT JOIN funds AS f ON f.name = c.fund_name
    WHERE f.id IS NULL
)
BEGIN
    SELECT c.fund_name AS missing_fund_name, c.cik
    FROM @CorrectedCiks AS c
    LEFT JOIN funds AS f ON f.name = c.fund_name
    WHERE f.id IS NULL;
    ROLLBACK TRANSACTION;
    THROW 50001, 'One or more corrected fund names do not exist in funds. No changes were made.', 1;
END;

UPDATE f
SET f.cik = c.cik,
    f.updated_at = SYSUTCDATETIME()
FROM funds AS f
INNER JOIN @CorrectedCiks AS c ON c.fund_name = f.name;

SELECT
    f.name AS fund_name,
    f.cik,
    CASE WHEN f.cik = c.cik THEN 'OK' ELSE 'MISMATCH' END AS validation
FROM funds AS f
INNER JOIN @CorrectedCiks AS c ON c.fund_name = f.name
ORDER BY f.name;

COMMIT TRANSACTION;

SELECT COUNT(*) AS corrected_funds
FROM funds AS f
INNER JOIN @CorrectedCiks AS c ON c.fund_name = f.name
WHERE f.cik = c.cik;