"""Runtime settings loaded from environment variables."""

from dataclasses import dataclass
from functools import lru_cache
from os import getenv


def _env(name: str, default: str) -> str:
    value = getenv(name)
    if value is None or value == "":
        return default
    return value


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    app_name: str = "LingShu Nexus"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    default_domain_id: str = "acupuncture"
    mimo_api_key: str = ""
    mimo_base_url: str = "https://mimo.example.invalid/v1"
    mimo_model_id: str = "replace-with-mimo-model-id"
    mimo_extraction_model_id: str = ""
    mimo_chat_model_id: str = ""
    database_url: str = "postgresql://lingshu:change-me-postgres-password@localhost:5432/lingshu_nexus"
    redis_url: str = "redis://localhost:6379/0"
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "lingshu-documents"
    object_storage_local_path: str = "data/runtime/object-store"
    document_max_upload_bytes: int = 20 * 1024 * 1024
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=_env("APP_ENV", cls.app_env),
            app_name=_env("APP_NAME", cls.app_name),
            app_host=_env("APP_HOST", cls.app_host),
            app_port=int(_env("APP_PORT", str(cls.app_port))),
            default_domain_id=_env("DEFAULT_DOMAIN_ID", cls.default_domain_id),
            mimo_api_key=_env("MIMO_API_KEY", cls.mimo_api_key),
            mimo_base_url=_env("MIMO_BASE_URL", cls.mimo_base_url),
            mimo_model_id=_env("MIMO_MODEL_ID", cls.mimo_model_id),
            mimo_extraction_model_id=_env(
                "MIMO_EXTRACTION_MODEL_ID",
                cls.mimo_extraction_model_id,
            ),
            mimo_chat_model_id=_env("MIMO_CHAT_MODEL_ID", cls.mimo_chat_model_id),
            database_url=_env("DATABASE_URL", cls.database_url),
            redis_url=_env("REDIS_URL", cls.redis_url),
            object_storage_endpoint=_env("OBJECT_STORAGE_ENDPOINT", cls.object_storage_endpoint),
            object_storage_bucket=_env("OBJECT_STORAGE_BUCKET", cls.object_storage_bucket),
            object_storage_local_path=_env(
                "OBJECT_STORAGE_LOCAL_PATH", cls.object_storage_local_path
            ),
            document_max_upload_bytes=int(
                _env("DOCUMENT_MAX_UPLOAD_BYTES", str(cls.document_max_upload_bytes))
            ),
            neo4j_uri=_env("NEO4J_URI", cls.neo4j_uri),
            neo4j_username=_env("NEO4J_USERNAME", cls.neo4j_username),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
