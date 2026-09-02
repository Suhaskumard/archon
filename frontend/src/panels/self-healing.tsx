import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { patchStateTone } from "../components/tokens";
import { Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function SelfHealingPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Self-Healing"
      load={() => api.getPatches(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      hideWhenAbsent
    >
      {(rows) => (
        <TableScroll>
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Lines +/-</th>
                <th>Rank</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="meta">{r.strategy}</td>
                  <td className="meta">
                    +{r.lines_added} / -{r.lines_removed}
                  </td>
                  <td className="meta">{r.rank_score?.toFixed(0) ?? "—"}</td>
                  <td>
                    <Pill tone={patchStateTone(r.state)}>{r.state}</Pill>
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
