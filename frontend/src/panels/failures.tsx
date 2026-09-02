import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function FailuresPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Failures"
      load={() => api.getFailures(runId)}
      deps={[runId]}
      isEmpty={(r) => r.length === 0}
      hideWhenAbsent
    >
      {(rows) => (
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
      )}
    </AsyncPanel>
  );
}
