"""Small model context, with exact identifiers and no uploaded file contents."""

import json

from ..core import engine
from ..core.canvas import inputs
from ..models import ApiError

MAX_PROMPT_CHARACTERS = 48_000


def encode(payload):
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def compact_profile(profile):
    return dict(
        table_id=profile.get("table_id"),
        alias=profile["alias"],
        name=profile.get("name", profile["alias"]),
        kind=profile.get("kind"),
        row_count=profile.get("rowCount", 0),
        columns=[
            dict(
                name=column["name"],
                type=column.get("sqlType", column["type"]),
                missing=column.get("missing", 0),
                min=column.get("min"),
                max=column.get("max"),
                samples=[
                    value[:64] if isinstance(value, str) else value
                    for value in column.get("samples", [])[:2]
                ],
            )
            for column in profile["columns"]
        ],
    )


def workspace_context(project):
    consumed = {
        key for node in project["canvas"]["operations"] for key in inputs(node["operation"])
    }
    tables = [
        compact_profile(dict(**table, table_id=table["id"], alias=engine.alias(table["id"])))
        for table in project["tables"]
    ]
    return dict(
        tables=tables,
        relationships=[
            dict(table_id=node["id"], **node["operation"])
            for node in project["canvas"]["operations"]
        ],
        preferred_table_ids=[
            table["id"] for table in project["tables"] if table["id"] not in consumed
        ],
    )


def planning_payload(context, question, history, **extra):
    payload = dict(**context, question=question, history=history[-6:], **extra)
    # Copy before shedding optional context; identifiers and relationships are never truncated.
    payload = json.loads(encode(payload))
    if len(encode(payload)) > MAX_PROMPT_CHARACTERS:
        for table in payload["tables"]:
            for column in table["columns"]:
                column.pop("samples", None)
                column.pop("min", None)
                column.pop("max", None)
    while payload["history"] and len(encode(payload)) > MAX_PROMPT_CHARACTERS:
        payload["history"].pop(0)
    if len(encode(payload)) > MAX_PROMPT_CHARACTERS:
        raise ApiError(
            "The combined table schemas are too large. Select an individual table or use shorter column names."
        )
    return payload


def explanation_payload(results, question):
    overall_warnings = []
    relationships = []
    if isinstance(results, dict) and results.get("sections"):
        overall_warnings = results.get("warnings", [])
        relationships = results.get("relationships", [])
        results = results["sections"]
    results = results if isinstance(results, list) else [results]
    cards = []
    for result in results:
        cards.append(
            dict(
                title=result["title"],
                table=result.get("tableName"),
                table_ids=result.get("tableIds", [result.get("tableId")]),
                method=result["plan"]["explanation"],
                warnings=list(dict.fromkeys(result.get("warnings", []) + overall_warnings)),
                result_rows=len(result["rows"]),
                rows=[
                    {
                        key: value[:160] if isinstance(value, str) else value
                        for key, value in row.items()
                    }
                    for row in result["rows"][:30]
                ],
            )
        )
    payload = dict(question=question, results=cards, relationships=relationships)
    for limit in (30, 10, 5, 1):
        for card in cards:
            card["rows"] = card["rows"][:limit]
            card["shown_rows"] = len(card["rows"])
        if len(encode(payload)) <= MAX_PROMPT_CHARACTERS:
            return payload
    raise ApiError(
        "The calculated result is too wide for a written explanation. The result tables are available."
    )
