import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel } from "../components/ui";
import type { PanelProps } from "./types";

export function ArchaeologyPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getBehavior(runId), [runId]);
  const [sel, setSel] = useState<string>("");
  if (!rows || rows.length === 0) return null;
  const current = rows.find((r) => r.component_qn === sel) ?? rows[0];
  return (
    <Panel title="Software Archaeology — Why Does This Exist?">
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
    </Panel>
  );
}
