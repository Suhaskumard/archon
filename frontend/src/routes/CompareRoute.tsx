import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { RepositoryComparisonPanel } from "../panels";

export function CompareRoute() {
  const { id = "" } = useParams();
  const { data: run, error } = useAsync(() => api.getRun(id), [id]);

  return (
    <>
      <Link className="back" to={`/runs/${id}`}>
        ← back to run
      </Link>
      <h2>Compare run {id}</h2>
      {error && <p className="err">{error}</p>}
      {!run ? (
        <p className="meta">Loading…</p>
      ) : !run.snapshot_id ? (
        <p className="meta">This run has no snapshot to compare.</p>
      ) : (
        <RepositoryComparisonPanel
          runId={run.id}
          snapshotId={run.snapshot_id}
          repoId={run.repository_id}
        />
      )}
    </>
  );
}
