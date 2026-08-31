"""AI patch generation under the Minimal Patch Principle (spec section 39) - the
``GENERATING_PATCH`` stage.

Scoped, like every mock AI op, to the one bug pattern the fixture (and Phase 4's
``division``-kind ``Assumption`` detector) actually recognizes: an unguarded
division. Two deterministic candidates are proposed per gated ``Investigation`` - a
correct guard and a deliberately-wrong one - so ranking/verification have a real
choice to make (spec's own acceptance bar). ``old_snippet``/``new_snippet`` are exact
source text; applying is a literal string replacement, so "applies cleanly" is a
verifiable fact recorded in ``static_validation``, not a claim.
"""

from __future__ import annotations

import ast
import difflib
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archon.core.artifacts import write_text
from archon.core.logging import get_logger
from archon.db.models import (
    AnalysisRun,
    Component,
    Evidence,
    Investigation,
    Patch,
    RepositorySnapshot,
)
from archon.domain.ai_schemas import PATCH_PROPOSAL_SCHEMA_VERSION, PatchProposal
from archon.domain.enums import Classification, PatchState, Stage
from archon.investigation.engine import PATCH_GENERATION_CONFIDENCE_THRESHOLD
from archon.providers.ai import get_ai_provider
from archon.testing._safety import parses, source_is_safe
from archon.testing.characterization import _find_function_node
from archon.workspace.manager import Workspace

log = get_logger("archon.healing.generation")

PATCH_GENERATION_VERSION = "patch_generation.v1"
_MAX_CHANGED_LINES = 20  # Minimal Patch Principle
_STRATEGY_HINTS = ("guard_zero_divisor", "naive_integer_division")


def _find_divisor(node: ast.FunctionDef, source: str) -> tuple[str | None, str | None, int]:
    """Best-effort: find a ``return <a> / <b>`` statement, its divisor name, and its
    real column offset (``ast.get_source_segment`` strips leading indentation, so the
    caller needs ``col_offset`` separately to re-indent a multi-line replacement
    correctly when it's spliced back into the file)."""
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and isinstance(child.value, ast.BinOp) and isinstance(child.value.op, ast.Div):
            divisor = child.value.right
            if isinstance(divisor, ast.Name):
                return divisor.id, ast.get_source_segment(source, child), child.col_offset
    return None, None, 0


@dataclass
class PatchGenerationSummary:
    generated: int

    def as_dict(self) -> dict:
        return {"generated": self.generated}


def generate_patches(
    session: Session, run: AnalysisRun, snapshot: RepositorySnapshot, workspace: Workspace
) -> PatchGenerationSummary:
    session.execute(delete(Patch).where(Patch.run_id == run.id))
    session.flush()

    investigations = session.scalars(
        select(Investigation).where(
            Investigation.run_id == run.id,
            Investigation.confidence >= PATCH_GENERATION_CONFIDENCE_THRESHOLD,
        )
    ).all()
    repo_dir = workspace.resolve_within("repo")
    ai = get_ai_provider()
    generated = 0

    for investigation in investigations:
        if not investigation.affected_component_ids:
            continue
        component = session.get(Component, investigation.affected_component_ids[0])
        if component is None:
            continue

        file_path = repo_dir / component.path
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        node = _find_function_node(source, component.name, component.start_line or -1)
        if node is None:
            continue
        divisor, return_expr, col_offset = _find_divisor(node, source)

        base_context = {
            "component": {
                "id": component.id, "qualified_name": component.qualified_name,
                "path": component.path, "name": component.name,
            },
            "divisor_param": divisor, "return_expr_source": return_expr,
            "indent": " " * col_offset,
            "known_refs": {"component": {component.qualified_name}},
        }

        for hint in _STRATEGY_HINTS:
            result = ai.complete_structured(
                "patch_proposal", PatchProposal, {**base_context, "strategy_hint": hint}
            )
            if not result.old_snippet or not result.new_snippet:
                session.add(
                    Evidence(
                        run_id=run.id, stage=Stage.GENERATING_PATCH, classification=Classification.INFERENCE,
                        summary=f"No patch proposal for {component.qualified_name} (strategy={hint})",
                        produced_by=PATCH_GENERATION_VERSION, confidence=1.0,
                    )
                )
                continue

            occurrences = source.count(result.old_snippet)
            applies_cleanly = occurrences == 1
            new_source = source.replace(result.old_snippet, result.new_snippet, 1) if applies_cleanly else source

            diff_lines = list(difflib.unified_diff(
                source.splitlines(keepends=True), new_source.splitlines(keepends=True),
                fromfile=f"a/{component.path}", tofile=f"b/{component.path}",
            ))
            lines_added = sum(1 for dl in diff_lines if dl.startswith("+") and not dl.startswith("+++"))
            lines_removed = sum(1 for dl in diff_lines if dl.startswith("-") and not dl.startswith("---"))

            errors: list[str] = []
            if not applies_cleanly:
                errors.append(f"old_snippet occurs {occurrences} time(s), expected exactly 1")
            ok, err = parses(new_source)
            if not ok:
                errors.append(f"static: {err}")
            elif not source_is_safe(new_source):
                errors.append("static: contains a banned construct")
            if lines_added + lines_removed > _MAX_CHANGED_LINES:
                errors.append(f"exceeds the {_MAX_CHANGED_LINES}-line Minimal Patch Principle cap")

            diff_art = write_text(
                session, run.id, f"patch_diff_{component.id}_{hint}", "".join(diff_lines),
                stage=Stage.GENERATING_PATCH, ext=".diff", mime="text/x-diff",
            )
            patch = Patch(
                run_id=run.id, investigation_id=investigation.id, strategy=result.strategy,
                diff_ref=diff_art.id, target_component_ids=[component.id],
                lines_added=lines_added, lines_removed=lines_removed,
                old_snippet=result.old_snippet, new_snippet=result.new_snippet,
                static_validation={
                    "parses": ok, "source_is_safe": source_is_safe(new_source) if ok else False,
                    "applies_cleanly": applies_cleanly, "errors": errors,
                },
                state=PatchState.PROPOSED, ai_schema_version=PATCH_PROPOSAL_SCHEMA_VERSION,
                produced_by=PATCH_GENERATION_VERSION,
            )
            session.add(patch)
            session.flush()
            generated += 1

            session.add(
                Evidence(
                    run_id=run.id, stage=Stage.GENERATING_PATCH,
                    classification=Classification.FACT if not errors else Classification.INFERENCE,
                    summary=f"Proposed patch {result.strategy!r} for {component.qualified_name}"[:512],
                    detail="; ".join(errors) or "static validation clean",
                    produced_by=PATCH_GENERATION_VERSION, confidence=1.0,
                    refs={"patch_id": patch.id},
                )
            )
            session.flush()

    if not investigations:
        session.add(
            Evidence(
                run_id=run.id, stage=Stage.GENERATING_PATCH, classification=Classification.FACT,
                summary="No investigations cleared the confidence threshold - no patches generated",
                produced_by=PATCH_GENERATION_VERSION, confidence=1.0,
            )
        )
        session.flush()

    log.info("patches generated", extra={"extra_fields": {"run_id": run.id, "generated": generated}})
    return PatchGenerationSummary(generated=generated)
