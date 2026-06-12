"""FastAPI entrypoint for LingShu Nexus."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lingshu_domain import DEFAULT_DOMAIN_ID
from lingshu_nexus.api.routes.chat import router as chat_router
from lingshu_nexus.api.routes.documents import router as documents_router
from lingshu_nexus.api.routes.retrieval import router as retrieval_router
from lingshu_nexus.api.routes.review import router as review_router
from lingshu_nexus.api.routes.skills import router as skills_router
from lingshu_nexus.chat import create_chat_service
from lingshu_nexus.config.settings import get_settings
from lingshu_nexus.documents import create_document_service
from lingshu_nexus.persistence.object_store import LocalFilesystemObjectStore
from lingshu_nexus.retrieval import create_retrieval_service
from lingshu_nexus.review import create_review_release_service
from lingshu_nexus.skills import create_skill_registry_service


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    if settings.app_env != "production":
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["content-type"],
        )
    object_store = LocalFilesystemObjectStore(settings.object_storage_local_path)
    app.state.document_service = create_document_service(
        object_store=object_store,
        max_upload_bytes=settings.document_max_upload_bytes,
    )
    app.state.review_release_service = create_review_release_service(object_store=object_store)
    app.state.retrieval_service = create_retrieval_service(
        release_reader=app.state.review_release_service
    )
    app.state.skill_registry_service = create_skill_registry_service(
        retrieval_service=app.state.retrieval_service,
        skills_root=Path(settings.skill_registry_path),
    )
    app.state.chat_service = create_chat_service(
        skill_registry=app.state.skill_registry_service,
    )
    app.include_router(documents_router)
    app.include_router(review_router)
    app.include_router(retrieval_router)
    app.include_router(skills_router)
    app.include_router(chat_router)

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
