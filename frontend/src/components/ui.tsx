// Presentational primitives shared by every panel (Phase 17; a11y + states in 18).

import { useId, type ReactNode } from "react";
import type { Tone } from "./tokens";

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      <div className="card">{children}</div>
    </section>
  );
}

export function Pill({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return (
    <span className="pill" data-tone={tone}>
      {children}
    </span>
  );
}

export function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="err" role="alert">
      {error}
    </p>
  );
}

export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-live="polite" data-testid="skeleton">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="meta">{children}</p>;
}

export function ProgressBar({ pct, label }: { pct: number; label?: string | null }) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="progress">
      <div
        className="bar"
        role="progressbar"
        aria-label="run progress"
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={label ? `${Math.round(clamped)}% — ${label}` : undefined}
      >
        <div style={{ width: `${clamped}%` }} />
      </div>
      {label && <span className="meta">{label}</span>}
    </div>
  );
}

export function TableScroll({ children }: { children: ReactNode }) {
  return <div className="table-scroll">{children}</div>;
}

/** Tiny inline trend line, reused by Git Evolution and elsewhere. */
export function Sparkline({
  values,
  width = 160,
  height = 36,
  ariaLabel,
}: {
  values: number[];
  width?: number;
  height?: number;
  ariaLabel: string;
}) {
  if (values.length === 0) return null;
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - (v / max) * (height - 4) - 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={ariaLabel}
      className="sparkline"
    >
      <polyline points={points} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
    </svg>
  );
}

export function signed(n: number | null | undefined, digits = 2): string {
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;
}

export function DeltaCell({
  value,
  goodWhenNegative = true,
}: {
  value: number;
  goodWhenNegative?: boolean;
}) {
  const good = goodWhenNegative ? value < 0 : value > 0;
  const tone: Tone = Math.abs(value) < 0.05 ? "neutral" : good ? "good" : "bad";
  return (
    <td className="meta" style={{ color: `var(--tone-${tone})` }}>
      {signed(value)}
    </td>
  );
}
