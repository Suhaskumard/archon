import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function CharacterizationPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Characterization"
      load={() => api.getCharacterization(runId)}
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
                  <th>Component</th>
                  <th>Inputs tried</th>
                  <th>Baseline hash</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.component_qn ?? r.component_id}</td>
                    <td className="meta">{r.input_spec.length}</td>
                    <td className="meta">
                      <code>{r.baseline_hash.slice(0, 16)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
          <div className="meta" style={{ marginTop: 6 }}>
            A baseline pins today's observed behaviour (including bugs) — it is not a claim
            that the behaviour is correct.
          </div>
        </>
      )}
    </AsyncPanel>
  );
}
