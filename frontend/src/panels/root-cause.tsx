import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function RootCauseAnalysisPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getInvestigations(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Root Cause Analysis">
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
    </Panel>
  );
}
