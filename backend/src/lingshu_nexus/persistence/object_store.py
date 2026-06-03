"""Object storage port with an in-memory test adapter."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
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

