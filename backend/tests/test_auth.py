import asyncio
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.config import Settings
from app.infrastructure.auth import Auth
from app.models import ApiError

PROJECT = "https://test-project.supabase.co"
ISSUER = PROJECT + "/auth/v1"
OWNER = str(uuid4())
SECRET = "test-only-local-hmac-secret-with-enough-entropy"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=["ES256", "RS256"])
def signing(request):
    algorithm = request.param
    private = ec.generate_private_key(ec.SECP256R1()) if algorithm == "ES256" else rsa.generate_private_key(65537, 2048)
    implementation = jwt.algorithms.ECAlgorithm if algorithm == "ES256" else jwt.algorithms.RSAAlgorithm
    public = json.loads(implementation.to_jwk(private.public_key()))
    public.update(kid="test-key", alg=algorithm, use="sig")
    return private, algorithm, public


def claims(**changes):
    return dict(sub=OWNER, role="authenticated", aud="authenticated", iss=ISSUER,
                exp=int(time.time()) + 3600, **changes)


def request_for(token):
    return SimpleNamespace(headers={"authorization": "Bearer " + token}, state=SimpleNamespace())


async def hosted_auth(handler, **changes):
    settings = Settings(jwt_secret="", jwt_issuer=ISSUER, supabase_public_url=PROJECT, **changes)
    auth = Auth(settings)
    await auth.client.aclose()
    auth.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return auth


@pytest.mark.anyio
async def test_hosted_signature_verification_caches_keys_and_preserves_identity(signing):
    private, algorithm, public = signing
    calls = []

    async def respond(request):
        calls.append(str(request.url))
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"keys": [public]})

    auth = await hosted_auth(respond)
    token = jwt.encode(claims(), private, algorithm=algorithm, headers={"kid": "test-key"})
    try:
        auth.validate()  # Hosted startup must not require a symmetric secret.
        identities = await asyncio.gather(*(auth(request_for(token)) for _ in range(5)))
        assert identities == [OWNER] * 5
        assert calls == [PROJECT + "/auth/v1/.well-known/jwks.json"]
    finally:
        await auth.close()


@pytest.mark.anyio
@pytest.mark.parametrize("changed", [
    {"iss": "https://another-project.supabase.co/auth/v1"},
    {"aud": "anon"}, {"role": "service_role"}, {"sub": "not-a-user-id"}, {"exp": 1},
    {"is_anonymous": True},
])
async def test_hosted_tokens_validate_claims(signing, changed):
    private, algorithm, public = signing
    auth = await hosted_auth(lambda _: httpx.Response(200, json={"keys": [public]}))
    payload = claims()
    payload.update(changed)
    token = jwt.encode(payload, private, algorithm=algorithm, headers={"kid": "test-key"})
    try:
        with pytest.raises(ApiError) as error:
            await auth(request_for(token))
        assert error.value.status == 401
    finally:
        await auth.close()


@pytest.mark.anyio
async def test_unknown_ids_throttle_refresh_and_rotation_refreshes(signing):
    private, algorithm, public = signing
    keys, calls = [public], []

    def respond(_):
        calls.append(True)
        return httpx.Response(200, json={"keys": keys})

    auth = await hosted_auth(respond)
    first = jwt.encode(claims(), private, algorithm=algorithm, headers={"kid": "test-key"})
    try:
        assert await auth(request_for(first)) == OWNER
        for kid in ["missing-one", "missing-two"]:
            token = jwt.encode(claims(), private, algorithm=algorithm, headers={"kid": kid})
            with pytest.raises(ApiError) as error:
                await auth(request_for(token))
            assert error.value.status == 401
        assert len(calls) == 1
        keys[:] = [dict(public, kid="rotated-key")]
        auth.next_refresh = 0
        rotated = jwt.encode(claims(), private, algorithm=algorithm, headers={"kid": "rotated-key"})
        assert await auth(request_for(rotated)) == OWNER
        assert len(calls) == 2
        # Expired caches cannot keep using keys removed by rotation.
        auth.expires = auth.next_refresh = 0
        with pytest.raises(ApiError):
            await auth(request_for(first))
    finally:
        await auth.close()


@pytest.mark.anyio
async def test_invalid_signature_unknown_kid_and_token_supplied_urls_are_rejected(signing):
    private, algorithm, _ = signing
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"keys": []})

    auth = await hosted_auth(respond)
    token = jwt.encode(claims(), private, algorithm=algorithm,
                       headers={"kid": "unknown", "jku": "https://attacker.example/keys"})
    try:
        with pytest.raises(ApiError) as error:
            await auth(request_for(token))
        assert error.value.status == 401
        assert calls == [PROJECT + "/auth/v1/.well-known/jwks.json"]
    finally:
        await auth.close()


@pytest.mark.anyio
async def test_signature_cannot_be_forged_with_a_different_key():
    private = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(other.public_key()))
    public.update(kid="test-key", alg="ES256", use="sig")
    auth = await hosted_auth(lambda _: httpx.Response(200, json={"keys": [public]}))
    try:
        token = jwt.encode(claims(), private, algorithm="ES256", headers={"kid": "test-key"})
        with pytest.raises(ApiError) as error:
            await auth(request_for(token))
        assert error.value.status == 401
    finally:
        await auth.close()


@pytest.mark.anyio
async def test_hs256_local_sessions_keep_working_without_network():
    auth = Auth(Settings(jwt_secret=SECRET, jwt_issuer=ISSUER))
    try:
        token = jwt.encode(claims(), SECRET, algorithm="HS256")
        assert await auth(request_for(token)) == OWNER
        with pytest.raises(ApiError, match="Sign in with an account") as error:
            await auth(request_for(jwt.encode(claims(is_anonymous=True), SECRET, algorithm="HS256")))
        assert error.value.status == 401
        with pytest.raises(ApiError):
            await auth(request_for(jwt.encode(claims(), "wrong-secret" * 4, algorithm="HS256")))
    finally:
        await auth.close()


@pytest.mark.anyio
async def test_hosted_auth_does_not_accept_unsigned_or_unconfigured_hmac():
    auth = await hosted_auth(lambda _: pytest.fail("Unsupported tokens must not fetch signing keys"))
    try:
        for token in (jwt.encode(claims(), "", algorithm="none"),
                      jwt.encode(claims(), SECRET, algorithm="HS256")):
            with pytest.raises(ApiError) as error:
                await auth(request_for(token))
            assert error.value.status == 401
    finally:
        await auth.close()


@pytest.mark.anyio
@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, json={"keys": "invalid"})])
async def test_signing_service_failures_fail_closed_without_a_retry_storm(response):
    calls = []

    def respond(_):
        calls.append(True)
        return response

    auth = await hosted_auth(respond)
    private = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(claims(), private, algorithm="ES256", headers={"kid": "test-key"})
    try:
        for _ in range(3):
            with pytest.raises(ApiError) as error:
                await auth(request_for(token))
            assert error.value.status == 503
        assert len(calls) == 1
    finally:
        await auth.close()


def test_issuer_defaults_to_configured_project(monkeypatch):
    monkeypatch.delenv("JWT_ISSUER", raising=False)
    assert Settings(supabase_public_url=PROJECT).jwt_issuer == ISSUER


@pytest.mark.anyio
async def test_hosted_app_starts_without_jwt_secret(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.main import create_app

    repository = SimpleNamespace(open=AsyncMock(), close=AsyncMock())
    provider = SimpleNamespace(ready=False, close=AsyncMock())
    app = create_app(
        Settings(jwt_secret="", jwt_issuer=ISSUER, supabase_public_url=PROJECT,
                 cache_directory=str(tmp_path / "cache")),
        repository=repository, provider=provider,
    )
    monkeypatch.setattr(app.state.storage, "initialize", AsyncMock())
    monkeypatch.setattr(app.state.cache, "initialize", AsyncMock())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
    repository.open.assert_awaited_once()
    repository.close.assert_awaited_once()
