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
                   (SELECT SUM(fl.total_value) FROM filings fl
                    WHERE fl.fund_id = f.id
                      AND fl.report_period = (SELECT MAX(report_period) FROM filings WHERE fund_id = f.id)
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
        if period:
            sql = """
                SELECT h.ticker, h.cusip, h.issuer_name, h.shares, h.value_usd,
                       h.put_call, f.report_period, f.filing_date,
                       CAST(h.value_usd * 1000.0 / NULLIF(
                           (SELECT SUM(h2.value_usd) FROM holdings h2
                            JOIN filings f2 ON h2.filing_id = f2.id
                            WHERE f2.fund_id = :fund_id AND f2.report_period = f.report_period), 0
                       ) AS DECIMAL(8,4)) AS weight_pct
                FROM holdings h
                JOIN filings f ON h.filing_id = f.id
                WHERE h.fund_id = :fund_id AND f.report_period = :period
                ORDER BY h.value_usd DESC
            """
            params = {"fund_id": fund_id, "period": period}
        else:
            sql = """
                SELECT h.ticker, h.cusip, h.issuer_name, h.shares, h.value_usd,
                       h.put_call, f.report_period, f.filing_date,
                       CAST(h.value_usd * 1000.0 / NULLIF(
                           (SELECT SUM(h2.value_usd) FROM holdings h2
                            JOIN filings f2 ON h2.filing_id = f2.id
                            WHERE f2.fund_id = :fund_id AND f2.report_period = f.report_period), 0
                       ) AS DECIMAL(8,4)) AS weight_pct
                FROM holdings h
                JOIN filings f ON h.filing_id = f.id
                WHERE h.fund_id = :fund_id
                  AND f.report_period = (SELECT MAX(report_period) FROM filings WHERE fund_id = :fund_id)
                ORDER BY h.value_usd DESC
            """
            params = {"fund_id": fund_id}

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
            SELECT period_start, period_end, total_return, benchmark_return, alpha, num_positions, computed_at
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


@app.route(route="dashboard")
def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    try:
        summary = query_one(
            """
            SELECT
                (SELECT COUNT(*) FROM funds WHERE is_active = 1) AS total_funds,
                (SELECT COUNT(*) FROM filings) AS total_filings,
                (SELECT COUNT(DISTINCT ticker) FROM holdings WHERE ticker IS NOT NULL) AS unique_tickers,
                (SELECT COUNT(*) FROM backtest_results) AS backtest_periods
            """
        )
        recent_sync = query_all(
            "SELECT TOP 5 job_type, status, records_affected, started_at, finished_at FROM sync_log ORDER BY started_at DESC"
        )
        return _json_response({"summary": summary, "recent_sync": recent_sync})
    except Exception as e:
        logging.exception("Error getting dashboard")
        return _json_response({"error": str(e)}, 500)
