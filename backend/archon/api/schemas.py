"""Request/response models for the API (spec section 47)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from archon.domain.enums import RunMode


class RepositoryCreate(BaseModel):
    url: str = Field(min_length=1, description="github.com URL, owner/repo shorthand, or local path")
    default_branch: str | None = None


class RepositoryOut(BaseModel):
    id: str
    provider: str
    url: str
    owner: str | None
    name: str | None
    default_branch: str | None
    created_at: datetime


class RunCreate(BaseModel):
    ref: str | None = Field(default=None, description="branch, tag or commit sha; default branch if omitted")
    mode: RunMode = RunMode.INGEST_ONLY


class EvidenceOut(BaseModel):
    id: str
    stage: str | None
    classification: str
    summary: str
    detail: str | None
    source_path: str | None
    source_line: int | None
    confidence: float | None
    produced_by: str
    refs: dict | None
    created_at: datetime


class SnapshotOut(BaseModel):
    id: str
    commit_sha: str
    branch: str | None
    requested_ref: str | None
    size_bytes: int
    file_count: int
    commit_count: int
    support_level: str
    support_notes: dict | None
    created_at: datetime


class RunOut(BaseModel):
    id: str
    repository_id: str
    snapshot_id: str | None
    mode: str
    state: str
    current_stage: str | None
    last_completed_stage: str | None
    progress_pct: float
    engine_versions: dict
    error: dict | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    # Phase 19: {"source": "webhook", "event": "push", "sha", "before", "delivery_id"} for a
    # push-triggered run; None for API / CLI / bulk runs.
    trigger: dict | None = None
    snapshot: SnapshotOut | None = None
    evidence: list[EvidenceOut] = []


class Page(BaseModel):
    total: int
    limit: int
    offset: int


# --- Phase 2: source intelligence ---------------------------------------------------


class ComponentOut(BaseModel):
    id: str
    snapshot_id: str
    parent_id: str | None
    kind: str
    name: str
    qualified_name: str
    path: str
    start_line: int | None
    end_line: int | None
    metrics: dict
    attributes: dict
    is_test: bool
    is_entrypoint: bool
    is_config: bool
    role: str | None


class DependencyOut(BaseModel):
    id: str
    kind: str
    src_component_id: str
    dst_component_id: str | None
    target_name: str
    resolved: bool
    external: bool
    source_line: int | None
    attributes: dict


class SourceSummaryOut(BaseModel):
    snapshot_id: str
    analyzed: bool
    components: dict[str, int]
    edges: dict[str, int]
    entrypoints: list[ComponentOut] = []
    tests: int = 0
    config_files: int = 0


# --- Phase 3: architecture ---------------------------------------------------------


class ModuleArchOut(BaseModel):
    id: str
    qualified_name: str
    path: str
    role: str | None
    is_test: bool
    is_entrypoint: bool
    fan_in: int = 0
    fan_out: int = 0
    instability: float = 0.0
    degree_centrality: float = 0.0
    betweenness_centrality: float = 0.0
    pagerank: float = 0.0
    in_cycle: bool = False
    scc_size: int = 1
    dependents: list[str] = []
    dependencies: list[str] = []


class ArchitectureOut(BaseModel):
    run_id: str
    snapshot_id: str
    reconstructed: bool
    roles: dict[str, int]
    modules: list[ModuleArchOut]
    cycles: list[list[str]]
    layering_violations: list[dict]
    top_hubs: list[dict]
    artifact_ref: str | None = None


# --- Phase 4: software archaeology -----------------------------------------------


class CommitOut(BaseModel):
    id: str
    sha: str
    author_name: str | None
    author_email: str | None
    authored_at: datetime | None
    message: str | None
    files_changed: int
    insertions: int
    deletions: int
    is_merge: bool
    changed_paths: list[str] | None


class EvolutionOut(BaseModel):
    run_id: str
    snapshot_id: str
    total_commits: int
    analyzed_commits: int
    span_days: int
    authors: int
    truncated: bool
    timeline: list[dict]          # [{month: "2026-06", commits: n, churn: n}]
    top_churn: list[dict]         # [{path, churn, commits}]
    top_co_change: list[dict]     # [{a, b, count, confidence}]


class AssumptionOut(BaseModel):
    id: str
    kind: str
    description: str
    location: str | None
    risk: str | None
    confidence: str | None
    suggested_test: str | None
    component_id: str | None
    component_qn: str | None = None
    produced_by: str
    detail: str | None
    created_at: datetime


class BehaviorOut(BaseModel):
    id: str
    component_id: str
    component_qn: str | None = None
    purpose: str | None
    historical_context: str | None
    current_role: str | None
    inputs: list[str] | None
    outputs: list[str] | None
    side_effects: list[str] | None
    exceptions: list[str] | None
    callers: list[str] | None
    callees: list[str] | None
    tests: list[str] | None
    likely_invariants: list[str] | None
    git: dict | None
    classification: str | None
    confidence: str | None
    produced_by: str


class ComponentHistoryOut(BaseModel):
    component_id: str
    qualified_name: str
    path: str
    git: dict
    commits: list[CommitOut]
    co_changed_with: list[dict]   # [{qualified_name, count, confidence}]


# --- Phase 5: scoring (legacy risk, hotspots, tech debt, understanding) -------------


class RiskAssessmentOut(BaseModel):
    id: str
    component_id: str
    component_qn: str | None = None
    engine_version: str
    score: float
    category: str
    factor_breakdown: dict
    confidence: float


class LegacyDnaOut(BaseModel):
    id: str
    component_id: str
    component_qn: str | None = None
    age_days: int | None
    complexity: float | None
    churn: float | None
    coupling: float | None
    coverage: float | None
    coverage_is_proxy: bool
    failure_count: int | None
    assumption_count: int
    debt_score: float | None
    legacy_risk_score: float
    category: str
    confidence: float
    factor_breakdown: dict


class TechnicalDebtFindingOut(BaseModel):
    id: str
    component_id: str | None
    component_qn: str | None = None
    category: str
    location: str
    evidence: str | None
    severity: str
    impact: str | None
    confidence: float
    recommendation: str | None


class HotspotOut(BaseModel):
    id: str
    component_id: str
    component_qn: str | None = None
    score: float
    classification: str
    reasons: dict


class UnderstandingDimensionOut(BaseModel):
    name: str
    score: float


class RepositoryUnderstandingOut(BaseModel):
    run_id: str
    snapshot_id: str
    overall_score: float
    confidence: float
    dimensions: list[UnderstandingDimensionOut]
    evidence_coverage: dict


# --- Phase 6: change safety & change impact -----------------------------------------


class ChangeAssessmentOut(BaseModel):
    id: str
    component_id: str
    component_qn: str | None = None
    safety_score: float
    risk_category: str
    factor_breakdown: dict
    recommended_preparation: list[str]
    confidence: float


class ChangeImpactRequest(BaseModel):
    component_id: str = Field(min_length=1)


class ChangeImpactOut(BaseModel):
    id: str
    component_id: str
    component_qn: str | None = None
    direct_dependents: list[dict]
    indirect_dependents: list[dict]
    callers: list[dict]
    related_tests: list[dict]
    historical_co_changes: list[dict]
    external_integrations: list[dict]
    potential_impact: dict


# --- Phase 7: execution --------------------------------------------------------------


class TestCaseOut(BaseModel):
    id: str
    component_id: str | None
    kind: str
    path: str
    name: str
    origin: str
    validated: bool
    validation_errors: list | None = None


class ExecutionOut(BaseModel):
    id: str
    kind: str
    command: list[str]
    exit_code: int | None
    passed: int
    failed: int
    errors: int
    timed_out: bool
    duration_ms: int
    stdout_preview: str
    stderr_preview: str
    stdout_ref: str | None
    stderr_ref: str | None
    coverage_ref: str | None
    started_at: datetime | None
    ended_at: datetime | None


# --- Phase 8: characterization & test gaps --------------------------------------------


class CharacterizationOut(BaseModel):
    id: str
    component_id: str | None
    component_qn: str | None = None
    input_spec: list
    observed_output_ref: str | None
    observed_side_effects: list
    baseline_hash: str
    test_case_id: str | None


class TestGapOut(BaseModel):
    id: str
    component_id: str
    component_qn: str | None = None
    kind: str
    coverage_pct: float
    legacy_risk_score: float | None
    change_safety_score: float | None
    priority_score: float
    priority: str
    confidence: float
    factor_breakdown: dict


# --- Phase 9: failure investigation & self-healing ------------------------------------


class FailureOut(BaseModel):
    id: str
    execution_id: str
    test_identifier: str
    message: str
    exception_type: str
    stack_trace_ref: str | None
    parsed_frames: list
    reproducible: bool
    occurrences: int
    first_seen: datetime


class InvestigationOut(BaseModel):
    id: str
    failure_id: str
    summary: str
    root_cause_hypotheses: list
    affected_component_ids: list
    recommended_verification: list
    confidence: float
    ai_schema_version: str
    cited_incident_ids: list


class PatchOut(BaseModel):
    id: str
    investigation_id: str
    strategy: str
    diff_preview: str
    diff_ref: str | None
    target_component_ids: list
    lines_added: int
    lines_removed: int
    static_validation: dict
    rank_score: float | None
    rank_breakdown: dict | None
    state: str
    ai_schema_version: str


class PatchVerificationOut(BaseModel):
    id: str
    patch_id: str
    original_failure_fixed: bool
    characterization_pass: bool
    regression_pass: bool
    existing_tests_pass: bool
    new_critical_failures: int
    applies_cleanly: bool
    verdict: str
    execution_ids: list


# --- Phase 10: incident memory --------------------------------------------------------


class IncidentOut(BaseModel):
    id: str
    run_id: str | None
    repo_id: str
    failure_signature: str
    failure_summary: str
    root_cause: str
    evidence_ids: list
    affected_component_ids: list
    fix_ref: str | None
    patch_id: str | None
    regression_test_ids: list
    verification_id: str | None
    confidence: float
    created_at: datetime


# --- Phase 11: repository comparison -------------------------------------------------


class ComparisonCreate(BaseModel):
    base_run_id: str = Field(min_length=1, description="the 'before' run")
    head_run_id: str = Field(min_length=1, description="the 'after' run")


class ComparisonSummaryOut(BaseModel):
    id: str
    repo_id: str
    base_run_id: str
    head_run_id: str
    base_snapshot_id: str | None
    head_snapshot_id: str | None
    base_commit_sha: str | None
    head_commit_sha: str | None
    summary: dict
    produced_by: str
    created_at: datetime


class ComparisonOut(ComparisonSummaryOut):
    report: dict
    report_artifact_id: str | None


# --- Phase 12: modernization ------------------------------------------------------------


class ModernizationRecommendationOut(BaseModel):
    id: str
    run_id: str
    target: str
    component_id: str | None
    component_qn: str | None
    strategy: str
    risk: str
    effort: str
    impact: str
    order_index: int
    rationale: str | None
    dependencies: list
    required_tests: list
    prerequisites: list
    change_safety_ref: str | None
    confidence: float
    classification: str | None
    ai_schema_version: str | None
    evidence_ids: list
    created_at: datetime
