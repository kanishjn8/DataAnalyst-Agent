import pytest

from app.core.engine import alias, ingest, prepare, query
from app.core.sql import validate_sql
from app.infrastructure.execution import Task
from app.models import ApiError


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT getenv('HOME') FROM sales",
        "SELECT * FROM sales; DELETE FROM sales",
        "SELECT * INTO output FROM sales",
        "ATTACH 'other.db'",
        "SELECT * FROM other_user",
        "WITH RECURSIVE x AS (SELECT * FROM sales) SELECT * FROM x",
        "WITH x AS (SELECT 1 value) SELECT * FROM x",
    ],
)
def test_rejects_unsafe_sql(sql):
    with pytest.raises(ApiError):
        validate_sql(sql, ["sales"])


def test_cte_and_window_queries():
    for sql in [
        "SELECT DATE_TRUNC('month', CAST(date AS DATE)) month, SUM(revenue) total FROM sales GROUP BY month",
        "SELECT STRFTIME(CAST(date AS DATE), '%Y-%m') month FROM sales",
        "SELECT region,SUM(revenue) total FROM sales GROUP BY region",
        "WITH totals AS (SELECT region,SUM(revenue) total FROM sales GROUP BY region) SELECT * FROM totals",
        "SELECT revenue,AVG(revenue) OVER() average FROM sales",
    ]:
        assert validate_sql(sql, ["sales"])


def test_profile_and_aggregate(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text("region,revenue\nNorth,100\nSouth,50\nNorth,20")
    profile = ingest(Task(), path, "sales.csv")
    assert profile["rowCount"] == 3 and profile["columns"][1]["sqlType"] == "DOUBLE"
    assert path.with_suffix(".parquet").exists()
    table = {"id": "sales", "name": "sales.csv", **profile}
    rows, _ = query(
        Task(),
        [(table, path)],
        f"SELECT region,SUM(revenue) total FROM {alias('sales')} GROUP BY region ORDER BY total DESC",
    )
    assert rows == [dict(region="North", total=120), dict(region="South", total=50)]


def test_duckdb_join_preserves_identifiers_nulls_and_duplicate_keys(tmp_path):
    tables = []
    for identity, content in [
        ("left", "id,value\n001,10\n002,20"),
        ("right", "id,region\n001,North\n001,East"),
    ]:
        path = tmp_path / f"{identity}.csv"
        path.write_text(content)
        tables.append(
            (
                dict(
                    id=identity, name=f"{identity}.csv", **ingest(Task(), path, f"{identity}.csv")
                ),
                path,
            )
        )
    content, _, _ = prepare(
        Task(),
        tables,
        dict(
            kind="join",
            leftId="left",
            rightId="right",
            leftKey="id",
            rightKey="id",
            joinType="left",
        ),
    )
    assert "001,10.0,001,North" in content and "002,20.0,," in content
    assert content.count("001,10.0") == 2
