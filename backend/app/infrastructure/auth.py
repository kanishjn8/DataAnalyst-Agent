"""Verify local HS256 sessions and hosted Supabase asymmetric sessions."""

import asyncio
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt

from ..models import ApiError

ASYMMETRIC_ALGORITHMS = ("ES256", "RS256")


class Auth:
    def __init__(self, settings):
        self.settings = settings
        # The endpoint is trusted configuration, never a URL from an incoming token.
        self.jwks_url = settings.supabase_public_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        self.client = httpx.AsyncClient(timeout=5, follow_redirects=False)
        self.keys = {}
        self.expires = self.next_refresh = 0.0
        self.lock = asyncio.Lock()

    def validate(self):
        project = urlsplit(self.settings.supabase_public_url)
        local = project.hostname in ("localhost", "127.0.0.1", "::1")
        if (
            not project.hostname
            or project.username is not None
            or project.password is not None
            or project.path not in ("", "/")
            or project.query
            or project.fragment
            or (project.scheme != "https" and not (local and project.scheme == "http"))
        ):
            raise RuntimeError("SUPABASE_PUBLIC_URL must be the project base URL, without /rest/v1.")
        if local and not self.settings.jwt_secret:
            raise RuntimeError("Local authentication needs JWT_SECRET. Run the local Compose setup.")

    async def close(self):
        await self.client.aclose()

    async def signing_key(self, kid, algorithm):
        if not isinstance(kid, str) or not 1 <= len(kid) <= 200:
            raise jwt.InvalidTokenError("Missing signing key ID")
        async with self.lock:
            now = time.monotonic()
            if now >= self.expires or (kid not in self.keys and now >= self.next_refresh):
                # Unknown key IDs may cause at most one refresh per 30 seconds.
                if now < self.next_refresh:
                    raise ApiError("Sign-in is temporarily unavailable. Please try again.", 503)
                self.next_refresh = now + 30
                try:
                    response = await self.client.get(self.jwks_url)
                    response.raise_for_status()
                    document = response.json()
                    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
                        raise ValueError("Invalid signing key response")
                    keys = {}
                    for item in document["keys"]:
                        if not isinstance(item, dict):
                            raise ValueError("Invalid signing key")
                        if item.get("alg") not in ASYMMETRIC_ALGORITHMS or item.get("use", "sig") != "sig":
                            continue
                        if "key_ops" in item and "verify" not in item["key_ops"]:
                            continue
                        key = jwt.PyJWK.from_dict(item)
                        keys[key.key_id] = key
                except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError):
                    raise ApiError("Sign-in is temporarily unavailable. Please try again.", 503) from None
                self.keys, self.expires = keys, now + 300
            key = self.keys.get(kid)
            if not key or key.algorithm_name != algorithm:
                raise jwt.InvalidTokenError("Unknown signing key")
            return key.key

    async def __call__(self, request):
        value = request.headers.get("authorization", "")
        if not value.startswith("Bearer "):
            raise ApiError("Sign in to continue.", 401)
        try:
            token = value[7:]
            if len(token) > 16384:
                raise jwt.InvalidTokenError("Token too large")
            header = jwt.get_unverified_header(token)
            if header.get("alg") == "HS256" and self.settings.jwt_secret:
                key, algorithms = self.settings.jwt_secret, ["HS256"]
            elif header.get("alg") in ASYMMETRIC_ALGORITHMS:
                key = await self.signing_key(header.get("kid"), header["alg"])
                algorithms = list(ASYMMETRIC_ALGORITHMS)
            else:
                raise jwt.InvalidAlgorithmError("Unsupported signing algorithm")
            claims = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience="authenticated",
                issuer=self.settings.jwt_issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            if claims.get("role") != "authenticated":
                raise ValueError("Invalid role")
            request.state.is_guest = bool(claims.get("is_anonymous"))
            return str(UUID(claims["sub"]))
        except (jwt.PyJWTError, ValueError, TypeError):
            raise ApiError("Your session expired. Sign in again.", 401) from None
