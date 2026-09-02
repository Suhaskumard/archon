import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { severityTone } from "../components/tokens";
import { Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function AssumptionsPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Hidden Assumptions"
      load={() => api.getAssumptions(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      emptyText="No hidden assumptions surfaced for this run."
    >
      {(rows) => (
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
      )}
    </AsyncPanel>
  );
}
