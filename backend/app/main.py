import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from .config import Settings
from .database.repository import Repository
from .infrastructure.auth import Auth
from .infrastructure.cache import DashboardCache
from .infrastructure.execution import Execution
from .infrastructure.storage import FileCache, Storage
from .models import AnalysisRequest, ApiError, DashboardRequest, UploadRequest, WorkspaceAction
from .services.analyst import Analyst
from .services.gemini import GeminiProvider
from .services.workspaces import Workspaces

logger = logging.getLogger("analysis_api")


def create_app(settings=None, repository=None, provider=None, authenticate=None):
    settings = settings or Settings()
    repository = repository or Repository(settings.database_url)
    storage = Storage(settings)
    files = FileCache(settings, storage)
    cache = DashboardCache(settings.redis_url, namespace=settings.redis_namespace)
    execution = Execution()
    workspaces = Workspaces(repository, storage, files, execution, cache)
    provider = provider or GeminiProvider(settings)
    analyst = Analyst(workspaces, provider)
    authenticate = authenticate or Auth(settings)
    busy = set()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            if isinstance(authenticate, Auth):
                authenticate.validate()
            await repository.open()
            await storage.initialize()
            await cache.initialize()
            yield
        finally:
            if isinstance(authenticate, Auth):
                await authenticate.close()
            await cache.close()
            await provider.close()
            await storage.close()
            await repository.close()
            execution.close()

    app = FastAPI(title="Data analysis API", version="2.0.0", lifespan=lifespan)
    app.state.workspaces, app.state.analyst, app.state.repository = workspaces, analyst, repository
    app.state.cache, app.state.files, app.state.storage = cache, files, storage
    app.state.provider = provider

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        started = time.monotonic()
        request_id = str(uuid4())
        request.state.request_id = request_id
        origin = request.headers.get("origin")
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Request-Id": request_id,
            "Vary": "Origin",
        }
        if origin and origin not in settings.allowed_origins:
            return JSONResponse(
                {"error": "This request is not allowed."}, status_code=403, headers=headers
            )
        if origin:
            headers.update(
                {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
                    "Access-Control-Allow-Headers": "content-type,authorization",
                    "Access-Control-Expose-Headers": "X-Request-Id,X-Cache",
                }
            )
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=headers)
        try:
            response = await call_next(request)
        except Exception:
            logger.error("request_failed id=%s", request_id)
            response = JSONResponse(
                {
                    "error": "Could not process this request. Please try again.",
                    "requestId": request_id,
                },
                status_code=500,
            )
        logger.info(
            "request id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            round((time.monotonic() - started) * 1000),
        )
        for key, value in headers.items():
            response.headers[key] = value
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, error):
        return JSONResponse(
            {"error": error.message, "requestId": request.state.request_id},
            status_code=error.status,
        )

    async def body(request, model, limit=100_000):
        if "application/json" not in request.headers.get("content-type", ""):
            raise ApiError("Content-Type must be application/json.", 415)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > limit:
                raise ApiError("Request is too large.", 413)
        try:
            return model.model_validate_json(data)
        except ValidationError:
            raise ApiError("Invalid request. Check the selected files and fields.") from None

    @asynccontextmanager
    async def analytical_request(owner):
        if owner in busy or len(busy) >= 2:
            raise ApiError("The server is busy. Please try again shortly.", 429)
        busy.add(owner)
        try:
            yield
        finally:
            busy.remove(owner)

    @app.get("/health")
    async def health():
        # Liveness must not use analytical capacity, model quota or database connections.
        return dict(status="ok", capabilities={"analysis": provider.ready})

    @app.get("/ready")
    async def ready():
        async with repository.pool.connection() as db:
            await db.execute("SELECT 1")
        return dict(status="ok")

    @app.get("/config")
    async def config():
        return dict(url=settings.supabase_public_url, anonKey=settings.supabase_anon_key)

    @app.post("/workspace")
    async def workspace(request: Request):
        owner = await authenticate(request)
        action = await body(request, WorkspaceAction)
        # Metadata operations use revision checks/transactions; DuckDB work is
        # independently bounded by Execution. A preview must not block a save or load.
        result = await workspaces.execute(owner, action)
        if "export" in result:
            file = result["export"]
            return Response(
                file["content"],
                media_type=file["type"],
                headers={"Content-Disposition": f'attachment; filename="{file["name"]}"'},
            )
        return {**result, "capabilities": {"analysis": provider.ready}}

    @app.post("/analyses/{workspace_id}/uploads")
    async def reserve(workspace_id: str, request: Request):
        return await workspaces.reserve(
            await authenticate(request), workspace_id, await body(request, UploadRequest, 8000)
        )

    @app.post("/uploads/{upload_id}/complete")
    async def complete(upload_id: str, request: Request):
        owner = await authenticate(request)
        async with analytical_request(owner):
            return dict(project=await workspaces.complete(owner, upload_id))

    @app.get("/uploads/{upload_id}")
    async def upload_status(upload_id: str, request: Request):
        from .services.workspaces import identity

        upload = await repository.upload(await authenticate(request), identity(upload_id))
        return dict(state=upload["state"], outcome=upload["outcome"], error=upload["error"])

    @app.get("/analyses/{workspace_id}/dashboard")
    async def dashboard_get(workspace_id: str, request: Request):
        ids = (
            request.query_params.get("tableIds", "").split(",")
            if request.query_params.get("tableIds")
            else []
        )
        if len(ids) > 13:
            raise ApiError("Select at most 13 tables.")
        result, hit = await analyst.read_dashboard(await authenticate(request), workspace_id, ids)
        return JSONResponse({"dashboard": result}, headers={"X-Cache": "HIT" if hit else "MISS"})

    @app.post("/analyses/{workspace_id}/dashboard")
    async def dashboard_generate(workspace_id: str, request: Request):
        owner = await authenticate(request)
        async with analytical_request(owner):
            async with asyncio.timeout(120):
                result = await analyst.dashboard(
                    owner, workspace_id, await body(request, DashboardRequest, 8000)
                )
        return dict(dashboard=result)

    @app.post("/analyze")
    async def analyze(request: Request):
        owner = await authenticate(request)
        question = await body(request, AnalysisRequest, 8000)
        # Acquire before returning headers so overload remains a normal HTTP error.
        context = analytical_request(owner)
        await context.__aenter__()
        try:
            events = await analyst.start(owner, question)
        except BaseException:
            await context.__aexit__(None, None, None)
            raise

        async def stream():
            try:
                async with asyncio.timeout(120):
                    async for event in events:
                        if await request.is_disconnected():
                            return
                        yield json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
            except asyncio.CancelledError:
                raise
            except Exception as error:
                message = (
                    error.message
                    if isinstance(error, ApiError)
                    else "Could not complete this analysis. Please retry or rephrase the question."
                )
                yield (
                    json.dumps(dict(type="error", message=message, requestId=question.requestId))
                    + "\n"
                )
            finally:
                await events.aclose()
                await context.__aexit__(None, None, None)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    return app


app = create_app()
