// Deterministic role-grouped radial layout for the module dependency graph.
// Pure function of the module list so tests can assert exact positions.

import type { ModuleArch } from "../api";

export const GRAPH_SIZE = 360;

// Outer rings are the "entry" roles, inner rings the "leaf" roles.
const ROLE_RING: Record<string, number> = {
  entrypoint: 0,
  api: 0,
  cli: 0,
  domain: 1,
  model: 1,
  io: 2,
  util: 2,
  config: 2,
  test: 3,
  unknown: 3,
};

export interface Point {
  x: number;
  y: number;
}

export function layoutModules(mods: ModuleArch[]): Map<string, Point> {
  const cx = GRAPH_SIZE / 2;
  const cy = GRAPH_SIZE / 2;
  const maxR = GRAPH_SIZE / 2 - 36;

  // bucket by ring, stable order = input order
  const rings = new Map<number, ModuleArch[]>();
  for (const m of mods) {
    const ring = ROLE_RING[m.role ?? "unknown"] ?? 3;
    (rings.get(ring) ?? rings.set(ring, []).get(ring)!).push(m);
  }

  const ringCount = Math.max(...rings.keys(), 0) + 1;
  const pos = new Map<string, Point>();
  for (const [ring, members] of [...rings.entries()].sort((a, b) => a[0] - b[0])) {
    const radius = ringCount === 1 ? 0 : (maxR * (ring + 1)) / ringCount;
    members.forEach((m, i) => {
      const angle = (2 * Math.PI * i) / members.length - Math.PI / 2 + ring * 0.4;
      pos.set(m.qualified_name, {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      });
    });
  }
  return pos;
}
