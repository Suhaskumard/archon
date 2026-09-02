import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

/** Parse the `--name: #hex;` declarations inside the first `{ ... }` after `selector`. */
function tokenBlock(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`selector not found: ${selector}`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  const body = css.slice(open + 1, close);
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})/g)) {
    out[m[1]] = m[2];
  }
  return out;
}

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const rgb = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
  const lin = rgb.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function contrast(a: string, b: string): number {
  const l1 = luminance(a);
  const l2 = luminance(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

const light = tokenBlock(":root {");
const dark = tokenBlock(':root[data-theme="dark"]');

describe.each([
  ["light", light],
  ["dark", dark],
])("%s palette WCAG contrast", (_name, t) => {
  it("body text meets AA (>= 4.5) on bg and surface", () => {
    expect(contrast(t["--text"], t["--bg"])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(t["--text"], t["--surface"])).toBeGreaterThanOrEqual(4.5);
  });

  it("muted text is at least 4 on surface", () => {
    expect(contrast(t["--text-muted"], t["--surface"])).toBeGreaterThanOrEqual(4);
  });

  it("every semantic tone is at least 4.5 on surface", () => {
    for (const tone of ["good", "warn", "bad", "critical", "neutral", "info"]) {
      const ratio = contrast(t[`--tone-${tone}`], t["--surface"]);
      expect(ratio, `--tone-${tone}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("accent has >= 3 against surface (UI component bound)", () => {
    expect(contrast(t["--accent"], t["--surface"])).toBeGreaterThanOrEqual(3);
  });
});
