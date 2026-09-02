import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { severityTone } from "../components/tokens";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function AssumptionsPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getAssumptions(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Hidden Assumptions">
      <TableScroll>
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
                  <Pill tone={severityTone(a.risk ?? "LOW")}>{a.risk}</Pill>
                </td>
                <td className="meta">{a.kind}</td>
                <td>{a.description}</td>
                <td className="meta">{a.location}</td>
                <td className="meta">{a.suggested_test}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}
