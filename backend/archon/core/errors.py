"""ARCHON error taxonomy (spec section 54).

Every error carries: code, message, context, recoverability, suggested action.
Nothing is ever silently swallowed - callers either handle an ``ArchonError`` or let it
propagate to the API layer, which renders it as a structured JSON body.
"""

from __future__ import annotations

import enum
from typing import Any


class Recoverability(str, enum.Enum):
    RECOVERABLE = "RECOVERABLE"        # retrying or fixing input may succeed
    NON_RECOVERABLE = "NON_RECOVERABLE"  # will not succeed without a different request
    TRANSIENT = "TRANSIENT"            # external/temporary; automatic retry is reasonable


class ErrorCode(str, enum.Enum):
    # generic
    INTERNAL = "INTERNAL"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"  # bad/missing credential or signature (spec section 51 webhook)
    # repository ingestion (spec sections 21, 54)
    INVALID_REPOSITORY_URL = "INVALID_REPOSITORY_URL"
    REPOSITORY_NOT_FOUND = "REPOSITORY_NOT_FOUND"
    REPOSITORY_PRIVATE = "REPOSITORY_PRIVATE"
    GITHUB_RATE_LIMITED = "GITHUB_RATE_LIMITED"
    GITHUB_UNAUTHORIZED = "GITHUB_UNAUTHORIZED"
    CLONE_FAILED = "CLONE_FAILED"
    BRANCH_NOT_FOUND = "BRANCH_NOT_FOUND"
    COMMIT_NOT_FOUND = "COMMIT_NOT_FOUND"
    EMPTY_REPOSITORY = "EMPTY_REPOSITORY"
    NO_GIT_HISTORY = "NO_GIT_HISTORY"
    REPOSITORY_TOO_LARGE = "REPOSITORY_TOO_LARGE"
    UNSUPPORTED_REPOSITORY = "UNSUPPORTED_REPOSITORY"
    # workspace
    WORKSPACE_QUOTA_EXCEEDED = "WORKSPACE_QUOTA_EXCEEDED"
    PATH_TRAVERSAL = "PATH_TRAVERSAL"
    # jobs / pipeline
    ILLEGAL_STATE_TRANSITION = "ILLEGAL_STATE_TRANSITION"
    JOB_CANCELLED = "JOB_CANCELLED"
    TIMEOUT = "TIMEOUT"
    # AI (spec sections 13-14, 61)
    AI_PROVIDER_ERROR = "AI_PROVIDER_ERROR"
    AI_OUTPUT_INVALID = "AI_OUTPUT_INVALID"
    # sandbox / execution (spec sections 12, 36)
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    CONTAINER_START_FAILED = "CONTAINER_START_FAILED"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INTERNAL: 500,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION: 422,
    ErrorCode.CONFLICT: 409,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INVALID_REPOSITORY_URL: 422,
    ErrorCode.REPOSITORY_NOT_FOUND: 404,
    ErrorCode.REPOSITORY_PRIVATE: 403,
    ErrorCode.GITHUB_RATE_LIMITED: 429,
    ErrorCode.GITHUB_UNAUTHORIZED: 401,
    ErrorCode.CLONE_FAILED: 502,
    ErrorCode.BRANCH_NOT_FOUND: 404,
    ErrorCode.COMMIT_NOT_FOUND: 404,
    ErrorCode.EMPTY_REPOSITORY: 422,
    ErrorCode.NO_GIT_HISTORY: 422,
    ErrorCode.REPOSITORY_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_REPOSITORY: 422,
    ErrorCode.WORKSPACE_QUOTA_EXCEEDED: 507,
    ErrorCode.PATH_TRAVERSAL: 400,
    ErrorCode.ILLEGAL_STATE_TRANSITION: 500,
    ErrorCode.JOB_CANCELLED: 409,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.AI_PROVIDER_ERROR: 502,
    ErrorCode.AI_OUTPUT_INVALID: 500,
    ErrorCode.SANDBOX_UNAVAILABLE: 503,
    ErrorCode.CONTAINER_START_FAILED: 502,
}


class ArchonError(Exception):
    """Base class for every deliberate ARCHON failure."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        recoverability: Recoverability = Recoverability.NON_RECOVERABLE,
        suggested_action: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}
        self.recoverability = recoverability
        self.suggested_action = suggested_action

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self.code, 500)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "context": self.context,
                "recoverability": self.recoverability.value,
                "suggested_action": self.suggested_action,
            }
        }

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code.value}] {self.message}"


# --- convenience constructors for the common cases ---

def not_found(entity: str, entity_id: str) -> ArchonError:
    return ArchonError(
        ErrorCode.NOT_FOUND,
        f"{entity} {entity_id!r} does not exist",
        context={"entity": entity, "id": entity_id},
        suggested_action="Check the id or list the resource collection.",
    )


def validation(message: str, **context: Any) -> ArchonError:
    return ArchonError(
        ErrorCode.VALIDATION,
        message,
        context=context,
        suggested_action="Fix the request payload and retry.",
    )
