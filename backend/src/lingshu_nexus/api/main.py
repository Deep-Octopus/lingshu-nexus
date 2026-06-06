"""FastAPI entrypoint for LingShu Nexus."""

from fastapi import FastAPI

from lingshu_domain import DEFAULT_DOMAIN_ID
from lingshu_nexus.config.settings import get_settings
from lingshu_nexus.documents import create_document_service
from lingshu_nexus.persistence.object_store import LocalFilesystemObjectStore
from lingshu_nexus.api.routes.documents import router as documents_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    app.state.document_service = create_document_service(
        object_store=LocalFilesystemObjectStore(settings.object_storage_local_path),
        max_upload_bytes=settings.document_max_upload_bytes,
    )
    app.include_router(documents_router)

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "environment": settings.app_env,
            "default_domain_id": DEFAULT_DOMAIN_ID,
        }

    return app


app = create_app()
