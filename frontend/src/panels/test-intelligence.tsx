import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { severityTone } from "../components/tokens";
import { Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function TestIntelligencePanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Test Intelligence"
      load={() => api.getTestGaps(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      hideWhenAbsent
    >
      {(rows) => (
        <TableScroll>
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
                    <Pill tone={severityTone(r.priority)}>
                      {r.priority} · {r.priority_score.toFixed(0)}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </AsyncPanel>
  );
}
