import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { severityTone } from "../components/tokens";
import { Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function TechnicalDebtPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Technical Debt"
      load={() => api.getTechnicalDebt(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      emptyText="No technical-debt findings for this run."
    >
      {(rows) => (
        <TableScroll>
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
                    <Pill tone={severityTone(f.severity)}>{f.severity}</Pill>
                  </td>
                  <td className="meta">{f.location}</td>
                  <td>{f.evidence}</td>
                  <td className="meta">{f.recommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </AsyncPanel>
  );
}
