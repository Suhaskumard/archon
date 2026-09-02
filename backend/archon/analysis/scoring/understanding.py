"""Repository Understanding scoring engine (spec section 30).

``understanding.v2`` - six dimensions, each an evidence-coverage fraction in [0, 1]:

    architecture    % of MODULE components with a resolved ``role`` (Phase 3)
    dependency      % of dependency edges that resolved to a real component (Phase 2)
    behavior        % of components with a behavior reconstruction (Phase 4)
    historical      git history depth available, capped at a "deep enough" span (Phase 4)
    testing         % of MODULE components with a TESTED_BY edge (coarse - no real
                    coverage data exists until Phase 8; this is presence, not amount)
    configuration   % of recognised config files parsed without error (Phase 2)

The overall score is a weighted average of the six fractions; confidence tracks the same
fractions again (sparse evidence lowers both the score *and* the confidence, per spec sec
30 - a repo that is small-but-fully-understood should not look as confident as one with
deep, broad evidence).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archon.analysis.scoring.thresholds import UNDERSTANDING_DIMENSION_WEIGHTS

UNDERSTANDING_VERSION = "understanding.v2"

DIMENSIONS = ("architecture", "dependency", "behavior", "historical", "testing", "configuration")


@dataclass
class UnderstandingDimensions:
    architecture: float = 0.0
    dependency: float = 0.0
    behavior: float = 0.0
    historical: float = 0.0
    testing: float = 0.0
    configuration: float = 0.0
    evidence_counts: dict = field(default_factory=dict)  # raw counts behind each fraction


@dataclass
class ScoreResult:
    score: float
    confidence: float
    dimensions: dict
    evidence_coverage: dict = field(default_factory=dict)

    def explain(self) -> dict:
        return {"dimensions": dict(self.dimensions), "evidence_coverage": dict(self.evidence_coverage)}


def understanding_score(d: UnderstandingDimensions) -> ScoreResult:
    values = {name: max(0.0, min(getattr(d, name), 1.0)) for name in DIMENSIONS}
    weights = UNDERSTANDING_DIMENSION_WEIGHTS
    total_weight = sum(weights.values())
    weighted = sum(values[name] * weights[name] for name in DIMENSIONS)
    score = round(100.0 * weighted / total_weight, 2) if total_weight else 0.0
    confidence = round(sum(values.values()) / len(values), 4) if values else 0.0

    return ScoreResult(
        score=score,
        confidence=confidence,
        dimensions=values,
        evidence_coverage=dict(d.evidence_counts),
    )
