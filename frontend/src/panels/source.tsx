import { useState } from "react";
import { api, type Component } from "../api";
import { useAsync } from "../lib/hooks";
import { Panel, TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function SourceIntelPanel({ runId, snapshotId }: PanelProps) {
  const { data: sum, error } = useAsync(() => api.getRunSource(runId), [runId]);
  const [comps, setComps] = useState<Component[] | null>(null);

  if (error) return <p className="err">source: {error}</p>;
  if (!sum || !sum.analyzed) return null;

  const topComplex = (comps ?? [])
    .filter((c) => typeof c.metrics.complexity === "number")
    .sort((a, b) => (b.metrics.complexity as number) - (a.metrics.complexity as number))
    .slice(0, 8);

  return (
    <Panel title="Source Intelligence">
      <div className="row" style={{ gap: 16 }}>
        {Object.entries(sum.components).map(([k, v]) => (
          <span key={k} className="meta">
            <b>{v}</b> {k.toLowerCase()}
          </span>
        ))}
      </div>
      <div className="row" style={{ gap: 16, marginTop: 6 }}>
        {["IMPORTS", "CALLS", "INHERITS", "CONTAINS"].map((k) => (
          <span key={k} className="meta">
            <b>{sum.edges[k] ?? 0}</b> {k.toLowerCase()}
          </span>
        ))}
        <span className="meta">
          <b>{sum.edges.resolved ?? 0}</b> resolved
        </span>
        <span className="meta">
          <b>{sum.tests}</b> test modules · <b>{sum.config_files}</b> config files
        </span>
      </div>
      {sum.entrypoints.length > 0 && (
        <div className="meta" style={{ marginTop: 6 }}>
          entry points: {sum.entrypoints.map((e) => e.qualified_name).join(", ")}
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        <a
          onClick={() => {
            void api.listComponents(snapshotId).then(setComps).catch(() => setComps([]));
          }}
        >
          {comps ? "loaded" : "load components →"}
        </a>
      </div>
      {topComplex.length > 0 && (
        <TableScroll>
          <table style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>Most complex</th>
                <th>Kind</th>
                <th>Cx</th>
                <th>LOC</th>
                <th>Path</th>
              </tr>
            </thead>
            <tbody>
              {topComplex.map((c) => (
                <tr key={c.id}>
                  <td>{c.qualified_name}</td>
                  <td className="meta">{c.kind}</td>
                  <td>{String(c.metrics.complexity)}</td>
                  <td className="meta">{String(c.metrics.loc ?? "")}</td>
                  <td className="meta">
                    {c.path}:{c.start_line}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </Panel>
  );
}
