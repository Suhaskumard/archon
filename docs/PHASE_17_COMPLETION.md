# Phase 17 — Frontend architecture — Completion Record

Per `docs/ROADMAP.md` Phase 17. The frontend was a single flat `frontend/src/App.tsx`
(1782 lines): ~23 panel components, 10 module-level colour maps, a `useError` helper, and
~20 hand-rolled `useEffect(() => { let live = true; … .catch(() => undefined); … })` data
blocks. No router — `App` toggled list ↔ run view with `useState<string|null>`, so a run
was not deep-linkable and a refresh lost it. This phase splits it into `lib` / `components`
/ `panels` / `routes`, adds routing and a design-token layer, and replaces every
hand-rolled effect with one of two shared hooks.

## Scope delivered

| Area | Detail |
|---|---|
| **Routing** | `react-router-dom` v7, `<HashRouter>` in `main.tsx`. Routes: `#/` (repositories), `#/runs/:id` (run view), `#/runs/:id/compare` (comparison). `App.tsx` → 20-line `<Routes>` shell with a `*` → `/` redirect. HashRouter chosen because `GET /runs/:id` is a real API endpoint and the Vite dev proxy forwards all `/runs/*` to the backend — fragment routes avoid the collision with zero proxy / SPA-fallback config. Deep-links and browser back/forward work and survive a hard refresh. |
| **`src/lib/hooks.ts`** (new) | `useAsync<T>(fn, deps) → { data, error, loading, reload }` — fetch, cancel a stale result on unmount/dep-change, **capture** the error message; `reload()` bumps an internal nonce (covers the "load components →" link). `usePoll<T>(fn, deps, isTerminal, intervalMs=800)` — chained `setTimeout` (never `setInterval`, so a slow response can't stack), stops when `isTerminal(value)`, clears the pending timer on unmount. `useErrorGuard()` — the old `useError` `{ err, guard }` shape, for imperative POST flows. `TERMINAL_RUN_STATES` set moved here. |
| **`src/components/ui.tsx`** (new) | `Panel`, `Pill` (semantic `tone` prop → `data-tone` attr, no inline style), `ProgressBar` (ARIA), `DeltaCell` + `signed()` (moved verbatim), `TableScroll` (horizontal-scroll wrapper), `ErrorBanner`, `LoadingSkeleton`, `Empty`. |
| **`src/components/tokens.ts`** (new) | The 10 inline colour maps from `App.tsx` collapse into value→tone functions (`severityTone`, `riskCategoryTone`, `hotspotTone`, `changeSafetyTone`, `patchStateTone`, `verdictTone`, `modernizationStrategyTone`, `boolTone`) returning one of `good/warn/bad/critical/neutral/info`; `roleColor(role)` returns a theme-aware `var(--role-*)`. No panel carries a hex literal. |
| **`src/panels/*.tsx`** (new) | One file per panel (~20) + `module-graph.tsx` / `comparison-movement.tsx` split-outs + `types.ts` + `index.ts`. Name preserved, ported verbatim except: `useEffect` block → `useAsync`; `<><h2>…<div className="card">` → `<Panel>`; hand-styled pill → `<Pill tone={…}>`; `<table>` → wrapped in `<TableScroll>`. `module-graph.tsx` and `comparison-movement.tsx` split out to keep every file ≤ ~150 lines. `panels/index.ts` exports the ordered `RUN_PANELS` registry. |
| **`src/routes/`** (new, 3 files) | `RepositoriesRoute` (`RepositoryManager` + `RunsInline`, `useNavigate` instead of `onOpenRun`); `RunRoute` (`useParams` + `usePoll(api.getRun, …, isTerminal)`, status row + progress bar + report button + snapshot card + `RUN_PANELS.map(...)` + evidence table, `<Link>` to `/` and `/compare`); `CompareRoute` (loads the run for repo/snapshot context, renders `RepositoryComparisonPanel` full-width). |
| **`src/styles/tokens.css`** (new) | Full **light** palette on bare `:root` (surfaces, text, accent, `--tone-*` + borders, `--role-*`, space/type scale, radii). Dark re-declares the same tokens with **today's exact values** under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` and `:root[data-theme="dark"]` — dark mode is pixel-identical to before; a future toggle wins both ways (no toggle UI ships here). |
| **`src/styles.css`** (rewritten) | `@import "./styles/tokens.css"`; every hex → `var(--*)`; `.pill[data-tone=…]` variants; `.skeleton` + `@keyframes shimmer` with a `prefers-reduced-motion` opt-out; `@media (max-width: 900px)` collapses `.split` rows (architecture graph+table, etc.) to one column; `img,svg{max-width:100%}`; `.table-scroll{overflow-x:auto}`. Legacy `.pill.COMPLETED`/`.pill.FACT`/state classes kept (evidence + run/snapshot pills still use `className={\`pill ${x}\`}`). |
| **Deps** | `frontend/package.json` + `react-router-dom@^7`. No `vite.config.ts` / `tsconfig.json` change. |

## Verification

| Check | Result |
|---|---|
| `npm run typecheck` (`tsc -b --noEmit`, strict + `noUnusedLocals`/`noUnusedParameters`) | clean |
| `npm run build` (`tsc -b && vite build`) | green — 71 modules, `index.js` 220 kB / 69 kB gzip, `index.css` 6 kB |
| `grep -rn "let live = true\|catch(() => undefined)" src` | 0 hits |
| `grep -rn "#[0-9a-fA-F]{6}" src --include=*.tsx` | 0 hits (hex lives only in `tokens.css`) |
| largest component file | `RunRoute.tsx` / `repository-comparison.tsx` at 124 lines — none over ~150 (`api.ts` at 578 is the pre-existing typed client, untouched) |
| `make ci` frontend leg (`frontend-check` from Phase 14) | typecheck + build green |
| manual: start run → `#/runs/:id`, poller advances then **stops** at `COMPLETED`; hard-refresh rebuilds the same view; `#/runs/:id/compare` deep-links; back/forward moves list ↔ run ↔ compare; report download works; OS light/dark toggles the palette, dark unchanged; < 900 px is single-column | pass |

## Known limitations / deferred (Phase 18)

* **No frontend test suite yet** — `vitest` + `@testing-library/react` + a mocked `api`,
  per-panel render tests, a poller-stops test, `vitest-axe` per route: Phase 18. That is the
  main lever on Testing → 9.
* **No theme-toggle UI** — the `data-theme` hook points exist in `tokens.css`; the control
  and its persistence land in Phase 18's UX polish.
* **`LoadingSkeleton` / `Empty` are defined but lightly used** — panels still return `null`
  when a resource is legitimately absent for the run mode (visual parity with today). Phase
  18 wires skeleton/empty/error states into every panel.
* **Module graph is still the inline circular-layout SVG** — a real force/hierarchy layout
  with zoom/pan is Phase 18's visualization item.
