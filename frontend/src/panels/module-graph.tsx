import type { Architecture } from "../api";
import { roleColor } from "../components/tokens";

export function ModuleGraphSvg({ arch }: { arch: Architecture }) {
  const mods = arch.modules;
  if (mods.length === 0) return null;
  const size = 320;
  const r = size / 2 - 34;
  const cx = size / 2;
  const cy = size / 2;
  const pos = new Map<string, { x: number; y: number }>();
  mods.forEach((m, i) => {
    const a = (2 * Math.PI * i) / mods.length - Math.PI / 2;
    pos.set(m.qualified_name, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
  });
  const edges: Array<[string, string]> = [];
  for (const m of mods) for (const dep of m.dependencies) edges.push([m.qualified_name, dep]);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ maxWidth: "100%" }}>
      <defs>
        <marker
          id="arr"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" fill="var(--graph-arrow)" />
        </marker>
      </defs>
      {edges.map(([u, v], i) => {
        const a = pos.get(u)!;
        const b = pos.get(v)!;
        return (
          <line
            key={i}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="var(--graph-edge)"
            strokeWidth={1.2}
            markerEnd="url(#arr)"
          />
        );
      })}
      {mods.map((m) => {
        const p = pos.get(m.qualified_name)!;
        const nodeR = 5 + Math.min(m.fan_in + m.fan_out, 8);
        return (
          <g key={m.id}>
            <circle
              cx={p.x}
              cy={p.y}
              r={nodeR}
              fill={roleColor(m.role)}
              stroke={m.in_cycle ? "var(--graph-cycle)" : "var(--graph-node-stroke)"}
              strokeWidth={m.in_cycle ? 2 : 1}
            />
            <text
              x={p.x}
              y={p.y - nodeR - 4}
              textAnchor="middle"
              fontSize="9"
              fill="var(--text-muted)"
            >
              {m.qualified_name.split(".").slice(-1)[0]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
