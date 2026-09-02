import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function GitEvolutionPanel({ runId }: PanelProps) {
  const { data: evo } = useAsync(() => api.getEvolution(runId), [runId]);
  if (!evo) return null;
  const maxC = Math.max(1, ...evo.timeline.map((t) => t.commits));
  return (
    <Panel title="Git Evolution">
      <div className="meta">
        {evo.analyzed_commits} commit(s) over {evo.span_days} day(s) · {evo.authors} author(s)
        {evo.truncated && " · history truncated"}
      </div>
      <svg
        viewBox={`0 0 ${Math.max(evo.timeline.length * 26, 40)} 60`}
        height={60}
        style={{ marginTop: 6 }}
      >
        {evo.timeline.map((t, i) => (
          <g key={t.month}>
            <rect
              x={i * 26 + 4}
              y={54 - (t.commits / maxC) * 44}
              width={16}
              height={(t.commits / maxC) * 44}
              fill="var(--accent)"
            />
            <text x={i * 26 + 12} y={60} textAnchor="middle" fontSize="7" fill="var(--text-muted)">
              {t.month.slice(2)}
            </text>
          </g>
        ))}
      </svg>
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
    </Panel>
  );
}
