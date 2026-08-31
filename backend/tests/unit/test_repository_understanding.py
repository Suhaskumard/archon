from archon.analysis.scoring.understanding import UnderstandingDimensions, understanding_score


def test_rich_evidence_scores_and_is_more_confident_than_sparse():
    rich = understanding_score(
        UnderstandingDimensions(
            architecture=1.0, dependency=0.9, behavior=0.8, historical=1.0,
            testing=0.7, configuration=1.0,
        )
    )
    sparse = understanding_score(
        UnderstandingDimensions(
            architecture=0.1, dependency=0.1, behavior=0.0, historical=0.0,
            testing=0.0, configuration=0.2,
        )
    )
    assert rich.score > sparse.score
    assert rich.confidence > sparse.confidence


def test_score_is_weighted_average_of_dimensions():
    result = understanding_score(UnderstandingDimensions(
        architecture=1.0, dependency=1.0, behavior=1.0, historical=1.0, testing=1.0, configuration=1.0,
    ))
    assert result.score == 100.0
    assert result.confidence == 1.0


def test_evidence_coverage_passthrough():
    counts = {"modules_with_role": 4, "modules_total": 5}
    result = understanding_score(UnderstandingDimensions(architecture=0.8, evidence_counts=counts))
    assert result.evidence_coverage == counts
