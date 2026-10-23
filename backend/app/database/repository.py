"""Postgres persistence. Dataset contents never enter application records."""

from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..models import MAX_BYTES, MAX_FILES, MAX_ROWS, ApiError


class Repository:
    def __init__(self, url):
        self.pool = AsyncConnectionPool(
            url,
            min_size=1,
            max_size=8,
            open=False,
            kwargs={"row_factory": dict_row, "options": "-c search_path=analysis,public"},
        )

    async def open(self):
        await self.pool.open(wait=True)
        async with self.pool.connection() as db:
            await db.execute(Path(__file__).with_name("schema.sql").read_text())

    async def close(self):
        await self.pool.close()

    async def list(self, owner):
        async with self.pool.connection() as db:
            rows = await (
                await db.execute(
                    "SELECT document FROM workspaces WHERE owner=%s ORDER BY document->>'updatedAt' DESC",
                    (owner,),
                )
            ).fetchall()
            return [row["document"] for row in rows]

    async def get(self, owner, identity):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "SELECT document FROM workspaces WHERE owner=%s AND id=%s", (owner, identity)
                )
            ).fetchone()
            return row["document"] if row else None

    async def create(self, owner, project):
        async with self.pool.connection() as db:
            # Owner-scoped advisory lock makes the workspace-count check atomic.
            await db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (owner,))
            count = await (
                await db.execute("SELECT count(*) AS n FROM workspaces WHERE owner=%s", (owner,))
            ).fetchone()
            if count["n"] >= 100:
                raise ApiError("You have reached the limit of 100 analyses.")
            await db.execute(
                "INSERT INTO workspaces(id,owner,document) VALUES(%s,%s,%s)",
                (project["id"], owner, Jsonb(project)),
            )

    async def save(self, owner, project, revision, db=None):
        if db is None:
            async with self.pool.connection() as connection:
                return await self.save(owner, project, revision, connection)
        old = await (
            await db.execute(
                "SELECT data_version FROM workspaces WHERE owner=%s AND id=%s AND revision=%s FOR UPDATE",
                (owner, project["id"], revision),
            )
        ).fetchone()
        if not old:
            raise ApiError("This analysis changed. Reload it and try again.", 409)
        await db.execute(
            "UPDATE workspaces SET document=%s,revision=%s,data_version=%s WHERE owner=%s AND id=%s",
            (Jsonb(project), project["revision"], project["dataVersion"], owner, project["id"]),
        )
        if old["data_version"] != project["dataVersion"]:
            await db.execute(
                "INSERT INTO snapshots(workspace_id,data_version,document) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                (project["id"], project["dataVersion"], Jsonb(project)),
            )

    async def delete(self, owner, identity):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "DELETE FROM workspaces WHERE owner=%s AND id=%s RETURNING id",
                    (owner, identity),
                )
            ).fetchone()
            if not row:
                raise ApiError("Analysis not found.", 404)
            await db.execute(
                "UPDATE objects SET delete_after=now() WHERE owner=%s AND workspace_id=%s",
                (owner, identity),
            )

    async def reserve_upload(self, owner, identity, upload_id, name, size, key):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "SELECT document FROM workspaces WHERE owner=%s AND id=%s FOR UPDATE",
                    (owner, identity),
                )
            ).fetchone()
            if not row:
                raise ApiError("Analysis not found.", 404)
            files = row["document"]["files"]
            pending = await (
                await db.execute(
                    "SELECT name,expected_bytes FROM uploads WHERE workspace_id=%s AND state IN ('pending','validating') AND expires_at>now()",
                    (identity,),
                )
            ).fetchall()
            if len(files) + len(pending) >= MAX_FILES:
                raise ApiError("Each analysis can contain up to five files.")
            if name in [f.get("originalName", f["name"]) for f in files] + [f["name"] for f in pending]:
                raise ApiError("A file with that name is already in this analysis.")
            if (
                size + sum(f["bytes"] for f in files) + sum(f["expected_bytes"] for f in pending)
                > MAX_BYTES
            ):
                raise ApiError("Source files must total 15 MB or less.")
            await db.execute(
                "INSERT INTO uploads(id,workspace_id,owner,name,object_key,expected_bytes) VALUES(%s,%s,%s,%s,%s,%s)",
                (upload_id, identity, owner, name, key, size),
            )
            await db.execute(
                "INSERT INTO objects(object_key,owner,workspace_id,delete_after) VALUES(%s,%s,%s,now()+interval '3 hours')",
                (key, owner, identity),
            )

    async def upload(self, owner, identity, claim=False):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "SELECT *,expires_at>now() AS valid,lease_until>now() AS busy FROM uploads WHERE owner=%s AND id=%s FOR UPDATE",
                    (owner, identity),
                )
            ).fetchone()
            if not row:
                raise ApiError("Upload not found.", 404)
            if claim and row["state"] != "ready":
                if not row["valid"]:
                    raise ApiError("The upload expired. Upload the file again.", 410)
                if row["busy"]:
                    raise ApiError("This file is being validated. Try again shortly.", 409)
                await db.execute(
                    "UPDATE uploads SET state='validating',lease_until=now()+interval '2 minutes',error=NULL WHERE id=%s",
                    (identity,),
                )
            return row

    async def fail_upload(self, owner, identity, message):
        async with self.pool.connection() as db:
            await db.execute(
                "UPDATE uploads SET state='failed',error=%s,lease_until=NULL WHERE owner=%s AND id=%s AND state!='ready'",
                (message, owner, identity),
            )

    async def finish_upload(self, owner, upload, table, timestamp):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "SELECT document FROM workspaces WHERE owner=%s AND id=%s FOR UPDATE",
                    (owner, upload["workspace_id"]),
                )
            ).fetchone()
            if not row:
                raise ApiError("Analysis not found.", 404)
            project = row["document"]
            if sum(f["rowCount"] for f in project["files"]) + table["rowCount"] > MAX_ROWS:
                raise ApiError("Use at most 20,000 source rows.")
            if sum(f["bytes"] for f in project["files"]) + table["bytes"] > MAX_BYTES:
                raise ApiError("Source files must total 15 MB or less.")
            if len(project["files"]) >= MAX_FILES or any(
                f.get("originalName", f["name"]) == table["name"] for f in project["files"]
            ):
                raise ApiError("The file list changed. Reload the analysis before retrying.", 409)
            revision = project["revision"]
            project["files"].append(table)
            project["tables"].append(table)
            project.update(
                revision=revision + 1,
                dataVersion=project["dataVersion"] + 1,
                updatedAt=timestamp,
                question="",
            )
            await self.save(owner, project, revision, db)
            await db.execute(
                "UPDATE uploads SET state='ready',outcome=%s,lease_until=NULL WHERE id=%s",
                (Jsonb({"tableId": table["id"]}), upload["id"]),
            )
            await db.execute(
                "UPDATE objects SET delete_after=NULL WHERE object_key=%s", (table["objectKey"],)
            )
            return project

    async def register_object(self, owner, workspace_id, key):
        async with self.pool.connection() as db:
            await db.execute(
                "INSERT INTO objects(object_key,owner,workspace_id,delete_after) VALUES(%s,%s,%s,now()+interval '3 hours') ON CONFLICT DO NOTHING",
                (key, owner, workspace_id),
            )

    async def publish_objects(self, owner, identity, keys):
        async with self.pool.connection() as db:
            await db.execute(
                "UPDATE objects SET delete_after=NULL WHERE owner=%s AND workspace_id=%s AND object_key=ANY(%s)",
                (owner, identity, keys),
            )

    async def analyses(self, owner, identity, version):
        async with self.pool.connection() as db:
            rows = await (
                await db.execute(
                    "SELECT f.* FROM findings f JOIN workspaces w ON w.id=f.workspace_id WHERE w.owner=%s AND w.id=%s AND f.data_version=%s ORDER BY f.created_at,f.id",
                    (owner, identity, version),
                )
            ).fetchall()
            return [
                dict(
                    id=str(r["id"]),
                    question=r["question"],
                    result=r["result"],
                    pinned=r["pinned"],
                    createdAt=r["created_at"],
                )
                for r in rows
            ]

    async def insert_analysis(self, owner, identity, version, turn, cache_key):
        async with self.pool.connection() as db:
            result = await db.execute(
                "INSERT INTO findings(id,workspace_id,data_version,question,result,pinned,created_at,cache_key) SELECT %s,id,%s,%s,%s,false,%s,%s FROM workspaces WHERE owner=%s AND id=%s AND data_version=%s ON CONFLICT DO NOTHING",
                (
                    turn["id"],
                    version,
                    turn["question"],
                    Jsonb(turn["result"]),
                    turn["createdAt"],
                    cache_key,
                    owner,
                    identity,
                    version,
                ),
            )
            return result.rowcount == 1

    async def cached(self, owner, identity, version, cache_key):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "SELECT f.result FROM findings f JOIN workspaces w ON w.id=f.workspace_id WHERE w.owner=%s AND w.id=%s AND f.data_version=%s AND f.cache_key=%s AND f.created_at::timestamptz > now()-interval '1 day' ORDER BY f.created_at DESC LIMIT 1",
                    (owner, identity, version, cache_key),
                )
            ).fetchone()
            return row["result"] if row else None

    async def pin(self, owner, identity, turn_id, pinned):
        async with self.pool.connection() as db:
            r = await db.execute(
                "UPDATE findings f SET pinned=%s FROM workspaces w WHERE w.id=f.workspace_id AND w.owner=%s AND w.id=%s AND f.id=%s AND f.data_version=w.data_version",
                (pinned, owner, identity, turn_id),
            )
            if not r.rowcount:
                raise ApiError("Result not found.", 404)

    async def dashboard(self, owner, identity, scope):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "SELECT d.payload FROM dashboards d JOIN workspaces w ON w.id=d.workspace_id WHERE w.owner=%s AND w.id=%s AND d.data_version=w.data_version AND (%s::text IS NULL OR d.scope_key=%s) ORDER BY d.payload->>'createdAt' DESC LIMIT 1",
                    (owner, identity, scope, scope),
                )
            ).fetchone()
            return row["payload"] if row else None

    async def save_dashboard(self, owner, identity, version, scope, payload):
        async with self.pool.connection() as db:
            r = await db.execute(
                "INSERT INTO dashboards(workspace_id,data_version,scope_key,payload) SELECT id,%s,%s,%s FROM workspaces WHERE owner=%s AND id=%s AND data_version=%s ON CONFLICT(workspace_id,data_version,scope_key) DO UPDATE SET payload=excluded.payload",
                (version, scope, Jsonb(payload), owner, identity, version),
            )
            if not r.rowcount:
                raise ApiError("The dataset changed while the dashboard was generated.", 409)

    async def consume_quota(self, owner):
        async with self.pool.connection() as db:
            row = await (
                await db.execute(
                    "INSERT INTO request_limits(owner,window_start,count) VALUES(%s,now(),1) ON CONFLICT(owner) DO UPDATE SET count=CASE WHEN request_limits.window_start < now()-interval '1 minute' THEN 1 ELSE request_limits.count+1 END,window_start=CASE WHEN request_limits.window_start < now()-interval '1 minute' THEN now() ELSE request_limits.window_start END RETURNING count",
                    (owner,),
                )
            ).fetchone()
            if row["count"] > 15:
                raise ApiError("Too many questions. Wait a minute and try again.", 429)
