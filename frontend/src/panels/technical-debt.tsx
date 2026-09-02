import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { severityTone } from "../components/tokens";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function TechnicalDebtPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getTechnicalDebt(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Technical Debt">
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
    </Panel>
  );
}
