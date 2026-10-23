import hashlib
import json
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from ..core import engine
from ..core.canvas import inputs, prune
from ..core.exports import export_csv, export_report, result_rows
from ..models import ApiError, TableGraph, WorkspaceAction


def now():
    return datetime.now(UTC).isoformat()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def identity(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        raise ApiError("Invalid analysis ID.") from None


class Workspaces:
    def __init__(self, repository, storage, files, execution, cache):
        self.repository, self.storage, self.files, self.execution, self.cache = (
            repository,
            storage,
            files,
            execution,
            cache,
        )

    async def get(self, owner, workspace_id):
        project = await self.repository.get(owner, identity(workspace_id))
        if not project:
            raise ApiError("Analysis not found.", 404)
        return project

    @staticmethod
    def summary(project):
        return {
            **{key: project[key] for key in ("id", "title", "createdAt", "updatedAt")},
            "fileCount": len(project["files"]),
            "ready": bool(project["files"]),
        }

    @staticmethod
    def public_table(table):
        return {key: table[key] for key in ("id", "name", "kind", "rowCount", "columns", "bytes")}

    async def load(self, owner, workspace_id):
        project = await self.get(owner, workspace_id)
        turns = await self.repository.analyses(owner, project["id"], project["dataVersion"])
        visible = {t["id"] for t in turns[-20:] + [t for t in turns if t["pinned"]]}
        return {
            **self.summary(project),
            "revision": project["revision"],
            "dataVersion": project["dataVersion"],
            "files": [self.public_table(table) for table in project["files"]],
            "tables": [self.public_table(table) for table in project["tables"]],
            "canvas": project["canvas"],
            "question": project["question"],
            "analyses": [turn for turn in turns if turn["id"] in visible],
        }

    async def save(self, owner, project, revision, changed=False):
        project = {
            **project,
            "revision": revision + 1,
            "dataVersion": project["dataVersion"] + int(changed),
            "updatedAt": now(),
        }
        await self.repository.save(owner, project, revision)
        await self.repository.publish_objects(
            owner, project["id"], [t["objectKey"] for t in project["tables"]]
        )
        return await self.load(owner, project["id"])

    @asynccontextmanager
    async def materialized(self, owner, project, graph=None, persist=False):
        graph = TableGraph.model_validate(graph or project["canvas"]).model_dump()
        nodes = {node["id"]: node for node in graph["operations"]}
        sources = {table["id"]: table for table in project["files"]}
        if len(nodes) != len(graph["operations"]) or set(nodes) & set(sources) or "all" in nodes:
            raise ApiError("Each table must have a unique ID.")
        if set(graph["positions"]) - (set(nodes) | set(sources)):
            raise ApiError("The canvas has a position for a missing table.")
        saved = {table["id"]: table for table in project["tables"]}
        results = {}
        visiting = set()
        async with AsyncExitStack() as stack:
            temporary = TemporaryDirectory()
            stack.callback(temporary.cleanup)

            async def resolve(table_id):
                if table_id in results:
                    return results[table_id]
                if table_id in visiting:
                    raise ApiError("Tables cannot form a circular connection.")
                visiting.add(table_id)
                if table_id in sources:
                    table = sources[table_id]
                    path = await stack.enter_async_context(self.files.use(table["objectKey"]))
                else:
                    node = nodes.get(table_id)
                    if not node:
                        raise ApiError("A connected table is missing.")
                    if not node["name"].strip():
                        raise ApiError("Enter a result table name.")
                    parents = [await resolve(key) for key in inputs(node["operation"])]
                    version = digest(
                        {
                            "operation": node["operation"],
                            "inputs": [table["version"] for table, _ in parents],
                            "engine": 1,
                        }
                    )
                    old = saved.get(table_id)
                    if old and old["version"] == version:
                        table = {**old, "name": node["name"].strip()}
                        path = await stack.enter_async_context(self.files.use(table["objectKey"]))
                    else:
                        content, sql, notes = await self.execution.run(
                            engine.prepare, parents, node["operation"]
                        )
                        path = Path(temporary.name) / (
                            hashlib.sha256(table_id.encode()).hexdigest() + ".csv"
                        )
                        path.write_text(content)
                        profile = await self.execution.run(engine.ingest, path, "derived.csv")
                        key = f"{owner}/{project['id']}/versions/{version}.csv"
                        table = dict(
                            id=table_id,
                            name=node["name"].strip(),
                            kind=node["operation"]["kind"],
                            bytes=len(content.encode()),
                            version=version,
                            objectKey=key,
                            sql=sql,
                            notes=notes,
                            **profile,
                        )
                        if persist:
                            await self.repository.register_object(owner, project["id"], key)
                            # A deterministic version key can already exist after an interrupted save.
                            try:
                                await self.storage.info(key)
                            except ApiError:
                                await self.storage.put(key, content.encode())
                results[table_id] = (table, path)
                visiting.remove(table_id)
                return table, path

            for table_id in [*sources, *nodes]:
                await resolve(table_id)
            yield {key: results[key] for key in [*sources, *nodes]}

    async def reserve(self, owner, workspace_id, request):
        workspace_id = identity(workspace_id)
        if not request.name.lower().endswith(".csv"):
            raise ApiError("Please choose a .csv file.")
        upload_id = str(uuid4())
        key = f"{owner}/{workspace_id}/uploads/{upload_id}.csv"
        await self.repository.reserve_upload(
            owner, workspace_id, upload_id, request.name, request.bytes, key
        )
        try:
            signed = await self.storage.grant(key)
        except Exception:
            await self.repository.fail_upload(owner, upload_id, "Could not authorize the upload.")
            raise
        return dict(
            uploadId=upload_id,
            url=signed,
            method="PUT",
            headers={"Content-Type": "text/csv"},
            expiresIn=7200,
        )

    async def complete(self, owner, upload_id):
        upload = await self.repository.upload(owner, identity(upload_id), claim=True)
        if upload["state"] == "ready":
            return await self.load(owner, str(upload["workspace_id"]))
        try:
            actual = await self.storage.info(upload["object_key"])
            if actual != upload["expected_bytes"]:
                raise ApiError("The uploaded file size does not match. Upload it again.")
            async with self.files.use(upload["object_key"]) as path:
                profile = await self.execution.run(engine.ingest, path, upload["name"])
                version = hashlib.sha256(path.read_bytes()).hexdigest()
            table = dict(
                id=str(upload["id"]),
                name=upload["name"],
                kind="source",
                bytes=actual,
                version=version,
                objectKey=upload["object_key"],
                **profile,
            )
            async with self.cache.mutation(owner, str(upload["workspace_id"])):
                await self.repository.finish_upload(owner, upload, table, now())
            return await self.load(owner, str(upload["workspace_id"]))
        except Exception as error:
            message = (
                error.message
                if isinstance(error, ApiError)
                else "Could not validate this file. Please try again."
            )
            await self.repository.fail_upload(owner, upload_id, message)
            raise

    async def execute(self, owner, action: WorkspaceAction):
        name = action.action
        fields = {
            "list": set(),
            "create": {"title"},
            "load": {"workspaceId"},
            "delete": {"workspaceId"},
            "patch": {"workspaceId", "revision", "title", "question"},
            "removeFile": {"workspaceId", "revision", "fileId"},
            "renameTable": {"workspaceId", "revision", "tableId", "name"},
            "canvas": {"workspaceId", "revision", "canvas"},
            "tablePreview": {"workspaceId", "revision", "tableId", "canvas"},
            "pin": {"workspaceId", "analysisId", "pinned"},
            "exportDataset": {"workspaceId", "tableId"},
            "exportResult": {"workspaceId", "analysisId"},
            "exportReport": {"workspaceId"},
        }
        if name not in fields or action.model_fields_set - {"action"} - fields[name]:
            raise ApiError("Invalid fields for this request.")
        required = fields[name] - (
            {"title", "question"}
            if name == "patch"
            else {"canvas"}
            if name == "tablePreview"
            else {"tableId"}
            if name == "exportDataset"
            else set()
        )
        if any(getattr(action, key) is None for key in required):
            raise ApiError("Required request fields are missing.")
        if name == "list":
            return dict(
                projects=[self.summary(project) for project in await self.repository.list(owner)]
            )
        if name == "create":
            if not action.title.strip():
                raise ApiError("Enter an analysis name.")
            project = dict(
                id=str(uuid4()),
                title=action.title.strip(),
                createdAt=now(),
                updatedAt=now(),
                revision=0,
                dataVersion=0,
                files=[],
                tables=[],
                canvas=dict(kind="graph", operations=[], positions={}),
                question="",
            )
            await self.repository.create(owner, project)
            return dict(project=await self.load(owner, project["id"]))
        project = await self.get(owner, action.workspaceId)
        if action.revision is not None and action.revision != project["revision"]:
            raise ApiError("This analysis changed. Reload it before editing.", 409)
        if name == "load":
            return dict(project=await self.load(owner, project["id"]))
        if name == "tablePreview":
            # Saved tables are already materialized. Read just the selected
            # object, without resolving every other join/stack on the canvas.
            if action.canvas is None or action.canvas.model_dump() == project["canvas"]:
                table = next((t for t in project["tables"] if t["id"] == action.tableId), None)
                if not table:
                    raise ApiError("Table not found.", 404)
                async with self.files.use(table["objectKey"]) as path:
                    result = await self.execution.run(engine.preview, table, path, 8)
                return dict(
                    preview=result, tables=[self.public_table(t) for t in project["tables"]]
                )
            async with self.materialized(
                owner, project, action.canvas.model_dump() if action.canvas else None
            ) as tables:
                if action.tableId not in tables:
                    raise ApiError("Table not found.", 404)
                table, path = tables[action.tableId]
                result = await self.execution.run(engine.preview, table, path, 8)
                return dict(
                    preview=result,
                    tables=[self.public_table(table) for table, _ in tables.values()],
                )
        if name.startswith("export"):
            if name == "exportDataset":
                selected = next(
                    (table for table in project["tables"] if table["id"] == action.tableId), None
                )
                if not selected:
                    raise ApiError("Choose a table to export.")
                async with self.files.use(selected["objectKey"]) as path:
                    # Reparse only on export so spreadsheet formulas can be escaped safely.
                    from ..core.ingestion import parse_csv

                    data = await self.execution.run(
                        lambda _task: parse_csv({"name": "export.csv", "content": path.read_text()})
                    )
                return dict(
                    export=dict(
                        content=export_csv(data.rows),
                        name="prepared-data.csv",
                        type="text/csv;charset=utf-8",
                    )
                )
            turns = await self.repository.analyses(owner, project["id"], project["dataVersion"])
            if name == "exportResult":
                turn = next((turn for turn in turns if turn["id"] == action.analysisId), None)
                if not turn:
                    raise ApiError("Result not found.", 404)
                return dict(
                    export=dict(
                        content=export_csv(result_rows(turn["result"])),
                        name="analysis.csv",
                        type="text/csv;charset=utf-8",
                    )
                )
            return dict(
                export=dict(
                    content=export_report(turns),
                    name="analysis-report.md",
                    type="text/markdown;charset=utf-8",
                )
            )
        async with self.cache.mutation(owner, project["id"]):
            if name == "renameTable":
                renamed = action.name.strip()
                if not renamed:
                    raise ApiError("Enter a table name.")
                table = next((t for t in project["tables"] if t["id"] == action.tableId), None)
                if not table:
                    raise ApiError("Table not found.", 404)
                if any(
                    t["id"] != table["id"] and t["name"].casefold() == renamed.casefold()
                    for t in project["tables"]
                ):
                    raise ApiError("Another table already uses that name.")
                for item in project["files"] + project["tables"]:
                    if item["id"] == action.tableId:
                        if item["kind"] == "source":
                            item.setdefault("originalName", item["name"])
                        item["name"] = renamed
                        item["profile"]["name"] = renamed
                for node in project["canvas"]["operations"]:
                    if node["id"] == action.tableId:
                        node["name"] = renamed
                return dict(project=await self.save(owner, project, action.revision))
            if name == "delete":
                await self.repository.delete(owner, project["id"])
                keys = [table["objectKey"] for table in project["tables"]]
                await self.files.evict(keys)
                await self.cleanup(owner, project["id"])
                return dict(deletedId=project["id"])
            if name == "pin":
                turns = await self.repository.analyses(owner, project["id"], project["dataVersion"])
                if action.pinned and sum(turn["pinned"] for turn in turns) >= 12:
                    raise ApiError("Your dashboard can hold up to 12 pinned findings.")
                await self.repository.pin(
                    owner, project["id"], identity(action.analysisId), action.pinned
                )
                return dict(project=await self.load(owner, project["id"]))
            if name == "patch":
                if action.title is not None:
                    if not action.title.strip():
                        raise ApiError("Enter an analysis name.")
                    project["title"] = action.title.strip()
                if action.question is not None:
                    project["question"] = action.question
                return dict(project=await self.save(owner, project, action.revision))
            graph = (
                action.canvas.model_dump()
                if name == "canvas"
                else prune(project["canvas"], [action.fileId])
            )
            if name == "removeFile":
                if not any(table["id"] == action.fileId for table in project["files"]):
                    raise ApiError("File not found.", 404)
                project["files"] = [
                    table for table in project["files"] if table["id"] != action.fileId
                ]
            changed = name == "removeFile" or [
                {k: v for k, v in node.items() if k != "name"} for node in graph["operations"]
            ] != [
                {k: v for k, v in node.items() if k != "name"}
                for node in project["canvas"]["operations"]
            ]
            if changed:
                async with self.materialized(owner, project, graph, persist=True) as tables:
                    project["tables"] = [table for table, _ in tables.values()]
            else:
                names = {node["id"]: node["name"].strip() for node in graph["operations"]}
                if any(not value for value in names.values()):
                    raise ApiError("Enter a result table name.")
                for table in project["tables"]:
                    if table["id"] in names:
                        table["name"] = names[table["id"]]
                        table["profile"]["name"] = table["name"]
            project["canvas"] = graph
            return dict(project=await self.save(owner, project, action.revision, changed))

    async def cleanup(self, owner=None, workspace_id=None):
        async with self.repository.pool.connection() as db:
            rows = await (
                await db.execute(
                    "SELECT object_key FROM objects WHERE delete_after<now() AND (%s::uuid IS NULL OR owner=%s) AND (%s::uuid IS NULL OR workspace_id=%s)",
                    (owner, owner, workspace_id, workspace_id),
                )
            ).fetchall()
        for row in rows:
            try:
                await self.storage.delete([row["object_key"]])
            except Exception:
                continue  # Retained in the ledger for the explicit cleanup command.
            async with self.repository.pool.connection() as db:
                await db.execute(
                    "DELETE FROM objects WHERE object_key=%s AND (object_key NOT LIKE '%%/uploads/%%' OR created_at < now()-interval '3 hours')",
                    (row["object_key"],),
                )
                await db.execute(
                    "UPDATE objects SET delete_after=created_at+interval '3 hours' WHERE object_key=%s AND object_key LIKE '%%/uploads/%%'",
                    (row["object_key"],),
                )
