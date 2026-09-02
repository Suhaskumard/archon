import { useState } from "react";
import { AsyncPanel } from "../components/async-panel";
import { api, type Component, type SourceSummary } from "../api";
import { TableScroll } from "../components/ui";
import type { PanelProps } from "./types";

export function SourceIntelPanel({ runId, snapshotId }: PanelProps) {
  return (
    <AsyncPanel
      title="Source Intelligence"
      load={() => api.getRunSource(runId)}
      deps={[runId]}
      isEmpty={(s) => !s.analyzed}
      emptyText="Source analysis did not run for this repository."
    >
      {(sum) => <SourceBody sum={sum} snapshotId={snapshotId} />}
    </AsyncPanel>
  );
}

function SourceBody({ sum, snapshotId }: { sum: SourceSummary; snapshotId: string }) {
  const [comps, setComps] = useState<Component[] | null>(null);
  const topComplex = (comps ?? [])
    .filter((c) => typeof c.metrics.complexity === "number")
    .sort((a, b) => (b.metrics.complexity as number) - (a.metrics.complexity as number))
    .slice(0, 8);

  return (
    <>
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
        <button
          className="linklike"
          onClick={() => {
            void api.listComponents(snapshotId).then(setComps).catch(() => setComps([]));
          }}
        >
          {comps ? "loaded" : "load components →"}
        </button>
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
    </>
  );
}
