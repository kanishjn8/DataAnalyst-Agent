"""Local integration tests: real Postgres/Storage/Auth, deterministic test-only model."""

import asyncio
import json
from uuid import uuid4

import httpx
import jwt
import pytest

from app.config import Settings
from app.main import create_app
from app.models import (
    ChartConfig,
    DashboardCard,
    DashboardPlan,
    SqlPlan,
    WorkspacePlan,
    WorkspaceQuery,
)


class Model:
    ready = True
    model_key = "test-only-sql-provider"

    def __init__(self):
        self.calls = 0
        self.explanations = 0
        self.fail_first = False
        self.contexts = []
        self.histories = []
        self.workspace_builder = None

    async def plan(self, profiles, question, history, previous=None, error=None):
        self.calls += 1
        table = profiles[0]
        if self.fail_first and not error:
            sql = f"SELECT missing_column FROM {table['alias']}"
        elif any(c["name"] == "revenue" for c in table["columns"]):
            sql = f"SELECT SUM(revenue) AS revenue FROM {table['alias']}"
        else:
            sql = f"SELECT COUNT(*) AS records FROM {table['alias']}"
        return SqlPlan(
            sql_query=sql,
            chart_config=ChartConfig(title="Summary"),
            reasoning="Calculate a total from the selected table.",
        )

    async def dashboard(self, profiles):
        self.calls += 1
        return DashboardPlan(
            cards=[
                DashboardCard(
                    table_id=p["table_id"],
                    plan=SqlPlan(
                        sql_query=f"SELECT COUNT(*) records FROM {p['alias']}",
                        chart_config=ChartConfig(title=p["name"]),
                        reasoning="Count records.",
                    ),
                )
                for p in profiles[:3]
            ]
        )

    async def workspace_plan(self, context, question, history):
        self.calls += 1
        self.contexts.append(context)
        self.histories.append(history)
        if self.workspace_builder:
            return self.workspace_builder(context)
        tables = {table["table_id"]: table for table in context["tables"]}
        return WorkspacePlan(
            title="Workspace summary",
            reasoning="Use final outputs and independent sources.",
            queries=[
                WorkspaceQuery(
                    table_ids=[key],
                    plan=SqlPlan(
                        sql_query=f"SELECT SUM(revenue) revenue FROM {tables[key]['alias']}"
                        if any(column["name"] == "revenue" for column in tables[key]["columns"])
                        else f"SELECT COUNT(*) records FROM {tables[key]['alias']}",
                        chart_config=ChartConfig(title=tables[key]["name"]),
                        reasoning="Calculate the requested metric.",
                    ),
                )
                for key in context["preferred_table_ids"][:3]
            ],
        )

    async def explain(self, results, question):
        self.explanations += 1
        yield "The figures were calculated from the selected table."

    async def close(self):
        pass


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def stack(tmp_path):
    settings = Settings(
        cache_directory=str(tmp_path / "cache"), redis_namespace=f"integration:{uuid4().hex}"
    )
    provider = Model()
    app = create_app(settings, provider=provider)
    owner = str(uuid4())
    token = jwt.encode(
        {
            "sub": owner,
            "role": "authenticated",
            "aud": "authenticated",
            "iss": settings.jwt_issuer,
            "exp": 4102444800,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client, app, provider, owner
        for project in await app.state.repository.list(owner):
            await app.state.workspaces.execute(
                owner,
                __import__("app.models", fromlist=["WorkspaceAction"]).WorkspaceAction(
                    action="delete", workspaceId=project["id"]
                ),
            )


async def action(client, action_name, **fields):
    response = await client.post("/workspace", json={"action": action_name, **fields})
    assert response.status_code == 200, response.text
    return response.json()


async def upload(client, project, name, content):
    grant = await client.post(
        f"/analyses/{project['id']}/uploads", json={"name": name, "bytes": len(content.encode())}
    )
    assert grant.status_code == 200, grant.text
    data = grant.json()
    async with httpx.AsyncClient() as direct:
        sent = await direct.put(data["url"], content=content.encode(), headers=data["headers"])
        assert sent.is_success, sent.text
    done = await client.post(f"/uploads/{data['uploadId']}/complete", json={})
    assert done.status_code == 200, done.text
    return done.json()["project"], data


@pytest.mark.anyio
async def test_direct_upload_profile_completion_and_cold_cache(stack):
    client, app, _, owner = stack
    project = (await action(client, "create", title="Upload test"))["project"]
    project, grant = await upload(
        client, project, "sales.csv", "region,revenue\nNorth,100\nSouth,50"
    )
    table = project["tables"][0]
    assert table["rowCount"] == 2 and table["columns"][1]["sqlType"] == "DOUBLE"
    again = await client.post(f"/uploads/{grant['uploadId']}/complete", json={})
    assert again.json()["project"]["revision"] == project["revision"]
    internal = await app.state.workspaces.get(owner, project["id"])
    assert "content" not in json.dumps(internal)
    await app.state.files.evict([internal["files"][0]["objectKey"]])
    preview = await action(
        client,
        "tablePreview",
        workspaceId=project["id"],
        revision=project["revision"],
        tableId=table["id"],
    )
    assert preview["preview"]["rows"][0]["revenue"] == 100


@pytest.mark.anyio
async def test_join_materialization_graph_validation_and_persistence(stack):
    client, app, _, owner = stack
    project = (await action(client, "create", title="Join test"))["project"]
    project, _ = await upload(client, project, "orders.csv", "id,revenue\n001,10\n002,20")
    project, _ = await upload(client, project, "customers.csv", "id,region\n001,North")
    left, right = project["files"]
    canvas = {
        "kind": "graph",
        "positions": {},
        "operations": [
            {
                "id": "joined",
                "name": "Regional sales",
                "operation": {
                    "kind": "join",
                    "leftId": left["id"],
                    "rightId": right["id"],
                    "leftKey": "id",
                    "rightKey": "id",
                    "joinType": "left",
                },
            }
        ],
    }
    project = (
        await action(
            client, "canvas", workspaceId=project["id"], revision=project["revision"], canvas=canvas
        )
    )["project"]
    internal = await app.state.workspaces.get(owner, project["id"])
    joined = internal["tables"][-1]
    assert joined["objectKey"] and await app.state.storage.info(joined["objectKey"]) > 0
    # A stored derived table has a display name, not a CSV filename. Both
    # CSV and Parquet must be able to hydrate after a container restart.
    await app.state.files.evict([joined["objectKey"]])
    preview = (
        await action(
            client,
            "tablePreview",
            workspaceId=project["id"],
            revision=project["revision"],
            tableId="joined",
        )
    )["preview"]
    assert preview["rowCount"] == 2
    assert preview["rows"][0]["revenue"] == 10
    assert "North" in preview["rows"][0].values()
    before = internal["dataVersion"]
    canvas["positions"]["joined"] = {"x": 400, "y": 300}
    moved = (
        await action(
            client, "canvas", workspaceId=project["id"], revision=project["revision"], canvas=canvas
        )
    )["project"]
    assert moved["dataVersion"] == before
    removed = (
        await action(
            client,
            "removeFile",
            workspaceId=project["id"],
            revision=moved["revision"],
            fileId=left["id"],
        )
    )["project"]
    assert len(removed["tables"]) == 1 and not removed["canvas"]["operations"]


@pytest.mark.anyio
async def test_stack_preview_and_rename_preserve_saved_data(stack, monkeypatch):
    client, app, model, owner = stack
    project = (await action(client, "create", title="Prepared previews"))["project"]
    project, _ = await upload(
        client,
        project,
        "first.csv",
        "id,revenue\n" + "\n".join(f"{i},{i * 10}" for i in range(1, 10)),
    )
    project, _ = await upload(client, project, "second.csv", "id,revenue\n10,100\n11,110")
    left, right = project["files"]
    canvas = dict(
        kind="graph",
        positions={},
        operations=[
            dict(
                id="stacked",
                name="Combined sales",
                operation=dict(kind="stack", fileIds=[left["id"], right["id"]]),
            )
        ],
    )
    project = (
        await action(
            client, "canvas", workspaceId=project["id"], revision=project["revision"], canvas=canvas
        )
    )["project"]
    before = await app.state.workspaces.get(owner, project["id"])
    saved = before["tables"][-1]
    await app.state.files.evict([saved["objectKey"]])

    def unexpected_rebuild(*_args):
        raise AssertionError("Saved previews and renaming must not rebuild prepared tables")

    from app.core import engine

    monkeypatch.setattr(engine, "prepare", unexpected_rebuild)
    preview = (
        await action(
            client,
            "tablePreview",
            workspaceId=project["id"],
            revision=project["revision"],
            tableId="stacked",
        )
    )["preview"]
    assert preview["rowCount"] == 11 and len(preview["rows"]) == 8
    assert preview["rows"][0] == {"id": 1, "revenue": 10}
    project = (
        await action(
            client,
            "renameTable",
            workspaceId=project["id"],
            revision=project["revision"],
            tableId="stacked",
            name="  Sales history  ",
        )
    )["project"]
    assert project["dataVersion"] == before["dataVersion"]
    assert project["canvas"]["operations"][0]["name"] == "Sales history"
    assert project["tables"][-1]["name"] == "Sales history"
    after = await app.state.workspaces.get(owner, project["id"])
    assert after["tables"][-1]["objectKey"] == saved["objectKey"]
    assert after["tables"][-1]["profile"]["name"] == "Sales history"
    project = (
        await action(
            client,
            "renameTable",
            workspaceId=project["id"],
            revision=project["revision"],
            tableId=left["id"],
            name="Quarter one",
        )
    )["project"]
    assert project["files"][0]["name"] == "Quarter one"
    duplicate = await client.post(
        f"/analyses/{project['id']}/uploads", json={"name": "first.csv", "bytes": 10}
    )
    assert duplicate.status_code == 400 and "already" in duplicate.text
    await app.state.files.evict([before["files"][0]["objectKey"]])
    source = (
        await action(
            client,
            "tablePreview",
            workspaceId=project["id"],
            revision=project["revision"],
            tableId=left["id"],
        )
    )["preview"]
    assert source["description"] == "Quarter one" and len(source["rows"]) == 8
    assert model.calls == 0 and model.explanations == 0


@pytest.mark.anyio
async def test_actual_duckdb_question_repairs_and_saved_context(stack):
    client, app, model, _ = stack
    project = (await action(client, "create", title="Questions"))["project"]
    project, _ = await upload(client, project, "sales.csv", "revenue\n100\n50")
    model.fail_first = True
    payload = dict(
        workspaceId=project["id"],
        dataVersion=project["dataVersion"],
        tableId=project["tables"][0]["id"],
        requestId=str(uuid4()),
        question="Total revenue?",
    )
    response = await client.post("/analyze", json=payload)
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done", events
    result = next(event["result"] for event in events if event["type"] == "result")
    assert result["rows"] == [{"revenue": 150}]
    assert model.calls == 2 and model.explanations == 1
    calls = model.calls
    retry = await client.post("/analyze", json=payload)
    assert '"cached": true' in retry.text and model.calls == calls


@pytest.mark.anyio
async def test_dashboard_cache_and_invalidation_without_regeneration(stack):
    client, app, model, owner = stack
    project = (await action(client, "create", title="Dashboard"))["project"]
    project, _ = await upload(client, project, "sales.csv", "revenue\n100\n50")
    generated = await client.post(
        f"/analyses/{project['id']}/dashboard", json={"tableIds": [], "requestId": str(uuid4())}
    )
    assert generated.status_code == 200, generated.text
    assert model.calls == 1 and model.explanations == 1
    route = f"/analyses/{project['id']}/dashboard"
    assert (await client.get(route)).headers["x-cache"] == "HIT"
    assert (await client.get(route)).headers["x-cache"] == "HIT"
    assert model.calls == 1
    # Persistence is the fallback, so clearing only cache does not rerun the model.
    await app.state.cache.invalidate(owner, project["id"])
    assert (await client.get(route)).json()["dashboard"]["cards"][0]["rows"] == [{"records": 2}]
    assert model.calls == 1
    project, _ = await upload(client, project, "more.csv", "revenue\n10")
    assert (await client.get(route)).json()["dashboard"] is None


@pytest.mark.anyio
async def test_auth_ownership_untrusted_sizes_and_delete(stack):
    client, app, _, owner = stack
    project = (await action(client, "create", title="Private"))["project"]
    unauth = await client.post(
        "/workspace",
        json={"action": "load", "workspaceId": project["id"]},
        headers={"Authorization": ""},
    )
    assert unauth.status_code == 401
    settings = Settings()
    other = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": "authenticated",
            "aud": "authenticated",
            "iss": settings.jwt_issuer,
            "exp": 4102444800,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert (
        await client.post(
            "/workspace",
            json={"action": "delete", "workspaceId": project["id"]},
            headers={"Authorization": f"Bearer {other}"},
        )
    ).status_code == 404
    project, grant = await upload(client, project, "sales.csv", "revenue\n100")
    internal = await app.state.workspaces.get(owner, project["id"])
    key = internal["files"][0]["objectKey"]
    await action(client, "delete", workspaceId=project["id"])
    with pytest.raises(Exception):
        await app.state.storage.info(key)
    assert (await client.get(f"/analyses/{project['id']}/dashboard")).status_code == 404


@pytest.mark.anyio
async def test_anonymous_sessions_cannot_access_workspaces(stack):
    client, _, model, owner = stack
    settings = Settings()
    token = jwt.encode(
        {
            "sub": owner,
            "role": "authenticated",
            "aud": "authenticated",
            "iss": settings.jwt_issuer,
            "exp": 4102444800,
            "is_anonymous": True,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    responses = await asyncio.gather(*[
        client.post(
            "/workspace", headers={"Authorization": f"Bearer {token}"}, json={"action": "list"}
        )
        for _ in range(2)
    ])
    assert all(response.status_code == 401 for response in responses)
    assert model.calls == 0


@pytest.mark.anyio
async def test_real_local_gotrue_signup_and_token_verification(stack):
    client, _, _, _ = stack
    settings = Settings()
    async with httpx.AsyncClient() as direct:
        result = await direct.post(
            settings.supabase_public_url + "/auth/v1/signup",
            headers={"apikey": settings.supabase_anon_key},
            json={"email": f"test-{uuid4()}@example.com", "password": "Local-only-password-42"},
        )
    assert result.status_code == 200, result.text
    token = result.json()["access_token"]
    response = await client.post(
        "/workspace", headers={"Authorization": f"Bearer {token}"}, json={"action": "list"}
    )
    assert response.status_code == 200, response.text


@pytest.mark.anyio
async def test_reads_saves_and_health_do_not_compete_with_model_requests(stack, monkeypatch):
    client, app, model, owner = stack
    project = (await action(client, "create", title="Concurrent requests"))["project"]
    project, _ = await upload(client, project, "sales.csv", "revenue\n100\n50")
    started, release = asyncio.Event(), asyncio.Event()
    original = model.plan

    async def slow_plan(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(model, "plan", slow_plan)
    payload = dict(
        workspaceId=project["id"],
        dataVersion=project["dataVersion"],
        tableId=project["tables"][0]["id"],
        requestId=str(uuid4()),
        question="Total revenue?",
    )
    running = asyncio.create_task(client.post("/analyze", json=payload))
    try:
        await asyncio.wait_for(started.wait(), 5)
        responses = await asyncio.gather(
            client.post("/workspace", json={"action": "load", "workspaceId": project["id"]}),
            client.post("/workspace", json={"action": "list"}),
            client.post(
                "/workspace",
                json={
                    "action": "patch",
                    "workspaceId": project["id"],
                    "revision": project["revision"],
                    "question": "Next question draft",
                },
            ),
            *[client.get("/health") for _ in range(20)],
        )
        assert all(response.status_code == 200 for response in responses)
        duplicate = await client.post("/analyze", json={**payload, "requestId": str(uuid4())})
        assert duplicate.status_code == 429  # Only duplicate analytical work is blocked.
        async with app.state.repository.pool.connection() as db:
            quota = await (
                await db.execute("SELECT count FROM request_limits WHERE owner=%s", (owner,))
            ).fetchone()
        assert quota["count"] == 1
    finally:
        release.set()
        result = await asyncio.wait_for(running, 5)
    assert '"type": "done"' in result.text


@pytest.mark.anyio
async def test_liveness_never_uses_database_or_model(stack, monkeypatch):
    client, app, model, _ = stack

    def unavailable_database():
        raise AssertionError("Liveness must not access the database")

    with monkeypatch.context() as context:
        context.setattr(app.state.repository.pool, "connection", unavailable_database)
        response = await client.get("/health")
    assert response.status_code == 200
    assert model.calls == 0 and model.explanations == 0


@pytest.mark.anyio
async def test_all_tables_one_plan_one_answer_lineage_history_and_export(stack):
    client, app, model, _ = stack
    project = (await action(client, "create", title="Workspace questions"))["project"]
    project, _ = await upload(client, project, "first.csv", "revenue\n100\n50")
    project, _ = await upload(client, project, "second.csv", "revenue\n20")
    project, _ = await upload(client, project, "inventory.csv", "product,stock\nWidget,4")
    first, second, inventory = project["files"]
    canvas = dict(
        kind="graph",
        positions={},
        operations=[
            dict(
                id="combined",
                name="Combined sales",
                operation=dict(kind="stack", fileIds=[first["id"], second["id"]]),
            )
        ],
    )
    project = (
        await action(
            client, "canvas", workspaceId=project["id"], revision=project["revision"], canvas=canvas
        )
    )["project"]
    payload = dict(
        workspaceId=project["id"],
        dataVersion=project["dataVersion"],
        tableId="all",
        requestId=str(uuid4()),
        question="Summarize sales and inventory.",
    )
    response = await client.post("/analyze", json=payload)
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done", events
    results = [event["result"] for event in events if event["type"] == "result"]
    assert len(results) == 1
    result = results[0]
    assert result["workspaceAnalysis"] and len(result["sections"]) == 2
    assert {tuple(section["rows"][0].values()) for section in result["sections"]} == {(170,), (1,)}
    assert set(result["sourceVersions"]) == {"combined", inventory["id"]}
    assert model.calls == 1 and model.explanations == 1
    context = model.contexts[0]
    assert len(context["tables"]) == 4  # Original schemas are still available to the planner.
    assert set(context["preferred_table_ids"]) == {"combined", inventory["id"]}
    assert context["relationships"][0]["fileIds"] == [first["id"], second["id"]]
    retry = await client.post("/analyze", json=payload)
    assert '"cached": true' in retry.text
    assert model.calls == 1 and model.explanations == 1
    loaded = (await action(client, "load", workspaceId=project["id"]))["project"]
    assert len(loaded["analyses"]) == 1
    assert loaded["analyses"][0]["result"]["sections"] == result["sections"]
    exported = await client.post(
        "/workspace",
        json=dict(
            action="exportResult", workspaceId=project["id"], analysisId=payload["requestId"]
        ),
    )
    assert exported.status_code == 200
    assert "revenue" in exported.text and "records" in exported.text and "170" in exported.text
    report = await client.post(
        "/workspace", json=dict(action="exportReport", workspaceId=project["id"])
    )
    assert "Combined sales" in report.text and "Executed DuckDB SQL" in report.text
    followup = await client.post(
        "/analyze",
        json={**payload, "requestId": str(uuid4()), "question": "Explain those figures."},
    )
    assert '"type": "done"' in followup.text
    assert model.calls == 2 and model.explanations == 2
    assert model.histories[-1][0]["question"] == payload["question"]
    assert len(model.histories[-1][0]["queries"]) == 2


@pytest.mark.anyio
async def test_workspace_only_loads_tables_referenced_in_sql(stack, monkeypatch):
    client, _, model, _ = stack
    project = (await action(client, "create", title="Relevant data"))["project"]
    project, _ = await upload(client, project, "sales.csv", "revenue\n100\n50")
    project, _ = await upload(client, project, "stock.csv", "stock\n4")
    selected = project["tables"][0]["id"]

    def choose(context):
        table = next(t for t in context["tables"] if t["table_id"] == selected)
        return WorkspacePlan(
            queries=[
                WorkspaceQuery(
                    table_ids=[t["table_id"] for t in context["tables"]],
                    plan=SqlPlan(sql_query=f"SELECT SUM(revenue) total FROM {table['alias']}"),
                )
            ]
        )

    model.workspace_builder = choose
    from app.core import engine

    original, seen = engine.query, []

    def capture(task, paths, sql):
        seen.extend(table["id"] for table, _ in paths)
        return original(task, paths, sql)

    monkeypatch.setattr(engine, "query", capture)
    response = await client.post(
        "/analyze",
        json=dict(
            workspaceId=project["id"],
            dataVersion=project["dataVersion"],
            tableId="all",
            requestId=str(uuid4()),
            question="Total revenue?",
        ),
    )
    assert '"type": "done"' in response.text
    assert seen == [selected]
    assert model.calls == 1 and model.explanations == 1


@pytest.mark.anyio
async def test_workspace_shared_repair_budget_and_partial_results(stack, monkeypatch):
    client, _, model, _ = stack
    project = (await action(client, "create", title="Repair budget"))["project"]
    project, _ = await upload(client, project, "sales.csv", "revenue\n100\n50")

    def choose(context):
        table = context["tables"][0]
        return WorkspacePlan(
            queries=[
                WorkspaceQuery(
                    table_ids=[table["table_id"]],
                    plan=SqlPlan(sql_query=f"SELECT {field} FROM {table['alias']}"),
                )
                for field in ("bad_one", "bad_two", "SUM(revenue) total")
            ]
        )

    model.workspace_builder = choose

    async def invalid_repair(profiles, *_args, **_kwargs):
        model.calls += 1
        return SqlPlan(sql_query=f"SELECT still_missing FROM {profiles[0]['alias']}")

    monkeypatch.setattr(model, "plan", invalid_repair)
    response = await client.post(
        "/analyze",
        json=dict(
            workspaceId=project["id"],
            dataVersion=project["dataVersion"],
            tableId="all",
            requestId=str(uuid4()),
            question="Summarize.",
        ),
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done", events
    result = next(event["result"] for event in events if event["type"] == "result")
    assert len(result["sections"]) == 1 and len(result["warnings"]) == 2
    assert result["sections"][0]["rows"] == [{"total": 150}]
    assert model.calls == 3 and model.explanations == 1  # Four calls total, not four per query.


@pytest.mark.anyio
async def test_workspace_rejects_foreign_scope_and_clarifies_without_explanation(stack):
    client, _, model, _ = stack
    project = (await action(client, "create", title="Safe workspace"))["project"]
    project, _ = await upload(client, project, "sales.csv", "revenue\n100")
    payload = dict(
        workspaceId=project["id"],
        dataVersion=project["dataVersion"],
        tableId="all",
        requestId=str(uuid4()),
        question="Summarize.",
    )
    model.workspace_builder = lambda _context: WorkspacePlan(
        queries=[WorkspaceQuery(table_ids=[str(uuid4())], plan=SqlPlan(sql_query="SELECT 1"))]
    )
    response = await client.post("/analyze", json=payload)
    assert '"type": "error"' in response.text and "outside this analysis" in response.text
    assert model.calls == 1 and model.explanations == 0
    model.workspace_builder = lambda _context: WorkspacePlan(
        clarification="Which metric should be compared?"
    )
    response = await client.post("/analyze", json={**payload, "requestId": str(uuid4())})
    assert '"type": "done"' in response.text and "Which metric" in response.text
    assert model.calls == 2 and model.explanations == 0
