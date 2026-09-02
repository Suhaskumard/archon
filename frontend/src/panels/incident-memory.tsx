import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function IncidentMemoryPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Incident Memory"
      load={() => api.getIncidents(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      hideWhenAbsent
    >
      {(rows) => (
        <>
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
            Recorded on a VERIFIED patch — retrieved by future investigations of a similar
            failure as historical context, cited but never overriding fresh evidence.
          </div>
        </>
      )}
    </AsyncPanel>
  );
}
