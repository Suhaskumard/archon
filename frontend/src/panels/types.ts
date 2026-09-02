// Every run-view panel takes the same props so the panel registry can map over
// them uniformly. Individual panels ignore the fields they don't need.
export interface PanelProps {
  runId: string;
  snapshotId: string;
  repoId: string;
}
