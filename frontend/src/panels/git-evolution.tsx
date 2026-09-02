import { api } from "../api";
import { AsyncPanel } from "../components/async-panel";
import { Sparkline, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function GitEvolutionPanel({ runId }: PanelProps) {
  return (
    <AsyncPanel
      title="Git Evolution"
      load={() => api.getEvolution(runId)}
      deps={[runId]}
      isEmpty={(e) => e.analyzed_commits === 0}
      emptyText="No commit history was analysed for this run."
    >
      {(evo) => (
        <>
          <div className="meta">
            {evo.analyzed_commits} commit(s) over {evo.span_days} day(s) · {evo.authors}{" "}
            author(s)
            {evo.truncated && " · history truncated"}
          </div>
          {evo.timeline.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <Sparkline
                values={evo.timeline.map((t) => t.commits)}
                width={Math.max(evo.timeline.length * 20, 60)}
                ariaLabel={`commits per month over ${evo.timeline.length} months`}
              />
              <div className="meta">
                {evo.timeline[0].month} → {evo.timeline[evo.timeline.length - 1].month}
              </div>
            </div>
          )}
          <TableScroll>
            <table style={{ marginTop: 8 }}>
              <thead>
                <tr>
                  <th>Most-changed module</th>
                  <th>Churn</th>
                  <th>Commits</th>
                  <th>Age (d)</th>
                </tr>
              </thead>
              <tbody>
                {evo.top_churn.slice(0, 6).map((m, i) => (
                  <tr key={i}>
                    <td>{String(m.qualified_name ?? m.path)}</td>
                    <td>{String(m.churn ?? "")}</td>
                    <td className="meta">{String(m.commit_count ?? "")}</td>
                    <td className="meta">{String(m.age_days ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
          {evo.top_co_change.length > 0 && (
            <div className="meta" style={{ marginTop: 6 }}>
              co-change:{" "}
              {evo.top_co_change
                .slice(0, 5)
                .map((c) => `${c.a?.split(".").pop()} ↔ ${c.b?.split(".").pop()} (${c.count})`)
                .join(", ")}
            </div>
          )}
        </>
      )}
    </AsyncPanel>
  );
}
