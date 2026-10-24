from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings, parse_allowed_origins


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_origins_normalize_slashes_spaces_quotes_and_default_ports():
    assert parse_allowed_origins(
        ' https://Frontend.Example:443/ , "http://localhost:3000/", '
        "https://frontend.example, http://[::1]:80/ "
    ) == ("https://frontend.example", "http://localhost:3000", "http://[::1]")


@pytest.mark.parametrize("value", [
    "*", "https://*.vercel.app", "https://frontend.example/path", "null",
    "https://frontend.example?key=value", "https://user:password@frontend.example",
    "https://frontend.example#fragment", "https://front end.example", "frontend.example",
])
def test_invalid_origin_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        parse_allowed_origins(value)


@pytest.mark.anyio
async def test_browser_origin_and_preflight_allow_only_configured_domains(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://frontend.example/ , http://localhost:3000/ ")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.main import create_app

    settings = Settings(cache_directory=str(tmp_path / "cache"))
    app = create_app(settings, provider=SimpleNamespace(ready=False))
    # No lifespan: these public endpoints and preflights must not contact a
    # database, Redis, Supabase or Gemini, including when cloud credentials exist.
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health", headers={"Origin": "https://frontend.example"})
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == "https://frontend.example"
            head = await client.head("/health")
            assert head.status_code == 200
            assert head.content == b""
            assert head.headers["cache-control"] == "no-store"
            preflight = await client.options("/workspace", headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            })
            assert preflight.status_code == 204
            assert preflight.headers["access-control-allow-origin"] == "https://frontend.example"
            assert "authorization" in preflight.headers["access-control-allow-headers"]
            for origin in ("https://evil.example", "https://frontend.example.evil.example",
                           "https://preview.vercel.app", "null"):
                for method in ("GET", "HEAD", "OPTIONS"):
                    denied = await client.request(method, "/health", headers={"Origin": origin})
                    assert denied.status_code == 403
                    assert "access-control-allow-origin" not in denied.headers
            assert (await client.get("/health")).status_code == 200
    finally:
        await app.state.storage.close()
        await app.state.cache.close()
        app.state.workspaces.execution.close()
