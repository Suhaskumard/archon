import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Repository, type Run } from "../api";
import { useAsync, useErrorGuard } from "../lib/hooks";

export function RepositoriesRoute() {
  const navigate = useNavigate();
  const { data: repos, error, reload } = useAsync(() => api.listRepositories(), []);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const { err, guard } = useErrorGuard();

  const addRepo = () =>
    guard(async () => {
      setBusy(true);
      try {
        await api.createRepository(url.trim());
        setUrl("");
        reload();
      } finally {
        setBusy(false);
      }
    });

  const startRun = (repoId: string) =>
    guard(async () => {
      const run = await api.createRun(repoId, "ANALYSIS_ONLY");
      navigate(`/runs/${run.id}`);
    });

  return (
    <>
      <h2>Add a repository</h2>
      <div className="row">
        <label className="visually-hidden" htmlFor="repo-url">
          repository URL or path
        </label>
        <input
          id="repo-url"
          placeholder="https://github.com/owner/repo, owner/repo, or a local path"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && url.trim() && void addRepo()}
        />
        <button className="primary" disabled={busy || !url.trim()} onClick={() => void addRepo()}>
          Add
        </button>
        <button onClick={() => reload()}>Refresh</button>
      </div>
      {(err || error) && (
        <p className="err" role="alert">
          {err || error}
        </p>
      )}

      <h2>Repositories</h2>
      {repos && repos.length === 0 && <p className="meta">No repositories yet.</p>}
      <ul className="cardlist" aria-label="repositories">
      {(repos ?? []).map((r: Repository) => (
        <li className="card" key={r.id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <div className="repo-url">
                {r.owner && r.name ? `${r.owner}/${r.name}` : r.url}
              </div>
              <div className="meta">
                {r.provider} · {r.url} · default branch {r.default_branch ?? "—"}
              </div>
            </div>
            <div className="row">
              <button className="primary" onClick={() => void startRun(r.id)}>
                Analyze
              </button>
              <RunsInline repoId={r.id} />
            </div>
          </div>
        </li>
      ))}
      </ul>
    </>
  );
}

function RunsInline({ repoId }: { repoId: string }) {
  const navigate = useNavigate();
  const { data: runs } = useAsync(() => api.listRuns(repoId), [repoId]);
  if (!runs || runs.length === 0) return null;
  return (
    <select
      onChange={(e) => e.target.value && navigate(`/runs/${e.target.value}`)}
      defaultValue=""
      title="Open a previous run"
      aria-label="open a previous run"
    >
      <option value="" disabled>
        {runs.length} run(s)…
      </option>
      {runs.map((r: Run) => (
        <option key={r.id} value={r.id}>
          {r.state} · {new Date(r.created_at).toLocaleString()}
        </option>
      ))}
    </select>
  );
}
