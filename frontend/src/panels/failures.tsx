import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function FailuresPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getFailures(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Failures">
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Test</th>
              <th>Exception</th>
              <th>Message</th>
              <th>Reproducible</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{r.test_identifier}</td>
                <td className="meta">{r.exception_type}</td>
                <td className="meta">{r.message}</td>
                <td>
                  <Pill tone={r.reproducible ? "bad" : "neutral"}>
                    {r.reproducible ? "reproducible" : "intermittent"}
                  </Pill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}
