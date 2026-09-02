import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { modernizationStrategyTone } from "../components/tokens";
import { Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function ModernizationPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Modernization"
      load={() => api.getModernization(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      hideWhenAbsent
    >
      {(rows) => {
        const conf = rows[0].confidence;
        const cls = rows[0].classification;
        return (
          <>
            <TableScroll>
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Target</th>
                    <th>Strategy</th>
                    <th>Risk</th>
                    <th>Effort</th>
                    <th>Impact</th>
                    <th>Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
                      <td className="meta">{r.order_index + 1}</td>
                      <td className="meta">{r.target}</td>
                      <td>
                        <Pill tone={modernizationStrategyTone(r.strategy)}>{r.strategy}</Pill>
                      </td>
                      <td className="meta">{r.risk}</td>
                      <td className="meta">{r.effort}</td>
                      <td className="meta">{r.impact}</td>
                      <td className="meta">{r.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
            <div className="meta" style={{ marginTop: 6 }}>
              Ordered safest-first from the dependency + change-safety graph — dependencies
              before dependents, tests before any structural change.{" "}
              {cls && <span className={`pill ${cls}`}>{cls}</span>} confidence{" "}
              {conf.toFixed(2)}
            </div>
          </>
        );
      }}
    </AsyncPanel>
  );
}
