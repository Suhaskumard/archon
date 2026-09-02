import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function IncidentMemoryPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getIncidents(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Incident Memory">
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Failure</th>
              <th>Root Cause</th>
              <th>Signature</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{r.failure_summary}</td>
                <td>{r.root_cause}</td>
                <td className="meta">
                  <code>{r.failure_signature}</code>
                </td>
                <td className="meta">{r.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <div className="meta" style={{ marginTop: 6 }}>
        Recorded on a VERIFIED patch — retrieved by future investigations of a similar failure
        as historical context, cited but never overriding fresh evidence.
      </div>
    </Panel>
  );
}
