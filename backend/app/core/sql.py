"""Validate model SQL before executing it over explicitly registered private tables."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from ..models import ApiError

FUNCTIONS = set(
    "ABS AVG SUM COUNT MIN MAX ROUND FLOOR CEIL CEILING STDDEV STDDEV_POP STDDEV_SAMP VARIANCE VAR_POP QUANTILE_CONT PERCENTILE_CONT MEDIAN COALESCE NULLIF CAST TRY_CAST EXTRACT DATE_TRUNC STRFTIME STRPTIME TRY_STRPTIME YEAR MONTH DAY DATE_DIFF DATEDIFF DATE_ADD DATE_SUB LAG LEAD ROW_NUMBER RANK DENSE_RANK FIRST_VALUE LAST_VALUE LOWER UPPER TRIM LENGTH CONCAT SUBSTRING REPLACE REGEXP_REPLACE REGEXP_MATCHES POWER SQRT IF CASE GREATEST LEAST ISNAN ISFINITE".split()
)


def validate_sql(sql, tables):
    try:
        queries = sqlglot.parse(sql, read="duckdb")
    except ParseError:
        raise ApiError("Invalid SQL syntax. Return a single DuckDB SELECT query.") from None
    if len(queries) != 1 or not isinstance(queries[0], (exp.Select, exp.Union)):
        raise ApiError("Only one read-only SELECT query is allowed.")
    query = queries[0]
    if sum(1 for _ in query.walk()) > 600:
        raise ApiError("The SQL query is too complex.")
    ctes = {cte.alias for cte in query.find_all(exp.CTE)}
    if ctes & set(tables):
        raise ApiError("CTE names must not shadow the selected tables.")
    canonical = {
        "TIME_TO_STR",
        "STR_TO_TIME",
        "TS_OR_DS_TO_DATE",
        "TIMESTAMP_TRUNC",
        "CURRENT_DATE",
        "CURRENT_TIMESTAMP",
        "REGR_SLOPE",
        "REGR_INTERCEPT",
        "CORR",
        "COVAR_POP",
    }
    for node in query.walk():
        if isinstance(
            node,
            (
                exp.Command,
                exp.Insert,
                exp.Update,
                exp.Delete,
                exp.Create,
                exp.Drop,
                exp.Into,
                exp.Copy,
                exp.Attach,
                exp.Pragma,
            ),
        ):
            raise ApiError("This SQL operation is not allowed.")
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise ApiError("Recursive queries are not allowed.")
        if isinstance(node, exp.Table):
            if (
                not isinstance(node.this, exp.Identifier)
                or node.db
                or node.catalog
                or node.name not in set(tables) | ctes
            ):
                raise ApiError("SQL may only reference the selected registered tables.")
        if isinstance(node, exp.Func):
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name().upper()
            if name not in FUNCTIONS | canonical:
                raise ApiError(
                    f"Function {name} is not supported. Use the allowed analytical functions."
                )
    if not any(table.name in tables for table in query.find_all(exp.Table)):
        raise ApiError("The query must use a selected table.")
    return query.sql(dialect="duckdb")


def referenced_tables(sql, tables):
    safe = validate_sql(sql, tables)
    query = sqlglot.parse_one(safe, read="duckdb")
    return {table.name for table in query.find_all(exp.Table) if table.name in tables}
