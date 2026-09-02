import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { riskCategoryTone } from "../components/tokens";
import { Panel, Pill, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function LegacyDnaPanel({ runId }: PanelProps) {
  const { data: rows } = useAsync(() => api.getLegacyDna(runId), [runId]);
  if (!rows || rows.length === 0) return null;
  return (
    <Panel title="Legacy DNA">
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Risk</th>
              <th>Complexity</th>
              <th>Churn</th>
              <th>Coupling</th>
              <th>Coverage</th>
              <th>Assumptions</th>
              <th>Debt</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.component_qn}</td>
                <td>
                  <Pill tone={riskCategoryTone(r.category)}>
                    {r.category} · {r.legacy_risk_score.toFixed(0)}
                  </Pill>
                </td>
                <td className="meta">{r.complexity?.toFixed(1) ?? "—"}</td>
                <td className="meta">{r.churn?.toFixed(0) ?? "—"}</td>
                <td className="meta">{r.coupling?.toFixed(0) ?? "—"}</td>
                <td
                  className="meta"
                  title={
                    r.coverage_is_proxy
                      ? "proxy — TESTED_BY presence, not measured coverage"
                      : ""
                  }
                >
                  {r.coverage != null ? r.coverage.toFixed(2) : "—"}
                  {r.coverage_is_proxy && "*"}
                </td>
                <td className="meta">{r.assumption_count}</td>
                <td className="meta">{r.debt_score?.toFixed(2) ?? "—"}</td>
                <td className="meta">{r.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <div className="meta" style={{ marginTop: 6 }}>
        * coverage is a proxy (presence of a test file), not measured coverage — a measured
        run (FULL mode) replaces it with a real fraction.
      </div>
    </Panel>
  );
}
