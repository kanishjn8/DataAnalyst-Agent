import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai.errors import ClientError

from app.config import Settings
from app.models import ApiError, SqlPlan, WorkspacePlan, WorkspaceQuery
from app.services.gemini import GeminiProvider


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_structured_sql_contract_and_repair_evidence(monkeypatch):
    provider = GeminiProvider(Settings(gemini_api_key="test-only-key"))
    reply = SimpleNamespace(
        text=SqlPlan(sql_query="SELECT SUM(revenue) total FROM sales").model_dump_json()
    )
    mock = AsyncMock(return_value=reply)
    monkeypatch.setattr(provider.client.aio.models, "generate_content", mock)
    try:
        result = await provider.plan(
            [{"alias": "sales", "columns": [{"name": "revenue", "type": "number"}]}],
            "Total?",
            [],
            error="Binder Error: missing column",
        )
        assert result.sql_query.startswith("SELECT")
        config = mock.call_args.kwargs["config"]
        assert config.response_mime_type == "application/json"
        assert config.response_schema is None
        assert config.response_json_schema == SqlPlan.model_json_schema()
        assert config.response_json_schema["additionalProperties"] is False
        payload = json.loads(mock.call_args.kwargs["contents"])
        assert payload["error"] == "Binder Error: missing column"
        assert "test-only-key" not in mock.call_args.kwargs["contents"]
    finally:
        await provider.close()


@pytest.mark.anyio
async def test_quota_failure_is_clear_and_does_not_start_a_repair_loop(monkeypatch):
    provider = GeminiProvider(Settings(gemini_api_key="test-only-key"))
    mock = AsyncMock(side_effect=ClientError(429, {"error": {"message": "Quota exhausted"}}))
    monkeypatch.setattr(provider.client.aio.models, "generate_content", mock)
    try:
        with pytest.raises(ApiError, match="quota resets") as problem:
            await provider.workspace_plan(
                dict(tables=[], relationships=[], preferred_table_ids=[]), "Total?", []
            )
        assert problem.value.status == 429 and mock.await_count == 1
    finally:
        await provider.close()


@pytest.mark.anyio
async def test_one_workspace_structured_request_contains_all_schema_and_relationships(monkeypatch):
    provider = GeminiProvider(Settings(gemini_api_key="test-only-key"))
    reply = WorkspacePlan(
        queries=[
            WorkspaceQuery(
                table_ids=["combined"],
                plan=SqlPlan(sql_query="SELECT SUM(revenue) FROM combined"),
            )
        ]
    )
    mock = AsyncMock(return_value=SimpleNamespace(text=reply.model_dump_json()))
    monkeypatch.setattr(provider.client.aio.models, "generate_content", mock)
    context = dict(
        tables=[dict(table_id=key, columns=[]) for key in ("first", "second", "combined")],
        relationships=[dict(table_id="combined", kind="stack", fileIds=["first", "second"])],
        preferred_table_ids=["combined"],
    )
    try:
        result = await provider.workspace_plan(context, "Total revenue?", [])
        assert len(result.queries) == 1
        assert mock.await_count == 1
        payload = json.loads(mock.call_args.kwargs["contents"])
        assert payload["tables"] == context["tables"]
        assert payload["relationships"] == context["relationships"]
        assert (
            mock.call_args.kwargs["config"].response_json_schema
            == WorkspacePlan.model_json_schema()
        )
    finally:
        await provider.close()
