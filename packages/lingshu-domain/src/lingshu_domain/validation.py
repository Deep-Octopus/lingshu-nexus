"""Validation helpers for domain schema objects."""

from __future__ import annotations

from collections.abc import Iterable


class SchemaValidationError(ValueError):
    """Raised when a domain object violates the Evidence Schema contract."""


def require_text(value: str | None, field_name: str) -> str:
    if value is None or value.strip() == "":
        raise SchemaValidationError(f"{field_name} is required")
    return value


def require_domain_id(domain_id: str | None) -> str:
    return require_text(domain_id, "domain_id")


def require_non_empty(values: Iterable[object], field_name: str) -> None:
    if not tuple(values):
        raise SchemaValidationError(f"{field_name} must not be empty")


def require_probability(value: float, field_name: str) -> None:
    if value < 0 or value > 1:
        raise SchemaValidationError(f"{field_name} must be between 0 and 1")
