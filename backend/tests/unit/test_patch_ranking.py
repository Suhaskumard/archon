from archon.db.models import PatchVerification
from archon.domain.enums import VerificationVerdict
from archon.healing.ranking import rank_static, rank_verified


def test_rank_static_gates_on_validation_failure():
    result = rank_static(static_validation_clean=False, lines_changed=1)
    assert result.score == 0.0
    assert result.factor_breakdown["gate"] == "static_validation_failed"


def test_rank_static_favors_smaller_patches():
    small = rank_static(static_validation_clean=True, lines_changed=2)
    large = rank_static(static_validation_clean=True, lines_changed=18)
    assert small.score > large.score
    assert small.score > 0.0


def _verification(**overrides) -> PatchVerification:
    defaults = dict(
        run_id="run_x", patch_id="ptc_x", original_failure_fixed=True, characterization_pass=True,
        regression_pass=True, existing_tests_pass=True, new_critical_failures=0, applies_cleanly=True,
        verdict=VerificationVerdict.VERIFIED, execution_ids=[], produced_by="patch_verification.v1",
    )
    defaults.update(overrides)
    return PatchVerification(**defaults)


def test_rank_verified_all_checks_pass_scores_highest():
    good = rank_verified(True, 2, _verification())
    bad = rank_verified(True, 2, _verification(
        original_failure_fixed=False, regression_pass=False, existing_tests_pass=False,
        characterization_pass=False, verdict=VerificationVerdict.REJECTED,
    ))
    assert good.score > bad.score
    assert good.factor_breakdown["correctness"] == 1.0
    assert bad.factor_breakdown["correctness"] == 0.0


def test_rank_verified_gates_on_static_validation():
    result = rank_verified(False, 2, _verification())
    assert result.score == 0.0
    assert result.factor_breakdown["gate"] == "static_validation_failed"
