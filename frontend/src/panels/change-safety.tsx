import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { changeSafetyTone } from "../components/tokens";
import { Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function ChangeSafetyPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Change Safety"
      load={() => api.getChangeSafety(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      emptyText="No change-safety assessments for this run."
    >
      {(rows) => (
        <TableScroll>
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
                    <Pill tone={changeSafetyTone(r.risk_category)}>
                      {r.risk_category} · {r.safety_score.toFixed(0)}
                    </Pill>
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
        </TableScroll>
      )}
    </AsyncPanel>
  );
}
