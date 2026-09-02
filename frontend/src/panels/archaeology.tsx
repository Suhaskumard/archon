import { useState } from "react";
import { AsyncPanel } from "../components/async-panel";
import { api, type Behavior } from "../api";
import type { PanelProps } from "./types";

export function ArchaeologyPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Software Archaeology — Why Does This Exist?"
      load={() => api.getBehavior(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      emptyText="No behavioural narratives for this run."
    >
      {(rows) => <ArchaeologyBody rows={rows} />}
    </AsyncPanel>
  );
}

function ArchaeologyBody({ rows }: { rows: Behavior[] }) {
  const [sel, setSel] = useState<string>("");
  const current = rows.find((r) => r.component_qn === sel) ?? rows[0];
  return (
    <>
      <label className="visually-hidden" htmlFor="arch-select">
        component
      </label>
      <select
        id="arch-select"
        value={current.component_qn ?? ""}
        onChange={(e) => setSel(e.target.value)}
      >
        {rows.map((r) => (
          <option key={r.id} value={r.component_qn ?? ""}>
            {r.component_qn}
          </option>
        ))}
      </select>
      <div style={{ marginTop: 8 }}>
        <div>
          <b>Purpose:</b> {current.purpose}{" "}
          <span className={`pill ${current.classification ?? ""}`}>
            {current.classification}
          </span>{" "}
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
          <div className="meta err">
            No tests reference this — characterize before changing.
          </div>
        )}
        {current.likely_invariants && current.likely_invariants.length > 0 && (
          <ul className="meta">
            {current.likely_invariants.map((inv, i) => (
              <li key={i}>{inv}</li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
