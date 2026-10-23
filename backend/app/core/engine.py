"""DuckDB owns calculations; model SQL never opens files or changes database settings."""

import hashlib
import json
import math
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from ..models import MAX_BYTES, MAX_COLUMNS, MAX_ROWS, ApiError
from .ingestion import csv_text, parse_csv
from .sql import validate_sql


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def alias(identity):
    return "table_" + hashlib.sha256(identity.encode()).hexdigest()[:16]


def values(cursor):
    names = [description[0] for description in cursor.description]

    def safe(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, (dict, list, bytes)):
            return str(value)[:1000]
        return value

    return [
        {key: safe(value) for key, value in zip(names, row, strict=True)}
        for row in cursor.fetchall()
    ]


@contextmanager
def connection(task):
    db = duckdb.connect(
        ":memory:",
        config={
            "threads": 2,
            "memory_limit": "192MB",
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
        },
    )
    task.attach(db)
    try:
        if task.cancelled.is_set():
            raise ApiError("Calculation cancelled.", 408)
        yield db
    finally:
        task.detach()
        db.close()


def lock(db):
    db.execute("SET enable_external_access=false")
    db.execute("SET lock_configuration=true")


def ingest(task, path, name):
    data = parse_csv({"name": name, "content": Path(path).read_text(encoding="utf-8-sig")})
    normalized = csv_text([column["name"] for column in data.columns], data.rows)
    with connection(task) as db, TemporaryDirectory() as temporary:
        csv_path = Path(temporary) / "normalized.csv"
        csv_path.write_text(normalized)
        types = {
            column["name"]: (
                "DOUBLE"
                if column["type"] == "number"
                else "DATE"
                if column["type"] == "date"
                else "VARCHAR"
            )
            for column in data.columns
        }
        db.execute(
            "CREATE TABLE source AS SELECT * FROM read_csv(?,columns=?,header=true,auto_detect=false)",
            [str(csv_path), types],
        )
        summary = values(db.execute("SUMMARIZE source"))
        samples = values(db.execute("SELECT * FROM source LIMIT 5"))
        for column, stats in zip(data.columns, summary, strict=True):
            column.update(
                sqlType=stats["column_type"],
                min=str(stats["min"])[:100],
                max=str(stats["max"])[:100],
                nullPercentage=round(column["missing"] / len(data.rows) * 100, 2),
                samples=[
                    row[column["name"]]
                    if not isinstance(row[column["name"]], str)
                    else row[column["name"]][:100]
                    for row in samples
                ],
            )
        target = Path(path).with_suffix(".parquet")
        temporary_target = target.with_suffix(".parquet.part")
        try:
            db.execute(
                f"COPY source TO '{str(temporary_target).replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            temporary_target.replace(target)
        finally:
            temporary_target.unlink(missing_ok=True)
    sample = [
        {key: value[:100] if isinstance(value, str) else value for key, value in row.items()}
        for row in samples
    ]
    return dict(
        columns=data.columns,
        rowCount=len(data.rows),
        warnings=data.warnings,
        profile=dict(
            name=name,
            rowCount=len(data.rows),
            columns=data.columns,
            sample=sample,
            warnings=data.warnings,
        ),
    )


def load(db, task, tables):
    for table, path in tables:
        parquet = Path(path).with_suffix(".parquet")
        if not parquet.exists():
            # Display names can be renamed and need not have a CSV extension.
            ingest(task, path, "table.csv")
            task.attach(db)
        db.execute(
            f"CREATE TABLE {quote(alias(table['id']))} AS SELECT * FROM read_parquet(?)",
            [str(parquet)],
        )


def query(task, tables, sql):
    safe = validate_sql(sql, [alias(table["id"]) for table, _ in tables])
    with connection(task) as db:
        load(db, task, tables)
        lock(db)
        rows = values(db.execute(f"SELECT * FROM ({safe}) AS answer LIMIT 201"))
        truncated = len(rows) > 200
        rows = rows[:200]
        if len(json.dumps(rows, default=str).encode()) > 500_000:
            raise ApiError("The result is too large. Select fewer columns or aggregate the data.")
        return rows, truncated


def preview(task, table, path, limit=20):
    with connection(task) as db:
        load(db, task, [(table, path)])
        lock(db)
        rows = values(db.execute(f"SELECT * FROM {quote(alias(table['id']))} LIMIT {int(limit)}"))
    return dict(
        description=table["name"],
        rowCount=table["rowCount"],
        columns=table["columns"],
        rows=rows,
        warnings=table.get("warnings", []),
        notes=table.get("notes", []),
        sql=table.get("sql"),
    )


def prepare(task, tables, operation):
    by_id = {table["id"]: table for table, _ in tables}
    if operation["kind"] == "stack":
        ids = operation["fileIds"]
        if len(ids) != len(set(ids)):
            raise ApiError("Choose each table only once when stacking.")
        sources = [by_id[identity] for identity in ids]
        names = [column["name"] for column in sources[0]["columns"]]
        if any(set(names) != {c["name"] for c in table["columns"]} for table in sources):
            raise ApiError("To stack tables, their column names must match.")
        for name in names:
            kinds = {
                c["type"]
                for table in sources
                for c in table["columns"]
                if c["name"] == name and c["unique"]
            }
            if len(kinds) > 1:
                raise ApiError(f"Column {name} has incompatible types across tables.")
        sql = " UNION ALL ".join(
            f"SELECT {', '.join(quote(name) for name in names)} FROM {quote(alias(identity))}"
            for identity in ids
        )
        notes = [
            "Rows are appended in the selected order, with columns matched by name. Duplicate rows are retained."
        ]
    else:
        if operation["leftId"] == operation["rightId"]:
            raise ApiError("Choose two different tables to join.")
        left, right = by_id[operation["leftId"]], by_id[operation["rightId"]]
        lc = next((c for c in left["columns"] if c["name"] == operation["leftKey"]), None)
        rc = next((c for c in right["columns"] if c["name"] == operation["rightKey"]), None)
        if not lc or not rc:
            raise ApiError("Choose valid join columns.")
        if lc["unique"] and rc["unique"] and lc["type"] != rc["type"]:
            raise ApiError("The key columns have different types.")
        if len(left["columns"]) + len(right["columns"]) > MAX_COLUMNS:
            raise ApiError("The joined table would exceed 40 columns.")
        used = {c["name"] for c in left["columns"]}
        select = [f"l.{quote(c['name'])}" for c in left["columns"]]
        for column in right["columns"]:
            base = "right." + column["name"] if column["name"] in used else column["name"]
            name = base[:120]
            index = 2
            while name in used:
                suffix = f"_{index}"
                name = base[: 120 - len(suffix)] + suffix
                index += 1
            used.add(name)
            select.append(f"r.{quote(column['name'])} AS {quote(name)}")
        sql = f"SELECT {', '.join(select)} FROM {quote(alias(left['id']))} l {operation['joinType'].upper()} JOIN {quote(alias(right['id']))} r ON l.{quote(lc['name'])}=r.{quote(rc['name'])}"
        notes = [
            "Blank keys do not match. Repeated keys can produce multiple rows, following SQL join behavior."
        ]
    with connection(task) as db:
        load(db, task, tables)
        lock(db)
        rows = values(db.execute(f"SELECT * FROM ({sql}) result LIMIT {MAX_ROWS + 1}"))
    if not rows:
        raise ApiError("No matching rows were found. Try a left join or check the keys.")
    if len(rows) > MAX_ROWS:
        raise ApiError("The result exceeds 20,000 rows. Check repeated keys.")
    content = csv_text(list(rows[0]), rows)
    if len(content.encode()) > MAX_BYTES:
        raise ApiError("The result exceeds 15 MB.")
    return content, sql, notes
