import pytest
from pydantic import ValidationError

from app.models import ApiError, SqlPlan, WorkspacePlan, WorkspaceQuery
from app.services.context import (
    MAX_PROMPT_CHARACTERS,
    encode,
    explanation_payload,
    planning_payload,
    workspace_context,
)


def project_with_wide_schemas(name_length=15):
    return dict(
        tables=[
            dict(
                id=f"table-{i}",
                name=f"Table {i}",
                kind="source",
                rowCount=20000,
                columns=[
                    dict(
                        name=f"{j:03d}" + "x" * (name_length - 3),
                        type="text",
                        missing=0,
                        samples=["z" * 200, "y" * 200],
                        min="a",
                        max="z",
                    )
                    for j in range(40)
                ],
            )
            for i in range(13)
        ],
        files=[dict(content="PRIVATE_FULL_CSV_CONTENT")],
        canvas=dict(operations=[], positions={}),
    )


def test_context_sheds_samples_and_history_without_losing_identifiers():
    context = workspace_context(project_with_wide_schemas())
    payload = planning_payload(
        context, "Summarize", [dict(question="Old question", answer="a" * 8000) for _ in range(8)]
    )
    assert len(encode(payload)) <= MAX_PROMPT_CHARACTERS
    assert len(payload["tables"]) == 13
    assert all(len(table["columns"]) == 40 for table in payload["tables"])
    assert payload["tables"][0]["columns"][0]["name"] == context["tables"][0]["columns"][0]["name"]
    assert "samples" not in payload["tables"][0]["columns"][0]
    assert len(context["tables"][0]["columns"][0]["samples"][0]) == 64
    assert "PRIVATE_FULL_CSV_CONTENT" not in encode(payload)


def test_oversized_identifiers_are_rejected_before_a_model_call():
    with pytest.raises(ApiError, match="schemas are too large"):
        planning_payload(workspace_context(project_with_wide_schemas(120)), "Summarize", [])


def test_combined_explanation_bounds_rows_and_carries_lineage_and_partial_errors():
    section = dict(
        title="Revenue",
        tableName="Combined sales",
        tableIds=["derived"],
        plan=dict(explanation="Sum revenue"),
        warnings=[],
        rows=[dict(label="x" * 2000, revenue=i) for i in range(100)],
        chart={"data": "not sent"},
    )
    result = dict(
        sections=[section],
        warnings=["One calculation failed"],
        relationships=[dict(table_id="derived", kind="stack", fileIds=["a", "b"])],
    )
    payload = explanation_payload(result, "Summarize")
    evidence = payload["results"][0]
    assert evidence["result_rows"] == 100 and evidence["shown_rows"] == 30
    assert len(evidence["rows"][0]["label"]) == 160
    assert evidence["warnings"] == result["warnings"]
    assert payload["relationships"] == result["relationships"]
    assert "chart" not in evidence
    assert len(section["rows"]) == 100 and len(section["rows"][0]["label"]) == 2000


def test_workspace_plan_caps_query_count_and_requires_one_outcome():
    query = WorkspaceQuery(
        table_ids=["sales"], plan=SqlPlan(sql_query="SELECT COUNT(*) FROM sales")
    )
    with pytest.raises(ValidationError):
        WorkspacePlan(queries=[query] * 4)
    with pytest.raises(ValidationError):
        WorkspacePlan()
    with pytest.raises(ValidationError):
        WorkspacePlan(queries=[query], clarification="Which metric?")
