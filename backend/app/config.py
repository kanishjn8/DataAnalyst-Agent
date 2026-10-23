import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")


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
        default_factory=lambda: os.getenv("JWT_ISSUER", "http://127.0.0.1:54321/auth/v1")
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
        default_factory=lambda: tuple(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        )
    )
