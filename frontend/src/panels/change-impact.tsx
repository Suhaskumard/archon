import { useEffect, useState } from "react";
import { AsyncPanel } from "../components/async-panel";
import { api, type ChangeImpact, type Component } from "../api";
import { useErrorGuard } from "../lib/hooks";
import type { PanelProps } from "./types";

export function ChangeImpactPanel({ runId, snapshotId }: PanelProps) {
  return (
    <AsyncPanel
      title="Change Impact"
      load={() => api.listComponents(snapshotId, "&kind=MODULE")}
      deps={[snapshotId]}
      isEmpty={(c) => c.length === 0}
      emptyText="No modules to analyse for change impact."
    >
      {(comps) => <ChangeImpactBody comps={comps} runId={runId} />}
    </AsyncPanel>
  );
}

function ChangeImpactBody({ comps, runId }: { comps: Component[]; runId: string }) {
  const [selected, setSelected] = useState<string>("");
  const [impact, setImpact] = useState<ChangeImpact | null>(null);
  const [busy, setBusy] = useState(false);
  const { err, guard } = useErrorGuard();

  useEffect(() => {
    if (comps.length > 0 && !selected) setSelected(comps[0].id);
  }, [comps, selected]);

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

  return (
    <>
      <div className="row">
        <label className="visually-hidden" htmlFor="ci-select">
          component
        </label>
        <select id="ci-select" value={selected} onChange={(e) => setSelected(e.target.value)}>
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
      {err && (
        <p className="err" role="alert">
          {err}
        </p>
      )}
      {impact && <ImpactDetail impact={impact} />}
    </>
  );
}

function names(xs: { qualified_name: string }[]): string {
  return xs.length > 0 ? xs.map((d) => d.qualified_name).join(", ") : "none";
}

function ImpactDetail({ impact }: { impact: ChangeImpact }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div className="meta">
        <b>Direct dependents:</b> {names(impact.direct_dependents)}
      </div>
      <div className="meta">
        <b>Indirect dependents:</b> {names(impact.indirect_dependents)}
      </div>
      <div className="meta">
        <b>Callers:</b> {names(impact.callers)}
      </div>
      <div className="meta">
        <b>Related tests:</b>{" "}
        {impact.related_tests.length > 0 ? names(impact.related_tests) : "none found"}
      </div>
      <div className="meta">
        <b>Historical co-changes:</b>{" "}
        {impact.historical_co_changes.length > 0
          ? impact.historical_co_changes.map((d) => `${d.qualified_name} (${d.count})`).join(", ")
          : "none"}
      </div>
      <div className="meta">
        <b>External integrations:</b>{" "}
        {impact.external_integrations.length > 0
          ? impact.external_integrations.map((d) => d.target_name).join(", ")
          : "none"}
      </div>
      <div style={{ marginTop: 8 }}>
        {(
          [
            ["What could break", impact.potential_impact.what_could_break],
            ["Which tests to run", impact.potential_impact.tests_to_run],
            ["What to do first", impact.potential_impact.what_to_do_first],
          ] as const
        ).map(([label, lines]) => (
          <div key={label}>
            <b>{label}</b>
            <ul className="meta">
              {lines.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
