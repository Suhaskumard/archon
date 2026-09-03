import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { ErrorBanner, LoadingSkeleton, Pill, TableScroll } from "../components/ui";

const STATES = ["", "RUNNING", "QUEUED", "PENDING", "COMPLETED", "FAILED", "CANCELLED"];

function fmtDuration(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(0)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

export function OpsRoute() {
  const [state, setState] = useState("");
  const { data, error, loading } = useAsync(() => api.getAdminRuns(state || undefined), [state]);

  return (
    <>
      <Link className="back" to="/">
        ← back to repositories
      </Link>
      <h2>Operations</h2>
      <p className="meta">
        Run-level operational view. Prometheus metrics are served at{" "}
        <a href="/metrics">/metrics</a>; readiness at <a href="/readyz">/readyz</a>.
      </p>

      <label>
        Filter by state{" "}
        <select value={state} onChange={(e) => setState(e.target.value)} aria-label="run state filter">
          {STATES.map((s) => (
            <option key={s || "all"} value={s}>
              {s || "all"}
            </option>
          ))}
        </select>
      </label>

      <ErrorBanner error={error} />
      {loading && !data ? (
        <LoadingSkeleton rows={5} />
      ) : (
        <TableScroll>
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Repository</th>
                <th>Mode</th>
                <th>State</th>
                <th>Stage</th>
                <th>Trigger</th>
                <th>Duration</th>
                <th>AI</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {(data?.runs ?? []).map((r) => (
                <tr key={r.run_id}>
                  <td>
                    <Link to={`/runs/${r.run_id}`}>{r.run_id.slice(0, 12)}</Link>
                  </td>
                  <td className="meta">{r.repository ?? "—"}</td>
                  <td>{r.mode}</td>
                  <td>
                    <span className={`pill ${r.state}`}>{r.state}</span>
                  </td>
                  <td className="meta">
                    {r.state === "RUNNING"
                      ? (r.current_stage ?? "—")
                      : (r.last_completed_stage ?? "—")}
                  </td>
                  <td>
                    {r.trigger === "webhook" ? <Pill tone="info">push</Pill> : r.trigger}
                  </td>
                  <td className="meta">{fmtDuration(r.duration_seconds)}</td>
                  <td className="meta">{r.ai_evidence_count || "—"}</td>
                  <td className="meta">{r.error ? r.error.code : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
      <p className="meta">{data?.total ?? 0} run(s)</p>
    </>
  );
}
