"""Private Supabase Storage adapter. Browser uploads never pass through FastAPI."""

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx

from ..models import MAX_BYTES, ApiError


class Storage:
    bucket = "datasets"

    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.storage_url.rstrip("/"),
            timeout=30,
            headers={
                "Authorization": f"Bearer {settings.storage_service_key}",
                "apikey": settings.storage_service_key,
            },
        )

    async def initialize(self):
        response = await self.client.post(
            "/bucket",
            json={
                "id": self.bucket,
                "name": self.bucket,
                "public": False,
                "file_size_limit": MAX_BYTES,
            },
        )
        if response.status_code not in (200, 201, 400, 409):
            response.raise_for_status()
        check = await self.client.get(f"/bucket/{self.bucket}")
        check.raise_for_status()
        if check.json().get("public"):
            raise RuntimeError("The dataset bucket must be private.")

    def path(self, key):
        return f"{self.bucket}/{quote(key, safe='/')}"

    async def grant(self, key):
        response = await self.client.post(
            f"/object/upload/sign/{self.path(key)}", json={"upsert": False}
        )
        response.raise_for_status()
        data = response.json()
        url = data.get("url") or data.get("signedURL")
        # The storage API returns a relative path; only the trusted configured public origin is used.
        if not url or not url.startswith("/object/upload/sign/"):
            raise ApiError("Could not authorize the upload.", 502)
        return self.settings.storage_public_url.rstrip("/") + url

    async def info(self, key):
        response = await self.client.get(f"/object/info/{self.path(key)}")
        if response.status_code == 404 or (
            response.status_code == 400 and response.json().get("code") == "NoSuchKey"
        ):
            raise ApiError("The uploaded file was not found. Try uploading it again.")
        response.raise_for_status()
        data = response.json()
        return int(data.get("size") or data.get("metadata", {}).get("size", 0))

    async def download(self, key, destination):
        size = 0
        async with self.client.stream("GET", f"/object/{self.path(key)}") as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ApiError("The stored file exceeds 15 MB.")
                    output.write(chunk)
        return size

    async def put(self, key, content):
        response = await self.client.post(
            f"/object/{self.path(key)}",
            content=content,
            headers={"Content-Type": "text/csv", "x-upsert": "false"},
        )
        response.raise_for_status()

    async def delete(self, keys):
        if keys:
            response = await self.client.request(
                "DELETE", f"/object/{self.bucket}", json={"prefixes": keys}
            )
            response.raise_for_status()

    async def close(self):
        await self.client.aclose()


class FileCache:
    """Bounded ephemeral files, pinned for the duration of active requests."""

    def __init__(self, settings, storage):
        import asyncio

        self.root = Path(settings.cache_directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.storage, self.budget = storage, settings.disk_cache_bytes
        self.lock = asyncio.Lock()
        self.pins = {}
        self.hits = self.misses = 0

    def path(self, key):
        return self.root / (hashlib.sha256(key.encode()).hexdigest() + ".csv")

    @asynccontextmanager
    async def use(self, key):
        import os

        async with self.lock:
            path = self.path(key)
            if not path.exists():
                self.misses += 1
                temporary = path.with_suffix(".part")
                try:
                    await self.storage.download(key, temporary)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                self.hits += 1
            path.touch()
            self.pins[path] = self.pins.get(path, 0) + 1
        try:
            yield path
        finally:
            async with self.lock:
                self.pins[path] -= 1
                total = sum(
                    file.stat().st_size
                    for file in self.root.iterdir()
                    if file.suffix in (".csv", ".parquet")
                )
                for file in sorted(self.root.glob("*.csv"), key=lambda p: p.stat().st_mtime):
                    if total <= self.budget:
                        break
                    if not self.pins.get(file, 0):
                        total -= file.stat().st_size
                        parquet = file.with_suffix(".parquet")
                        if parquet.exists():
                            total -= parquet.stat().st_size
                            parquet.unlink(missing_ok=True)
                        file.unlink(missing_ok=True)

    async def evict(self, keys):
        async with self.lock:
            for key in keys:
                path = self.path(key)
                if not self.pins.get(path, 0):
                    path.unlink(missing_ok=True)
                    path.with_suffix(".parquet").unlink(missing_ok=True)
