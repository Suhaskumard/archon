"""Patch Ranking (spec section 40) - deterministic and explainable, matching the shape
of ``analysis/scoring/legacy_risk.py`` (versioned, per-signal breakdown, ``explain()``)
rather than another AI call - "never just the first candidate" is best guaranteed by a
real, inspectable formula.

Ranked twice per patch: once right after generation (static-only signals - decides
*which* candidate ``verify_patches`` tries first) and once after verification (the
real pass/fail signals dominate once they exist).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from archon.db.models import AnalysisRun, Patch, PatchVerification
from archon.domain.enums import PatchState

PATCH_RANKING_VERSION = "patch_ranking.v1"

_SIZE_SCALE = 20.0  # Minimal Patch Principle cap - a patch at the cap scores ~0 on size
_STATIC_WEIGHT = {"size": 1.0}
_VERIFIED_WEIGHT = {"correctness": 0.8, "size": 0.2}


@dataclass
class RankResult:
    score: float
    factor_breakdown: dict = field(default_factory=dict)

    def explain(self) -> dict:
        return dict(self.factor_breakdown)


def _size_score(lines_changed: int) -> float:
    return max(0.0, 1.0 - min(lines_changed, _SIZE_SCALE) / _SIZE_SCALE)


def rank_static(static_validation_clean: bool, lines_changed: int) -> RankResult:
    """Pre-verification rank: static validation is a hard gate, size is the only signal."""
    if not static_validation_clean:
        return RankResult(score=0.0, factor_breakdown={"gate": "static_validation_failed"})
    size = _size_score(lines_changed)
    score = round(100.0 * size * _STATIC_WEIGHT["size"], 2)
    return RankResult(score=score, factor_breakdown={"size_score": size, "lines_changed": lines_changed})


def rank_verified(
    static_validation_clean: bool, lines_changed: int, verification: PatchVerification
) -> RankResult:
    """Post-verification rank: real pass/fail signals dominate the score."""
    if not static_validation_clean:
        return RankResult(score=0.0, factor_breakdown={"gate": "static_validation_failed"})
    checks = (
        verification.original_failure_fixed, verification.regression_pass,
        verification.existing_tests_pass, verification.characterization_pass,
    )
    correctness = sum(1.0 for c in checks if c) / len(checks)
    size = _size_score(lines_changed)
    score = round(
        100.0 * (_VERIFIED_WEIGHT["correctness"] * correctness + _VERIFIED_WEIGHT["size"] * size), 2
    )
    return RankResult(
        score=score,
        factor_breakdown={
            "correctness": correctness, "size_score": size,
            "original_failure_fixed": verification.original_failure_fixed,
            "regression_pass": verification.regression_pass,
            "existing_tests_pass": verification.existing_tests_pass,
            "characterization_pass": verification.characterization_pass,
            "new_critical_failures": verification.new_critical_failures,
            "applies_cleanly": verification.applies_cleanly,
        },
    )


@dataclass
class PatchRankingSummary:
    ranked: int

    def as_dict(self) -> dict:
        return {"ranked": self.ranked}


def rank_patches(session: Session, run: AnalysisRun) -> PatchRankingSummary:
    """Pre-verification pass - orders which candidate ``verify_patches`` tries first."""
    patches = session.scalars(select(Patch).where(Patch.run_id == run.id)).all()
    for patch in patches:
        result = rank_static(
            static_validation_clean=not patch.static_validation.get("errors"),
            lines_changed=patch.lines_added + patch.lines_removed,
        )
        patch.rank_score = result.score
        patch.rank_breakdown = result.explain()
        patch.state = PatchState.TESTING if result.score > 0 else PatchState.REJECTED
    session.flush()
    return PatchRankingSummary(ranked=len(patches))
