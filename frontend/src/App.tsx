import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Repository, type Run } from "./api";

export function App() {
  const [runId, setRunId] = useState<string | null>(null);
  return (
    <div className="wrap">
      <h1>ARCHON — Repository Intelligence</h1>
      {runId ? (
        <RunView runId={runId} onBack={() => setRunId(null)} />
      ) : (
        <RepositoryManager onOpenRun={setRunId} />
      )}
    </div>
  );
}

function useError() {
  const [err, setErr] = useState<string | null>(null);
  const guard = useCallback(async (fn: () => Promise<void>) => {
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);
  return { err, guard };
}

function RepositoryManager({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const { err, guard } = useError();

  const refresh = useCallback(
    () => guard(async () => setRepos(await api.listRepositories())),
    [guard],
  );
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addRepo = () =>
    guard(async () => {
      setBusy(true);
      try {
        await api.createRepository(url.trim());
        setUrl("");
        await refresh();
      } finally {
        setBusy(false);
      }
    });

  const startRun = (repoId: string) =>
    guard(async () => {
      const run = await api.createRun(repoId);
      onOpenRun(run.id);
    });

  return (
    <>
      <h2>Add a repository</h2>
      <div className="row">
        <input
          placeholder="https://github.com/owner/repo, owner/repo, or a local path"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && url.trim() && void addRepo()}
        />
        <button className="primary" disabled={busy || !url.trim()} onClick={() => void addRepo()}>
          Add
        </button>
        <button onClick={() => void refresh()}>Refresh</button>
      </div>
      {err && <p className="err">{err}</p>}

      <h2>Repositories</h2>
      {repos.length === 0 && <p className="meta">No repositories yet.</p>}
      {repos.map((r) => (
        <div className="card" key={r.id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <div className="repo-url">{r.owner && r.name ? `${r.owner}/${r.name}` : r.url}</div>
              <div className="meta">
                {r.provider} · {r.url} · default branch {r.default_branch ?? "—"}
              </div>
            </div>
            <div className="row">
              <button className="primary" onClick={() => void startRun(r.id)}>
                Ingest
              </button>
              <RunsInline repoId={r.id} onOpenRun={onOpenRun} />
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

function RunsInline({ repoId, onOpenRun }: { repoId: string; onOpenRun: (id: string) => void }) {
  const [runs, setRuns] = useState<Run[]>([]);
  useEffect(() => {
    let live = true;
    api
      .listRuns(repoId)
      .then((r) => live && setRuns(r))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [repoId]);
  if (runs.length === 0) return null;
  return (
    <select
      onChange={(e) => e.target.value && onOpenRun(e.target.value)}
      defaultValue=""
      title="Open a previous run"
    >
      <option value="" disabled>
        {runs.length} run(s)…
      </option>
      {runs.map((r) => (
        <option key={r.id} value={r.id}>
          {r.state} · {new Date(r.created_at).toLocaleString()}
        </option>
      ))}
    </select>
  );
}

const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

function RunView({ runId, onBack }: { runId: string; onBack: () => void }) {
  const [run, setRun] = useState<Run | null>(null);
  const { err, guard } = useError();
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let live = true;
    const poll = async () => {
      await guard(async () => {
        const r = await api.getRun(runId);
        if (!live) return;
        setRun(r);
        if (!TERMINAL.has(r.state)) {
          timer.current = window.setTimeout(poll, 800);
        }
      });
    };
    void poll();
    return () => {
      live = false;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [runId, guard]);

  return (
    <>
      <a className="back" onClick={onBack}>
        ← back to repositories
      </a>
      <h2>Run {runId}</h2>
      {err && <p className="err">{err}</p>}
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
          </div>
          <div className="bar">
            <div style={{ width: `${run.progress_pct}%` }} />
          </div>

          {run.error && (
            <div className="card err">
              <b>{run.error.code}</b>: {run.error.message}
              {run.error.suggested_action && <div className="meta">{run.error.suggested_action}</div>}
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

          <h2>Evidence</h2>
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
        </>
      )}
    </>
  );
}
