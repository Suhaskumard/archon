// Fixture factories — one representative object per DTO in src/api.ts.
// Each takes Partial<T> overrides.

import type {
  Architecture,
  Assumption,
  Behavior,
  ChangeAssessment,
  ChangeImpact,
  Characterization,
  Comparison,
  Component,
  Evidence,
  Evolution,
  Execution,
  Failure,
  Hotspot,
  Incident,
  Investigation,
  LegacyDna,
  ModernizationRecommendation,
  ModuleArch,
  Patch,
  PatchVerification,
  Repository,
  RepositoryUnderstanding,
  Run,
  Snapshot,
  SourceSummary,
  TechnicalDebtFinding,
  TestCase,
  TestGap,
} from "../api";

const mk =
  <T>(base: T) =>
  (over: Partial<T> = {}): T => ({ ...base, ...over });

export const repository = mk<Repository>({
  id: "repo-1",
  provider: "github",
  url: "https://github.com/acme/widgets",
  owner: "acme",
  name: "widgets",
  default_branch: "main",
  created_at: "2026-01-01T00:00:00Z",
});

export const snapshot = mk<Snapshot>({
  id: "snap-1",
  commit_sha: "a".repeat(40),
  branch: "main",
  requested_ref: null,
  size_bytes: 204800,
  file_count: 42,
  commit_count: 3,
  support_level: "SUPPORTED",
  support_notes: null,
  created_at: "2026-01-01T00:00:00Z",
});

export const evidence = mk<Evidence>({
  id: "ev-1",
  stage: "SCORING_LEGACY_RISK",
  classification: "FACT",
  summary: "pricing_engine scored HIGH legacy risk",
  detail: "complexity 12, churn 40",
  source_path: "src/pricing_engine.py",
  source_line: 10,
  confidence: 0.9,
  produced_by: "legacy_risk.v2",
  refs: null,
  created_at: "2026-01-01T00:01:00Z",
});

export const run = mk<Run>({
  id: "run-1",
  repository_id: "repo-1",
  snapshot_id: "snap-1",
  mode: "ANALYSIS_ONLY",
  state: "COMPLETED",
  current_stage: null,
  last_completed_stage: "ANALYZING_TESTS",
  progress_pct: 100,
  engine_versions: { legacy_risk: "legacy_risk.v2" },
  error: null,
  created_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z",
  ended_at: "2026-01-01T00:02:00Z",
  snapshot: snapshot(),
  evidence: [evidence()],
});

export const component = mk<Component>({
  id: "cmp-1",
  snapshot_id: "snap-1",
  parent_id: null,
  kind: "MODULE",
  name: "pricing_engine",
  qualified_name: "acme.pricing_engine",
  path: "src/pricing_engine.py",
  start_line: 1,
  end_line: 200,
  metrics: { complexity: 12, loc: 180 },
  attributes: {},
  is_test: false,
  is_entrypoint: false,
  is_config: false,
  role: "domain",
});

export const sourceSummary = mk<SourceSummary>({
  snapshot_id: "snap-1",
  analyzed: true,
  components: { MODULE: 5, FUNCTION: 20, CLASS: 3 },
  edges: { IMPORTS: 8, CALLS: 30, INHERITS: 1, CONTAINS: 25, resolved: 60 },
  entrypoints: [component({ id: "cmp-ep", qualified_name: "acme.cli", is_entrypoint: true })],
  tests: 4,
  config_files: 2,
});

export const moduleArch = mk<ModuleArch>({
  id: "cmp-1",
  qualified_name: "acme.pricing_engine",
  path: "src/pricing_engine.py",
  role: "domain",
  is_test: false,
  is_entrypoint: false,
  fan_in: 3,
  fan_out: 2,
  instability: 0.4,
  degree_centrality: 0.5,
  betweenness_centrality: 0.12,
  pagerank: 0.2,
  in_cycle: false,
  scc_size: 1,
  dependents: ["acme.api"],
  dependencies: ["acme.tax_rules"],
});

export const architecture = mk<Architecture>({
  run_id: "run-1",
  snapshot_id: "snap-1",
  reconstructed: true,
  roles: { domain: 3, api: 1, util: 1 },
  modules: [
    moduleArch(),
    moduleArch({ id: "cmp-2", qualified_name: "acme.tax_rules", dependencies: [], dependents: ["acme.pricing_engine"] }),
  ],
  cycles: [],
  layering_violations: [],
  top_hubs: [],
  artifact_ref: null,
});

export const evolution = mk<Evolution>({
  run_id: "run-1",
  snapshot_id: "snap-1",
  total_commits: 3,
  analyzed_commits: 3,
  span_days: 30,
  authors: 2,
  truncated: false,
  timeline: [
    { month: "2026-01", commits: 2, churn: 100 },
    { month: "2026-02", commits: 1, churn: 20 },
  ],
  top_churn: [{ qualified_name: "acme.pricing_engine", churn: 120, commit_count: 3, age_days: 30 }],
  top_co_change: [{ a: "acme.pricing_engine", b: "acme.tax_rules", count: 2, confidence: 0.8 }],
});

export const assumption = mk<Assumption>({
  id: "asm-1",
  kind: "boundary",
  description: "assumes positive quantity",
  location: "pricing_engine.py:20",
  risk: "HIGH",
  confidence: "0.7",
  suggested_test: "negative quantity raises",
  component_qn: "acme.pricing_engine",
  produced_by: "assumptions.v1",
  detail: null,
});

export const behavior = mk<Behavior>({
  id: "bhv-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  purpose: "compute a line price",
  historical_context: "added for the 2019 pricing revamp",
  current_role: "core pricing path",
  inputs: ["quantity", "unit_price"],
  outputs: ["total"],
  side_effects: [],
  exceptions: ["ValueError"],
  callers: ["acme.api.checkout"],
  callees: ["acme.tax_rules.rate_for"],
  tests: ["test_pricing.py::test_basic"],
  likely_invariants: ["total >= 0"],
  git: null,
  classification: "INFERENCE",
  confidence: "0.6",
});

export const legacyDna = mk<LegacyDna>({
  id: "dna-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  age_days: 300,
  complexity: 12,
  churn: 40,
  coupling: 6,
  coverage: 0.35,
  coverage_is_proxy: false,
  failure_count: 2,
  assumption_count: 1,
  debt_score: 0.4,
  legacy_risk_score: 72,
  category: "HIGH",
  confidence: 0.8,
  factor_breakdown: {},
});

export const hotspot = mk<Hotspot>({
  id: "hs-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  score: 68,
  classification: "RISKY",
  reasons: { elevated_signals: ["complexity", "churn"] },
});

export const technicalDebt = mk<TechnicalDebtFinding>({
  id: "td-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  category: "long_function",
  location: "pricing_engine.py:1",
  evidence: "180 LOC",
  severity: "MEDIUM",
  impact: "hard to change",
  confidence: 0.7,
  recommendation: "extract helpers",
});

export const understanding = mk<RepositoryUnderstanding>({
  run_id: "run-1",
  snapshot_id: "snap-1",
  overall_score: 71.5,
  confidence: 0.62,
  dimensions: [
    { name: "architecture", score: 80 },
    { name: "behavior", score: 65 },
    { name: "testing", score: 55 },
  ],
  evidence_coverage: {},
});

export const changeAssessment = mk<ChangeAssessment>({
  id: "ca-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  safety_score: 40,
  risk_category: "RISKY",
  factor_breakdown: {},
  recommended_preparation: ["add characterization tests", "review callers"],
  confidence: 0.7,
});

export const changeImpact = mk<ChangeImpact>({
  id: "ci-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  direct_dependents: [{ component_id: "cmp-3", qualified_name: "acme.api" }],
  indirect_dependents: [],
  callers: [{ component_id: "cmp-3", qualified_name: "acme.api.checkout" }],
  related_tests: [{ component_id: "cmp-t", qualified_name: "test_pricing.py" }],
  historical_co_changes: [{ component_id: "cmp-2", qualified_name: "acme.tax_rules", count: 2, confidence: 0.8 }],
  external_integrations: [{ target_name: "stripe", kind: "http" }],
  potential_impact: {
    what_could_break: ["checkout total"],
    tests_to_run: ["test_pricing.py"],
    what_to_do_first: ["pin current behaviour"],
  },
});

export const testCase = mk<TestCase>({
  id: "tc-1",
  component_id: "cmp-1",
  kind: "unit",
  path: "tests/test_pricing.py",
  name: "test_basic",
  origin: "discovered",
  validated: true,
  validation_errors: null,
});

export const execution = mk<Execution>({
  id: "ex-1",
  kind: "existing_suite",
  command: ["pytest", "-q"],
  exit_code: 1,
  passed: 10,
  failed: 1,
  errors: 0,
  timed_out: false,
  duration_ms: 1234,
  stdout_preview: "",
  stderr_preview: "",
  stdout_ref: null,
  stderr_ref: null,
  coverage_ref: "art-cov",
  started_at: null,
  ended_at: null,
});

export const characterization = mk<Characterization>({
  id: "ch-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  input_spec: [{ quantity: 2 }],
  observed_output_ref: null,
  observed_side_effects: [],
  baseline_hash: "deadbeefdeadbeefdeadbeef",
  test_case_id: "tc-1",
});

export const testGap = mk<TestGap>({
  id: "tg-1",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  kind: "function",
  coverage_pct: 0.2,
  legacy_risk_score: 72,
  change_safety_score: 40,
  priority_score: 88,
  priority: "HIGH",
  confidence: 0.8,
  factor_breakdown: {},
});

export const failure = mk<Failure>({
  id: "f-1",
  execution_id: "ex-1",
  test_identifier: "test_pricing.py::test_zero",
  message: "division by zero",
  exception_type: "ZeroDivisionError",
  stack_trace_ref: null,
  parsed_frames: [{ component_id: "cmp-1" }],
  reproducible: true,
  occurrences: 1,
  first_seen: "2026-01-01T00:01:30Z",
});

export const investigation = mk<Investigation>({
  id: "inv-1",
  failure_id: "f-1",
  summary: "divide() lacks a zero guard",
  root_cause_hypotheses: [{ text: "no guard", confidence: 0.8 }],
  affected_component_ids: ["cmp-1"],
  recommended_verification: ["add a test for zero"],
  confidence: 0.8,
  ai_schema_version: "archon.investigation.v1",
  cited_incident_ids: [],
});

export const patch = mk<Patch>({
  id: "p-1",
  investigation_id: "inv-1",
  strategy: "GUARD_CLAUSE",
  diff_preview: "+ if d == 0: raise ValueError",
  diff_ref: null,
  target_component_ids: ["cmp-1"],
  lines_added: 2,
  lines_removed: 0,
  static_validation: {},
  rank_score: 90,
  rank_breakdown: {},
  state: "VERIFIED",
  ai_schema_version: "archon.patch.v1",
});

export const patchVerification = mk<PatchVerification>({
  id: "pv-1",
  patch_id: "p-1",
  original_failure_fixed: true,
  characterization_pass: true,
  regression_pass: true,
  existing_tests_pass: true,
  new_critical_failures: 0,
  applies_cleanly: true,
  verdict: "VERIFIED",
  execution_ids: ["ex-2"],
});

export const incident = mk<Incident>({
  id: "inc-1",
  run_id: "run-1",
  repo_id: "repo-1",
  failure_signature: "ZeroDivisionError:divide",
  failure_summary: "divide by zero in pricing",
  root_cause: "missing zero guard",
  evidence_ids: ["ev-1"],
  affected_component_ids: ["cmp-1"],
  fix_ref: null,
  patch_id: "p-1",
  regression_test_ids: ["tc-2"],
  verification_id: "pv-1",
  confidence: 0.9,
  created_at: "2026-01-01T00:02:00Z",
});

export const modernization = mk<ModernizationRecommendation>({
  id: "mr-1",
  run_id: "run-1",
  target: "acme.pricing_engine",
  component_id: "cmp-1",
  component_qn: "acme.pricing_engine",
  strategy: "ADD_TESTS",
  risk: "LOW",
  effort: "M",
  impact: "HIGH",
  order_index: 0,
  rationale: "characterize before refactor",
  dependencies: [],
  required_tests: [],
  prerequisites: [],
  change_safety_ref: null,
  confidence: 0.75,
  classification: "RECOMMENDATION",
  ai_schema_version: "archon.modernization.v1",
  evidence_ids: [],
  created_at: "2026-01-01T00:02:00Z",
});

const componentDelta = {
  qualified_name: "acme.pricing_engine",
  base_score: 60,
  head_score: 72,
  delta: 12,
  base_category: "MODERATE",
  head_category: "HIGH",
};

export const comparison = mk<Comparison>({
  id: "cmp-run-1",
  repo_id: "repo-1",
  base_run_id: "run-0",
  head_run_id: "run-1",
  base_snapshot_id: "snap-0",
  head_snapshot_id: "snap-1",
  base_commit_sha: "b".repeat(40),
  head_commit_sha: "a".repeat(40),
  summary: {
    modules_added: 1,
    modules_removed: 0,
    dependencies_added: 2,
    dependencies_removed: 1,
    debt_findings_added: 1,
    debt_findings_resolved: 0,
    mean_legacy_risk_delta: 4.2,
    mean_change_safety_delta: -1.1,
    mean_coverage_delta: 0.05,
    risk_category_regressions: ["acme.pricing_engine"],
    change_safety_regressions: [],
  },
  produced_by: "differ.v1",
  created_at: "2026-01-02T00:00:00Z",
  report_artifact_id: "art-cmp",
  report: {
    architecture: {
      modules_added: ["acme.new_mod"],
      modules_removed: [],
      role_changes: [],
      module_count_base: 4,
      module_count_head: 5,
    },
    dependencies: { edges_added: ["a->b"], edges_removed: ["c->d"], edge_count_base: 7, edge_count_head: 8 },
    legacy_dna: {
      added: [],
      removed: [],
      changed: [{ ...componentDelta, debt_delta: 0.1 }],
      mean_legacy_risk_delta: 4.2,
      risk_category_regressions: ["acme.pricing_engine"],
    },
    change_safety: {
      added: [],
      removed: [],
      changed: [{ ...componentDelta, base_category: "CAUTION", head_category: "RISKY" }],
      mean_change_safety_delta: -1.1,
      change_safety_regressions: [],
    },
    coverage: {
      is_proxy: false,
      mean_coverage_delta: 0.05,
      components_worse: [],
      components_better: ["acme.pricing_engine"],
      changed: [{ qualified_name: "acme.pricing_engine", base_coverage: 0.3, head_coverage: 0.35, delta: 0.05 }],
    },
    technical_debt: {
      findings_added: [{ qualified_name: "acme.pricing_engine", category: "long_function", location: "x", severity: "MEDIUM" }],
      findings_resolved: [],
      count_base: 2,
      count_head: 3,
    },
    risk: { available: false },
  },
});
