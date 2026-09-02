// Presentational primitives shared by every panel (Phase 17).

import type { ReactNode } from "react";
import type { Tone } from "./tokens";

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <h2>{title}</h2>
      <div className="card">{children}</div>
    </>
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
  return <p className="err">{error}</p>;
}

export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="meta">{children}</p>;
}

export function ProgressBar({ pct }: { pct: number }) {
  return (
    <div
      className="bar"
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  );
}

export function TableScroll({ children }: { children: ReactNode }) {
  return <div className="table-scroll">{children}</div>;
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
  const tone: Tone =
    Math.abs(value) < 0.05 ? "neutral" : good ? "good" : "bad";
  const color = `var(--tone-${tone})`;
  return (
    <td className="meta" style={{ color }}>
      {signed(value)}
    </td>
  );
}
