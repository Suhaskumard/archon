import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { patchStateTone } from "../components/tokens";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function SelfHealingPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getPatches(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Self-Healing">
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
    </Panel>
  );
}
