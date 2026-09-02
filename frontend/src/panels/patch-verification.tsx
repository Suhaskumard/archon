import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { verdictTone } from "../components/tokens";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

const yn = (b: boolean) => (b ? "yes" : "no");

export function PatchVerificationPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getVerifications(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Patch Verification">
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Original Fixed</th>
              <th>Regression</th>
              <th>Existing Tests</th>
              <th>Characterization</th>
              <th>Applies Cleanly</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="meta">{yn(r.original_failure_fixed)}</td>
                <td className="meta">{yn(r.regression_pass)}</td>
                <td className="meta">{yn(r.existing_tests_pass)}</td>
                <td className="meta">{yn(r.characterization_pass)}</td>
                <td className="meta">{yn(r.applies_cleanly)}</td>
                <td>
                  <Pill tone={verdictTone(r.verdict)}>{r.verdict}</Pill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}
