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
};
