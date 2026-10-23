from ..models import Json, Row
from .ingestion import csv_text


def export_csv(rows: list[Row]) -> str:
    return csv_text(list(rows[0]), rows, escape_formulas=True) if rows else ""


def result_rows(result):
    if not result.get("sections"):
        return result["rows"]
    sections = result["sections"]
    columns = list(
        dict.fromkeys(key for section in sections for row in section["rows"] for key in row)
    )
    label, source = "_calculation", "_tables"
    while label in columns:
        label = "_" + label
    while source in columns:
        source = "_" + source
    return [
        {
            label: section["title"],
            source: section.get("tableName", ""),
            **{key: row.get(key) for key in columns},
        }
        for section in sections
        for row in section["rows"]
    ]


def export_report(turns: list[Json]) -> str:
    sections = ["# Analysis report"]
    for turn in turns:
        result = turn["result"]
        sections += [
            f"## {turn['question']}",
            f"Table: {result.get('tableName', 'Prepared data')}",
            result["answer"],
            "### Method",
            "\n".join("- " + step for step in result["steps"]),
            "### Limitations",
            "\n".join("- " + note for note in result["warnings"]),
        ]
        for calculation in result.get("sections") or [result]:
            if calculation is not result:
                sections += [
                    f"### {calculation['title']}",
                    f"Tables: {calculation.get('tableName', '')}",
                    calculation["plan"]["explanation"],
                ]
            if calculation.get("sql"):
                sections += ["### Executed DuckDB SQL", "```sql\n" + calculation["sql"] + "\n```"]
    return "\n\n".join(sections)
