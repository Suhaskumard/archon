import { useMemo, useRef, useState } from "react";
import type { Architecture } from "../api";
import { roleColor } from "../components/tokens";
import { GRAPH_SIZE, layoutModules } from "./graph-layout";

interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}
const RESET: View = { x: 0, y: 0, w: GRAPH_SIZE, h: GRAPH_SIZE };

export function ModuleGraphSvg({ arch }: { arch: Architecture }) {
  const mods = arch.modules;
  const pos = useMemo(() => layoutModules(mods), [mods]);
  const [view, setView] = useState<View>(RESET);
  const drag = useRef<{ px: number; py: number } | null>(null);

  if (mods.length === 0) return null;

  const edges: Array<[string, string]> = [];
  for (const m of mods) for (const dep of m.dependencies) edges.push([m.qualified_name, dep]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.1 : 1 / 1.1;
    const w = Math.min(GRAPH_SIZE * 3, Math.max(GRAPH_SIZE * 0.3, view.w * factor));
    const h = w;
    // zoom about the svg centre
    setView({ x: view.x + (view.w - w) / 2, y: view.y + (view.h - h) / 2, w, h });
  };
  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { px: e.clientX, py: e.clientY };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const k = view.w / GRAPH_SIZE;
    setView((v) => ({
      ...v,
      x: v.x - (e.clientX - drag.current!.px) * k,
      y: v.y - (e.clientY - drag.current!.py) * k,
    }));
    drag.current = { px: e.clientX, py: e.clientY };
  };
  const endDrag = () => {
    drag.current = null;
  };

  const roles = [...new Set(mods.map((m) => m.role ?? "unknown"))];

  return (
    <div>
      <svg
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        width={GRAPH_SIZE}
        height={GRAPH_SIZE}
        style={{ maxWidth: "100%", touchAction: "none", cursor: drag.current ? "grabbing" : "grab" }}
        role="img"
        aria-label={`module dependency graph — ${mods.length} modules, ${edges.length} edges`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
      >
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
          const a = pos.get(u);
          const b = pos.get(v);
          if (!a || !b) return null;
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
          const p = pos.get(m.qualified_name);
          if (!p) return null;
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
              >
                <title>{m.qualified_name}</title>
              </circle>
              <text x={p.x} y={p.y - nodeR - 4} textAnchor="middle" fontSize="9" fill="var(--text-muted)">
                {m.qualified_name.split(".").slice(-1)[0]}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="row" style={{ gap: 12, marginTop: 4 }}>
        <button className="linklike" onClick={() => setView(RESET)}>
          reset view
        </button>
        <ul className="legend">
          {roles.map((r) => (
            <li key={r}>
              <span className="legend-dot" style={{ background: roleColor(r) }} /> {r}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
