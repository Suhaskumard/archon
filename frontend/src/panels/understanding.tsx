import { api } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel } from "../components/ui";
import type { PanelProps } from "./types";

export function UnderstandingPanel({ runId }: PanelProps) {
  const { data } = useAsync(() => api.getUnderstanding(runId), [runId]);
  if (!data) return null;
  return (
    <Panel title="Repository Understanding">
      <div className="meta">
        overall score <b>{data.overall_score.toFixed(1)}</b>/100 · confidence{" "}
        {data.confidence.toFixed(2)}
      </div>
      <svg
        viewBox={`0 0 220 ${data.dimensions.length * 18 + 4}`}
        width={320}
        height={data.dimensions.length * 18 + 4}
        style={{ marginTop: 8 }}
      >
        {data.dimensions.map((d, i) => (
          <g key={d.name}>
            <text x={0} y={i * 18 + 11} fontSize="9" fill="var(--text-muted)">
              {d.name}
            </text>
            <rect
              x={70}
              y={i * 18 + 2}
              width={(d.score / 100) * 140}
              height={10}
              fill="var(--accent)"
            />
            <text
              x={214}
              y={i * 18 + 11}
              fontSize="8"
              fill="var(--text-muted)"
              textAnchor="end"
            >
              {d.score.toFixed(0)}
            </text>
          </g>
        ))}
      </svg>
    </Panel>
  );
}
