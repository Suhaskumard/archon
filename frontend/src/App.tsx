import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type Architecture,
  type Assumption,
  type Behavior,
  type Component,
  type Evolution,
  type ModuleArch,
  type Repository,
  type Run,
  type SourceSummary,
} from "./api";

const RISK_COLOR: Record<string, string> = {
  HIGH: "#ff9d9d",
  MEDIUM: "#ffd479",
  LOW: "#9aa4b2",
};

const ROLE_COLOR: Record<string, string> = {
  api: "#5b9dff",
  cli: "#8ab4f8",
  entrypoint: "#c58af9",
  domain: "#7ee0a2",
  model: "#ffd479",
  io: "#ff9d9d",
  util: "#9aa4b2",
  config: "#6ee7d6",
  test: "#b0b8c4",
  unknown: "#4a5160",
};

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
      const run = await api.createRun(repoId, "ANALYSIS_ONLY");
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
                Analyze
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

function SourceIntel({ runId, snapshotId }: { runId: string; snapshotId: string }) {
  const [sum, setSum] = useState<SourceSummary | null>(null);
  const [comps, setComps] = useState<Component[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .getRunSource(runId)
      .then((s) => live && setSum(s))
      .catch((e) => live && setErr(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [runId]);

  if (err) return <p className="err">source: {err}</p>;
  if (!sum || !sum.analyzed) return null;

  const topComplex = (comps ?? [])
    .filter((c) => typeof c.metrics.complexity === "number")
    .sort((a, b) => (b.metrics.complexity as number) - (a.metrics.complexity as number))
    .slice(0, 8);

  return (
    <>
      <h2>Source Intelligence</h2>
      <div className="card">
        <div className="row" style={{ gap: 16 }}>
          {Object.entries(sum.components).map(([k, v]) => (
            <span key={k} className="meta">
              <b>{v}</b> {k.toLowerCase()}
            </span>
          ))}
        </div>
        <div className="row" style={{ gap: 16, marginTop: 6 }}>
          {["IMPORTS", "CALLS", "INHERITS", "CONTAINS"].map((k) => (
            <span key={k} className="meta">
              <b>{sum.edges[k] ?? 0}</b> {k.toLowerCase()}
            </span>
          ))}
          <span className="meta">
            <b>{sum.edges.resolved ?? 0}</b> resolved
          </span>
          <span className="meta">
            <b>{sum.tests}</b> test modules · <b>{sum.config_files}</b> config files
          </span>
        </div>
        {sum.entrypoints.length > 0 && (
          <div className="meta" style={{ marginTop: 6 }}>
            entry points: {sum.entrypoints.map((e) => e.qualified_name).join(", ")}
          </div>
        )}
        <div style={{ marginTop: 8 }}>
          <a onClick={() => void api.listComponents(snapshotId).then(setComps).catch(() => undefined)}>
            {comps ? "loaded" : "load components →"}
          </a>
        </div>
        {topComplex.length > 0 && (
          <table style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>Most complex</th>
                <th>Kind</th>
                <th>Cx</th>
                <th>LOC</th>
                <th>Path</th>
              </tr>
            </thead>
            <tbody>
              {topComplex.map((c) => (
                <tr key={c.id}>
                  <td>{c.qualified_name}</td>
                  <td className="meta">{c.kind}</td>
                  <td>{String(c.metrics.complexity)}</td>
                  <td className="meta">{String(c.metrics.loc ?? "")}</td>
                  <td className="meta">
                    {c.path}:{c.start_line}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function ModuleGraphSvg({ arch }: { arch: Architecture }) {
  const mods = arch.modules;
  if (mods.length === 0) return null;
  const size = 320;
  const r = size / 2 - 34;
  const cx = size / 2;
  const cy = size / 2;
  const pos = new Map<string, { x: number; y: number }>();
  mods.forEach((m, i) => {
    const a = (2 * Math.PI * i) / mods.length - Math.PI / 2;
    pos.set(m.qualified_name, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
  });
  const edges: Array<[string, string]> = [];
  for (const m of mods) for (const dep of m.dependencies) edges.push([m.qualified_name, dep]);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ maxWidth: "100%" }}>
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#5a6472" />
        </marker>
      </defs>
      {edges.map(([u, v], i) => {
        const a = pos.get(u)!;
        const b = pos.get(v)!;
        return (
          <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#3a4150" strokeWidth={1.2} markerEnd="url(#arr)" />
        );
      })}
      {mods.map((m) => {
        const p = pos.get(m.qualified_name)!;
        const size2 = 5 + Math.min(m.fan_in + m.fan_out, 8);
        return (
          <g key={m.id}>
            <circle cx={p.x} cy={p.y} r={size2} fill={ROLE_COLOR[m.role ?? "unknown"] ?? "#4a5160"} stroke={m.in_cycle ? "#ff5555" : "#0f1115"} strokeWidth={m.in_cycle ? 2 : 1} />
            <text x={p.x} y={p.y - size2 - 4} textAnchor="middle" fontSize="9" fill="#9aa4b2">
              {m.qualified_name.split(".").slice(-1)[0]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function ArchitecturePanel({ runId }: { runId: string }) {
  const [arch, setArch] = useState<Architecture | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .getArchitecture(runId)
      .then((a) => live && setArch(a))
      .catch((e) => live && setErr(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [runId]);

  if (err) return null; // architecture not reconstructed for this run (e.g. INGEST_ONLY)
  if (!arch || !arch.reconstructed) return null;

  const modules: ModuleArch[] = [...arch.modules].sort(
    (a, b) => b.betweenness_centrality - a.betweenness_centrality || b.fan_in - a.fan_in,
  );

  return (
    <>
      <h2>Architecture</h2>
      <div className="card">
        <div className="row" style={{ gap: 12 }}>
          {Object.entries(arch.roles).map(([role, n]) => (
            <span key={role} className="pill" style={{ borderColor: ROLE_COLOR[role], color: ROLE_COLOR[role] }}>
              {role} · {n}
            </span>
          ))}
        </div>
        <div className="row" style={{ alignItems: "flex-start", gap: 20, marginTop: 10 }}>
          <ModuleGraphSvg arch={arch} />
          <div style={{ flex: 1, minWidth: 320 }}>
            <table>
              <thead>
                <tr>
                  <th>Module</th>
                  <th>Role</th>
                  <th title="fan-in">in</th>
                  <th title="fan-out">out</th>
                  <th title="instability">I</th>
                  <th title="betweenness">btw</th>
                </tr>
              </thead>
              <tbody>
                {modules.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.qualified_name}
                      {m.in_cycle && <span className="err"> ⟳</span>}
                    </td>
                    <td>
                      <span className="pill" style={{ borderColor: ROLE_COLOR[m.role ?? "unknown"], color: ROLE_COLOR[m.role ?? "unknown"] }}>
                        {m.role}
                      </span>
                    </td>
                    <td>{m.fan_in}</td>
                    <td>{m.fan_out}</td>
                    <td className="meta">{m.instability.toFixed(2)}</td>
                    <td className="meta">{m.betweenness_centrality.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {arch.cycles.length > 0 && (
          <div className="err" style={{ marginTop: 8 }}>
            Import cycles: {arch.cycles.map((c) => c.join(" → ")).join("  |  ")}
          </div>
        )}
        {arch.layering_violations.length > 0 && (
          <div className="err" style={{ marginTop: 8 }}>
            Layering violations:{" "}
            {arch.layering_violations
              .map((v) => `${v.from} → ${v.to} (${v.reason})`)
              .join("; ")}
          </div>
        )}
        {arch.cycles.length === 0 && arch.layering_violations.length === 0 && (
          <div className="meta" style={{ marginTop: 8 }}>
            No import cycles or layering violations detected.
          </div>
        )}
      </div>
    </>
  );
}

function GitEvolutionPanel({ runId }: { runId: string }) {
  const [evo, setEvo] = useState<Evolution | null>(null);
  useEffect(() => {
    let live = true;
    api.getEvolution(runId).then((e) => live && setEvo(e)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!evo) return null;
  const maxC = Math.max(1, ...evo.timeline.map((t) => t.commits));
  return (
    <>
      <h2>Git Evolution</h2>
      <div className="card">
        <div className="meta">
          {evo.analyzed_commits} commit(s) over {evo.span_days} day(s) · {evo.authors} author(s)
          {evo.truncated && " · history truncated"}
        </div>
        <svg viewBox={`0 0 ${Math.max(evo.timeline.length * 26, 40)} 60`} height={60} style={{ marginTop: 6 }}>
          {evo.timeline.map((t, i) => (
            <g key={t.month}>
              <rect
                x={i * 26 + 4}
                y={54 - (t.commits / maxC) * 44}
                width={16}
                height={(t.commits / maxC) * 44}
                fill="#5b9dff"
              />
              <text x={i * 26 + 12} y={60} textAnchor="middle" fontSize="7" fill="#9aa4b2">
                {t.month.slice(2)}
              </text>
            </g>
          ))}
        </svg>
        <table style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Most-changed module</th>
              <th>Churn</th>
              <th>Commits</th>
              <th>Age (d)</th>
            </tr>
          </thead>
          <tbody>
            {evo.top_churn.slice(0, 6).map((m, i) => (
              <tr key={i}>
                <td>{String(m.qualified_name ?? m.path)}</td>
                <td>{String(m.churn ?? "")}</td>
                <td className="meta">{String(m.commit_count ?? "")}</td>
                <td className="meta">{String(m.age_days ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {evo.top_co_change.length > 0 && (
          <div className="meta" style={{ marginTop: 6 }}>
            co-change:{" "}
            {evo.top_co_change
              .slice(0, 5)
              .map((c) => `${c.a?.split(".").pop()} ↔ ${c.b?.split(".").pop()} (${c.count})`)
              .join(", ")}
          </div>
        )}
      </div>
    </>
  );
}

function AssumptionsPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Assumption[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getAssumptions(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Hidden Assumptions</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Risk</th>
              <th>Kind</th>
              <th>Assumption</th>
              <th>Location</th>
              <th>Suggested test</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td>
                  <span
                    className="pill"
                    style={{ borderColor: RISK_COLOR[a.risk ?? "LOW"], color: RISK_COLOR[a.risk ?? "LOW"] }}
                  >
                    {a.risk}
                  </span>
                </td>
                <td className="meta">{a.kind}</td>
                <td>{a.description}</td>
                <td className="meta">{a.location}</td>
                <td className="meta">{a.suggested_test}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ArchaeologyPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Behavior[] | null>(null);
  const [sel, setSel] = useState<string>("");
  useEffect(() => {
    let live = true;
    api.getBehavior(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  const current = rows.find((r) => r.component_qn === sel) ?? rows[0];
  return (
    <>
      <h2>Software Archaeology — Why Does This Exist?</h2>
      <div className="card">
        <select value={current.component_qn ?? ""} onChange={(e) => setSel(e.target.value)}>
          {rows.map((r) => (
            <option key={r.id} value={r.component_qn ?? ""}>
              {r.component_qn}
            </option>
          ))}
        </select>
        <div style={{ marginTop: 8 }}>
          <div>
            <b>Purpose:</b> {current.purpose}{" "}
            <span className={`pill ${current.classification ?? ""}`}>{current.classification}</span>{" "}
            <span className="meta">confidence {current.confidence}</span>
          </div>
          <div className="meta">Historical context: {current.historical_context}</div>
          <div className="meta">Current role: {current.current_role}</div>
          {current.exceptions && current.exceptions.length > 0 && (
            <div className="meta">Raises: {current.exceptions.join(", ")}</div>
          )}
          {current.callees && current.callees.length > 0 && (
            <div className="meta">Calls: {current.callees.join(", ")}</div>
          )}
          {current.tests && current.tests.length > 0 ? (
            <div className="meta">Tested by: {current.tests.join(", ")}</div>
          ) : (
            <div className="meta err">No tests reference this — characterize before changing.</div>
          )}
          {current.likely_invariants && current.likely_invariants.length > 0 && (
            <ul className="meta">
              {current.likely_invariants.map((inv, i) => (
                <li key={i}>{inv}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
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

          {run.state === "COMPLETED" && run.snapshot_id && (
            <>
              <SourceIntel runId={run.id} snapshotId={run.snapshot_id} />
              <GitEvolutionPanel runId={run.id} />
              <ArchitecturePanel runId={run.id} />
              <ArchaeologyPanel runId={run.id} />
              <AssumptionsPanel runId={run.id} />
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
