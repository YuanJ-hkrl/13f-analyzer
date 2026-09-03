import azure.functions as func
import json
import logging

from shared.db import query_all, query_one

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _json_response(data, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status_code,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.route(route="health")
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json_response({"status": "ok", "service": "13f-analyzer"})


@app.route(route="securities")
def list_securities(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("q") or "").strip()
    try:
        rows = query_all(
            """
            WITH names AS (
                SELECT DISTINCT UPPER(TRIM(h.ticker)) AS ticker
                FROM holdings h
                WHERE h.ticker IS NOT NULL AND TRIM(h.ticker) <> ''
                GROUP BY UPPER(TRIM(h.ticker))
            ), latest_period AS (SELECT MAX(report_period) AS period FROM filings),
            latest_filings AS (
                SELECT f.id, f.fund_id, ROW_NUMBER() OVER (
                    PARTITION BY f.fund_id ORDER BY f.report_period DESC, f.filing_date DESC, f.id DESC
                ) rn FROM filings f
            ), ownership AS (
                SELECT UPPER(TRIM(h.ticker)) ticker, COUNT(DISTINCT lf.fund_id) owner_count,
                       SUM(h.value_usd) aggregate_value
                FROM latest_filings lf JOIN holdings h ON h.filing_id=lf.id
                WHERE lf.rn=1 AND h.ticker IS NOT NULL
                GROUP BY UPPER(TRIM(h.ticker))
            )
            SELECT TOP 100 n.ticker, nm.company, COALESCE(o.owner_count,0) owner_count,
                   COALESCE(o.aggregate_value,0) aggregate_value,
                   p.price AS latest_price, p.price_date
            FROM names n LEFT JOIN ownership o ON o.ticker=n.ticker
            OUTER APPLY (SELECT TOP 1 h.issuer_name company FROM holdings h JOIN filings f ON f.id=h.filing_id WHERE UPPER(TRIM(h.ticker))=n.ticker ORDER BY f.report_period DESC,f.filing_date DESC,f.id DESC) nm
            OUTER APPLY (SELECT TOP 1 dp.price_date, COALESCE(dp.adj_close,dp.close_price) price
                         FROM daily_prices dp WHERE dp.ticker=n.ticker ORDER BY dp.price_date DESC) p
            WHERE :search = '' OR n.ticker LIKE :pattern OR nm.company LIKE :pattern
            ORDER BY CASE WHEN n.ticker=:exact THEN 0 ELSE 1 END, o.owner_count DESC, n.ticker
            """,
            {"search": search, "pattern": f"%{search}%", "exact": search.upper()},
        )
        return _json_response({"securities": rows})
    except Exception as e:
        logging.exception("Error searching securities")
        return _json_response({"error": str(e)}, 500)


@app.route(route="securities/{ticker}")
def get_security(req: func.HttpRequest) -> func.HttpResponse:
    ticker = str(req.route_params["ticker"]).strip().upper()
    params = {"ticker": ticker}
    try:
        security = query_one(
            """
            SELECT :ticker ticker, latest_name.company,
                   MIN(f.report_period) first_appearance,
                   lp.price latest_price, lp.price_date
            FROM holdings h JOIN filings f ON f.id=h.filing_id
            OUTER APPLY (SELECT TOP 1 h2.issuer_name company FROM holdings h2 JOIN filings f2 ON f2.id=h2.filing_id WHERE UPPER(TRIM(h2.ticker))=:ticker ORDER BY f2.report_period DESC,f2.filing_date DESC,f2.id DESC) latest_name
            OUTER APPLY (SELECT TOP 1 dp.price_date, COALESCE(dp.adj_close,dp.close_price) price
                         FROM daily_prices dp WHERE dp.ticker=:ticker ORDER BY dp.price_date DESC) lp
            WHERE UPPER(TRIM(h.ticker))=:ticker
            GROUP BY latest_name.company,lp.price, lp.price_date
            """, params)
        if not security:
            return _json_response({"error": "Security not found"}, 404)

        history = query_all(
            """
            WITH periods AS (
              SELECT DISTINCT report_period FROM filings
            ), first_owned AS (
              SELECT MIN(f.report_period) report_period
              FROM filings f JOIN holdings h ON h.filing_id=f.id
              WHERE UPPER(TRIM(h.ticker))=:ticker AND h.shares>0
            ), ranked AS (
              SELECT f.id,f.fund_id,f.report_period,
                     ROW_NUMBER() OVER(PARTITION BY f.fund_id,f.report_period ORDER BY f.filing_date DESC,f.id DESC) rn
              FROM filings f
            ), positions AS (
              SELECT r.report_period,r.fund_id,
                     SUM(h.value_usd) position_value,SUM(h.shares) shares
              FROM ranked r JOIN holdings h ON h.filing_id=r.id
              WHERE r.rn=1 AND UPPER(TRIM(h.ticker))=:ticker
              GROUP BY r.report_period,r.fund_id
            )
            SELECT qtr.report_period,
                   COUNT(p.fund_id) fund_count,
                   COALESCE(SUM(p.position_value),0) aggregate_value,
                   COALESCE(SUM(p.shares),0) aggregate_shares,
                   q.price quarter_price
            FROM periods qtr
            CROSS JOIN first_owned first_seen
            LEFT JOIN positions p ON p.report_period=qtr.report_period
            OUTER APPLY(SELECT TOP 1 COALESCE(dp.adj_close,dp.close_price) price FROM daily_prices dp WHERE dp.ticker=:ticker AND dp.price_date<=qtr.report_period ORDER BY dp.price_date DESC) q
            WHERE qtr.report_period>=first_seen.report_period
            GROUP BY qtr.report_period,q.price
            ORDER BY qtr.report_period
            """, params)
        owners = query_all(
            """
            WITH ranked AS (
              SELECT f.*,ROW_NUMBER() OVER(PARTITION BY f.fund_id ORDER BY f.report_period DESC,f.filing_date DESC,f.id DESC) rn FROM filings f),
            current_pos AS (
              SELECT r.fund_id,r.report_period,SUM(h.value_usd) value_usd,SUM(h.shares) shares
              FROM ranked r JOIN holdings h ON h.filing_id=r.id WHERE r.rn=1 AND UPPER(TRIM(h.ticker))=:ticker GROUP BY r.fund_id,r.report_period),
            totals AS (SELECT r.fund_id,SUM(h.value_usd) total_value FROM ranked r JOIN holdings h ON h.filing_id=r.id WHERE r.rn=1 GROUP BY r.fund_id),
            first_owned AS (SELECT f.fund_id,MIN(f.report_period) first_owned FROM filings f JOIN holdings h ON h.filing_id=f.id WHERE UPPER(TRIM(h.ticker))=:ticker GROUP BY f.fund_id)
            SELECT fu.id fund_id,fu.name,fu.fund_type,c.report_period,c.value_usd,c.shares,
                   CAST(c.value_usd*1.0/NULLIF(t.total_value,0) AS DECIMAL(18,6)) portfolio_weight,
                   fo.first_owned
            FROM current_pos c JOIN funds fu ON fu.id=c.fund_id JOIN totals t ON t.fund_id=c.fund_id JOIN first_owned fo ON fo.fund_id=c.fund_id
            WHERE c.value_usd>0 ORDER BY c.value_usd DESC
            """, params)
        activity = query_all(
            """
            WITH periods AS (SELECT DISTINCT report_period FROM filings), latest AS (SELECT MAX(report_period) p FROM periods), prior AS (SELECT MAX(report_period) p FROM periods WHERE report_period<(SELECT p FROM latest)),
            pos AS (SELECT f.fund_id,f.report_period,SUM(h.shares) shares,SUM(h.value_usd) value_usd FROM filings f JOIN holdings h ON h.filing_id=f.id WHERE UPPER(TRIM(h.ticker))=:ticker AND f.report_period IN((SELECT p FROM latest),(SELECT p FROM prior)) GROUP BY f.fund_id,f.report_period),
            compared AS (SELECT fu.id fund_id,fu.name,fu.fund_type,COALESCE(c.shares,0) shares,COALESCE(p.shares,0) previous_shares,COALESCE(c.value_usd,0) value_usd,COALESCE(p.value_usd,0) previous_value FROM funds fu LEFT JOIN pos c ON c.fund_id=fu.id AND c.report_period=(SELECT p FROM latest) LEFT JOIN pos p ON p.fund_id=fu.id AND p.report_period=(SELECT p FROM prior) WHERE c.fund_id IS NOT NULL OR p.fund_id IS NOT NULL)
            SELECT *,CASE WHEN previous_shares=0 AND shares>0 THEN 'new' WHEN shares=0 AND previous_shares>0 THEN 'exit' WHEN shares>previous_shares THEN 'add' WHEN shares<previous_shares THEN 'reduce' ELSE 'unchanged' END action
            FROM compared WHERE shares<>previous_shares ORDER BY ABS(shares-previous_shares) DESC
            """, params)
        early = query_all(
            """
            WITH firsts AS (
              SELECT f.fund_id,MIN(f.filing_date) first_filing_date,MIN(f.report_period) first_report_period
              FROM filings f JOIN holdings h ON h.filing_id=f.id WHERE UPPER(TRIM(h.ticker))=:ticker GROUP BY f.fund_id)
            SELECT fu.id fund_id,fu.name,fu.fund_type,x.first_report_period,x.first_filing_date,
                   ep.price entry_price,lp.price latest_price,
                   CASE WHEN ep.price>0 THEN (lp.price-ep.price)/ep.price END return_since_first
            FROM firsts x JOIN funds fu ON fu.id=x.fund_id
            OUTER APPLY(SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price FROM daily_prices dp WHERE dp.ticker=:ticker AND dp.price_date>x.first_filing_date ORDER BY dp.price_date) ep
            OUTER APPLY(SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price FROM daily_prices dp WHERE dp.ticker=:ticker ORDER BY dp.price_date DESC) lp
            ORDER BY x.first_report_period,x.first_filing_date
            """, params)
        prices = query_all(
            """WITH p AS (SELECT price_date,COALESCE(adj_close,close_price) price,ROW_NUMBER() OVER(ORDER BY price_date) rn FROM daily_prices WHERE ticker=:ticker)
               SELECT price_date,price FROM p WHERE rn%5=1 ORDER BY price_date""", params)
        return _json_response({"security": security, "history": history, "owners": owners,
                               "buyers": [r for r in activity if r["action"] in ("new","add")],
                               "sellers": [r for r in activity if r["action"] in ("reduce","exit")],
                               "early_investors": early, "prices": prices})
    except Exception as e:
        logging.exception("Error loading security")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds")
def list_funds(req: func.HttpRequest) -> func.HttpResponse:
    fund_type = req.params.get("type")
    sql = """
        SELECT f.id, f.name, f.fund_type, f.cik,
               (SELECT COUNT(*) FROM filings fl WHERE fl.fund_id = f.id) AS filing_count,
               (SELECT MAX(fl.report_period) FROM filings fl WHERE fl.fund_id = f.id) AS latest_period
        FROM funds f
        WHERE f.is_active = 1
    """
    params = {}
    if fund_type:
        sql += " AND f.fund_type = :fund_type"
        params["fund_type"] = fund_type
    sql += " ORDER BY f.fund_type, f.name"

    try:
        funds = query_all(sql, params)
        return _json_response({"funds": funds})
    except Exception as e:
        logging.exception("Error listing funds")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}")
def get_fund(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    try:
        fund = query_one(
            """
            SELECT f.id, f.name, f.fund_type, f.cik,
                   (SELECT COUNT(*) FROM filings fl WHERE fl.fund_id = f.id) AS filing_count,
                   (SELECT MAX(fl.report_period) FROM filings fl WHERE fl.fund_id = f.id) AS latest_period,
                   (SELECT TOP 1 fl.total_value FROM filings fl
                    WHERE fl.fund_id = f.id
                    ORDER BY fl.report_period DESC, fl.filing_date DESC, fl.id DESC
                   ) AS latest_total_value
            FROM funds f WHERE f.id = :id
            """,
            {"id": fund_id},
        )
        if not fund:
            return _json_response({"error": "Fund not found"}, 404)
        return _json_response(fund)
    except Exception as e:
        logging.exception("Error getting fund")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}/holdings")
def get_holdings(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    period = req.params.get("period")

    try:
        sql = """
            WITH filing_rank AS (
                SELECT f.id, f.report_period, f.filing_date,
                       ROW_NUMBER() OVER (
                           PARTITION BY f.report_period
                           ORDER BY f.filing_date DESC, f.id DESC
                       ) AS rn
                FROM filings f WHERE f.fund_id = :fund_id
            ),
            current_filing AS (
                SELECT TOP 1 id, report_period, filing_date
                FROM filing_rank
                WHERE rn = 1 AND (:period IS NULL OR report_period = :period)
                ORDER BY report_period DESC
            ),
            prior_filing AS (
                SELECT TOP 1 fr.id
                FROM filing_rank fr CROSS JOIN current_filing cf
                WHERE fr.rn = 1 AND fr.report_period < cf.report_period
                ORDER BY fr.report_period DESC
            ),
            current_positions AS (
                SELECT UPPER(TRIM(COALESCE(h.ticker, h.cusip))) AS position_key,
                       MAX(h.ticker) AS ticker, MAX(h.cusip) AS cusip,
                       MAX(h.issuer_name) AS issuer_name, MAX(h.put_call) AS put_call,
                       SUM(h.shares) AS shares, SUM(h.value_usd) AS value_usd
                FROM holdings h CROSS JOIN current_filing cf
                WHERE h.filing_id = cf.id
                GROUP BY UPPER(TRIM(COALESCE(h.ticker, h.cusip)))
            ),
            prior_positions AS (
                SELECT UPPER(TRIM(COALESCE(h.ticker, h.cusip))) AS position_key,
                       MAX(h.ticker) AS ticker, MAX(h.cusip) AS cusip,
                       MAX(h.issuer_name) AS issuer_name, MAX(h.put_call) AS put_call,
                       SUM(h.shares) AS previous_shares, SUM(h.value_usd) AS previous_value
                FROM holdings h CROSS JOIN prior_filing pf
                WHERE h.filing_id = pf.id
                GROUP BY UPPER(TRIM(COALESCE(h.ticker, h.cusip)))
            ),
            positions AS (
                SELECT cp.position_key, cp.ticker, cp.cusip, cp.issuer_name, cp.put_call,
                       cp.shares, cp.value_usd, pp.previous_shares, 0 AS is_exit
                FROM current_positions cp
                LEFT JOIN prior_positions pp ON pp.position_key = cp.position_key
                UNION ALL
                SELECT pp.position_key, pp.ticker, pp.cusip, pp.issuer_name, pp.put_call,
                       0 AS shares, pp.previous_value AS value_usd,
                       pp.previous_shares, 1 AS is_exit
                FROM prior_positions pp
                LEFT JOIN current_positions cp ON cp.position_key = pp.position_key
                WHERE cp.position_key IS NULL
            )
            SELECT p.ticker, p.cusip, p.issuer_name, p.shares, p.value_usd,
                   p.put_call, cf.report_period, cf.filing_date,
                   CAST(CASE WHEN p.is_exit = 0 THEN p.value_usd * 100.0
                        / NULLIF(SUM(CASE WHEN p.is_exit = 0 THEN p.value_usd ELSE 0 END) OVER (), 0)
                        ELSE 0 END
                        AS DECIMAL(8,4)) AS weight_pct,
                   COALESCE(p.previous_shares, 0) AS previous_shares,
                   p.shares - COALESCE(p.previous_shares, 0) AS share_change,
                   CAST((p.shares - p.previous_shares) * 1.0
                        / NULLIF(p.previous_shares, 0) AS DECIMAL(18,6)) AS share_change_pct,
                   CASE WHEN p.is_exit = 1 THEN 'exit'
                        WHEN p.previous_shares IS NULL THEN 'new'
                        WHEN p.shares > p.previous_shares THEN 'added'
                        WHEN p.shares < p.previous_shares THEN 'reduced'
                        ELSE 'unchanged' END AS change_type,
                   CASE WHEN p.is_exit = 0 AND filed.price > 0 AND latest.price > 0
                        THEN (latest.price - filed.price) / filed.price END AS since_filed_return
            FROM positions p
            CROSS JOIN current_filing cf
            OUTER APPLY (
                SELECT TOP 1 CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS price
                FROM daily_prices dp
                WHERE dp.ticker = p.ticker AND dp.price_date >= cf.filing_date
                ORDER BY dp.price_date
            ) filed
            OUTER APPLY (
                SELECT TOP 1 CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS price
                FROM daily_prices dp WHERE dp.ticker = p.ticker
                ORDER BY dp.price_date DESC
            ) latest
            ORDER BY p.is_exit, p.value_usd DESC
        """
        params = {"fund_id": fund_id, "period": period}

        holdings = query_all(sql, params)
        periods = query_all(
            "SELECT DISTINCT report_period FROM filings WHERE fund_id = :id ORDER BY report_period DESC",
            {"id": fund_id},
        )
        return _json_response({
            "holdings": holdings,
            "available_periods": [p["report_period"] for p in periods],
        })
    except Exception as e:
        logging.exception("Error getting holdings")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}/backtest")
def get_backtest(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    try:
        results = query_all(
            """
            SELECT period_start, period_end, total_return, benchmark_return, alpha,
                   num_positions, computed_at
            FROM backtest_results
            WHERE fund_id = :id
            ORDER BY period_start
            """,
            {"id": fund_id},
        )
        return _json_response({"backtest": results})
    except Exception as e:
        logging.exception("Error getting backtest")
        return _json_response({"error": str(e)}, 500)


@app.route(route="trade-copy/rankings")
def trade_copy_rankings(req: func.HttpRequest) -> func.HttpResponse:
    """Rank funds using investable post-filing simulations and position hit rates."""
    try:
        rankings = query_all(
            """
            WITH period_metrics AS (
                SELECT
                    fund_id,
                    COUNT(*) AS periods,
                    MIN(entry_date) AS first_entry_date,
                    MAX(exit_date) AS last_exit_date,
                    EXP(SUM(LOG(CASE WHEN total_return > -0.999999
                                     THEN 1.0 + total_return ELSE 0.000001 END))) - 1.0
                        AS cumulative_return,
                    AVG(total_return) AS average_period_return,
                    AVG(alpha) AS average_alpha,
                    AVG(price_coverage) AS average_price_coverage,
                    AVG(turnover) AS average_turnover
                FROM trade_copy_results
                GROUP BY fund_id
            ),
            position_metrics AS (
                SELECT
                    fund_id,
                    SUM(CASE WHEN is_resolved = 1 AND trade_type IN ('new_buy', 'increase')
                             THEN 1 ELSE 0 END) AS resolved_trades,
                    SUM(CASE WHEN is_resolved = 1 AND trade_type IN ('new_buy', 'increase')
                                  AND total_return > 0 THEN 1 ELSE 0 END) AS winning_trades,
                    SUM(CASE WHEN is_resolved = 1 AND position_rank <= 10
                             THEN 1 ELSE 0 END) AS resolved_top10,
                    SUM(CASE WHEN is_resolved = 1 AND position_rank <= 10
                                  AND total_return > 0 THEN 1 ELSE 0 END) AS winning_top10,
                    SUM(CASE WHEN is_resolved = 1 AND trade_type IN ('new_buy', 'increase')
                                  AND excess_return > 0 THEN 1 ELSE 0 END) AS benchmark_beating_trades
                FROM trade_copy_position_results
                GROUP BY fund_id
            )
            SELECT
                f.id AS fund_id,
                f.name,
                f.fund_type,
                p.periods,
                p.first_entry_date,
                p.last_exit_date,
                p.cumulative_return,
                CASE WHEN DATEDIFF(day, p.first_entry_date, p.last_exit_date) > 0
                     AND 1.0 + p.cumulative_return > 0
                     THEN POWER(1.0 + p.cumulative_return,
                                365.0 / DATEDIFF(day, p.first_entry_date, p.last_exit_date)) - 1.0
                END AS annualized_return,
                p.average_period_return,
                p.average_alpha,
                p.average_price_coverage,
                p.average_turnover,
                m.resolved_trades,
                CAST(m.winning_trades * 1.0 / NULLIF(m.resolved_trades, 0) AS DECIMAL(12,6))
                    AS trade_hit_rate,
                CAST(m.benchmark_beating_trades * 1.0 / NULLIF(m.resolved_trades, 0) AS DECIMAL(12,6))
                    AS excess_hit_rate,
                m.resolved_top10,
                CAST(m.winning_top10 * 1.0 / NULLIF(m.resolved_top10, 0) AS DECIMAL(12,6))
                    AS top10_hit_rate
            FROM period_metrics p
            INNER JOIN funds f ON f.id = p.fund_id
            LEFT JOIN position_metrics m ON m.fund_id = p.fund_id
            ORDER BY annualized_return DESC, p.average_alpha DESC
            """
        )
        return _json_response({"rankings": rankings})
    except Exception as e:
        logging.exception("Error loading trade-copy rankings")
        return _json_response({"error": str(e)}, 500)


@app.route(route="quarterly-changes/quarters")
def quarterly_change_quarters(req: func.HttpRequest) -> func.HttpResponse:
    try:
        rows = query_all(
            "SELECT DISTINCT report_period FROM filings ORDER BY report_period DESC"
        )
        return _json_response({"quarters": [row["report_period"] for row in rows]})
    except Exception as e:
        logging.exception("Error loading quarterly-change periods")
        return _json_response({"error": str(e)}, 500)


@app.route(route="quarterly-changes")
def quarterly_changes(req: func.HttpRequest) -> func.HttpResponse:
    quarter = req.params.get("quarter")
    fund_type = req.params.get("fund_type")
    rank_by = req.params.get("rank_by", "fund_count")
    if not quarter:
        return _json_response({"error": "quarter is required"}, 400)
    if fund_type not in (None, "Long Only", "Hedge Core"):
        return _json_response({"error": "invalid fund_type"}, 400)
    if rank_by not in ("fund_count", "group_percentage"):
        return _json_response({"error": "invalid rank_by"}, 400)

    try:
        rows = query_all(
            """
            WITH eligible_funds AS (
                SELECT id
                FROM funds
                WHERE is_active = 1
                  AND (:fund_type IS NULL OR fund_type = :fund_type)
            ),
            filing_rank AS (
                SELECT fl.id, fl.fund_id, fl.report_period,
                       ROW_NUMBER() OVER (
                           PARTITION BY fl.fund_id, fl.report_period
                           ORDER BY fl.filing_date DESC, fl.id DESC
                       ) AS rn
                FROM filings fl
                INNER JOIN eligible_funds ef ON ef.id = fl.fund_id
            ),
            current_filings AS (
                SELECT id, fund_id, report_period
                FROM filing_rank
                WHERE rn = 1 AND report_period = :quarter
            ),
            prior_filings AS (
                SELECT cf.fund_id, prior_f.id, prior_f.report_period
                FROM current_filings cf
                CROSS APPLY (
                    SELECT TOP 1 id, report_period
                    FROM filing_rank
                    WHERE fund_id = cf.fund_id
                      AND rn = 1
                      AND report_period < cf.report_period
                    ORDER BY report_period DESC
                ) prior_f
            ),
            current_positions AS (
                SELECT cf.fund_id, UPPER(TRIM(h.ticker)) AS ticker,
                       SUM(h.value_usd) AS position_value,
                       SUM(h.shares) AS position_shares
                FROM current_filings cf
                INNER JOIN prior_filings comparable ON comparable.fund_id = cf.fund_id
                INNER JOIN holdings h ON h.filing_id = cf.id
                WHERE h.ticker IS NOT NULL AND TRIM(h.ticker) <> ''
                  AND (h.put_call IS NULL OR h.put_call = '')
                GROUP BY cf.fund_id, UPPER(TRIM(h.ticker))
            ),
            prior_positions AS (
                SELECT pf.fund_id, UPPER(TRIM(h.ticker)) AS ticker,
                       SUM(h.value_usd) AS position_value,
                       SUM(h.shares) AS position_shares
                FROM prior_filings pf
                INNER JOIN holdings h ON h.filing_id = pf.id
                WHERE h.ticker IS NOT NULL AND TRIM(h.ticker) <> ''
                  AND (h.put_call IS NULL OR h.put_call = '')
                GROUP BY pf.fund_id, UPPER(TRIM(h.ticker))
            ),
            group_totals AS (
                SELECT
                    (SELECT SUM(position_value) FROM current_positions) AS current_total,
                    (SELECT SUM(position_value) FROM prior_positions) AS previous_total
            ),
            fund_changes AS (
                SELECT
                    COALESCE(c.fund_id, p.fund_id) AS fund_id,
                    COALESCE(c.ticker, p.ticker) AS ticker,
                    COALESCE(c.position_value, 0) AS current_value,
                    COALESCE(p.position_value, 0) AS previous_value,
                    CASE
                        WHEN p.ticker IS NULL THEN 'new'
                        WHEN c.ticker IS NULL THEN 'exit'
                        WHEN c.position_shares > p.position_shares THEN 'add'
                        WHEN c.position_shares < p.position_shares THEN 'reduce'
                    END AS change_type
                FROM current_positions c
                FULL OUTER JOIN prior_positions p
                  ON p.fund_id = c.fund_id AND p.ticker = c.ticker
            ),
            aggregated AS (
                SELECT
                    fc.change_type,
                    fc.ticker,
                    COUNT(DISTINCT fc.fund_id) AS fund_count,
                    SUM(fc.current_value) AS current_value,
                    SUM(fc.previous_value) AS previous_value,
                    CAST(SUM(fc.current_value) * 1.0 / NULLIF(gt.current_total, 0)
                         AS DECIMAL(18,8)) AS current_group_percentage,
                    CAST(SUM(fc.previous_value) * 1.0 / NULLIF(gt.previous_total, 0)
                         AS DECIMAL(18,8)) AS previous_group_percentage,
                    CAST(
                        SUM(fc.current_value) * 1.0 / NULLIF(gt.current_total, 0)
                        - SUM(fc.previous_value) * 1.0 / NULLIF(gt.previous_total, 0)
                        AS DECIMAL(18,8)
                    ) AS group_percentage_change
                FROM fund_changes fc
                CROSS JOIN group_totals gt
                WHERE fc.change_type IS NOT NULL
                GROUP BY fc.change_type, fc.ticker, gt.current_total, gt.previous_total
            ),
            ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY change_type
                    ORDER BY
                        CASE WHEN :rank_by = 'fund_count' THEN fund_count END DESC,
                        CASE WHEN :rank_by = 'group_percentage'
                             THEN ABS(group_percentage_change) END DESC,
                        fund_count DESC,
                        ticker
                ) AS rank_number
                FROM aggregated
            )
            SELECT change_type, ticker, fund_count, current_value, previous_value,
                   current_group_percentage, previous_group_percentage,
                   group_percentage_change, rank_number
            FROM ranked
            WHERE rank_number <= 5
            ORDER BY CASE change_type
                         WHEN 'new' THEN 1 WHEN 'add' THEN 2
                         WHEN 'reduce' THEN 3 WHEN 'exit' THEN 4 END,
                     rank_number
            """,
            {"quarter": quarter, "fund_type": fund_type, "rank_by": rank_by},
        )
        grouped = {"new": [], "add": [], "reduce": [], "exit": []}
        for row in rows:
            grouped[row["change_type"]].append(row)
        return _json_response(
            {
                "quarter": quarter,
                "fund_type": fund_type or "All",
                "rank_by": rank_by,
                "changes": grouped,
            }
        )
    except Exception as e:
        logging.exception("Error calculating quarterly changes")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}/trade-copy")
def get_fund_trade_copy(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    try:
        results = query_all(
            """
            SELECT id, signal_filing_id, signal_date, entry_date, exit_date,
                   total_return, benchmark_return, alpha, turnover, transaction_cost,
                   price_coverage, unresolved_policy, num_positions,
                   no_start_price_positions, delisted_positions,
                   resolved_event_positions, unresolved_positions, computed_at
            FROM trade_copy_results
            WHERE fund_id = :fund_id
            ORDER BY entry_date
            """,
            {"fund_id": fund_id},
        )
        return _json_response({"trade_copy": results})
    except Exception as e:
        logging.exception("Error loading fund trade-copy results")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}/trade-copy/attribution")
def get_fund_trade_copy_attribution(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    try:
        rows = query_all(
            """
            SELECT ticker,
                   SUM(contribution) AS contribution,
                   SUM(CASE WHEN excess_return IS NOT NULL
                            THEN target_weight * excess_return END) AS excess_contribution,
                   COUNT(*) AS periods,
                   AVG(total_return) AS average_return
            FROM trade_copy_position_results
            WHERE fund_id = :fund_id AND is_resolved = 1
            GROUP BY ticker
            """,
            {"fund_id": fund_id},
        )
        ranked = sorted(rows, key=lambda row: float(row["contribution"] or 0))
        tickers = sorted({str(row["ticker"]) for row in rows if row["ticker"]})
        return _json_response({
            "contributors": list(reversed(ranked[-10:])),
            "detractors": ranked[:10],
            "tickers": tickers,
        })
    except Exception as e:
        logging.exception("Error loading trade-copy attribution")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}/trade-copy/prices")
def get_fund_trade_copy_prices(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    ticker = (req.params.get("ticker") or "").strip().upper()
    if not ticker:
        return _json_response({"error": "ticker is required"}, 400)
    try:
        prices = query_all(
            """
            WITH bounds AS (
                SELECT DATEADD(day, -30, MIN(f.filing_date)) AS first_date,
                       DATEADD(day, 30, MAX(f.filing_date)) AS last_date
                FROM filings f
                INNER JOIN holdings h ON h.filing_id = f.id
                WHERE f.fund_id = :fund_id AND UPPER(TRIM(h.ticker)) = :ticker
            ), ranked AS (
                SELECT dp.price_date, COALESCE(dp.adj_close, dp.close_price) AS price,
                       ROW_NUMBER() OVER (ORDER BY dp.price_date) AS rn
                FROM daily_prices dp CROSS JOIN bounds b
                WHERE dp.ticker = :ticker
                  AND dp.price_date BETWEEN b.first_date AND
                      CASE WHEN b.last_date > CAST(GETDATE() AS DATE)
                           THEN CAST(GETDATE() AS DATE) ELSE b.last_date END
            )
            SELECT price_date, price FROM ranked
            WHERE rn % 3 = 1 OR EXISTS (
                SELECT 1 FROM filings f
                WHERE f.fund_id = :fund_id
                  AND f.filing_date BETWEEN DATEADD(day, -3, ranked.price_date) AND ranked.price_date
            )
            ORDER BY price_date
            """,
            {"fund_id": fund_id, "ticker": ticker},
        )
        signals = query_all(
            """
            WITH filing_rank AS (
                SELECT f.id, f.filing_date, f.report_period,
                       ROW_NUMBER() OVER (
                           PARTITION BY f.report_period ORDER BY f.filing_date, f.id
                       ) AS rn
                FROM filings f
                WHERE f.fund_id = :fund_id AND f.form_type = '13F-HR'
            ),
            filing_positions AS (
                SELECT fr.id, fr.filing_date, fr.report_period,
                       COALESCE(SUM(h.value_usd), 0) AS position_value,
                       COALESCE(SUM(h.shares), 0) AS position_shares
                FROM filing_rank fr
                LEFT JOIN holdings h ON h.filing_id = fr.id
                    AND UPPER(TRIM(h.ticker)) = :ticker
                    AND (h.put_call IS NULL OR h.put_call = '')
                WHERE fr.rn = 1
                GROUP BY fr.id, fr.filing_date, fr.report_period
            ), first_owned AS (
                SELECT MIN(report_period) report_period
                FROM filing_positions WHERE position_shares>0
            ),
            compared AS (
                SELECT *,
                       LAG(position_value) OVER (ORDER BY report_period) AS previous_value,
                       LAG(position_shares) OVER (ORDER BY report_period) AS previous_shares
                FROM filing_positions
            )
            SELECT filing_date, marker.price_date AS marker_date,
                   report_period, position_value, previous_value,
                   position_shares, previous_shares,
                   CASE WHEN position_shares > 0 AND COALESCE(previous_shares, 0) = 0 THEN 'new'
                        WHEN position_shares > previous_shares THEN 'add'
                        WHEN position_shares = 0 AND previous_shares > 0 THEN 'exit'
                        WHEN position_shares < previous_shares THEN 'reduce' END AS action
            FROM compared
            CROSS JOIN first_owned first_seen
            OUTER APPLY (
                SELECT TOP 1 dp.price_date FROM daily_prices dp
                WHERE dp.ticker = :ticker AND dp.price_date >= compared.filing_date
                ORDER BY dp.price_date
            ) marker
            WHERE compared.report_period>=first_seen.report_period
            ORDER BY filing_date
            """,
            {"fund_id": fund_id, "ticker": ticker},
        )
        return _json_response({"ticker": ticker, "prices": prices, "signals": signals})
    except Exception as e:
        logging.exception("Error loading ticker history")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}/filings")
def get_filings(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    try:
        filings = query_all(
            """
            SELECT id, accession_no, form_type, report_period, filing_date, total_value, total_holdings
            FROM filings
            WHERE fund_id = :id
            ORDER BY report_period DESC
            """,
            {"id": fund_id},
        )
        return _json_response({"filings": filings})
    except Exception as e:
        logging.exception("Error getting filings")
        return _json_response({"error": str(e)}, 500)


def _dashboard_recent_quarters():
    return query_all(
        """
        WITH recent_periods AS (
            SELECT TOP 4 report_period
            FROM filings
            GROUP BY report_period
            ORDER BY report_period DESC
        ),
        latest_period AS (
            SELECT MAX(report_period) AS report_period FROM recent_periods
        ),
        reporting AS (
            SELECT fl.report_period, COUNT(DISTINCT fl.fund_id) AS reporting_count
            FROM filings fl
            INNER JOIN funds f ON f.id = fl.fund_id AND f.is_active = 1
            GROUP BY fl.report_period
        ),
        historical_performance AS (
            SELECT b.period_start, MAX(b.period_end) AS period_end,
                   AVG(b.total_return) AS aggregate_return,
                   AVG(b.benchmark_return) AS benchmark_return,
                   AVG(b.alpha) AS aggregate_alpha,
                   COUNT(DISTINCT b.fund_id) AS fund_count
            FROM backtest_results b
            INNER JOIN funds f ON f.id = b.fund_id AND f.is_active = 1
            GROUP BY b.period_start
        ),
        latest_filing_rank AS (
            SELECT fl.id, fl.fund_id, fl.report_period,
                   ROW_NUMBER() OVER (
                       PARTITION BY fl.fund_id, fl.report_period
                       ORDER BY fl.filing_date DESC, fl.id DESC
                   ) AS rn
            FROM filings fl
            INNER JOIN funds f ON f.id = fl.fund_id AND f.is_active = 1
            INNER JOIN latest_period lp ON lp.report_period = fl.report_period
        ),
        latest_positions AS (
            SELECT lfr.fund_id, UPPER(TRIM(h.ticker)) AS ticker,
                   SUM(h.value_usd) AS position_value
            FROM latest_filing_rank lfr
            INNER JOIN holdings h ON h.filing_id = lfr.id
            WHERE lfr.rn = 1 AND h.ticker IS NOT NULL AND TRIM(h.ticker) <> ''
              AND (h.put_call IS NULL OR h.put_call = '')
            GROUP BY lfr.fund_id, UPPER(TRIM(h.ticker))
        ),
        latest_position_returns AS (
            SELECT lp.fund_id, lp.position_value,
                   CASE WHEN qtr.price > 0 AND latest.price > 0
                        THEN (latest.price - qtr.price) / qtr.price END AS position_return
            FROM latest_positions lp
            CROSS JOIN latest_period period
            OUTER APPLY (
                SELECT TOP 1 CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS price
                FROM daily_prices dp
                WHERE dp.ticker = lp.ticker AND dp.price_date <= period.report_period
                ORDER BY dp.price_date DESC
            ) qtr
            OUTER APPLY (
                SELECT TOP 1 CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS price
                FROM daily_prices dp WHERE dp.ticker = lp.ticker
                ORDER BY dp.price_date DESC
            ) latest
        ),
        latest_fund_returns AS (
            SELECT fund_id,
                   SUM(CASE WHEN position_return IS NOT NULL AND position_value > 0
                            THEN CAST(position_value AS FLOAT) * position_return ELSE 0.0 END)
                   / NULLIF(SUM(CASE WHEN position_value > 0
                                     THEN CAST(position_value AS FLOAT) ELSE 0.0 END), 0.0) AS total_return
            FROM latest_position_returns
            GROUP BY fund_id
        ),
        latest_qtd AS (
            SELECT period.report_period AS period_start,
                   spy_latest.price_date AS period_end,
                   AVG(lfr.total_return) AS aggregate_return,
                   (spy_latest.price - spy_qtr.price) / NULLIF(spy_qtr.price, 0) AS benchmark_return,
                   AVG(lfr.total_return)
                     - (spy_latest.price - spy_qtr.price) / NULLIF(spy_qtr.price, 0) AS aggregate_alpha,
                   COUNT(*) AS fund_count
            FROM latest_fund_returns lfr
            CROSS JOIN latest_period period
            CROSS APPLY (
                SELECT TOP 1 dp.price_date,
                       CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS price
                FROM daily_prices dp
                WHERE dp.ticker = 'SPY' AND dp.price_date <= period.report_period
                ORDER BY dp.price_date DESC
            ) spy_qtr
            CROSS APPLY (
                SELECT TOP 1 dp.price_date,
                       CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS price
                FROM daily_prices dp WHERE dp.ticker = 'SPY'
                ORDER BY dp.price_date DESC
            ) spy_latest
            GROUP BY period.report_period, spy_latest.price_date,
                     spy_latest.price, spy_qtr.price
        ),
        performance AS (
            SELECT * FROM historical_performance
            WHERE period_start <> (SELECT report_period FROM latest_period)
            UNION ALL
            SELECT * FROM latest_qtd
        )
        SELECT rp.report_period AS period_start, p.period_end,
               p.aggregate_return, p.benchmark_return, p.aggregate_alpha,
               COALESCE(p.fund_count, 0) AS fund_count,
               COALESCE(r.reporting_count, 0) AS reporting_count,
               (SELECT COUNT(*) FROM funds WHERE is_active = 1) AS total_funds
        FROM recent_periods rp
        LEFT JOIN reporting r ON r.report_period = rp.report_period
        LEFT JOIN performance p ON p.period_start = rp.report_period
        ORDER BY rp.report_period DESC
        """
    )


def _dashboard_funds():
    return query_all(
        """
        WITH latest_filing AS (
            SELECT fl.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY fl.fund_id
                       ORDER BY fl.report_period DESC, fl.filing_date DESC, fl.id DESC
                   ) AS rn
            FROM filings fl
        ),
        backtest_growth AS (
            SELECT fund_id, COUNT(*) AS backtest_periods,
                   MIN(period_start) AS first_period, MAX(period_end) AS last_period,
                   EXP(SUM(LOG(CASE WHEN total_return > -0.999999
                                    THEN 1.0 + total_return ELSE 0.000001 END))) AS portfolio_growth,
                   EXP(SUM(LOG(CASE WHEN benchmark_return IS NULL THEN 1.0
                                    WHEN benchmark_return > -0.999999
                                    THEN 1.0 + benchmark_return ELSE 0.000001 END))) AS benchmark_growth
            FROM backtest_results
            GROUP BY fund_id
        )
        SELECT f.id AS fund_id, f.name, f.fund_type,
               lf.total_value AS aum,
               COALESCE(lf.total_holdings, hv.holdings_count) AS holdings,
               lf.report_period AS latest_quarter, lf.filing_date,
               bg.backtest_periods,
               CASE WHEN DATEDIFF(day, bg.first_period, bg.last_period) > 0
                    THEN POWER(bg.portfolio_growth,
                               365.0 / DATEDIFF(day, bg.first_period, bg.last_period)) - 1.0
               END AS annualized_return,
               CASE WHEN DATEDIFF(day, bg.first_period, bg.last_period) > 0
                    THEN POWER(bg.portfolio_growth,
                               365.0 / DATEDIFF(day, bg.first_period, bg.last_period))
                         - POWER(bg.benchmark_growth,
                                 365.0 / DATEDIFF(day, bg.first_period, bg.last_period))
               END AS annualized_alpha
        FROM funds f
        LEFT JOIN latest_filing lf ON lf.fund_id = f.id AND lf.rn = 1
        OUTER APPLY (
            SELECT SUM(h.value_usd) AS holdings_value, COUNT(*) AS holdings_count
            FROM holdings h WHERE h.filing_id = lf.id
        ) hv
        LEFT JOIN backtest_growth bg ON bg.fund_id = f.id
        WHERE f.is_active = 1
        ORDER BY f.name
        """
    )


def _dashboard_consensus(latest_quarter):
    return query_all(
        """
        WITH filing_rank AS (
            SELECT fl.id, fl.fund_id, fl.report_period,
                   ROW_NUMBER() OVER (
                       PARTITION BY fl.fund_id, fl.report_period
                       ORDER BY fl.filing_date DESC, fl.id DESC
                   ) AS rn
            FROM filings fl
            INNER JOIN funds f ON f.id = fl.fund_id AND f.is_active = 1
        ),
        current_filings AS (
            SELECT id, fund_id, report_period FROM filing_rank
            WHERE rn = 1 AND report_period = :quarter
        ),
        prior_filings AS (
            SELECT cf.fund_id, prior_f.id
            FROM current_filings cf
            CROSS APPLY (
                SELECT TOP 1 id FROM filing_rank
                WHERE fund_id = cf.fund_id AND rn = 1
                  AND report_period < cf.report_period
                ORDER BY report_period DESC
            ) prior_f
        ),
        current_positions AS (
            SELECT cf.fund_id, UPPER(TRIM(h.ticker)) AS ticker,
                   MAX(h.issuer_name) AS company,
                   SUM(h.shares) AS shares, SUM(h.value_usd) AS position_value
            FROM current_filings cf
            INNER JOIN prior_filings pf ON pf.fund_id = cf.fund_id
            INNER JOIN holdings h ON h.filing_id = cf.id
            WHERE h.ticker IS NOT NULL AND TRIM(h.ticker) <> ''
              AND (h.put_call IS NULL OR h.put_call = '')
            GROUP BY cf.fund_id, UPPER(TRIM(h.ticker))
        ),
        prior_positions AS (
            SELECT pf.fund_id, UPPER(TRIM(h.ticker)) AS ticker,
                   MAX(h.issuer_name) AS company,
                   SUM(h.shares) AS shares, SUM(h.value_usd) AS position_value
            FROM prior_filings pf
            INNER JOIN holdings h ON h.filing_id = pf.id
            WHERE h.ticker IS NOT NULL AND TRIM(h.ticker) <> ''
              AND (h.put_call IS NULL OR h.put_call = '')
            GROUP BY pf.fund_id, UPPER(TRIM(h.ticker))
        ),
        changes AS (
            SELECT COALESCE(c.fund_id, p.fund_id) AS fund_id,
                   COALESCE(c.ticker, p.ticker) AS ticker,
                   COALESCE(c.company, p.company) AS company,
                   COALESCE(c.position_value, 0) AS current_value,
                   COALESCE(p.position_value, 0) AS previous_value,
                   COALESCE(c.shares, 0) AS current_shares,
                   COALESCE(p.shares, 0) AS previous_shares,
                   CASE WHEN p.ticker IS NULL THEN 'buy'
                        WHEN c.ticker IS NULL THEN 'sell'
                        WHEN c.shares > p.shares THEN 'buy'
                        WHEN c.shares < p.shares THEN 'sell' END AS side
            FROM current_positions c
            FULL OUTER JOIN prior_positions p
              ON p.fund_id = c.fund_id AND p.ticker = c.ticker
        ),
        aggregated AS (
            SELECT side, ticker, MAX(company) AS company,
                   COUNT(DISTINCT fund_id) AS fund_count,
                   SUM(current_shares - previous_shares) AS net_share_change
            FROM changes WHERE side IS NOT NULL
            GROUP BY side, ticker
        ),
        enriched AS (
            SELECT a.*,
                   a.net_share_change * qtr.market_price AS net_change,
                   CASE WHEN qtr.return_price IS NOT NULL AND qtr.return_price > 0
                        THEN (latest.price - qtr.return_price) / qtr.return_price END AS move_since_quarter_end,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.side
                       ORDER BY a.fund_count DESC,
                                ABS(a.net_share_change * qtr.market_price) DESC, a.ticker
                   ) AS rank_number
            FROM aggregated a
            OUTER APPLY (
                SELECT TOP 1 CAST(dp.close_price AS FLOAT) AS market_price,
                       CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS return_price
                FROM daily_prices dp
                WHERE dp.ticker = a.ticker AND dp.price_date <= :quarter
                ORDER BY dp.price_date DESC
            ) qtr
            OUTER APPLY (
                SELECT TOP 1 CAST(COALESCE(dp.adj_close, dp.close_price) AS FLOAT) AS price
                FROM daily_prices dp WHERE dp.ticker = a.ticker
                ORDER BY dp.price_date DESC
            ) latest
        )
        SELECT side, ticker, company, fund_count, move_since_quarter_end,
               net_change, rank_number
        FROM enriched WHERE rank_number <= 10
        ORDER BY CASE side WHEN 'buy' THEN 1 ELSE 2 END, rank_number
        """,
        {"quarter": latest_quarter},
    )


@app.route(route="dashboard")
def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    try:
        recent_quarters = _dashboard_recent_quarters()
        funds = _dashboard_funds()
        latest_row = query_one("SELECT MAX(report_period) AS quarter FROM filings")
        latest_quarter = latest_row["quarter"] if latest_row else None
        consensus = _dashboard_consensus(latest_quarter) if latest_quarter else []
        grouped = {"buys": [], "sells": []}
        for row in consensus:
            grouped["buys" if row["side"] == "buy" else "sells"].append(row)
        return _json_response({
            "recent_quarters": recent_quarters,
            "latest_quarter": latest_quarter,
            "consensus": grouped,
            "funds": funds,
        })
    except Exception as e:
        logging.exception("Error getting dashboard")
        return _json_response({"error": str(e)}, 500)
