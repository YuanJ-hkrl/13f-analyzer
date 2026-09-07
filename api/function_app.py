import azure.functions as func
import json
import logging
import time

from shared.db import cached, capture_read_timings, query_all, query_one
from shared.analytics import rank_alpha, recent_strategy_trades

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _json_response(data, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status_code,
        mimetype="application/json",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
        },
    )


@app.route(route="health")
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json_response({"status": "ok", "service": "13f-analyzer"})


@app.route(route="securities")
def list_securities(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("q") or "").strip()
    try:
        rows = cached(f"securities:{search.lower()}", lambda: query_all(
            """
            WITH names AS (
                SELECT ticker,MAX(issuer_name) company FROM securities
                WHERE ticker IS NOT NULL AND TRIM(ticker)<>'' GROUP BY ticker
                UNION
                SELECT ticker,MAX(issuer_name) company FROM latest_fund_positions
                WHERE ticker IS NOT NULL AND is_exit=0 GROUP BY ticker
            ), ownership AS (
                SELECT ticker,COUNT(DISTINCT fund_id) owner_count,
                       SUM(value_usd) aggregate_value
                FROM latest_fund_positions
                WHERE ticker IS NOT NULL AND is_exit=0
                GROUP BY ticker
            )
            SELECT TOP 100 n.ticker,n.company,COALESCE(o.owner_count,0) owner_count,
                   COALESCE(o.aggregate_value,0) aggregate_value,
                   p.price AS latest_price, p.price_date
            FROM names n LEFT JOIN ownership o ON o.ticker=n.ticker
            OUTER APPLY (SELECT TOP 1 dp.price_date, COALESCE(dp.adj_close,dp.close_price) price
                         FROM daily_prices dp WHERE dp.ticker=n.ticker ORDER BY dp.price_date DESC) p
            WHERE :search = '' OR n.ticker LIKE :pattern OR n.company LIKE :pattern
            ORDER BY CASE WHEN n.ticker=:exact THEN 0 ELSE 1 END, o.owner_count DESC, n.ticker
            """,
            {"search": search, "pattern": f"%{search}%", "exact": search.upper()},
        ), 300)
        return _json_response({"securities": rows})
    except Exception as e:
        logging.exception("Error searching securities")
        return _json_response({"error": str(e)}, 500)


@app.route(route="securities/{ticker}")
def get_security(req: func.HttpRequest) -> func.HttpResponse:
    ticker = str(req.route_params["ticker"]).strip().upper()
    return cached(
        f"security-detail:{ticker}",
        lambda: _load_security(req),
        900,
    )


def _load_security(req: func.HttpRequest) -> func.HttpResponse:
    ticker = str(req.route_params["ticker"]).strip().upper()
    params = {"ticker": ticker}
    try:
        security = query_one(
            """
            SELECT TOP 1 :ticker ticker,p.issuer_name company,
                   MIN(p.report_period) OVER() first_appearance,
                   lp.price latest_price, lp.price_date
            FROM fund_quarter_positions p
            OUTER APPLY (SELECT TOP 1 dp.price_date, COALESCE(dp.adj_close,dp.close_price) price
                         FROM daily_prices dp WHERE dp.ticker=:ticker ORDER BY dp.price_date DESC) lp
            WHERE p.ticker=:ticker
            ORDER BY p.report_period DESC,p.filing_date DESC
            """, params)
        if not security:
            return _json_response({"error": "Security not found"}, 404)

        history = query_all(
            """
            WITH periods AS (
              SELECT DISTINCT report_period FROM fund_quarter_positions
            ), first_owned AS (
              SELECT MIN(report_period) report_period FROM fund_quarter_positions
              WHERE ticker=:ticker AND shares>0 AND is_exit=0
            ), positions AS (
              SELECT report_period,fund_id,value_usd position_value,shares
              FROM fund_quarter_positions
              WHERE ticker=:ticker AND is_exit=0
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
            WITH first_owned AS (SELECT fund_id,MIN(report_period) first_owned
              FROM fund_quarter_positions WHERE ticker=:ticker AND is_exit=0 GROUP BY fund_id)
            SELECT fu.id fund_id,fu.name,fu.fund_type,c.report_period,c.value_usd,c.shares,
                   c.portfolio_weight,
                   fo.first_owned
            FROM latest_fund_positions c JOIN funds fu ON fu.id=c.fund_id
            JOIN first_owned fo ON fo.fund_id=c.fund_id
            WHERE c.ticker=:ticker AND c.is_exit=0 AND c.value_usd>0 ORDER BY c.value_usd DESC
            """, params)
        activity = query_all(
            """
            SELECT p.fund_id,fu.name,fu.fund_type,p.shares,p.previous_shares,
                   p.value_usd,p.previous_value,
                   CASE p.change_type WHEN 'added' THEN 'add' WHEN 'reduced' THEN 'reduce'
                        ELSE p.change_type END action
            FROM fund_quarter_positions p JOIN funds fu ON fu.id=p.fund_id
            WHERE p.report_period=(SELECT MAX(report_period) FROM fund_quarter_positions)
              AND p.ticker=:ticker AND p.change_type<>'unchanged'
            ORDER BY ABS(p.share_change) DESC
            """, params)
        position_changes = query_all(
            """
            WITH recent_periods AS (
              SELECT TOP 8 report_period
              FROM fund_quarter_positions
              GROUP BY report_period
              ORDER BY report_period DESC
            ), relevant_funds AS (
              SELECT DISTINCT fund_id FROM fund_quarter_positions
              WHERE report_period IN (SELECT report_period FROM recent_periods)
                AND ticker=:ticker
                AND (shares>0 OR previous_shares>0)
            )
            SELECT p.fund_id,fu.name,fu.fund_type,p.report_period,
                   p.shares,p.previous_shares,
                   CASE p.change_type WHEN 'added' THEN 'add' WHEN 'reduced' THEN 'reduce'
                        ELSE p.change_type END action
            FROM fund_quarter_positions p
            JOIN relevant_funds r ON r.fund_id=p.fund_id
            JOIN funds fu ON fu.id=p.fund_id
            WHERE p.ticker=:ticker AND p.report_period IN (SELECT report_period FROM recent_periods)
            ORDER BY fu.name,p.report_period DESC
            """, params)
        position_change_quarters = query_all(
            """SELECT TOP 8 report_period
               FROM fund_quarter_positions GROUP BY report_period ORDER BY report_period DESC"""
        )
        prices = query_all(
            """WITH p AS (SELECT price_date,COALESCE(adj_close,close_price) price,ROW_NUMBER() OVER(ORDER BY price_date) rn FROM daily_prices WHERE ticker=:ticker)
               SELECT price_date,price FROM p WHERE rn%5=1 ORDER BY price_date""", params)
        return _json_response({"security": security, "history": history, "owners": owners,
                               "buyers": [r for r in activity if r["action"] in ("new","add")],
                               "sellers": [r for r in activity if r["action"] in ("reduce","exit")],
                               "position_changes": {
                                   "quarters": [r["report_period"] for r in position_change_quarters],
                                   "rows": position_changes,
                               },
                               "prices": prices})
    except Exception as e:
        logging.exception("Error loading security")
        return _json_response({"error": str(e)}, 500)


def _fund_summaries_persisted(fund_type=None, fund_id=None):
    filters=["f.is_active=1"]
    params={}
    if fund_type: filters.append("f.fund_type=:fund_type"); params["fund_type"]=fund_type
    if fund_id is not None: filters.append("f.id=:fund_id"); params["fund_id"]=fund_id
    where=" AND ".join(filters)
    funds=query_all(f"""
      WITH filing_rank AS (
        SELECT fl.*,ROW_NUMBER() OVER(PARTITION BY fund_id ORDER BY report_period DESC,filing_date DESC,id DESC) rn,
               COUNT(*) OVER(PARTITION BY fund_id) filing_count FROM filings fl
      ), owned AS (
        SELECT p.*,SUM(CASE WHEN change_type='new' THEN 1 ELSE 0 END) OVER(
          PARTITION BY fund_id,position_key ORDER BY report_period) episode_group
        FROM fund_quarter_positions p WHERE is_exit=0 AND value_usd>0
      ), episodes AS (
        SELECT fund_id,position_key,episode_group,COUNT(*) quarters_held,MAX(report_period) last_period
        FROM owned GROUP BY fund_id,position_key,episode_group
      ), latest_periods AS (
        SELECT fund_id,MAX(report_period) latest_period FROM fund_quarter_positions GROUP BY fund_id
      ), holding_periods AS (
        SELECT e.fund_id,AVG(CAST(e.quarters_held AS FLOAT)) average_holding_period_quarters
        FROM episodes e JOIN latest_periods lp ON lp.fund_id=e.fund_id
        WHERE e.last_period<lp.latest_period GROUP BY e.fund_id
      ), position_returns AS (
        SELECT p.fund_id,p.value_usd,
          CASE WHEN q.price>0 AND latest.price>0 THEN (latest.price-q.price)/q.price END position_return
        FROM latest_fund_positions p
        OUTER APPLY(SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price
          FROM daily_prices dp WHERE dp.ticker=p.ticker AND dp.price_date<=p.report_period ORDER BY dp.price_date DESC) q
        OUTER APPLY(SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price
          FROM daily_prices dp WHERE dp.ticker=p.ticker ORDER BY dp.price_date DESC) latest
        WHERE p.is_exit=0
      ), returns AS (
        SELECT fund_id,SUM(CASE WHEN position_return IS NOT NULL THEN CAST(value_usd AS FLOAT)*position_return ELSE 0 END)
          /NULLIF(SUM(CASE WHEN position_return IS NOT NULL THEN CAST(value_usd AS FLOAT) ELSE 0 END),0) return_since_report
        FROM position_returns GROUP BY fund_id
      )
      SELECT f.id,f.name,f.fund_type,f.cik,fl.filing_count,fl.report_period latest_period,
             fl.filing_date latest_filing_date,fl.total_value latest_total_value,
             r.return_since_report,hp.average_holding_period_quarters
      FROM funds f LEFT JOIN filing_rank fl ON fl.fund_id=f.id AND fl.rn=1
      LEFT JOIN returns r ON r.fund_id=f.id LEFT JOIN holding_periods hp ON hp.fund_id=f.id
      WHERE {where} ORDER BY f.fund_type,f.name
    """,params)
    top=query_all(f"""
      WITH ranked AS (SELECT p.fund_id,p.ticker,p.issuer_name,p.value_usd position_value,
        ROW_NUMBER() OVER(PARTITION BY p.fund_id ORDER BY p.value_usd DESC) rn
        FROM latest_fund_positions p JOIN funds f ON f.id=p.fund_id WHERE {where} AND p.is_exit=0)
      SELECT fund_id,ticker,issuer_name,position_value FROM ranked WHERE rn<=5 ORDER BY fund_id,rn
    """,params)
    by_fund={row["id"]:[] for row in funds}
    for position in top: by_fund.setdefault(position["fund_id"],[]).append(position)
    for fund in funds: fund["top_positions"]=by_fund.get(fund["id"],[])
    return funds


def _fund_summaries(fund_type=None, fund_id=None):
    return _fund_summaries_persisted(fund_type,fund_id)


def _fund_summaries_legacy(fund_type=None, fund_id=None):
    filters = ["f.is_active = 1"]
    params = {}
    if fund_type:
        filters.append("f.fund_type = :fund_type")
        params["fund_type"] = fund_type
    if fund_id is not None:
        filters.append("f.id = :fund_id")
        params["fund_id"] = fund_id
    where_clause = " AND ".join(filters)
    funds = query_all(
        f"""
        WITH filing_rank AS (
          SELECT fl.*,
                 ROW_NUMBER() OVER(PARTITION BY fl.fund_id
                   ORDER BY fl.report_period DESC,fl.filing_date DESC,fl.id DESC) rn
          FROM filings fl
        ), quarterly_filing_rank AS (
          SELECT fl.*,
                 ROW_NUMBER() OVER(PARTITION BY fl.fund_id,fl.report_period
                   ORDER BY fl.filing_date DESC,fl.id DESC) quarter_rn
          FROM filings fl
        ), fund_filings AS (
          SELECT id,fund_id,report_period,
                 ROW_NUMBER() OVER(PARTITION BY fund_id ORDER BY report_period) filing_sequence
          FROM quarterly_filing_rank WHERE quarter_rn=1
        ), current_filings AS (
          SELECT * FROM filing_rank WHERE rn=1
        ), current_positions AS (
          SELECT cf.fund_id,cf.report_period,
                 UPPER(TRIM(COALESCE(NULLIF(h.cusip,''),h.ticker))) position_key,
                 MAX(h.ticker) ticker,MAX(h.issuer_name) issuer_name,
                 SUM(h.value_usd) position_value
          FROM current_filings cf JOIN holdings h ON h.filing_id=cf.id
          WHERE (h.put_call IS NULL OR TRIM(h.put_call)='')
          GROUP BY cf.fund_id,cf.report_period,
                   UPPER(TRIM(COALESCE(NULLIF(h.cusip,''),h.ticker)))
        ), historical_positions AS (
          SELECT ff.fund_id,ff.report_period,ff.filing_sequence,
                 UPPER(TRIM(COALESCE(NULLIF(h.cusip,''),h.ticker))) position_key,
                 SUM(h.value_usd) position_value
          FROM fund_filings ff JOIN holdings h ON h.filing_id=ff.id
          WHERE (h.put_call IS NULL OR TRIM(h.put_call)='') AND h.value_usd>0
          GROUP BY ff.fund_id,ff.report_period,ff.filing_sequence,
                   UPPER(TRIM(COALESCE(NULLIF(h.cusip,''),h.ticker)))
        ), position_islands AS (
          SELECT hp.*,
                 hp.filing_sequence-ROW_NUMBER() OVER(
                   PARTITION BY hp.fund_id,hp.position_key ORDER BY hp.filing_sequence) episode_group
          FROM historical_positions hp WHERE hp.position_value>0
        ), holding_episodes AS (
          SELECT fund_id,position_key,episode_group,
                 MIN(filing_sequence) first_sequence,MAX(filing_sequence) last_sequence,
                 COUNT(*) quarters_held
          FROM position_islands
          GROUP BY fund_id,position_key,episode_group
        ), completed_holding_periods AS (
          SELECT he.* FROM holding_episodes he
          WHERE EXISTS(SELECT 1 FROM fund_filings ff
                       WHERE ff.fund_id=he.fund_id AND ff.filing_sequence>he.last_sequence)
        ), holding_periods AS (
          SELECT fund_id,AVG(CAST(quarters_held AS FLOAT)) average_holding_period_quarters
          FROM completed_holding_periods GROUP BY fund_id
        ), position_returns AS (
          SELECT cp.fund_id,cp.position_value,
                 CASE WHEN qtr.price>0 AND latest.price>0
                      THEN (latest.price-qtr.price)/qtr.price END position_return
          FROM current_positions cp
          OUTER APPLY(SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price
                      FROM daily_prices dp WHERE dp.ticker=cp.ticker
                        AND dp.price_date<=cp.report_period ORDER BY dp.price_date DESC) qtr
          OUTER APPLY(SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price
                      FROM daily_prices dp WHERE dp.ticker=cp.ticker ORDER BY dp.price_date DESC) latest
        ), fund_returns AS (
          SELECT fund_id,
                 SUM(CASE WHEN position_return IS NOT NULL AND position_value>0
                          THEN CAST(position_value AS FLOAT)*position_return ELSE 0 END)
                 /NULLIF(SUM(CASE WHEN position_return IS NOT NULL AND position_value>0
                                  THEN CAST(position_value AS FLOAT) ELSE 0 END),0)
                   return_since_report
          FROM position_returns GROUP BY fund_id
        )
        SELECT f.id,f.name,f.fund_type,f.cik,
               (SELECT COUNT(*) FROM filings fl WHERE fl.fund_id=f.id) filing_count,
               cf.report_period latest_period,cf.filing_date latest_filing_date,
               cf.total_value latest_total_value,
               fr.return_since_report,hp.average_holding_period_quarters
        FROM funds f
        LEFT JOIN current_filings cf ON cf.fund_id=f.id
        LEFT JOIN fund_returns fr ON fr.fund_id=f.id
        LEFT JOIN holding_periods hp ON hp.fund_id=f.id
        WHERE {where_clause}
        ORDER BY f.fund_type,f.name
        """,
        params,
    )
    top_positions = query_all(
        f"""
        WITH positions AS (
          SELECT f.id fund_id,p.ticker,p.issuer_name,p.value_usd position_value,
                 ROW_NUMBER() OVER(PARTITION BY f.id ORDER BY p.value_usd DESC) position_rank
          FROM funds f JOIN latest_fund_positions p ON p.fund_id=f.id
          WHERE {where_clause} AND p.is_exit=0
        )
        SELECT fund_id,ticker,issuer_name,position_value
        FROM positions WHERE position_rank<=5 ORDER BY fund_id,position_rank
        """,
        params,
    )
    by_fund = {row["id"]: [] for row in funds}
    for position in top_positions:
        by_fund.setdefault(position["fund_id"], []).append(position)
    for fund in funds:
        fund["top_positions"] = by_fund.get(fund["id"], [])
    return funds


@app.route(route="funds")
def list_funds(req: func.HttpRequest) -> func.HttpResponse:
    try:
        fund_type = req.params.get("type")
        return _json_response({"funds": cached(
            f"funds:{fund_type or 'all'}", lambda: _fund_summaries(fund_type), 900
        )})
    except Exception as e:
        logging.exception("Error listing funds")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}")
def get_fund(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    try:
        funds = cached(
            f"fund:{fund_id}", lambda: _fund_summaries(fund_id=fund_id), 900
        )
        fund = funds[0] if funds else None
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

        # The filing-to-filing comparison is materialized by the ingestion pipeline.
        # Price-relative performance remains live because it changes after each quote sync.
        holdings = query_all(
            """
            WITH selected_period AS (
                SELECT COALESCE(CAST(:period AS DATE), MAX(report_period)) report_period
                FROM fund_quarter_positions WHERE fund_id=:fund_id
            )
            SELECT p.ticker,p.cusip,p.issuer_name,p.shares,p.value_usd,p.put_call,
                   p.report_period,p.filing_date,
                   CAST(p.portfolio_weight*100 AS DECIMAL(8,4)) weight_pct,
                   p.previous_shares,p.share_change,p.share_change_pct,p.change_type,
                   CASE WHEN p.is_exit=0 AND filed.price>0 AND latest.price>0
                        THEN (latest.price-filed.price)/filed.price END since_filed_return
            FROM fund_quarter_positions p
            CROSS JOIN selected_period sp
            OUTER APPLY (
                SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price
                FROM daily_prices dp
                WHERE dp.ticker=p.ticker AND dp.price_date>=p.filing_date
                ORDER BY dp.price_date
            ) filed
            OUTER APPLY (
                SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price
                FROM daily_prices dp WHERE dp.ticker=p.ticker ORDER BY dp.price_date DESC
            ) latest
            WHERE p.fund_id=:fund_id AND p.report_period=sp.report_period
            ORDER BY p.is_exit,p.value_usd DESC
            """,
            params,
        )
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
    quarter=req.params.get("quarter")
    fund_type=req.params.get("fund_type")
    rank_by=req.params.get("rank_by","fund_count")
    if not quarter:
        return _json_response({"error":"quarter is required"},400)
    if fund_type not in (None,"Long Only","Hedge Core") or rank_by not in ("fund_count","group_percentage"):
        return _json_response({"error":"invalid filter"},400)
    try:
        rows=cached(f"quarterly-v2:{quarter}:{fund_type or 'all'}:{rank_by}",lambda:query_all(
            """
            WITH positions AS (
              SELECT p.* FROM fund_quarter_positions p JOIN funds f ON f.id=p.fund_id
              WHERE p.report_period=:quarter AND f.is_active=1
                AND (:fund_type IS NULL OR f.fund_type=:fund_type)
                AND p.ticker IS NOT NULL
                AND EXISTS(SELECT 1 FROM fund_quarter_positions prior
                           WHERE prior.fund_id=p.fund_id AND prior.report_period<p.report_period)
            ), totals AS (
              SELECT SUM(CASE WHEN is_exit=0 THEN value_usd ELSE 0 END) current_total,
                     SUM(previous_value) previous_total FROM positions
            ), aggregated AS (
              SELECT CASE change_type WHEN 'added' THEN 'add' WHEN 'reduced' THEN 'reduce'
                                      ELSE change_type END change_type,
                     ticker,COUNT(DISTINCT fund_id) fund_count,SUM(value_usd) current_value,
                     SUM(previous_value) previous_value,
                     CAST(SUM(value_usd)*1.0/NULLIF(MAX(current_total),0) AS DECIMAL(18,8)) current_group_percentage,
                     CAST(SUM(previous_value)*1.0/NULLIF(MAX(previous_total),0) AS DECIMAL(18,8)) previous_group_percentage,
                     CAST(SUM(value_usd)*1.0/NULLIF(MAX(current_total),0)
                         -SUM(previous_value)*1.0/NULLIF(MAX(previous_total),0) AS DECIMAL(18,8)) group_percentage_change
              FROM positions CROSS JOIN totals
              WHERE change_type IN ('new','added','reduced','exit')
              GROUP BY change_type,ticker
            ), ranked AS (
              SELECT *,ROW_NUMBER() OVER(PARTITION BY change_type ORDER BY
                CASE WHEN :rank_by='fund_count' THEN fund_count END DESC,
                CASE WHEN :rank_by='group_percentage' THEN ABS(group_percentage_change) END DESC,
                fund_count DESC,ticker) rank_number FROM aggregated
            )
            SELECT * FROM ranked WHERE rank_number<=10
            ORDER BY CASE change_type WHEN 'new' THEN 1 WHEN 'add' THEN 2
                 WHEN 'reduce' THEN 3 WHEN 'exit' THEN 4 END,rank_number
            """,{"quarter":quarter,"fund_type":fund_type,"rank_by":rank_by}),900)
        grouped={"new":[],"add":[],"reduce":[],"exit":[]}
        for row in rows: grouped[row["change_type"]].append(row)
        return _json_response({"quarter":quarter,"fund_type":fund_type or "All","rank_by":rank_by,"changes":grouped})
    except Exception as e:
        logging.exception("Error loading persisted quarterly changes")
        return _json_response({"error":str(e)},500)


def quarterly_changes_legacy(req: func.HttpRequest) -> func.HttpResponse:
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
        rows = cached(
            f"quarterly-changes:{quarter}:{fund_type or 'all'}:{rank_by}",
            lambda: query_all(
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
            WHERE rank_number <= 10
            ORDER BY CASE change_type
                         WHEN 'new' THEN 1 WHEN 'add' THEN 2
                         WHEN 'reduce' THEN 3 WHEN 'exit' THEN 4 END,
                     rank_number
            """,
            {"quarter": quarter, "fund_type": fund_type, "rank_by": rank_by},
        ), 900)
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


@app.route(route="strategy-backtests")
def strategy_backtests(req: func.HttpRequest) -> func.HttpResponse:
    strategy = req.params.get("strategy", "top10")
    if strategy not in ("top10", "new_to_exit"):
        return _json_response({"error": "invalid strategy"}, 400)
    try:
        rows = cached(
            f"strategy-backtests:v2:equal-weight:{strategy}",
            lambda: query_all(
                """
                WITH filing_sequence AS (
                    SELECT id,fund_id,next_filing_id,entry_date,exit_date,
                           ROW_NUMBER() OVER(PARTITION BY fund_id ORDER BY entry_date,id) seq
                    FROM trade_copy_results
                ), next_values AS (
                    SELECT fs.fund_id,fs.seq,UPPER(TRIM(h.ticker)) ticker,
                           SUM(h.value_usd) position_value
                    FROM filing_sequence fs JOIN holdings h ON h.filing_id=fs.next_filing_id
                    WHERE h.ticker IS NOT NULL AND TRIM(h.ticker)<>''
                      AND (h.put_call IS NULL OR h.put_call='')
                    GROUP BY fs.fund_id,fs.seq,UPPER(TRIM(h.ticker))
                ), next_ranked AS (
                    SELECT *,ROW_NUMBER() OVER(
                        PARTITION BY fund_id,seq ORDER BY position_value DESC,ticker) position_rank
                    FROM next_values
                ), eligible AS (
                    SELECT p.fund_id,p.ticker,p.total_return,p.is_resolved,
                           f.seq,f.entry_date,f.exit_date
                    FROM trade_copy_position_results p
                    JOIN filing_sequence f ON f.id=p.trade_copy_result_id
                    WHERE (:strategy='new_to_exit' OR p.position_rank<=10)
                ), numbered AS (
                    SELECT *,seq-ROW_NUMBER() OVER(
                        PARTITION BY fund_id,ticker ORDER BY seq) episode_group
                    FROM eligible
                ), episode_base AS (
                    SELECT fund_id,ticker,episode_group,
                           MIN(entry_date) entry_date,MAX(exit_date) exit_date,
                           MAX(seq) last_seq,
                           COUNT(*) periods,
                           SUM(CASE WHEN is_resolved=1 THEN 1 ELSE 0 END) resolved_periods,
                           EXP(SUM(CASE WHEN is_resolved=1 THEN
                               LOG(CASE WHEN total_return>-.999999 THEN 1.0+total_return
                                        ELSE .000001 END) ELSE 0 END))-1 episode_return
                    FROM numbered GROUP BY fund_id,ticker,episode_group
                ), episodes AS (
                    SELECT eb.*,
                           CASE WHEN NOT EXISTS (
                               SELECT 1 FROM next_ranked nr
                               WHERE nr.fund_id=eb.fund_id AND nr.seq=eb.last_seq
                                 AND nr.ticker=eb.ticker
                                 AND (:strategy='new_to_exit' OR nr.position_rank<=10)
                           ) THEN 1 ELSE 0 END is_closed
                    FROM episode_base eb
                ), trade_metrics AS (
                    SELECT fund_id,SUM(is_closed) trade_count,
                           SUM(CASE WHEN is_closed=1 AND resolved_periods=periods AND episode_return>0
                                    THEN 1 ELSE 0 END) winning_trades,
                           SUM(CASE WHEN is_closed=1 AND resolved_periods=periods THEN 1 ELSE 0 END)
                               resolved_trades,
                           AVG(CASE WHEN is_closed=1 AND resolved_periods=periods THEN episode_return END)
                               average_trade_return
                    FROM episodes GROUP BY fund_id
                ), eligible_weighted AS (
                    SELECT *,
                           CASE WHEN is_resolved=1 THEN
                               1.0/NULLIF(SUM(CASE WHEN is_resolved=1 THEN 1 ELSE 0 END)
                                          OVER(PARTITION BY fund_id,seq),0)
                           END equal_weight
                    FROM eligible
                ), period_returns AS (
                    SELECT fund_id,seq,MIN(entry_date) entry_date,MAX(exit_date) exit_date,
                           SUM(CASE WHEN is_resolved=1
                                    THEN equal_weight*total_return END) period_return,
                           AVG(CAST(is_resolved AS FLOAT)) price_coverage
                    FROM eligible_weighted GROUP BY fund_id,seq
                ), portfolio AS (
                    SELECT fund_id,COUNT(period_return) periods,MIN(entry_date) first_entry,
                           MAX(exit_date) last_exit,AVG(price_coverage) price_coverage,
                           EXP(SUM(CASE WHEN period_return IS NOT NULL THEN
                               LOG(CASE WHEN period_return>-.999999 THEN 1.0+period_return
                                        ELSE .000001 END) ELSE 0 END))-1 cumulative_return
                    FROM period_returns GROUP BY fund_id
                )
                SELECT f.id fund_id,f.name,f.fund_type,p.periods,
                       p.cumulative_return,
                       CASE WHEN DATEDIFF(day,p.first_entry,p.last_exit)>0 THEN
                           POWER(1.0+p.cumulative_return,
                                 365.0/DATEDIFF(day,p.first_entry,p.last_exit))-1 END
                           annualized_return,
                       t.trade_count,t.resolved_trades,t.winning_trades,
                       CAST(t.winning_trades*1.0/NULLIF(t.resolved_trades,0)
                            AS DECIMAL(18,6)) win_rate,
                       t.average_trade_return,p.price_coverage,
                       p.first_entry,p.last_exit
                FROM portfolio p JOIN trade_metrics t ON t.fund_id=p.fund_id
                JOIN funds f ON f.id=p.fund_id
                WHERE f.is_active=1
                ORDER BY annualized_return DESC,f.name
                """,
                {"strategy": strategy},
            ),
            900,
        )
        return _json_response({"strategy": strategy, "weighting": "equal", "funds": rows})
    except Exception as e:
        logging.exception("Error loading strategy backtests")
        return _json_response({"error": str(e)}, 500)


@app.route(route="strategy-backtests/{fund_id:int}/trades")
def strategy_recent_trades(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    strategy = req.params.get("strategy", "top10")
    if strategy not in ("top10", "new_to_exit"):
        return _json_response({"error": "invalid strategy"}, 400)
    try:
        def load():
            rows = query_all("""
                WITH filing_sequence AS (
                    SELECT id,fund_id,next_filing_id,entry_date,
                           ROW_NUMBER() OVER(ORDER BY entry_date,id) seq
                    FROM trade_copy_results WHERE fund_id=:fund_id
                ), next_values AS (
                    SELECT fs.seq,UPPER(TRIM(h.ticker)) ticker,SUM(h.value_usd) position_value
                    FROM filing_sequence fs JOIN holdings h ON h.filing_id=fs.next_filing_id
                    WHERE h.ticker IS NOT NULL AND TRIM(h.ticker)<>''
                      AND (h.put_call IS NULL OR h.put_call='')
                    GROUP BY fs.seq,UPPER(TRIM(h.ticker))
                ), next_ranked AS (
                    SELECT *,ROW_NUMBER() OVER(PARTITION BY seq ORDER BY position_value DESC,ticker) position_rank
                    FROM next_values
                )
                SELECT p.ticker,p.entry_date,p.entry_price,p.exit_date,p.total_return,p.is_resolved,
                       fs.seq,fs.entry_date period_entry_date,
                       CASE WHEN EXISTS (
                           SELECT 1 FROM next_ranked nr WHERE nr.seq=fs.seq AND nr.ticker=p.ticker
                             AND (:strategy='new_to_exit' OR nr.position_rank<=10)
                       ) THEN 1 ELSE 0 END next_is_eligible
                FROM trade_copy_position_results p
                JOIN filing_sequence fs ON fs.id=p.trade_copy_result_id
                WHERE p.fund_id=:fund_id AND (:strategy='new_to_exit' OR p.position_rank<=10)
                ORDER BY fs.seq,p.ticker
            """, {"fund_id": fund_id, "strategy": strategy})
            return recent_strategy_trades(rows)
        trades = cached(f"strategy-trades:v1:{fund_id}:{strategy}", load, 900)
        return _json_response({"fund_id": fund_id, "strategy": strategy, "trades": trades})
    except Exception as e:
        logging.exception("Error loading recent strategy trades")
        return _json_response({"error": str(e)}, 500)


@app.route(route="funds/{fund_id:int}/alpha-attribution")
def fund_alpha_attribution(req: func.HttpRequest) -> func.HttpResponse:
    fund_id = int(req.route_params["fund_id"])
    try:
        def load():
            rows = query_all("""
                WITH history AS (
                    SELECT MIN(entry_date) history_start,MAX(exit_date) history_end
                    FROM trade_copy_results WHERE fund_id=:fund_id
                )
                SELECT p.ticker,SUM(p.target_weight*p.excess_return) excess_contribution,
                       COUNT(*) periods,h.history_start,h.history_end,
                       DATEDIFF(day,h.history_start,h.history_end) history_days
                FROM trade_copy_position_results p CROSS JOIN history h
                WHERE p.fund_id=:fund_id AND p.is_resolved=1 AND p.excess_return IS NOT NULL
                GROUP BY p.ticker,h.history_start,h.history_end
            """, {"fund_id": fund_id})
            return rank_alpha(rows)
        return _json_response(cached(f"fund-alpha:v1:{fund_id}", load, 900))
    except Exception as e:
        logging.exception("Error loading fund alpha attribution")
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
        latest_positions AS (
            SELECT p.fund_id,p.ticker,p.value_usd position_value
            FROM fund_quarter_positions p
            INNER JOIN funds f ON f.id=p.fund_id AND f.is_active=1
            INNER JOIN latest_period lp ON lp.report_period=p.report_period
            WHERE p.ticker IS NOT NULL AND p.is_exit=0
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


def _dashboard_consensus_persisted(latest_quarter):
    return query_all(
        """
        WITH aggregated AS (
            SELECT CASE WHEN p.change_type IN ('new','added') THEN 'buy' ELSE 'sell' END side,
                   p.ticker,MAX(p.issuer_name) company,COUNT(DISTINCT p.fund_id) fund_count,
                   SUM(p.share_change) net_share_change
            FROM fund_quarter_positions p
            JOIN funds f ON f.id=p.fund_id AND f.is_active=1
            WHERE p.report_period=:quarter AND p.ticker IS NOT NULL
              AND p.change_type IN ('new','added','reduced','exit')
            GROUP BY CASE WHEN p.change_type IN ('new','added') THEN 'buy' ELSE 'sell' END,p.ticker
        ), enriched AS (
            SELECT a.*,
                   a.net_share_change*qtr.market_price net_change,
                   CASE WHEN qtr.return_price>0 AND latest.price>0
                        THEN (latest.price-qtr.return_price)/qtr.return_price END move_since_quarter_end,
                   ROW_NUMBER() OVER(PARTITION BY a.side ORDER BY a.fund_count DESC,
                       ABS(a.net_share_change*qtr.market_price) DESC,a.ticker) rank_number
            FROM aggregated a
            OUTER APPLY (SELECT TOP 1 CAST(dp.close_price AS FLOAT) market_price,
                                CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) return_price
                         FROM daily_prices dp WHERE dp.ticker=a.ticker AND dp.price_date<=:quarter
                         ORDER BY dp.price_date DESC) qtr
            OUTER APPLY (SELECT TOP 1 CAST(COALESCE(dp.adj_close,dp.close_price) AS FLOAT) price
                         FROM daily_prices dp WHERE dp.ticker=a.ticker ORDER BY dp.price_date DESC) latest
        )
        SELECT side,ticker,company,fund_count,move_since_quarter_end,net_change,rank_number
        FROM enriched WHERE rank_number<=10
        ORDER BY CASE side WHEN 'buy' THEN 1 ELSE 2 END,rank_number
        """,
        {"quarter": latest_quarter},
    )


@app.route(route="dashboard")
def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    started = time.perf_counter()
    timings = {}
    load_started = False
    load_completed = False

    def measure(name, operation):
        stage_started = time.perf_counter()
        with capture_read_timings() as db_timings:
            try:
                return operation()
            finally:
                timings[name] = (time.perf_counter() - stage_started) * 1000
                timings.update({f"{name}_{phase}": duration for phase, duration in db_timings.items()})

    try:
        def load_dashboard():
            nonlocal load_started, load_completed
            load_started = True
            recent_quarters = measure("recent_quarters", _dashboard_recent_quarters)
            funds = measure("funds", _dashboard_funds)
            latest_row = measure("latest_quarter", lambda: query_one(
                "SELECT MAX(report_period) AS quarter FROM filings"
            ))
            latest_quarter = latest_row["quarter"] if latest_row else None
            consensus = measure("consensus", lambda: _dashboard_consensus_persisted(
                latest_quarter
            )) if latest_quarter else []
            grouped = {"buys": [], "sells": []}
            for row in consensus:
                grouped["buys" if row["side"] == "buy" else "sells"].append(row)
            load_completed = True
            return {
                "recent_quarters": recent_quarters,
                "latest_quarter": latest_quarter,
                "consensus": grouped,
                "funds": funds,
            }

        response = _json_response(cached("dashboard", load_dashboard, 300))
        cache_status = "miss" if load_completed else "stale" if load_started else "hit"
    except Exception as e:
        logging.exception("Error getting dashboard")
        response = _json_response({"error": str(e)}, 500)
        response.headers["Cache-Control"] = "no-store"
        cache_status = "error"

    # Handler time includes cache access, DB retries and JSON serialization, but
    # excludes platform startup/queueing and browser-to-API network latency.
    timings["app"] = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = ", ".join(
        [f'{name};dur={duration:.1f}' for name, duration in timings.items()]
        + [f'cache;desc="{cache_status}"']
    )
    logging.info("dashboard timing cache=%s durations_ms=%s", cache_status, timings)
    return response
