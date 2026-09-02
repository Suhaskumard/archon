import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function RootCauseAnalysisPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Root Cause Analysis"
      load={() => api.getInvestigations(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      hideWhenAbsent
    >
      {(rows) => (
        <TableScroll>
          <table>
            <thead>
              <tr>
                <th>Summary</th>
                <th>Confidence</th>
                <th>Recommended Verification</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.summary}</td>
                  <td className="meta">{r.confidence.toFixed(2)}</td>
                  <td className="meta">{r.recommended_verification.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </AsyncPanel>
  );
}
