import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type Architecture,
  type Assumption,
  type Behavior,
  type ChangeAssessment,
  type ChangeImpact,
  type Characterization,
  type Comparison,
  type Component,
  type Evolution,
  type Execution,
  type Failure,
  type Hotspot,
  type Incident,
  type Investigation,
  type LegacyDna,
  type ModernizationRecommendation,
  type ModuleArch,
  type Patch,
  type PatchVerification,
  type Repository,
  type RepositoryUnderstanding,
  type Run,
  type SourceSummary,
  type TechnicalDebtFinding,
  type TestGap,
} from "./api";

const TEST_GAP_PRIORITY_COLOR: Record<string, string> = {
  LOW: "#9aa4b2",
  MEDIUM: "#ffd479",
  HIGH: "#ff9d9d",
  CRITICAL: "#e5484d",
};

const PATCH_STATE_COLOR: Record<string, string> = {
  PROPOSED: "#9aa4b2",
  TESTING: "#ffd479",
  PARTIALLY_VERIFIED: "#ffd479",
  VERIFIED: "#7ee0a2",
  REJECTED: "#ff9d9d",
};

const VERDICT_COLOR: Record<string, string> = {
  VERIFIED: "#7ee0a2",
  REJECTED: "#ff9d9d",
};

const RISK_COLOR: Record<string, string> = {
  HIGH: "#ff9d9d",
  MEDIUM: "#ffd479",
  LOW: "#9aa4b2",
  CRITICAL: "#e5484d",
};

const RISK_CATEGORY_COLOR: Record<string, string> = {
  LOW: "#9aa4b2",
  MODERATE: "#ffd479",
  HIGH: "#ff9d9d",
  CRITICAL: "#e5484d",
};

const HOTSPOT_COLOR: Record<string, string> = {
  STABLE: "#7ee0a2",
  WATCH: "#ffd479",
  RISKY: "#ff9d9d",
  CRITICAL: "#e5484d",
};

const CHANGE_SAFETY_COLOR: Record<string, string> = {
  SAFE: "#7ee0a2",
  CAUTION: "#ffd479",
  RISKY: "#ff9d9d",
  DANGEROUS: "#e5484d",
};

const MODERNIZATION_STRATEGY_COLOR: Record<string, string> = {
  ADD_TESTS: "#7ee0a2",
  EXTRACT_DEPENDENCY: "#ffd479",
  REPLACE_DEPENDENCY: "#ffd479",
  REFACTOR: "#ffd479",
  REWRITE: "#ff9d9d",
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

function UnderstandingPanel({ runId }: { runId: string }) {
  const [data, setData] = useState<RepositoryUnderstanding | null>(null);
  useEffect(() => {
    let live = true;
    api.getUnderstanding(runId).then((d) => live && setData(d)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!data) return null;
  return (
    <>
      <h2>Repository Understanding</h2>
      <div className="card">
        <div className="meta">
          overall score <b>{data.overall_score.toFixed(1)}</b>/100 · confidence{" "}
          {data.confidence.toFixed(2)}
        </div>
        <svg
          viewBox={`0 0 220 ${data.dimensions.length * 18 + 4}`}
          width={320}
          height={data.dimensions.length * 18 + 4}
          style={{ marginTop: 8 }}
        >
          {data.dimensions.map((d, i) => (
            <g key={d.name}>
              <text x={0} y={i * 18 + 11} fontSize="9" fill="#9aa4b2">
                {d.name}
              </text>
              <rect x={70} y={i * 18 + 2} width={(d.score / 100) * 140} height={10} fill="#5b9dff" />
              <text x={214} y={i * 18 + 11} fontSize="8" fill="#9aa4b2" textAnchor="end">
                {d.score.toFixed(0)}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </>
  );
}

function LegacyDnaPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<LegacyDna[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getLegacyDna(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Legacy DNA</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Risk</th>
              <th>Complexity</th>
              <th>Churn</th>
              <th>Coupling</th>
              <th>Coverage</th>
              <th>Assumptions</th>
              <th>Debt</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.component_qn}</td>
                <td>
                  <span
                    className="pill"
                    style={{ borderColor: RISK_CATEGORY_COLOR[r.category], color: RISK_CATEGORY_COLOR[r.category] }}
                  >
                    {r.category} · {r.legacy_risk_score.toFixed(0)}
                  </span>
                </td>
                <td className="meta">{r.complexity?.toFixed(1) ?? "—"}</td>
                <td className="meta">{r.churn?.toFixed(0) ?? "—"}</td>
                <td className="meta">{r.coupling?.toFixed(0) ?? "—"}</td>
                <td className="meta" title={r.coverage_is_proxy ? "proxy — TESTED_BY presence, not measured coverage" : ""}>
                  {r.coverage != null ? r.coverage.toFixed(2) : "—"}
                  {r.coverage_is_proxy && "*"}
                </td>
                <td className="meta">{r.assumption_count}</td>
                <td className="meta">{r.debt_score?.toFixed(2) ?? "—"}</td>
                <td className="meta">{r.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="meta" style={{ marginTop: 6 }}>
          * coverage is a proxy (presence of a test file), not measured coverage — real
          coverage data lands in a later phase.
        </div>
      </div>
    </>
  );
}

function TechnicalDebtPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<TechnicalDebtFinding[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getTechnicalDebt(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Technical Debt</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Category</th>
              <th>Severity</th>
              <th>Location</th>
              <th>Evidence</th>
              <th>Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.id}>
                <td className="meta">{f.category}</td>
                <td>
                  <span
                    className="pill"
                    style={{ borderColor: RISK_COLOR[f.severity], color: RISK_COLOR[f.severity] }}
                  >
                    {f.severity}
                  </span>
                </td>
                <td className="meta">{f.location}</td>
                <td>{f.evidence}</td>
                <td className="meta">{f.recommendation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function HotspotsPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Hotspot[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getHotspots(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Hotspots</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Score</th>
              <th>Classification</th>
              <th>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => {
              const elevated = (h.reasons.elevated_signals as string[] | undefined) ?? [];
              return (
                <tr key={h.id}>
                  <td>{h.component_qn}</td>
                  <td className="meta">{h.score.toFixed(0)}</td>
                  <td>
                    <span
                      className="pill"
                      style={{ borderColor: HOTSPOT_COLOR[h.classification], color: HOTSPOT_COLOR[h.classification] }}
                    >
                      {h.classification}
                    </span>
                  </td>
                  <td className="meta">{elevated.join(", ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ChangeSafetyPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<ChangeAssessment[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getChangeSafety(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Change Safety</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Safety</th>
              <th>Confidence</th>
              <th>Recommended preparation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.component_qn}</td>
                <td>
                  <span
                    className="pill"
                    style={{
                      borderColor: CHANGE_SAFETY_COLOR[r.risk_category],
                      color: CHANGE_SAFETY_COLOR[r.risk_category],
                    }}
                  >
                    {r.risk_category} · {r.safety_score.toFixed(0)}
                  </span>
                </td>
                <td className="meta">{r.confidence.toFixed(2)}</td>
                <td className="meta">
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {r.recommended_preparation.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ChangeImpactPanel({ runId, snapshotId }: { runId: string; snapshotId: string }) {
  const [comps, setComps] = useState<Component[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [impact, setImpact] = useState<ChangeImpact | null>(null);
  const [busy, setBusy] = useState(false);
  const { err, guard } = useError();

  useEffect(() => {
    let live = true;
    api
      .listComponents(snapshotId, "&kind=MODULE")
      .then((c) => {
        if (!live) return;
        setComps(c);
        if (c.length > 0) setSelected(c[0].id);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [snapshotId]);

  const compute = () =>
    guard(async () => {
      if (!selected) return;
      setBusy(true);
      setImpact(null);
      try {
        setImpact(await api.postChangeImpact(runId, selected));
      } finally {
        setBusy(false);
      }
    });

  if (!comps || comps.length === 0) return null;

  return (
    <>
      <h2>Change Impact</h2>
      <div className="card">
        <div className="row">
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {comps.map((c) => (
              <option key={c.id} value={c.id}>
                {c.qualified_name}
              </option>
            ))}
          </select>
          <button className="primary" disabled={busy || !selected} onClick={() => void compute()}>
            {busy ? "Computing…" : "Compute impact"}
          </button>
        </div>
        {err && <p className="err">{err}</p>}
        {impact && (
          <div style={{ marginTop: 8 }}>
            <div className="meta">
              <b>Direct dependents:</b>{" "}
              {impact.direct_dependents.length > 0
                ? impact.direct_dependents.map((d) => d.qualified_name).join(", ")
                : "none"}
            </div>
            <div className="meta">
              <b>Indirect dependents:</b>{" "}
              {impact.indirect_dependents.length > 0
                ? impact.indirect_dependents.map((d) => d.qualified_name).join(", ")
                : "none"}
            </div>
            <div className="meta">
              <b>Callers:</b>{" "}
              {impact.callers.length > 0 ? impact.callers.map((d) => d.qualified_name).join(", ") : "none"}
            </div>
            <div className="meta">
              <b>Related tests:</b>{" "}
              {impact.related_tests.length > 0
                ? impact.related_tests.map((d) => d.qualified_name).join(", ")
                : "none found"}
            </div>
            <div className="meta">
              <b>Historical co-changes:</b>{" "}
              {impact.historical_co_changes.length > 0
                ? impact.historical_co_changes
                    .map((d) => `${d.qualified_name} (${d.count})`)
                    .join(", ")
                : "none"}
            </div>
            <div className="meta">
              <b>External integrations:</b>{" "}
              {impact.external_integrations.length > 0
                ? impact.external_integrations.map((d) => d.target_name).join(", ")
                : "none"}
            </div>
            <div style={{ marginTop: 8 }}>
              <b>What could break</b>
              <ul className="meta">
                {impact.potential_impact.what_could_break.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
              <b>Which tests to run</b>
              <ul className="meta">
                {impact.potential_impact.tests_to_run.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
              <b>What to do first</b>
              <ul className="meta">
                {impact.potential_impact.what_to_do_first.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function TestExecutionPanel({ runId }: { runId: string }) {
  const [executions, setExecutions] = useState<Execution[] | null>(null);
  const [testCount, setTestCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    api.getExecutions(runId).then((r) => live && setExecutions(r)).catch(() => undefined);
    api.getTests(runId).then((r) => live && setTestCount(r.length)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!executions || executions.length === 0) return null;
  return (
    <>
      <h2>Test Execution</h2>
      <div className="card">
        {testCount != null && (
          <div className="meta" style={{ marginBottom: 8 }}>
            {testCount} existing test(s) discovered
          </div>
        )}
        <table>
          <thead>
            <tr>
              <th>Kind</th>
              <th>Command</th>
              <th>Result</th>
              <th>Passed</th>
              <th>Failed</th>
              <th>Errors</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {executions.map((e) => {
              const ok = e.exit_code === 0 && !e.timed_out;
              return (
                <tr key={e.id}>
                  <td className="meta">{e.kind}</td>
                  <td className="meta">{e.command.join(" ").slice(0, 60)}</td>
                  <td>
                    <span
                      className="pill"
                      style={{
                        borderColor: ok ? "#7ee0a2" : "#ff9d9d",
                        color: ok ? "#7ee0a2" : "#ff9d9d",
                      }}
                    >
                      {e.timed_out ? "TIMED OUT" : `exit ${e.exit_code}`}
                    </span>
                  </td>
                  <td>{e.passed}</td>
                  <td>{e.failed}</td>
                  <td>{e.errors}</td>
                  <td className="meta">{e.duration_ms} ms</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function CharacterizationPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Characterization[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getCharacterization(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Characterization</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Inputs tried</th>
              <th>Baseline hash</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.component_qn ?? r.component_id}</td>
                <td className="meta">{r.input_spec.length}</td>
                <td className="meta">
                  <code>{r.baseline_hash.slice(0, 16)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="meta" style={{ marginTop: 6 }}>
          A baseline pins today's observed behaviour (including bugs) — it is not a
          claim that the behaviour is correct.
        </div>
      </div>
    </>
  );
}

function TestIntelligencePanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<TestGap[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getTestGaps(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Test Intelligence</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Kind</th>
              <th>Coverage</th>
              <th>Legacy Risk</th>
              <th>Change Safety</th>
              <th>Priority</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.component_qn ?? r.component_id}</td>
                <td className="meta">{r.kind}</td>
                <td className="meta">{(r.coverage_pct * 100).toFixed(0)}%</td>
                <td className="meta">{r.legacy_risk_score?.toFixed(0) ?? "—"}</td>
                <td className="meta">{r.change_safety_score?.toFixed(0) ?? "—"}</td>
                <td>
                  <span
                    className="pill"
                    style={{
                      borderColor: TEST_GAP_PRIORITY_COLOR[r.priority],
                      color: TEST_GAP_PRIORITY_COLOR[r.priority],
                    }}
                  >
                    {r.priority} · {r.priority_score.toFixed(0)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function FailuresPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Failure[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getFailures(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Failures</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Test</th>
              <th>Exception</th>
              <th>Message</th>
              <th>Reproducible</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{r.test_identifier}</td>
                <td className="meta">{r.exception_type}</td>
                <td className="meta">{r.message}</td>
                <td>
                  <span
                    className="pill"
                    style={{
                      borderColor: r.reproducible ? "#ff9d9d" : "#9aa4b2",
                      color: r.reproducible ? "#ff9d9d" : "#9aa4b2",
                    }}
                  >
                    {r.reproducible ? "reproducible" : "intermittent"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function RootCauseAnalysisPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Investigation[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getInvestigations(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Root Cause Analysis</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Summary</th>
              <th>Confidence</th>
              <th>Recommended Verification</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.summary}</td>
                <td className="meta">{r.confidence.toFixed(2)}</td>
                <td className="meta">{r.recommended_verification.join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SelfHealingPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Patch[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getPatches(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Self-Healing</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Lines +/-</th>
              <th>Rank</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{r.strategy}</td>
                <td className="meta">+{r.lines_added} / -{r.lines_removed}</td>
                <td className="meta">{r.rank_score?.toFixed(0) ?? "—"}</td>
                <td>
                  <span
                    className="pill"
                    style={{ borderColor: PATCH_STATE_COLOR[r.state], color: PATCH_STATE_COLOR[r.state] }}
                  >
                    {r.state}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function PatchVerificationPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<PatchVerification[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getVerifications(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Patch Verification</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Original Fixed</th>
              <th>Regression</th>
              <th>Existing Tests</th>
              <th>Characterization</th>
              <th>Applies Cleanly</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{r.original_failure_fixed ? "yes" : "no"}</td>
                <td className="meta">{r.regression_pass ? "yes" : "no"}</td>
                <td className="meta">{r.existing_tests_pass ? "yes" : "no"}</td>
                <td className="meta">{r.characterization_pass ? "yes" : "no"}</td>
                <td className="meta">{r.applies_cleanly ? "yes" : "no"}</td>
                <td>
                  <span
                    className="pill"
                    style={{ borderColor: VERDICT_COLOR[r.verdict], color: VERDICT_COLOR[r.verdict] }}
                  >
                    {r.verdict}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function IncidentMemoryPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<Incident[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getIncidents(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h2>Incident Memory</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Failure</th>
              <th>Root Cause</th>
              <th>Signature</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{r.failure_summary}</td>
                <td>{r.root_cause}</td>
                <td className="meta">
                  <code>{r.failure_signature}</code>
                </td>
                <td className="meta">{r.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="meta" style={{ marginTop: 6 }}>
          Recorded on a VERIFIED patch — retrieved by future investigations of a
          similar failure as historical context, cited but never overriding fresh
          evidence.
        </div>
      </div>
    </>
  );
}

function ModernizationPanel({ runId }: { runId: string }) {
  const [rows, setRows] = useState<ModernizationRecommendation[] | null>(null);
  useEffect(() => {
    let live = true;
    api.getModernization(runId).then((r) => live && setRows(r)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId]);
  if (!rows || rows.length === 0) return null;
  const conf = rows[0].confidence;
  const cls = rows[0].classification;
  return (
    <>
      <h2>Modernization</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Target</th>
              <th>Strategy</th>
              <th>Risk</th>
              <th>Effort</th>
              <th>Impact</th>
              <th>Rationale</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{r.order_index + 1}</td>
                <td className="meta">{r.target}</td>
                <td>
                  <span
                    className="pill"
                    style={{
                      borderColor: MODERNIZATION_STRATEGY_COLOR[r.strategy],
                      color: MODERNIZATION_STRATEGY_COLOR[r.strategy],
                    }}
                  >
                    {r.strategy}
                  </span>
                </td>
                <td className="meta">{r.risk}</td>
                <td className="meta">{r.effort}</td>
                <td className="meta">{r.impact}</td>
                <td className="meta">{r.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="meta" style={{ marginTop: 6 }}>
          Ordered safest-first from the dependency + change-safety graph — dependencies
          before dependents, tests before any structural change.{" "}
          {cls && <span className={`pill ${cls}`}>{cls}</span>} confidence {conf.toFixed(2)}
        </div>
      </div>
    </>
  );
}

function signed(n: number | null | undefined, digits = 2): string {
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;
}

function DeltaCell({ value, goodWhenNegative = true }: { value: number; goodWhenNegative?: boolean }) {
  const good = goodWhenNegative ? value < 0 : value > 0;
  const color = Math.abs(value) < 0.05 ? "#9aa4b2" : good ? "#7ee0a2" : "#ff9d9d";
  return <td className="meta" style={{ color }}>{signed(value)}</td>;
}

function RepositoryComparisonPanel({ runId, repoId }: { runId: string; repoId: string }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [baseId, setBaseId] = useState<string>("");
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const { err, guard } = useError();

  useEffect(() => {
    let live = true;
    api
      .listRuns(repoId)
      .then((rs) => {
        if (!live) return;
        const usable = rs.filter(
          (r) => r.id !== runId && r.snapshot_id && r.last_completed_stage,
        );
        setRuns(usable);
        if (usable.length > 0) setBaseId(usable[0].id);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [repoId, runId]);

  const compare = () =>
    guard(async () => {
      if (!baseId) return;
      setBusy(true);
      setCmp(null);
      try {
        setCmp(await api.createComparison(repoId, baseId, runId));
      } finally {
        setBusy(false);
      }
    });

  if (!runs || runs.length === 0) return null;
  const s = cmp?.summary;
  const rep = cmp?.report;

  return (
    <>
      <h2>Repository Comparison</h2>
      <div className="card">
        <div className="row">
          <span className="meta">baseline run</span>
          <select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.snapshot?.commit_sha?.slice(0, 10) ?? r.id} · {r.state} ·{" "}
                {new Date(r.created_at).toLocaleString()}
              </option>
            ))}
          </select>
          <button className="primary" disabled={busy || !baseId} onClick={() => void compare()}>
            {busy ? "Comparing…" : "Compare with this run"}
          </button>
        </div>
        {err && <p className="err">{err}</p>}

        {s && rep && (
          <div style={{ marginTop: 8 }}>
            <div className="row" style={{ gap: 16 }}>
              <span className="meta">
                modules <b>+{s.modules_added}</b> / <b>−{s.modules_removed}</b>
              </span>
              <span className="meta">
                dependencies <b>+{s.dependencies_added}</b> / <b>−{s.dependencies_removed}</b>
              </span>
              <span className="meta">
                debt findings <b>+{s.debt_findings_added}</b> / <b>−{s.debt_findings_resolved}</b>
              </span>
              <span className="meta">mean legacy-risk Δ <b>{signed(s.mean_legacy_risk_delta)}</b></span>
              <span className="meta">mean change-safety Δ <b>{signed(s.mean_change_safety_delta)}</b></span>
              <span className="meta">mean coverage Δ* <b>{signed(s.mean_coverage_delta)}</b></span>
            </div>

            {(rep.architecture.modules_added.length > 0 ||
              rep.architecture.modules_removed.length > 0) && (
              <div className="meta" style={{ marginTop: 8 }}>
                <b>Modules added:</b>{" "}
                {rep.architecture.modules_added.join(", ") || "none"} · <b>removed:</b>{" "}
                {rep.architecture.modules_removed.join(", ") || "none"}
              </div>
            )}

            {rep.legacy_dna.changed.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div className="meta"><b>Legacy risk movement</b></div>
                <table>
                  <thead>
                    <tr>
                      <th>Component</th><th>Base</th><th>Head</th><th>Δ</th><th>Category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rep.legacy_dna.changed.map((c) => (
                      <tr key={c.qualified_name}>
                        <td className="meta">{c.qualified_name}</td>
                        <td className="meta">{c.base_score.toFixed(1)}</td>
                        <td className="meta">{c.head_score.toFixed(1)}</td>
                        <DeltaCell value={c.delta} />
                        <td className="meta">
                          {c.base_category} →{" "}
                          <span
                            style={{ color: RISK_CATEGORY_COLOR[c.head_category ?? ""] ?? undefined }}
                          >
                            {c.head_category}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {rep.change_safety.changed.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div className="meta"><b>Change safety movement</b></div>
                <table>
                  <thead>
                    <tr>
                      <th>Component</th><th>Base</th><th>Head</th><th>Δ</th><th>Category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rep.change_safety.changed.map((c) => (
                      <tr key={c.qualified_name}>
                        <td className="meta">{c.qualified_name}</td>
                        <td className="meta">{c.base_score.toFixed(1)}</td>
                        <td className="meta">{c.head_score.toFixed(1)}</td>
                        <DeltaCell value={c.delta} goodWhenNegative={false} />
                        <td className="meta">
                          {c.base_category} →{" "}
                          <span
                            style={{ color: CHANGE_SAFETY_COLOR[c.head_category ?? ""] ?? undefined }}
                          >
                            {c.head_category}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {(rep.technical_debt.findings_added.length > 0 ||
              rep.technical_debt.findings_resolved.length > 0) && (
              <div className="meta" style={{ marginTop: 8 }}>
                <b>Debt findings added:</b>{" "}
                {rep.technical_debt.findings_added
                  .map((f) => `${f.qualified_name} (${f.category})`)
                  .join(", ") || "none"}
                <br />
                <b>Debt findings resolved:</b>{" "}
                {rep.technical_debt.findings_resolved
                  .map((f) => `${f.qualified_name} (${f.category})`)
                  .join(", ") || "none"}
              </div>
            )}

            <div className="meta" style={{ marginTop: 6 }}>
              * coverage is the Legacy-DNA proxy value, not a measured run. Full delta
              saved as artifact <code>{cmp?.report_artifact_id ?? "—"}</code>.
            </div>
          </div>
        )}
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
              <UnderstandingPanel runId={run.id} />
              <LegacyDnaPanel runId={run.id} />
              <TechnicalDebtPanel runId={run.id} />
              <HotspotsPanel runId={run.id} />
              <ChangeSafetyPanel runId={run.id} />
              <ChangeImpactPanel runId={run.id} snapshotId={run.snapshot_id} />
              <TestExecutionPanel runId={run.id} />
              <CharacterizationPanel runId={run.id} />
              <TestIntelligencePanel runId={run.id} />
              <FailuresPanel runId={run.id} />
              <RootCauseAnalysisPanel runId={run.id} />
              <SelfHealingPanel runId={run.id} />
              <PatchVerificationPanel runId={run.id} />
              <IncidentMemoryPanel runId={run.id} />
              <ModernizationPanel runId={run.id} />
              <RepositoryComparisonPanel runId={run.id} repoId={run.repository_id} />
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
