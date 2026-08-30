"""``AIProvider`` contract + the mandatory validation pipeline (spec sections 13-14, 61).

    complete_structured(operation, schema, context) -> validated schema instance

Never trust raw AI output: it is pydantic-validated, then every repository-specific
``EvidenceRef`` is checked against real rows the caller passed in ``context["known_refs"]``;
unresolvable refs are dropped and confidence is floored (hallucination control).
"""

from __future__ import annotations

import abc
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from archon.core.errors import ArchonError, ErrorCode, Recoverability
from archon.core.logging import get_logger
from archon.domain.ai_schemas import AIEnvelope, EvidenceRef
from archon.domain.enums import Confidence

log = get_logger("archon.ai")

T = TypeVar("T", bound=BaseModel)


class AIProviderError(ArchonError):
    def __init__(self, message: str, **ctx: Any) -> None:
        super().__init__(
            ErrorCode.AI_PROVIDER_ERROR, message, context=ctx,
            recoverability=Recoverability.TRANSIENT,
            suggested_action="Retry; if it persists check the AI provider configuration.",
        )


class AIOutputError(ArchonError):
    def __init__(self, message: str, **ctx: Any) -> None:
        super().__init__(
            ErrorCode.AI_OUTPUT_INVALID, message, context=ctx,
            recoverability=Recoverability.NON_RECOVERABLE,
            suggested_action="This is a provider/schema bug - AI output must match the schema.",
        )


class AIProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def _generate(self, operation: str, schema: type[BaseModel], context: dict) -> dict:
        """Return a raw dict that *should* satisfy ``schema``. Subclass-specific."""

    def complete_structured(
        self, operation: str, schema: type[T], context: dict | None = None
    ) -> T:
        context = context or {}
        raw = self._generate(operation, schema, context)
        try:
            result = schema.model_validate(raw)
        except ValidationError as exc:
            raise AIOutputError(
                f"AI output for {operation!r} failed schema validation",
                operation=operation, errors=exc.errors(include_url=False)[:5],
            ) from exc

        if isinstance(result, AIEnvelope):
            result = self._validate_evidence(operation, result, context)
        log.info(
            "ai op",
            extra={"extra_fields": {
                "provider": self.name, "operation": operation,
                "confidence": getattr(result, "confidence", None),
            }},
        )
        return result

    # --- hallucination control (spec section 14) ---------------------------------

    @staticmethod
    def _validate_evidence(operation: str, result: T, context: dict) -> T:
        known: dict[str, set[str]] = context.get("known_refs", {})
        kept: list[EvidenceRef] = []
        dropped = 0
        for ref in result.evidence:  # type: ignore[attr-defined]
            pool = known.get(ref.kind)
            if pool is None or ref.ref in pool:
                kept.append(ref)
            else:
                dropped += 1
        if dropped:
            result.evidence = kept  # type: ignore[attr-defined]
            if result.confidence in (Confidence.HIGH, Confidence.MEDIUM):  # type: ignore[attr-defined]
                result.confidence = Confidence.LOW  # type: ignore[attr-defined]
            log.warning(
                "dropped unresolved AI evidence refs",
                extra={"extra_fields": {"operation": operation, "dropped": dropped}},
            )
        if not result.evidence and result.confidence == Confidence.HIGH:  # type: ignore[attr-defined]
            result.confidence = Confidence.LOW  # type: ignore[attr-defined]
        return result
