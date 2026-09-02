import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { TERMINAL_RUN_STATES, usePoll } from "../lib/hooks";
import { ProgressBar, TableScroll } from "../components/ui";
import { RUN_PANELS } from "../panels";

export function RunRoute() {
  const { id = "" } = useParams();
  const { data: run, error } = usePoll(
    () => api.getRun(id),
    [id],
    (r) => TERMINAL_RUN_STATES.has(r.state),
  );

  return (
    <>
      <Link className="back" to="/">
        ← back to repositories
      </Link>
      <h2>
        Run {id}
        {run?.snapshot_id && (
          <>
            {" · "}
            <Link to={`/runs/${id}/compare`}>compare</Link>
          </>
        )}
      </h2>
      {error && <p className="err">{error}</p>}
      {!run ? (
        <p className="meta">Loading…</p>
      ) : (
        <>
          <div className="row">
            <span className={`pill ${run.state}`}>{run.state}</span>
            <span className="meta">
              stage: {run.current_stage ?? "—"} · last completed:{" "}
              {run.last_completed_stage ?? "—"} · mode {run.mode}
            </span>
            {run.state === "COMPLETED" && run.snapshot_id && (
              <button
                className="primary"
                onClick={() =>
                  void api.downloadReport(run.id).catch((e) => window.alert(String(e)))
                }
              >
                Download report (.xlsx)
              </button>
            )}
          </div>
          <ProgressBar pct={run.progress_pct} />

          {run.error && (
            <div className="card err">
              <b>{run.error.code}</b>: {run.error.message}
              {run.error.suggested_action && (
                <div className="meta">{run.error.suggested_action}</div>
              )}
            </div>
          )}

          {run.snapshot && (
            <>
              <h2>Snapshot</h2>
              <div className="card">
                <div>
                  commit <code>{run.snapshot.commit_sha}</code> on{" "}
                  {run.snapshot.branch ?? "(detached)"}
                </div>
                <div className="meta">
                  <span className={`pill ${run.snapshot.support_level}`}>
                    {run.snapshot.support_level}
                  </span>{" "}
                  {run.snapshot.file_count} files · {run.snapshot.commit_count} commits ·{" "}
                  {(run.snapshot.size_bytes / 1024).toFixed(0)} KiB
                </div>
              </div>
            </>
          )}

          {run.state === "COMPLETED" &&
            run.snapshot_id &&
            RUN_PANELS.map(({ key, Comp }) => (
              <Comp
                key={key}
                runId={run.id}
                snapshotId={run.snapshot_id!}
                repoId={run.repository_id}
              />
            ))}

          <h2>Evidence</h2>
          <TableScroll>
            <table>
              <thead>
                <tr>
                  <th>Class</th>
                  <th>Summary</th>
                  <th>Detail</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {run.evidence.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <span className={`pill ${e.classification}`}>{e.classification}</span>
                    </td>
                    <td>{e.summary}</td>
                    <td className="meta">{e.detail}</td>
                    <td className="meta">
                      {e.produced_by}
                      {e.confidence != null && ` · conf ${e.confidence.toFixed(2)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </>
      )}
    </>
  );
}
