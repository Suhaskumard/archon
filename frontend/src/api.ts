// Typed client for the ARCHON REST API (spec section 48: data comes only from real APIs).

export interface Repository {
  id: string;
  provider: string;
  url: string;
  owner: string | null;
  name: string | null;
  default_branch: string | null;
  created_at: string;
}

export interface Evidence {
  id: string;
  stage: string | null;
  classification: "FACT" | "INFERENCE" | "HYPOTHESIS" | "RECOMMENDATION";
  summary: string;
  detail: string | null;
  source_path: string | null;
  source_line: number | null;
  confidence: number | null;
  produced_by: string;
  refs: Record<string, unknown> | null;
  created_at: string;
}

export interface Snapshot {
  id: string;
  commit_sha: string;
  branch: string | null;
  requested_ref: string | null;
  size_bytes: number;
  file_count: number;
  commit_count: number;
  support_level: "SUPPORTED" | "PARTIALLY_SUPPORTED" | "UNSUPPORTED";
  support_notes: Record<string, unknown> | null;
  created_at: string;
}

export interface Run {
  id: string;
  repository_id: string;
  snapshot_id: string | null;
  mode: string;
  state: "PENDING" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  current_stage: string | null;
  last_completed_stage: string | null;
  progress_pct: number;
  engine_versions: Record<string, string>;
  error: { code: string; message: string; suggested_action?: string } | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  snapshot: Snapshot | null;
  evidence: Evidence[];
}

export interface Component {
  id: string;
  snapshot_id: string;
  parent_id: string | null;
  kind: "FILE" | "MODULE" | "CLASS" | "FUNCTION" | "METHOD";
  name: string;
  qualified_name: string;
  path: string;
  start_line: number | null;
  end_line: number | null;
  metrics: Record<string, unknown>;
  attributes: Record<string, unknown>;
  is_test: boolean;
  is_entrypoint: boolean;
  is_config: boolean;
  role: string | null;
}

export interface SourceSummary {
  snapshot_id: string;
  analyzed: boolean;
  components: Record<string, number>;
  edges: Record<string, number>;
  entrypoints: Component[];
  tests: number;
  config_files: number;
}

export interface ModuleArch {
  id: string;
  qualified_name: string;
  path: string;
  role: string | null;
  is_test: boolean;
  is_entrypoint: boolean;
  fan_in: number;
  fan_out: number;
  instability: number;
  degree_centrality: number;
  betweenness_centrality: number;
  pagerank: number;
  in_cycle: boolean;
  scc_size: number;
  dependents: string[];
  dependencies: string[];
}

export interface Architecture {
  run_id: string;
  snapshot_id: string;
  reconstructed: boolean;
  roles: Record<string, number>;
  modules: ModuleArch[];
  cycles: string[][];
  layering_violations: Array<Record<string, unknown>>;
  top_hubs: Array<Record<string, unknown>>;
  artifact_ref: string | null;
}

export interface Evolution {
  run_id: string;
  snapshot_id: string;
  total_commits: number;
  analyzed_commits: number;
  span_days: number;
  authors: number;
  truncated: boolean;
  timeline: Array<{ month: string; commits: number; churn: number }>;
  top_churn: Array<Record<string, unknown>>;
  top_co_change: Array<{ a: string; b: string; count: number; confidence: number }>;
}

export interface Assumption {
  id: string;
  kind: string;
  description: string;
  location: string | null;
  risk: "HIGH" | "MEDIUM" | "LOW" | null;
  confidence: string | null;
  suggested_test: string | null;
  component_qn: string | null;
  produced_by: string;
  detail: string | null;
}

export interface Behavior {
  id: string;
  component_id: string;
  component_qn: string | null;
  purpose: string | null;
  historical_context: string | null;
  current_role: string | null;
  inputs: string[] | null;
  outputs: string[] | null;
  side_effects: string[] | null;
  exceptions: string[] | null;
  callers: string[] | null;
  callees: string[] | null;
  tests: string[] | null;
  likely_invariants: string[] | null;
  git: Record<string, unknown> | null;
  classification: string | null;
  confidence: string | null;
}

export interface LegacyDna {
  id: string;
  component_id: string;
  component_qn: string | null;
  age_days: number | null;
  complexity: number | null;
  churn: number | null;
  coupling: number | null;
  coverage: number | null;
  coverage_is_proxy: boolean;
  failure_count: number | null;
  assumption_count: number;
  debt_score: number | null;
  legacy_risk_score: number;
  category: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  confidence: number;
  factor_breakdown: Record<string, unknown>;
}

export interface Hotspot {
  id: string;
  component_id: string;
  component_qn: string | null;
  score: number;
  classification: "STABLE" | "WATCH" | "RISKY" | "CRITICAL";
  reasons: Record<string, unknown>;
}

export interface TechnicalDebtFinding {
  id: string;
  component_id: string | null;
  component_qn: string | null;
  category: string;
  location: string;
  evidence: string | null;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  impact: string | null;
  confidence: number;
  recommendation: string | null;
}

export interface UnderstandingDimension {
  name: string;
  score: number;
}

export interface RepositoryUnderstanding {
  run_id: string;
  snapshot_id: string;
  overall_score: number;
  confidence: number;
  dimensions: UnderstandingDimension[];
  evidence_coverage: Record<string, unknown>;
}

export interface ChangeAssessment {
  id: string;
  component_id: string;
  component_qn: string | null;
  safety_score: number;
  risk_category: "SAFE" | "CAUTION" | "RISKY" | "DANGEROUS";
  factor_breakdown: Record<string, unknown>;
  recommended_preparation: string[];
  confidence: number;
}

export interface ChangeImpactEntry {
  component_id: string;
  qualified_name: string;
  kind?: string;
}

export interface ChangeCoChangeEntry {
  component_id: string | null;
  qualified_name: string;
  count: number;
  confidence: number;
}

export interface ChangeExternalIntegration {
  target_name: string;
  kind: string;
}

export interface ChangeImpact {
  id: string;
  component_id: string;
  component_qn: string | null;
  direct_dependents: ChangeImpactEntry[];
  indirect_dependents: ChangeImpactEntry[];
  callers: ChangeImpactEntry[];
  related_tests: ChangeImpactEntry[];
  historical_co_changes: ChangeCoChangeEntry[];
  external_integrations: ChangeExternalIntegration[];
  potential_impact: {
    what_could_break: string[];
    tests_to_run: string[];
    what_to_do_first: string[];
  };
}

export interface TestCase {
  id: string;
  component_id: string | null;
  kind: string;
  path: string;
  name: string;
  origin: string;
  validated: boolean;
  validation_errors: unknown[] | null;
}

export interface Execution {
  id: string;
  kind: string;
  command: string[];
  exit_code: number | null;
  passed: number;
  failed: number;
  errors: number;
  timed_out: boolean;
  duration_ms: number;
  stdout_preview: string;
  stderr_preview: string;
  stdout_ref: string | null;
  stderr_ref: string | null;
  coverage_ref: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface Characterization {
  id: string;
  component_id: string | null;
  component_qn: string | null;
  input_spec: Record<string, unknown>[];
  observed_output_ref: string | null;
  observed_side_effects: Record<string, unknown>[];
  baseline_hash: string;
  test_case_id: string | null;
}

export interface TestGap {
  id: string;
  component_id: string;
  component_qn: string | null;
  kind: string;
  coverage_pct: number;
  legacy_risk_score: number | null;
  change_safety_score: number | null;
  priority_score: number;
  priority: string;
  confidence: number;
  factor_breakdown: Record<string, unknown>;
}

export interface Failure {
  id: string;
  execution_id: string;
  test_identifier: string;
  message: string;
  exception_type: string;
  stack_trace_ref: string | null;
  parsed_frames: Record<string, unknown>[];
  reproducible: boolean;
  occurrences: number;
  first_seen: string;
}

export interface Investigation {
  id: string;
  failure_id: string;
  summary: string;
  root_cause_hypotheses: Record<string, unknown>[];
  affected_component_ids: string[];
  recommended_verification: string[];
  confidence: number;
  ai_schema_version: string;
  cited_incident_ids: string[];
}

export interface Patch {
  id: string;
  investigation_id: string;
  strategy: string;
  diff_preview: string;
  diff_ref: string | null;
  target_component_ids: string[];
  lines_added: number;
  lines_removed: number;
  static_validation: Record<string, unknown>;
  rank_score: number | null;
  rank_breakdown: Record<string, unknown> | null;
  state: string;
  ai_schema_version: string;
}

export interface PatchVerification {
  id: string;
  patch_id: string;
  original_failure_fixed: boolean;
  characterization_pass: boolean;
  regression_pass: boolean;
  existing_tests_pass: boolean;
  new_critical_failures: number;
  applies_cleanly: boolean;
  verdict: string;
  execution_ids: string[];
}

export interface Incident {
  id: string;
  run_id: string | null;
  repo_id: string;
  failure_signature: string;
  failure_summary: string;
  root_cause: string;
  evidence_ids: string[];
  affected_component_ids: string[];
  fix_ref: string | null;
  patch_id: string | null;
  regression_test_ids: string[];
  verification_id: string | null;
  confidence: number;
  created_at: string;
}

export interface ComparisonSummary {
  id: string;
  repo_id: string;
  base_run_id: string;
  head_run_id: string;
  base_snapshot_id: string | null;
  head_snapshot_id: string | null;
  base_commit_sha: string | null;
  head_commit_sha: string | null;
  summary: {
    modules_added: number;
    modules_removed: number;
    dependencies_added: number;
    dependencies_removed: number;
    debt_findings_added: number;
    debt_findings_resolved: number;
    mean_legacy_risk_delta: number | null;
    mean_change_safety_delta: number | null;
    mean_coverage_delta: number | null;
    risk_category_regressions: string[];
    change_safety_regressions: string[];
  };
  produced_by: string;
  created_at: string;
}

interface ComponentDelta {
  qualified_name: string;
  base_score: number;
  head_score: number;
  delta: number;
  base_category: string | null;
  head_category: string | null;
}

export interface Comparison extends ComparisonSummary {
  report_artifact_id: string | null;
  report: {
    architecture: {
      modules_added: string[];
      modules_removed: string[];
      role_changes: { qualified_name: string; base_role: string | null; head_role: string | null }[];
      module_count_base: number;
      module_count_head: number;
    };
    dependencies: {
      edges_added: string[];
      edges_removed: string[];
      edge_count_base: number;
      edge_count_head: number;
    };
    legacy_dna: {
      added: string[];
      removed: string[];
      changed: (ComponentDelta & { debt_delta: number })[];
      mean_legacy_risk_delta: number | null;
      risk_category_regressions: string[];
    };
    change_safety: {
      added: string[];
      removed: string[];
      changed: ComponentDelta[];
      mean_change_safety_delta: number | null;
      change_safety_regressions: string[];
    };
    coverage: {
      is_proxy: boolean;
      mean_coverage_delta: number | null;
      components_worse: string[];
      components_better: string[];
      changed: { qualified_name: string; base_coverage: number; head_coverage: number; delta: number }[];
    };
    technical_debt: {
      findings_added: { qualified_name: string; category: string; location: string; severity: string | null }[];
      findings_resolved: { qualified_name: string; category: string; location: string; severity: string | null }[];
      count_base: number;
      count_head: number;
    };
    risk: { available: boolean; changed?: ComponentDelta[] };
  };
}

export interface ApiError {
  error: { code: string; message: string; suggested_action?: string };
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const e = (body as ApiError).error;
    throw new Error(e ? `${e.code}: ${e.message}` : `HTTP ${res.status}`);
  }
  return body as T;
}

export const api = {
  listRepositories: () => req<Repository[]>("/repositories"),
  createRepository: (url: string) =>
    req<Repository>("/repositories", { method: "POST", body: JSON.stringify({ url }) }),
  listRuns: (repoId: string) => req<Run[]>(`/repositories/${repoId}/runs`),
  createRun: (repoId: string, mode: "INGEST_ONLY" | "ANALYSIS_ONLY" = "ANALYSIS_ONLY", ref?: string) =>
    req<Run>(`/repositories/${repoId}/runs`, {
      method: "POST",
      body: JSON.stringify({ ref: ref || null, mode }),
    }),
  getRun: (runId: string) => req<Run>(`/runs/${runId}`),
  getRunSource: (runId: string) => req<SourceSummary>(`/runs/${runId}/source`),
  listComponents: (snapshotId: string, params = "") =>
    req<Component[]>(`/snapshots/${snapshotId}/components?limit=1000${params}`),
  getArchitecture: (runId: string) => req<Architecture>(`/runs/${runId}/architecture`),
  getEvolution: (runId: string) => req<Evolution>(`/runs/${runId}/evolution`),
  getAssumptions: (runId: string) => req<Assumption[]>(`/runs/${runId}/assumptions`),
  getBehavior: (runId: string) => req<Behavior[]>(`/runs/${runId}/behavior`),
  getLegacyDna: (runId: string) => req<LegacyDna[]>(`/runs/${runId}/legacy-dna`),
  getHotspots: (runId: string) => req<Hotspot[]>(`/runs/${runId}/hotspots`),
  getTechnicalDebt: (runId: string) => req<TechnicalDebtFinding[]>(`/runs/${runId}/technical-debt`),
  getUnderstanding: (runId: string) => req<RepositoryUnderstanding>(`/runs/${runId}/understanding`),
  getChangeSafety: (runId: string) => req<ChangeAssessment[]>(`/runs/${runId}/change-safety`),
  postChangeImpact: (runId: string, componentId: string) =>
    req<ChangeImpact>(`/runs/${runId}/change-impact`, {
      method: "POST",
      body: JSON.stringify({ component_id: componentId }),
    }),
  getTests: (runId: string) => req<TestCase[]>(`/runs/${runId}/tests`),
  getExecutions: (runId: string) => req<Execution[]>(`/runs/${runId}/executions`),
  getCharacterization: (runId: string) =>
    req<Characterization[]>(`/runs/${runId}/characterization`),
  getTestGaps: (runId: string) => req<TestGap[]>(`/runs/${runId}/test-gaps`),
  getFailures: (runId: string) => req<Failure[]>(`/runs/${runId}/failures`),
  getInvestigations: (runId: string) => req<Investigation[]>(`/runs/${runId}/investigations`),
  getPatches: (runId: string) => req<Patch[]>(`/runs/${runId}/patches`),
  getVerifications: (runId: string) => req<PatchVerification[]>(`/runs/${runId}/verifications`),
  getIncidents: (runId: string) => req<Incident[]>(`/runs/${runId}/incidents`),
  getRepositoryIncidents: (repoId: string) => req<Incident[]>(`/repositories/${repoId}/incidents`),
  listComparisons: (repoId: string) =>
    req<ComparisonSummary[]>(`/repositories/${repoId}/comparisons`),
  createComparison: (repoId: string, baseRunId: string, headRunId: string) =>
    req<Comparison>(`/repositories/${repoId}/comparisons`, {
      method: "POST",
      body: JSON.stringify({ base_run_id: baseRunId, head_run_id: headRunId }),
    }),
  getComparison: (comparisonId: string) => req<Comparison>(`/comparisons/${comparisonId}`),
};
