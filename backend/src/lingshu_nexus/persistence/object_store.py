"""Object storage port with local and in-memory adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from lingshu_domain.validation import SchemaValidationError, require_domain_id, require_text
from lingshu_nexus.persistence.models import DataLayer, StoredObjectRecord


class DuplicateObjectError(ValueError):
    """Raised when code attempts to overwrite an immutable object version."""


@dataclass(frozen=True)
class ObjectRef:
    domain_id: str
    object_key: str
    version: int
    layer: DataLayer
    content_hash: str
    storage_uri: str


class ObjectStore(Protocol):
    def put(
        self,
        *,
        domain_id: str,
        object_key: str,
        content: bytes,
        layer: DataLayer,
        media_type: str,
        version: int = 1,
    ) -> ObjectRef:
        """Append an immutable object version."""

    def get(self, ref: ObjectRef, *, domain_id: str) -> bytes:
        """Read object bytes for the requested domain."""

    def record_for(self, ref: ObjectRef, *, domain_id: str) -> StoredObjectRecord:
        """Return storage metadata for the requested domain."""


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[tuple[str, str, int], bytes] = {}
        self._records: dict[tuple[str, str, int], StoredObjectRecord] = {}

    def put(
        self,
        *,
        domain_id: str,
        object_key: str,
        content: bytes,
        layer: DataLayer,
        media_type: str,
        version: int = 1,
    ) -> ObjectRef:
        require_domain_id(domain_id)
        require_text(object_key, "object_key")
        require_text(media_type, "media_type")
        if version < 1:
            raise SchemaValidationError("version must be >= 1")
        identity = (domain_id, object_key, version)
        if identity in self._objects:
            raise DuplicateObjectError(f"Object version already exists: {identity}")
        content_hash = sha256(content).hexdigest()
        storage_uri = f"memory://{domain_id}/{layer.value}/{object_key}?version={version}"
        self._objects[identity] = bytes(content)
        self._records[identity] = StoredObjectRecord(
            id=f"obj_{uuid4().hex}",
            domain_id=domain_id,
            layer=layer,
            object_key=object_key,
            content_hash=content_hash,
            media_type=media_type,
            byte_size=len(content),
            version=version,
            storage_uri=storage_uri,
        )
        return ObjectRef(
            domain_id=domain_id,
            object_key=object_key,
            version=version,
            layer=layer,
            content_hash=content_hash,
            storage_uri=storage_uri,
        )

    def get(self, ref: ObjectRef, *, domain_id: str) -> bytes:
        self._require_ref_domain(ref, domain_id)
        identity = (ref.domain_id, ref.object_key, ref.version)
        return self._objects[identity]

    def record_for(self, ref: ObjectRef, *, domain_id: str) -> StoredObjectRecord:
        self._require_ref_domain(ref, domain_id)
        identity = (ref.domain_id, ref.object_key, ref.version)
        return self._records[identity]

    @staticmethod
    def _require_ref_domain(ref: ObjectRef, domain_id: str) -> None:
        require_domain_id(domain_id)
        if ref.domain_id != domain_id:
            raise PermissionError("ObjectRef domain_id does not match requested domain")


class LocalFilesystemObjectStore:
    """Immutable object store adapter for local development and API smoke tests."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def put(
        self,
        *,
        domain_id: str,
        object_key: str,
        content: bytes,
        layer: DataLayer,
        media_type: str,
        version: int = 1,
    ) -> ObjectRef:
        require_domain_id(domain_id)
        require_text(object_key, "object_key")
        require_text(media_type, "media_type")
        if version < 1:
            raise SchemaValidationError("version must be >= 1")
        content_path = self._content_path(domain_id, layer, object_key, version)
        metadata_path = self._metadata_path(domain_id, layer, object_key, version)
        if content_path.exists() or metadata_path.exists():
            raise DuplicateObjectError(
                f"Object version already exists: {(domain_id, object_key, version)}"
            )
        content_hash = sha256(content).hexdigest()
        storage_uri = f"file://{content_path}"
        record = StoredObjectRecord(
            id=f"obj_{uuid4().hex}",
            domain_id=domain_id,
            layer=layer,
            object_key=object_key,
            content_hash=content_hash,
            media_type=media_type,
            byte_size=len(content),
            version=version,
            storage_uri=storage_uri,
        )
        content_path.parent.mkdir(parents=True, exist_ok=True)
        content_path.write_bytes(content)
        metadata_path.write_text(
            json.dumps(_record_to_json(record), ensure_ascii=False),
            encoding="utf-8",
        )
        return ObjectRef(
            domain_id=domain_id,
            object_key=object_key,
            version=version,
            layer=layer,
            content_hash=content_hash,
            storage_uri=storage_uri,
        )

    def get(self, ref: ObjectRef, *, domain_id: str) -> bytes:
        self._require_ref_domain(ref, domain_id)
        path = self._content_path(ref.domain_id, ref.layer, ref.object_key, ref.version)
        return path.read_bytes()

    def record_for(self, ref: ObjectRef, *, domain_id: str) -> StoredObjectRecord:
        self._require_ref_domain(ref, domain_id)
        metadata = json.loads(
            self._metadata_path(ref.domain_id, ref.layer, ref.object_key, ref.version).read_text(
                encoding="utf-8"
            )
        )
        return StoredObjectRecord(
            id=metadata["id"],
            domain_id=metadata["domain_id"],
            layer=DataLayer(metadata["layer"]),
            object_key=metadata["object_key"],
            content_hash=metadata["content_hash"],
            media_type=metadata["media_type"],
            byte_size=metadata["byte_size"],
            version=metadata["version"],
            storage_uri=metadata["storage_uri"],
        )

    def _content_path(
        self, domain_id: str, layer: DataLayer, object_key: str, version: int
    ) -> Path:
        return self._object_dir(domain_id, layer, object_key, version) / "content.bin"

    def _metadata_path(
        self, domain_id: str, layer: DataLayer, object_key: str, version: int
    ) -> Path:
        return self._object_dir(domain_id, layer, object_key, version) / "metadata.json"

    def _object_dir(self, domain_id: str, layer: DataLayer, object_key: str, version: int) -> Path:
        safe_domain_id = _safe_path_part(domain_id, "domain_id")
        safe_parts = _safe_object_key_parts(object_key)
        return self._root.joinpath(safe_domain_id, layer.value, *safe_parts, f"v{version}")

    @staticmethod
    def _require_ref_domain(ref: ObjectRef, domain_id: str) -> None:
        require_domain_id(domain_id)
        if ref.domain_id != domain_id:
            raise PermissionError("ObjectRef domain_id does not match requested domain")


def _safe_object_key_parts(object_key: str) -> tuple[str, ...]:
    parts = tuple(part for part in object_key.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise SchemaValidationError("object_key contains unsafe path segments")
    return parts


def _safe_path_part(value: str, field_name: str) -> str:
    require_text(value, field_name)
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise SchemaValidationError(f"{field_name} contains unsafe path segments")
    return value


def _record_to_json(record: StoredObjectRecord) -> dict[str, str | int]:
    return {
        "id": record.id,
        "domain_id": record.domain_id,
        "layer": record.layer.value,
        "object_key": record.object_key,
        "content_hash": record.content_hash,
        "media_type": record.media_type,
        "byte_size": record.byte_size,
        "version": record.version,
        "storage_uri": record.storage_uri,
    }
