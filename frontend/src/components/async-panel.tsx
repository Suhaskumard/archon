import type { ReactNode } from "react";
import { useAsync } from "../lib/hooks";
import { Empty, ErrorBanner, LoadingSkeleton, Panel } from "./ui";

/**
 * Render the right state for an async panel body: skeleton while loading,
 * an alert on error, an empty note when the resource returned nothing, else
 * the panel content.
 */
export function PanelStates({
  loading,
  error,
  empty,
  emptyText = "Nothing to show for this run.",
  children,
}: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyText?: string;
  children: ReactNode;
}) {
  if (error) return <ErrorBanner error={error} />;
  if (loading) return <LoadingSkeleton />;
  if (empty) return <Empty>{emptyText}</Empty>;
  return <>{children}</>;
}

/**
 * A panel whose body is loaded async. Handles the skeleton / error / empty
 * states and hands non-null data to the render child. `hideWhenAbsent` (for the
 * FULL-only panels) renders nothing at all when the resource errors or is empty,
 * so an ANALYSIS_ONLY run doesn't show a wall of empty cards.
 */
export function AsyncPanel<T>({
  title,
  load,
  deps,
  isEmpty,
  emptyText,
  hideWhenAbsent = false,
  children,
}: {
  title: string;
  load: () => Promise<T>;
  deps: unknown[];
  isEmpty?: (data: T) => boolean;
  emptyText?: string;
  hideWhenAbsent?: boolean;
  children: (data: T) => ReactNode;
}) {
  const { data, error, loading } = useAsync(load, deps);
  const empty = data != null && (isEmpty ? isEmpty(data) : false);
  if (hideWhenAbsent && (loading || error || data == null || empty)) return null;
  return (
    <Panel title={title}>
      <PanelStates loading={loading} error={error} empty={empty} emptyText={emptyText}>
        {data != null ? children(data) : null}
      </PanelStates>
    </Panel>
  );
}
