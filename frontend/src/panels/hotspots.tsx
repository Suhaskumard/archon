import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { hotspotTone } from "../components/tokens";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function HotspotsPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getHotspots(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Hotspots">
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Score</th>
              <th>Classification</th>
              <th>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => {
              const elevated = (h.reasons.elevated_signals as string[] | undefined) ?? [];
              return (
                <tr key={h.id}>
                  <td>{h.component_qn}</td>
                  <td className="meta">{h.score.toFixed(0)}</td>
                  <td>
                    <Pill tone={hotspotTone(h.classification)}>{h.classification}</Pill>
                  </td>
                  <td className="meta">{elevated.join(", ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}
