"""Streaming keeps the existing dashboard calculation and persistence workflow."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.models import ApiError, ChartConfig, DashboardCard, DashboardPlan, DashboardRequest, SqlPlan
from app.services.analyst import Analyst


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def scenario():
    table = dict(id="sales", name="Sales", profile={}, rowCount=2, version=1)
    project = dict(id=str(uuid4()), dataVersion=1, tables=[table], canvas=dict(operations=[]))
    repository = SimpleNamespace(
        consume_quota=AsyncMock(), dashboard=AsyncMock(return_value=None), save_dashboard=AsyncMock()
    )
    mutations = []

    @asynccontextmanager
    async def mutation(*args):
        mutations.append("start")
        yield
        mutations.append("end")

    workspaces = SimpleNamespace(
        repository=repository, get=AsyncMock(return_value=project),
        cache=SimpleNamespace(mutation=mutation),
    )
    plan = DashboardPlan(cards=[DashboardCard(
        table_id="sales", plan=SqlPlan(
            sql_query="SELECT COUNT(*) records FROM sales",
            chart_config=ChartConfig(title="Records"), reasoning="Count records.",
        ),
    )])

    async def explain(*args):
        yield "**Records:** "
        yield "2"

    provider = SimpleNamespace(ready=True, dashboard=AsyncMock(return_value=plan), explain=explain)
    analyst = Analyst(workspaces, provider)
    analyst.calculation = AsyncMock(return_value=(dict(title="Records", rows=[dict(records=2)]), None))
    analyst.read_dashboard = AsyncMock(return_value=(None, False))
    return SimpleNamespace(
        analyst=analyst, provider=provider, project=project, repository=repository,
        mutations=mutations, request=DashboardRequest(tableIds=["sales"], requestId=str(uuid4())),
    )


@pytest.mark.anyio
async def test_cards_and_summary_arrive_before_persistence_and_final_dashboard(scenario):
    s = scenario
    events = await s.analyst.start_dashboard("owner", s.project["id"], s.request)
    received = []
    async for event in events:
        received.append(event)
        if event["type"] in ("card", "text"):
            s.repository.save_dashboard.assert_not_awaited()
        if event["type"] == "dashboard":
            s.repository.save_dashboard.assert_awaited_once()
    assert [event["type"] for event in received] == [
        "status", "status", "card", "status", "text", "text", "status", "dashboard", "done"
    ]
    assert received[-2]["dashboard"]["summary"] == "**Records:** 2"
    assert received[-2]["dashboard"]["cards"][0]["rows"] == [dict(records=2)]
    assert s.provider.dashboard.await_count == 1
    assert s.mutations == ["start", "end"]
    s.analyst.read_dashboard.assert_awaited_once()


@pytest.mark.anyio
async def test_json_api_uses_same_workflow_and_completed_request_is_reused(scenario):
    s = scenario
    payload = await s.analyst.dashboard("owner", s.project["id"], s.request)
    s.repository.dashboard.return_value = payload
    s.provider.dashboard.reset_mock()
    s.repository.save_dashboard.reset_mock()
    events = await s.analyst.start_dashboard("owner", s.project["id"], s.request)
    assert [event["type"] async for event in events] == ["dashboard", "done"]
    s.provider.dashboard.assert_not_awaited()
    s.repository.save_dashboard.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_explanation_preserves_calculated_cards(scenario):
    s = scenario

    async def explain(*args):
        yield "Partial"
        raise RuntimeError("Provider unavailable")

    s.provider.explain = explain
    payload = await s.analyst.dashboard("owner", s.project["id"], s.request)
    assert payload["cards"]
    assert "overview was unavailable" in payload["summary"]


@pytest.mark.anyio
async def test_cancelled_stream_does_not_save_partial_dashboard(scenario):
    s = scenario
    events = await s.analyst.start_dashboard("owner", s.project["id"], s.request)
    async for event in events:
        if event["type"] == "card":
            await events.aclose()
            break
    s.repository.save_dashboard.assert_not_awaited()
    assert not s.mutations


@pytest.mark.anyio
async def test_changed_dataset_never_emits_a_saved_dashboard(scenario):
    s = scenario
    s.repository.save_dashboard.side_effect = ApiError("The dataset changed.", 409)
    events = await s.analyst.start_dashboard("owner", s.project["id"], s.request)
    received = []
    with pytest.raises(ApiError, match="dataset changed"):
        async for event in events:
            received.append(event["type"])
    assert "dashboard" not in received and "done" not in received


@pytest.mark.anyio
async def test_route_streams_errors_and_releases_user_capacity(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.config import Settings
    from app.main import create_app

    async def authenticate(request):
        return "test-owner"

    app = create_app(
        Settings(cache_directory=str(tmp_path)), authenticate=authenticate,
        provider=SimpleNamespace(ready=True),
    )
    request_id = str(uuid4())
    closed = []

    async def events():
        try:
            yield dict(type="status", message="Working…")
            raise ApiError("The dataset changed.", 409)
        finally:
            closed.append(True)

    app.state.analyst.start_dashboard = AsyncMock(side_effect=lambda *args: events())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(2):
                response = await client.post(
                    f"/analyses/{uuid4()}/dashboard/stream",
                    json=dict(tableIds=["sales"], requestId=request_id),
                )
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("application/x-ndjson")
                assert response.headers["x-accel-buffering"] == "no"
                messages = [json.loads(line) for line in response.text.splitlines()]
                assert messages[-1] == dict(type="error", message="The dataset changed.", requestId=request_id)
            assert len(closed) == 2
            app.state.analyst.start_dashboard.side_effect = ApiError("Analysis not found.", 404)
            response = await client.post(
                f"/analyses/{uuid4()}/dashboard/stream",
                json=dict(tableIds=["sales"], requestId=request_id),
            )
            assert response.status_code == 404
    finally:
        await app.state.storage.close()
        await app.state.cache.close()
        app.state.workspaces.execution.close()
