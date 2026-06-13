"""V1 role-based access control helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lingshu_domain.validation import require_text
from lingshu_nexus.skills import UserRole

ROLE_RANK: dict[UserRole, int] = {
    UserRole.READ_ONLY: 0,
    UserRole.RESEARCHER: 1,
    UserRole.REVIEWER: 2,
    UserRole.ADMIN: 3,
}


class AuthorizationError(PermissionError):
    """Raised when a V1 actor cannot perform an action."""


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    role: UserRole

    def __post_init__(self) -> None:
        require_text(self.actor_id, "actor_id")


def actor_from_payload(
    payload: dict[str, Any] | dict[str, object],
    *,
    default_actor_id: str,
    default_role: UserRole,
    actor_id_field: str = "actor_id",
    actor_role_field: str = "actor_role",
) -> ActorContext:
    raw_actor_id = payload.get(actor_id_field, default_actor_id)
    raw_role = payload.get(actor_role_field, default_role.value)
    if not isinstance(raw_actor_id, str) or not raw_actor_id.strip():
        raise ValueError(f"{actor_id_field} must be a non-empty string")
    if not isinstance(raw_role, str):
        raise ValueError(f"{actor_role_field} must be a string")
    return ActorContext(actor_id=raw_actor_id.strip(), role=parse_role(raw_role))


def actor_from_form(
    *,
    actor_id: str,
    actor_role: str,
    default_actor_id: str,
    default_role: UserRole,
) -> ActorContext:
    return ActorContext(
        actor_id=(actor_id or default_actor_id).strip(),
        role=parse_role(actor_role or default_role.value),
    )


def parse_role(value: str) -> UserRole:
    try:
        return UserRole(value)
    except ValueError as exc:
        raise ValueError("Unknown actor_role") from exc


def require_minimum_role(
    actor: ActorContext,
    minimum_role: UserRole,
    *,
    action: str,
) -> None:
    if ROLE_RANK[actor.role] < ROLE_RANK[minimum_role]:
        raise AuthorizationError(
            f"{action} requires {minimum_role.value} role or higher; got {actor.role.value}"
        )
