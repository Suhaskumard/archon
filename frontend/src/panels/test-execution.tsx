import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function TestExecutionPanel({ runId }: PanelProps) {
  const { data: executions } = useAsync(() => api.getExecutions(runId), [runId]);
  const { data: tests } = useAsync(() => api.getTests(runId), [runId]);
  if (!executions || executions.length === 0) return null;
  return (
    <Panel title="Test Execution">
      {tests != null && (
        <div className="meta" style={{ marginBottom: 8 }}>
          {tests.length} existing test(s) discovered
        </div>
      )}
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Kind</th>
              <th>Command</th>
              <th>Result</th>
              <th>Passed</th>
              <th>Failed</th>
              <th>Errors</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {executions.map((e) => {
              const ok = e.exit_code === 0 && !e.timed_out;
              return (
                <tr key={e.id}>
                  <td className="meta">{e.kind}</td>
                  <td className="meta">{e.command.join(" ").slice(0, 60)}</td>
                  <td>
                    <Pill tone={ok ? "good" : "bad"}>
                      {e.timed_out ? "TIMED OUT" : `exit ${e.exit_code}`}
                    </Pill>
                  </td>
                  <td>{e.passed}</td>
                  <td>{e.failed}</td>
                  <td>{e.errors}</td>
                  <td className="meta">{e.duration_ms} ms</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}
