import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")


def parse_allowed_origins(value):
    origins = []
    for entry in value.split(","):
        origin = entry.strip()
        if len(origin) >= 2 and origin[0] == origin[-1] and origin[0] in "\"'":
            origin = origin[1:-1].strip()
        origin = origin.rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in parsed.netloc
            or any(character.isspace() for character in origin)
        ):
            raise ValueError("ALLOWED_ORIGINS must contain comma-separated HTTP(S) origins without paths.")
        # Browsers lowercase hosts and omit default ports from their Origin header.
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if port and port != {"http": 80, "https": 443}[parsed.scheme]:
            host += f":{port}"
        normalized = f"{parsed.scheme}://{host}"
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            f"postgresql://analysis_app:{os.getenv('POSTGRES_PASSWORD', '')}@127.0.0.1:54322/postgres",
        )
    )
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", ""))
    jwt_issuer: str = field(
        default_factory=lambda: os.getenv("JWT_ISSUER", "")
    )
    storage_url: str = field(
        default_factory=lambda: os.getenv("STORAGE_URL", "http://127.0.0.1:54321/storage/v1")
    )
    storage_public_url: str = field(
        default_factory=lambda: os.getenv("STORAGE_PUBLIC_URL", "http://127.0.0.1:54321/storage/v1")
    )
    storage_service_key: str = field(
        default_factory=lambda: os.getenv("STORAGE_SERVICE_KEY", os.getenv("SERVICE_ROLE_KEY", ""))
    )
    supabase_public_url: str = field(
        default_factory=lambda: os.getenv("SUPABASE_PUBLIC_URL", "http://127.0.0.1:54321")
    )
    supabase_anon_key: str = field(
        default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", os.getenv("ANON_KEY", ""))
    )
    cache_directory: str = field(
        default_factory=lambda: os.getenv("CACHE_DIRECTORY", "/tmp/analysis-tables")
    )
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    redis_namespace: str = field(
        default_factory=lambda: os.getenv("REDIS_NAMESPACE", "data-analysis:v1")
    )
    disk_cache_bytes: int = 256_000_000
    query_timeout: float = 15
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: parse_allowed_origins(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
        )
    )

    def __post_init__(self):
        if not self.jwt_issuer:
            object.__setattr__(self, "jwt_issuer", self.supabase_public_url.rstrip("/") + "/auth/v1")
