// Domain value -> semantic tone, and categorical role -> CSS hue token.
// These are the only place the old inline colour maps from App.tsx survive.

export type Tone = "good" | "warn" | "bad" | "critical" | "neutral" | "info";

const RISK_SEVERITY: Record<string, Tone> = {
  LOW: "neutral",
  MEDIUM: "warn",
  MODERATE: "warn",
  HIGH: "bad",
  CRITICAL: "critical",
};

const HOTSPOT: Record<string, Tone> = {
  STABLE: "good",
  WATCH: "warn",
  RISKY: "bad",
  CRITICAL: "critical",
};

const CHANGE_SAFETY: Record<string, Tone> = {
  SAFE: "good",
  CAUTION: "warn",
  RISKY: "bad",
  DANGEROUS: "critical",
};

const PATCH_STATE: Record<string, Tone> = {
  PROPOSED: "neutral",
  TESTING: "warn",
  PARTIALLY_VERIFIED: "warn",
  VERIFIED: "good",
  REJECTED: "bad",
};

const VERDICT: Record<string, Tone> = {
  VERIFIED: "good",
  REJECTED: "bad",
};

const MODERNIZATION_STRATEGY: Record<string, Tone> = {
  ADD_TESTS: "good",
  EXTRACT_DEPENDENCY: "warn",
  REPLACE_DEPENDENCY: "warn",
  REFACTOR: "warn",
  REWRITE: "bad",
};

const pick = (map: Record<string, Tone>) => (value: string | null | undefined): Tone =>
  (value && map[value]) || "neutral";

export const severityTone = pick(RISK_SEVERITY);
export const riskCategoryTone = pick(RISK_SEVERITY);
export const hotspotTone = pick(HOTSPOT);
export const changeSafetyTone = pick(CHANGE_SAFETY);
export const patchStateTone = pick(PATCH_STATE);
export const verdictTone = pick(VERDICT);
export const modernizationStrategyTone = pick(MODERNIZATION_STRATEGY);

export const boolTone = (b: boolean): Tone => (b ? "good" : "bad");
export const inverseBoolTone = (b: boolean): Tone => (b ? "bad" : "neutral");

// Roles are a categorical palette, not a severity scale — keep them as hues,
// resolved to the theme-aware CSS custom properties in tokens.css.
const ROLE_KEYS = [
  "api", "cli", "entrypoint", "domain", "model",
  "io", "util", "config", "test", "unknown",
] as const;

export function roleColor(role: string | null | undefined): string {
  const key = (role ?? "unknown").toLowerCase();
  return `var(--role-${(ROLE_KEYS as readonly string[]).includes(key) ? key : "unknown"})`;
}
