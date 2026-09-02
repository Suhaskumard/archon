import { useEffect, useState } from "react";
import { api, type Comparison, type Run } from "../api";
import { useAsync, useErrorGuard } from "../lib/hooks";
import { changeSafetyTone, riskCategoryTone } from "../components/tokens";
import { Panel, signed } from "../components/ui";
import { MovementTable } from "./comparison-movement";
import type { PanelProps } from "./types";

export function RepositoryComparisonPanel({ runId, repoId }: PanelProps) {
  const { data: allRuns } = useAsync(() => api.listRuns(repoId), [repoId]);
  const [baseId, setBaseId] = useState<string>("");
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const { err, guard } = useErrorGuard();

  const runs: Run[] = (allRuns ?? []).filter(
    (r) => r.id !== runId && r.snapshot_id && r.last_completed_stage,
  );
  useEffect(() => {
    if (baseId === "" && runs.length > 0) setBaseId(runs[0].id);
  }, [baseId, runs]);

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

  if (runs.length === 0) return null;
  const s = cmp?.summary;
  const rep = cmp?.report;

  return (
    <Panel title="Repository Comparison">
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
            <span className="meta">
              mean legacy-risk Δ <b>{signed(s.mean_legacy_risk_delta)}</b>
            </span>
            <span className="meta">
              mean change-safety Δ <b>{signed(s.mean_change_safety_delta)}</b>
            </span>
            <span className="meta">
              mean coverage Δ* <b>{signed(s.mean_coverage_delta)}</b>
            </span>
          </div>

          {(rep.architecture.modules_added.length > 0 ||
            rep.architecture.modules_removed.length > 0) && (
            <div className="meta" style={{ marginTop: 8 }}>
              <b>Modules added:</b> {rep.architecture.modules_added.join(", ") || "none"} ·{" "}
              <b>removed:</b> {rep.architecture.modules_removed.join(", ") || "none"}
            </div>
          )}

          <MovementTable
            title="Legacy risk movement"
            rows={rep.legacy_dna.changed}
            tone={riskCategoryTone}
            goodWhenNegative
          />
          <MovementTable
            title="Change safety movement"
            rows={rep.change_safety.changed}
            tone={changeSafetyTone}
            goodWhenNegative={false}
          />

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
            * coverage is the Legacy-DNA proxy value, not a measured run. Full delta saved as
            artifact <code>{cmp?.report_artifact_id ?? "—"}</code>.
          </div>
        </div>
      )}
    </Panel>
  );
}
