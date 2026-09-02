import { api, type ModuleArch } from "../api";
import { useAsync } from "../lib/hooks";
import { roleColor } from "../components/tokens";
import { Panel, TableScroll } from "../components/ui";
import { ModuleGraphSvg } from "./module-graph";
import type { PanelProps } from "./types";

export function ArchitecturePanel({ runId }: PanelProps) {
  const { data: arch, error } = useAsync(() => api.getArchitecture(runId), [runId]);

  if (error) return null; // not reconstructed for this run (e.g. INGEST_ONLY)
  if (!arch || !arch.reconstructed) return null;

  const modules: ModuleArch[] = [...arch.modules].sort(
    (a, b) => b.betweenness_centrality - a.betweenness_centrality || b.fan_in - a.fan_in,
  );

  return (
    <Panel title="Architecture">
      <div className="row" style={{ gap: 12 }}>
        {Object.entries(arch.roles).map(([role, n]) => (
          <span
            key={role}
            className="pill"
            style={{ borderColor: roleColor(role), color: roleColor(role) }}
          >
            {role} · {n}
          </span>
        ))}
      </div>
      <div className="row split" style={{ alignItems: "flex-start", gap: 20, marginTop: 10 }}>
        <ModuleGraphSvg arch={arch} />
        <div style={{ flex: 1, minWidth: 320 }}>
          <TableScroll>
            <table>
              <thead>
                <tr>
                  <th>Module</th>
                  <th>Role</th>
                  <th title="fan-in">in</th>
                  <th title="fan-out">out</th>
                  <th title="instability">I</th>
                  <th title="betweenness">btw</th>
                </tr>
              </thead>
              <tbody>
                {modules.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.qualified_name}
                      {m.in_cycle && <span className="err"> ⟳</span>}
                    </td>
                    <td>
                      <span
                        className="pill"
                        style={{ borderColor: roleColor(m.role), color: roleColor(m.role) }}
                      >
                        {m.role}
                      </span>
                    </td>
                    <td>{m.fan_in}</td>
                    <td>{m.fan_out}</td>
                    <td className="meta">{m.instability.toFixed(2)}</td>
                    <td className="meta">{m.betweenness_centrality.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </div>
      </div>
      {arch.cycles.length > 0 && (
        <div className="err" style={{ marginTop: 8 }}>
          Import cycles: {arch.cycles.map((c) => c.join(" → ")).join("  |  ")}
        </div>
      )}
      {arch.layering_violations.length > 0 && (
        <div className="err" style={{ marginTop: 8 }}>
          Layering violations:{" "}
          {arch.layering_violations.map((v) => `${v.from} → ${v.to} (${v.reason})`).join("; ")}
        </div>
      )}
      {arch.cycles.length === 0 && arch.layering_violations.length === 0 && (
        <div className="meta" style={{ marginTop: 8 }}>
          No import cycles or layering violations detected.
        </div>
      )}
    </Panel>
  );
}
