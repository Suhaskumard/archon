# Phase 18 — Frontend testing, accessibility & visualization — Completion Record

Per `docs/ROADMAP.md` Phase 18. Phase 17 gave the frontend an architecture; this phase gives
it a test suite with a CI-enforced coverage gate, an accessibility pass (`vitest-axe` clean on
every route, semantic landmarks, keyboard-navigable controls, visible focus, AA-contrast
tokens), loading/empty/error states on every panel, and an interactive dependency graph.

## Scope delivered

| Area | Detail |
|---|---|
| **Test runner** | `vitest` 2.1 + `jsdom` + `@testing-library/react` / `user-event` + `@testing-library/jest-dom` + `vitest-axe`. `test` block added to `vite.config.ts` (`environment: jsdom`, `globals`, `setupFiles`, `restoreMocks`). Scripts: `test` (`vitest run`), `test:watch`, `test:cov`. |
| **Coverage gate** | v8 provider, scoped to `src/{lib,components,panels,routes}` (the 578-line `api.ts` fetch client is excluded from the gate and covered by its own `fetch`-mock spec). Thresholds `lines/functions/statements 80`, `branches 75`. **Actual: 98.3 / 94.9 / 98.3 lines-funcs-stmts, 78.9 branches** — `test:cov` exits non-zero if the gate is missed. |
| **Test harness** | `src/test/setup.ts` (jest-dom + axe matchers, `cleanup`, jsdom shims for `matchMedia`/`ResizeObserver`/`createObjectURL`/`scrollIntoView`); `src/test/fixtures.ts` (a `Partial<T>` factory per DTO); `src/test/mockApi.ts` (`makeApi()` — every `api.*` method a `vi.fn()` resolving to a fixture). Documented `vi.hoisted` + `vi.mock("../../api")` pattern used by every UI spec. |
| **Hook tests** (9) | `useAsync` resolve / reject-captures-message / no-set-after-unmount / `reload()`; `usePoll` polls-until-terminal-then-stops (fake timers) / error-then-recovers / clears-timer-on-unmount; `useErrorGuard` capture + clear. |
| **Panel tests** (57) | `panels.table.test.tsx` — data-driven over 13 uniform panels × {rows render, `[]` → empty-state or hidden, rejection → no throw}. `panels.special.test.tsx` — source lazy-load, git-evolution sparkline, understanding chart, archaeology `<select>` switch, architecture graph+table + `reconstructed:false`, change-impact compute, comparison baseline+run. `panels.states.test.tsx` — empty/proxy/error branches. `module-graph.test.tsx` — deterministic layout, node/edge counts, wheel-zoom, drag-pan, reset. |
| **Route + a11y tests** (9) | `routes.test.tsx` — repo list + add + Analyze-navigates; `RunRoute` renders completed run / **stops polling at terminal** / keeps polling while `RUNNING` (fake timers); `CompareRoute`. `routes.axe.test.tsx` — `axe()` has **no violations** on `#/`, `#/runs/:id`, `#/runs/:id/compare`. |
| **API client test** (7) | `req` success + `CODE: message` envelope + `HTTP <status>` fallback + POST body + query passthrough; `downloadReport` blob→anchor + error envelope. |
| **Contrast test** (8) | `src/test/contrast.test.ts` parses `styles/tokens.css`, computes WCAG 2.1 ratios for both palettes: body text ≥ 4.5 on bg/surface, muted ≥ 4, every `--tone-*` ≥ 4.5 on surface, accent ≥ 3. Forced one change: dark `--tone-critical` `#e5484d` → `#f2666b` (was 4.31:1, now 5.53:1). |
| **UX polish** | `PanelStates` + `AsyncPanel` (`components/async-panel.tsx`) — every panel now renders a skeleton while loading, a `role="alert"` banner on error, and a readable empty note (`hideWhenAbsent` keeps the FULL-only panels hidden on an ANALYSIS_ONLY run). `ProgressBar` gains a stage `label` + `aria-valuetext`. `RunRoute` progress bar shows the current/last stage; the evidence section is an `aria-live` region with a count. New `Sparkline` primitive, used by Git Evolution. |
| **Accessibility** | `App` wraps content in `<header>` + `<main>`; `Panel` → `<section aria-labelledby>`; repo list → `<ul role=list>`; every `<input>`/`<select>` has a `<label>` or `aria-label`; the "load components" link is now a real `<button class="linklike">`; `styles.css` adds `:focus-visible` rings, `.visually-hidden`, `prefers-reduced-motion` already covered. |
| **Visualization** | `panels/graph-layout.ts` — pure deterministic role-grouped radial layout (`layoutModules`). `module-graph.tsx` rewritten: SVG `viewBox` wheel-zoom (0.3×–3×) + pointer drag-pan + "reset view", `<title>` per node, `role="img"`, a role-swatch legend. |
| **CI** | `Makefile` `frontend-check` → `npm ci && typecheck && test:cov && build`. `.github/workflows/ci.yml` frontend job runs `npm run test:cov` between typecheck and build. |

## Verification

| Check | Result |
|---|---|
| `npm run typecheck` | clean (test files typed; `vitest-axe` matcher augmentation in `src/test/vitest-axe.d.ts`) |
| `npm run test` | **90 passed** (9 files) |
| `npm run test:cov` | exit 0 — 98.3 % lines / 94.9 % funcs / 98.3 % stmts / 78.9 % branches on `src/{lib,components,panels,routes}` |
| `npm run build` | green — 72 modules, 226 kB / 70 kB gz JS, 6.8 kB CSS |
| `axe()` per route | 0 violations on all three routes |
| largest component file | `RunRoute.tsx` 138 lines — none over ~150 |
| `make ci` frontend leg | typecheck + `test:cov` + build green |

## Known limitations / deferred

* **Lighthouse a11y ≥ 95** (ROADMAP acceptance) is not run here — no headless Chrome in this
  environment. `vitest-axe` (WCAG 2.0/2.1 A + AA rule set) on every route is the substitute;
  a Lighthouse CI step can be added to the GH workflow later.
* **"triggered by push `<sha>`" badge** — deferred to Phase 19, which adds the webhook and the
  `Run` field that would feed it.
* **Force-directed graph** — Phase 18 ships a deterministic role-grouped layout with zoom/pan
  (dependency-free, per the approved plan); a physics simulation was explicitly out of scope.
* **Branch coverage 78.9 %** clears the 75 % gate but is the thinnest margin; the untested
  branches are mostly defensive `?.` / `?? "—"` fallbacks in table cells.
