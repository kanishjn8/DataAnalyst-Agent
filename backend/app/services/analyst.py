from contextlib import AsyncExitStack
from uuid import uuid4

import duckdb

from ..core import engine
from ..core.canvas import inputs
from ..core.sql import referenced_tables
from ..models import ApiError, SqlPlan
from .context import workspace_context
from .workspaces import digest, identity, now


class Analyst:
    def __init__(self, workspaces, provider):
        self.workspaces, self.provider = workspaces, provider
        self.repository = workspaces.repository

    def selected(self, project, ids):
        by_id = {table["id"]: table for table in project["tables"]}
        if not ids:
            consumed = {
                key for node in project["canvas"]["operations"] for key in inputs(node["operation"])
            }
            ids = [key for key in by_id if key not in consumed]
        if not ids or len(ids) != len(set(ids)) or any(key not in by_id for key in ids):
            raise ApiError("Choose valid tables from this analysis.")
        return [by_id[key] for key in ids]

    def profiles(self, tables):
        return [
            dict(
                table_id=table["id"],
                alias=engine.alias(table["id"]),
                **{**table["profile"], "name": table["name"]},
            )
            for table in tables
        ]

    async def calculation(self, tables, plan, question, history, budget):
        for attempt in range(3):
            if plan.clarification:
                return self.result(tables, plan, [], False), plan
            try:
                aliases = {engine.alias(table["id"]): table for table in tables}
                used = referenced_tables(plan.sql_query, aliases)
                used_tables = [table for alias, table in aliases.items() if alias in used]
                async with AsyncExitStack() as stack:
                    paths = [
                        (
                            table,
                            await stack.enter_async_context(
                                self.workspaces.files.use(table["objectKey"])
                            ),
                        )
                        for table in used_tables
                    ]
                    rows, truncated = await self.workspaces.execution.run(
                        engine.query, paths, plan.sql_query, timeout=15
                    )
                return self.result(used_tables, plan, rows, truncated), plan
            except (
                duckdb.ParserException,
                duckdb.BinderException,
                duckdb.ConversionException,
                ApiError,
            ) as error:
                if isinstance(error, ApiError) and error.status in (408, 429):
                    raise
                if attempt >= 2 or budget["repairs"] <= 0:
                    raise ApiError(
                        "Could not calculate this question after checking the SQL. Try rephrasing it."
                    ) from None
                budget["repairs"] -= 1
                # Binder/parser errors describe query/schema problems; no credentials or object paths are supplied.
                message = str(error)[:1200]
                plan = await self.provider.plan(
                    self.profiles(tables),
                    question,
                    history,
                    previous=plan.model_dump(),
                    error=message,
                )

    def result(self, tables, plan: SqlPlan, rows, truncated):
        chart = None
        warnings = list(
            dict.fromkeys(note for table in tables for note in table.get("warnings", []))
        )
        config = plan.chart_config
        if config.type != "none" and rows:
            x, y = config.x_key, config.y_key
            valid = (
                x in rows[0]
                and y in rows[0]
                and any(isinstance(row.get(y), (int, float)) for row in rows)
            )
            if config.type == "scatter":
                valid = valid and any(isinstance(row.get(x), (int, float)) for row in rows)
            if config.type == "pie":
                valid = (
                    valid
                    and len(rows) <= 12
                    and all(isinstance(row.get(y), (int, float)) and row[y] >= 0 for row in rows)
                )
            if valid:
                chart = dict(type=config.type, x=x, y=y, data=rows)
            else:
                warnings.append(
                    "A chart could not be drawn from these columns; the result table is shown."
                )
        if truncated:
            warnings.append(
                "Only the first 200 result rows are shown. Aggregate or narrow the question for a complete result."
            )
        return dict(
            tableId=tables[0]["id"] if len(tables) == 1 else None,
            tableName=", ".join(table["name"] for table in tables),
            title=config.title,
            answer=plan.clarification
            or f"Calculated {len(rows)} result rows. See the result table and method below.",
            plan={"explanation": plan.reasoning},
            rows=rows,
            chart=chart,
            steps=[
                plan.reasoning or "Execute the validated SQL against the selected table versions."
            ],
            warnings=warnings,
            sourceVersions={table["id"]: table["version"] for table in tables},
            sql=plan.sql_query or None,
            matchedRows=sum(table["rowCount"] for table in tables),
            totalRows=sum(table["rowCount"] for table in tables),
        )

    def history(self, turns, table_id):
        relevant = (
            turns
            if table_id in (None, "all")
            else [
                turn
                for turn in turns
                if turn["result"].get("tableId") == table_id
                or table_id in turn["result"].get("tableIds", [])
            ]
        )
        return [
            dict(
                question=turn["question"],
                answer=turn["result"]["answer"][:1500],
                tables=turn["result"].get("tableIds", [turn["result"].get("tableId")]),
                sql=turn["result"].get("sql"),
                queries=[
                    dict(
                        tables=section.get("tableIds", [section.get("tableId")]),
                        sql=section.get("sql"),
                    )
                    for section in turn["result"].get("sections", [])
                ],
            )
            for turn in relevant[-6:]
        ]

    async def workspace_calculations(self, project, question, history):
        plan = await self.provider.workspace_plan(workspace_context(project), question, history)
        if plan.clarification:
            return dict(
                workspaceAnalysis=True,
                title=plan.title,
                tableName="Workspace analysis",
                tableIds=[],
                answer=plan.clarification,
                plan={"explanation": plan.reasoning},
                rows=[],
                chart=None,
                steps=[plan.reasoning] if plan.reasoning else [],
                warnings=[],
                sql=None,
                sections=[],
                sourceVersions={},
                matchedRows=0,
                totalRows=0,
            ), True
        by_id = {table["id"]: table for table in project["tables"]}
        # Validate every declared scope before opening any stored object.
        for query in plan.queries:
            if len(set(query.table_ids)) != len(query.table_ids) or any(
                key not in by_id for key in query.table_ids
            ):
                raise ApiError("The plan referred to tables outside this analysis.")
        budget = {"repairs": 2}
        results, warnings = [], []
        for index, query in enumerate(plan.queries, 1):
            try:
                if query.plan.clarification:
                    warnings.append(query.plan.clarification)
                    continue
                result, _ = await self.calculation(
                    [by_id[key] for key in query.table_ids],
                    query.plan,
                    question,
                    history,
                    budget,
                )
                if not result["sql"]:
                    warnings.append(result["answer"])
                    continue
                result["tableIds"] = list(result["sourceVersions"])
                result["answer"] = ""
                results.append(result)
            except ApiError as error:
                if error.status in (408, 429):
                    raise
                warnings.append(f"Calculation {index} could not be completed: {error.message}")
        if not results:
            raise ApiError("Could not calculate this question. Try narrowing or rephrasing it.")
        versions = {
            key: version for result in results for key, version in result["sourceVersions"].items()
        }
        return dict(
            workspaceAnalysis=True,
            title=plan.title,
            tableName="Workspace analysis",
            tableIds=list(versions),
            sourceVersions=versions,
            relationships=workspace_context(project)["relationships"],
            answer="The calculated results are shown below.",
            plan={"explanation": plan.reasoning},
            rows=[],
            chart=None,
            sql=None,
            sections=results,
            steps=[result["plan"]["explanation"] for result in results],
            warnings=list(
                dict.fromkeys(
                    warnings + [note for result in results for note in result["warnings"]]
                )
            ),
            matchedRows=sum(by_id[key]["rowCount"] for key in versions),
            totalRows=sum(by_id[key]["rowCount"] for key in versions),
        ), False

    async def start(self, owner, request):
        identity(request.requestId)
        project = await self.workspaces.get(owner, request.workspaceId)
        if project["dataVersion"] != request.dataVersion:
            raise ApiError("The dataset changed. Reload this analysis.", 409)
        if not request.question.strip():
            raise ApiError("Enter a question.")
        workspace = request.tableId in (None, "all")
        tables = project["tables"] if workspace else self.selected(project, [request.tableId])
        if not tables:
            raise ApiError("Upload a table before asking a question.")
        turns = await self.repository.analyses(owner, project["id"], project["dataVersion"])
        stored = next((turn for turn in turns if turn["id"] == request.requestId), None)
        for turn in turns:
            if (
                turn["id"] == request.requestId
                or turn["result"].get("requestGroupId") == request.requestId
            ) and (
                turn["question"] != request.question
                or turn["result"].get("requestScope") != request.tableId
            ):
                raise ApiError("This request ID belongs to another question or table.", 409)
        if not stored and len(turns) >= 200:
            raise ApiError("This analysis has reached 200 findings.")
        history = self.history(turns, request.tableId)
        key = digest(
            dict(
                workflow=2,
                scope=request.tableId,
                question=request.question,
                history=history,
                tables=[
                    dict(id=table["id"], version=table["version"], name=table["name"])
                    for table in tables
                ],
                relationships=project["canvas"]["operations"] if workspace else [],
                model=self.provider.model_key,
            )
        )
        cached = (
            stored["result"]
            if stored
            else await self.repository.cached(
                owner,
                project["id"],
                project["dataVersion"],
                key,
            )
        )
        if not cached:
            if not self.provider.ready:
                raise ApiError("Analysis is currently unavailable.", 503)
            await self.repository.consume_quota(owner)

        async def events():
            yield dict(
                type="status",
                message="Planning your workspace analysis…"
                if workspace
                else f"Analyzing {tables[0]['name']}…",
            )
            if cached:
                result = cached
            else:
                if workspace:
                    result, clarification = await self.workspace_calculations(
                        project, request.question, history
                    )
                else:
                    plan = await self.provider.plan(
                        self.profiles(tables), request.question, history
                    )
                    result, plan = await self.calculation(
                        tables, plan, request.question, history, {"repairs": 2}
                    )
                    clarification = bool(plan.clarification)
                if not clarification:
                    yield dict(type="status", message="Explaining the calculated results…")
                    answer = ""
                    try:
                        async for chunk in self.provider.explain(result, request.question):
                            answer += chunk
                            yield dict(type="text", text=chunk)
                        if answer.strip():
                            result["answer"] = answer
                    except Exception:
                        result["warnings"].append(
                            "The explanation was unavailable; the calculated results are shown."
                        )
            result = {
                **result,
                "requestGroupId": request.requestId,
                "requestScope": request.tableId,
            }
            if not stored:
                saved = await self.repository.insert_analysis(
                    owner,
                    project["id"],
                    project["dataVersion"],
                    dict(
                        id=request.requestId,
                        question=request.question,
                        result=result,
                        createdAt=now(),
                    ),
                    key,
                )
                if not saved:
                    raise ApiError("The dataset changed while the question was running.", 409)
            yield dict(
                type="result",
                result=result,
                requestId=request.requestId,
                analysisId=request.requestId,
                cached=bool(cached),
            )
            yield dict(type="done", requestId=request.requestId, completed=1, failed=0)

        return events()

    async def dashboard(self, owner, project_id, request):
        project = await self.workspaces.get(owner, project_id)
        selected = self.selected(project, request.tableIds)
        scope = digest(sorted(table["id"] for table in selected))
        await self.repository.consume_quota(owner)
        prior = await self.repository.dashboard(owner, project["id"], scope)
        if prior and prior.get("requestId") == request.requestId:
            return prior
        if not self.provider.ready:
            raise ApiError("Analysis is currently unavailable.", 503)
        plan = await self.provider.dashboard(self.profiles(selected))
        by_id = {table["id"]: table for table in selected}
        if (
            sum(card.plan.chart_config.type == "none" for card in plan.cards) > 3
            or sum(card.plan.chart_config.type != "none" for card in plan.cards) > 4
        ):
            raise ApiError("The dashboard plan exceeded its card limit. Please try again.")
        results = []
        budget = {"repairs": 2}
        for card in plan.cards:
            if card.table_id not in by_id:
                raise ApiError("The dashboard referred to an unselected table.")
            result, _ = await self.calculation(
                [by_id[card.table_id]], card.plan, "Generate a dashboard", [], budget
            )
            results.append(result)
        answer = ""
        try:
            async for text in self.provider.explain(
                results,
                "Summarize these dashboard findings without combining separate table totals.",
            ):
                answer += text
        except Exception:
            answer = "The calculated cards are shown below. The written overview was unavailable."
        payload = dict(
            id=str(uuid4()),
            requestId=request.requestId,
            dataVersion=project["dataVersion"],
            tableIds=[table["id"] for table in selected],
            cards=results,
            summary=answer,
            createdAt=now(),
        )
        async with self.workspaces.cache.mutation(owner, project["id"]):
            await self.repository.save_dashboard(
                owner, project["id"], project["dataVersion"], scope, payload
            )
        await self.read_dashboard(owner, project["id"], [])
        return payload

    async def read_dashboard(self, owner, project_id, table_ids):
        project_id = identity(project_id)
        # The empty scope is resolved once on a miss. Cached responses are owner scoped.
        key = (owner, project_id, digest(sorted(table_ids)))

        async def load():
            project = await self.workspaces.get(owner, project_id)
            selected = self.selected(project, table_ids) if table_ids else []
            return await self.repository.dashboard(
                owner,
                project_id,
                digest(sorted(table["id"] for table in selected)) if table_ids else None,
            )

        return await self.workspaces.cache.read(key, load)
