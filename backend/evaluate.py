"""Small reproducible DuckDB checks, with optional live Gemini planning."""

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.core.engine import alias, ingest, query
from app.infrastructure.execution import Task
from app.services.gemini import GeminiProvider


async def main():
    live = "--live" in sys.argv
    provider = GeminiProvider(Settings()) if live else None
    if provider and not provider.ready:
        raise SystemExit("Set GEMINI_API_KEY in .env before live evaluations.")
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sales.csv"
        path.write_text("region,revenue\nNorth,100.50\nSouth,200.25\nNorth,50.00\n")
        table = dict(id="sales", name="Evaluation sales", **ingest(Task(), path, "sales.csv"))
        name = alias("sales")
        cases = [
            ("How many sales records are there?", f"SELECT COUNT(*) value FROM {name}", 3),
            ("What is the total revenue?", f'SELECT SUM(revenue) value FROM {name}', 350.75),
        ]
        passed = 0
        try:
            for question, sql, expected in cases:
                if provider:
                    plan = await provider.plan(
                        [{"table_id": "sales", "alias": name, **table["profile"]}], question, []
                    )
                    sql = plan.sql_query
                rows, _ = query(Task(), [(table, path)], sql)
                actual = next(iter(rows[0].values()))
                ok = abs(float(actual) - expected) < 0.001
                passed += int(ok)
                print(("PASS " if ok else "FAIL ") + question)
        finally:
            if provider:
                await provider.close()
        print(
            f"{passed}/{len(cases)} passed. "
            + ("Live model planning was used." if live else "No model calls were made.")
        )
        if passed != len(cases):
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
