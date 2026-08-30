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
  createRun: (repoId: string, ref?: string) =>
    req<Run>(`/repositories/${repoId}/runs`, {
      method: "POST",
      body: JSON.stringify({ ref: ref || null, mode: "INGEST_ONLY" }),
    }),
  getRun: (runId: string) => req<Run>(`/runs/${runId}`),
};
