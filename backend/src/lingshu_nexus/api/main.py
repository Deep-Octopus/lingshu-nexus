"""FastAPI entrypoint for LingShu Nexus."""

from fastapi import FastAPI

from lingshu_domain import DEFAULT_DOMAIN_ID
from lingshu_nexus.api.routes.documents import router as documents_router
from lingshu_nexus.api.routes.review import router as review_router
from lingshu_nexus.config.settings import get_settings
from lingshu_nexus.documents import create_document_service
from lingshu_nexus.persistence.object_store import LocalFilesystemObjectStore
from lingshu_nexus.review import create_review_release_service


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    object_store = LocalFilesystemObjectStore(settings.object_storage_local_path)
    app.state.document_service = create_document_service(
        object_store=object_store,
        max_upload_bytes=settings.document_max_upload_bytes,
    )
    app.state.review_release_service = create_review_release_service(object_store=object_store)
    app.include_router(documents_router)
    app.include_router(review_router)

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
