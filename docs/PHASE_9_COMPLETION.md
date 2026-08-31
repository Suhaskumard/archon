# Phase 9 — Failure Investigation & Self-Healing — Completion Record

Per the plan's Phase 9 scope (§37-43) and the per-phase completion gate. Builds on
Phase 7's Docker sandbox/execution engine and Phase 8's characterization/AI test
generation. Closes the MVP loop: a real test failure is detected, investigated,
patched (two deterministic candidates), ranked, and verified - one VERIFIED, one
REJECTED and rolled back, exactly matching the spec's own acceptance bar.

## Scope delivered

```
… EXECUTING
   ─▶ DETECTING_FAILURES    parse junit.xml, resolve stack frames, reproducibility re-run
   ─▶ INVESTIGATING         AI root-cause hypotheses, evidence-backed, confidence-gated
   ─▶ GENERATING_PATCH      AI patch proposals (2 candidates), static validation
   ─▶ RANKING_PATCHES       deterministic, explainable ranking (pre-verification)
   ─▶ VERIFYING_PATCH       apply in a throwaway workspace copy, run in the sandbox
   ─▶ REGRESSION_VERIFYING  finalize/summarize the verification result
```

### Key design decisions

**Fixture change, not a fixture rewrite.** `billing.unit_price`'s existing guard made
the docstring's planted divide-by-zero bug unreachable by any existing test. Rather
than add a 4th git commit (which would have broken `Commit.id == 3`, hard-pinned by
Phase 4's acceptance test), the new failing test
(`test_divide_by_zero_returns_none`) was folded into the existing 3rd commit
alongside `billing.py`'s guard fix. This rippled into three other tests that pinned
exact counts against the fixture (`FUNCTION: 8 → 9` in Phase 2's and the source
pipeline's acceptance tests; `len(test_cases)`/`passed`/`failed` in Phase 7's
acceptance and execution-API tests) - all updated as expected, deliberate ripples,
the same kind Phase 8 made to Phase 7's pinned counts.

**MVP-loop stages don't catch-and-downgrade.** Unlike Phase 8's AI-call handling
(catch `AIProviderError`/`AIOutputError`, downgrade to an Evidence row, continue),
Phase 9's stage dispatch methods in the orchestrator have no try/except around their
module calls - per the state machine's own rule (spec §10), these are MVP-loop stages
that fail the run on an internal error, not analysis stages that degrade and
continue. A stage with legitimately *no work* (no failures, no investigations past
the confidence gate) still completes normally with a FACT Evidence row saying so.

**Patch Ranking is deterministic, not another AI call.** The spec lists `PatchRanking`
among the versioned AI schemas but describes the ranking engine itself in the exact
same "versioned, explainable, per-signal breakdown" language used for Legacy
Risk/Change Safety. `healing/ranking.py` mirrors `legacy_risk.py`'s shape directly:
pre-verification rank is static-validation-gated + patch-size; post-verification rank
is dominated by real pass/fail signals (`correctness` weight 0.8, `size` 0.2).

**Every generated candidate is verified, not just the top-ranked one.** An earlier
version stopped at the first VERIFIED patch - but since the mock's two candidates
(`guard_zero_divisor`, `naive_integer_division`) can tie on the static-only
pre-verification rank (both change 2 lines), whichever happened to sort first would
win immediately, silently skipping verification of the other and hiding the
"deliberately bad candidate is rejected" story the spec's acceptance bar calls for.
Fixed by verifying every generated (capped, cheap - at most 2 per investigation)
candidate regardless, surfacing every verdict for the human-approval step (§43)
rather than hiding a runner-up.

**Patches store `old_snippet`/`new_snippet` alongside `diff_ref`** - not in the
spec's exact field list (which only names `diff_ref`), but necessary for
verification to deterministically re-apply the identical change in a fresh
workspace copy without re-parsing the stored unified diff. The diff itself (computed
via `difflib.unified_diff`) remains the artifact of record.

**Mock AI scope**: `_op_root_cause_analysis`/`_op_patch_proposal` recognize exactly
one bug pattern class - an unguarded division, tied to Phase 4's existing
`division`-kind `Assumption` detector - not a general root-cause/code-generation
engine. A failure that doesn't match yields `confidence=UNKNOWN` and healing is
honestly skipped (Evidence, not silence), matching every other Mock op's scope
discipline.

### Components

| Area | Module(s) | Notes |
|---|---|---|
| Failure detection | `archon/failure/detection.py` | Parses the `execution_junit` artifact (captured since Phase 7, never read until now) for failing/erroring testcases; extracts `path:line: in func` stack frames from pytest's `--tb=short` text; resolves frames to `Component` rows; re-runs each failing test once more for a reproducibility check. Capped at 3 failures/run. |
| Investigation | `archon/investigation/engine.py` | Assembles context (implicated `Component`, its `Assumption` rows) → `root_cause_analysis` AI op → `Investigation` rows. `PATCH_GENERATION_CONFIDENCE_THRESHOLD = Confidence.MEDIUM.score` gates healing. |
| Patch generation | `archon/healing/generation.py` | `patch_proposal` AI op called twice per gated investigation (two strategy hints) → literal snippet-replace application → real unified diff → static validation (parses, no banned constructs, ≤20 changed lines) → `Patch(state=PROPOSED)`. |
| Patch ranking | `archon/healing/ranking.py` | `rank_static` (pre-verification, static+size only) / `rank_verified` (post-verification, correctness-dominated). Deterministic, versioned, `explain()`. |
| Verification | `archon/verification/engine.py` | `WorkspaceManager.clone()` (new) gives each candidate a throwaway copy; three sandbox runs per candidate (original failing test alone, full combined suite, characterization-only) → `PatchVerification` + final re-rank. |
| Schema | `alembic/versions/0009_healing.py` | `failures`, `investigations`, `patches`, `patch_verifications` |
| Enums | `domain/enums.py` | `PatchState`, `VerificationVerdict` (`_enum()`-backed) |
| AI schemas | `domain/ai_schemas.py` | `RootCauseHypothesis`, `RootCauseAnalysis`, `PatchProposal` |
| Pipeline | `archon/pipeline/orchestrator.py` | 6 new stages/dispatch methods; 4 new `PipelineResult` fields |
| API | `archon/api/routers/healing.py` (new file) | `GET /runs/{id}/failures`, `/investigations`, `/patches` (with `diff_preview`, `state` filter), `/verifications` |
| Frontend | `frontend/src/App.tsx`, `api.ts` | Failures, Root Cause Analysis, Self-Healing, Patch Verification panels |
| Fixture | `tests/fixtures/build_test_repo.py` | `test_divide_by_zero_returns_none` folded into commit 3 |

## Design findings (discovered empirically this phase, not assumed)

* **A guard patch reconstructed from `ast.get_source_segment` text was mis-indented.**
  `get_source_segment` strips the statement's leading whitespace, so building a
  multi-line replacement from it (`if b == 0:\n    return None\n<original>`) with a
  hand-derived indent produced code that failed to parse once spliced back into the
  file - the `if` line landed at the wrong column relative to what followed. **Fix**:
  use the AST node's real `col_offset` to compute indent, and never derive it from the
  (whitespace-free) source segment text. Caught by the acceptance test's own static
  validation failing loudly (`errors: ["static: expected an indented block..."]`) -
  never silently accepted, exactly as the sandbox threat model requires for generated
  patches too.
* **Stopping at the first VERIFIED patch hid the rejection story** the spec's
  acceptance bar explicitly wants demonstrated - see "Every generated candidate is
  verified" above.

## Tests — `cd backend && pytest`

Full suite green (~325 tests). `ruff check archon tests alembic` clean.
`alembic upgrade head` / `downgrade -1` round-trips cleanly.

| Tier | Files | Covers |
|---|---|---|
| unit | `test_junit_parsing.py`, `test_patch_ranking.py`, `test_static_patch_validation.py`, `test_workspace_manager.py` (extended) | frame/exception extraction from junit XML; pure ranking-formula behavior; the indent-reconstruction regression above; `WorkspaceManager.clone` independence |
| integration | `test_healing_api.py` (real Docker) | all 4 new endpoints end-to-end: shapes, `state`/rank-order filtering, verdict split |
| acceptance | `test_phase9_healing.py` (real Docker, skips cleanly if the daemon/image is missing) | the full VERIFIED/REJECTED story against the planted bug; the original repo checkout is provably untouched (mtimes + content) |

Four pre-existing tests were updated (not regressed) as a direct, expected
consequence of planting the new failing test: `test_phase2_source_intelligence.py`
and `test_source_pipeline.py` (`FUNCTION` count 8→9), `test_phase7_sandbox.py` and
`test_execution_api.py` (test/execution counts and the now-nonzero `failed`/nonzero
`exit_code` on the `EXISTING_TESTS` execution).

## Verified manually

* Full backend suite (`pytest`, no filters) exits 0 with Docker Desktop running
  throughout; zero orphaned containers after any run (`docker ps -a --filter
  label=archon.managed=true` empty).
* A manual end-to-end script run confirmed the exact story:
  `guard_zero_divisor` reaches `VERIFIED` with all four checks `True`;
  `naive_integer_division` reaches `REJECTED` with `original_failure_fixed=False`.
* `npm run build` clean; new panels follow the established fetch/render skeleton
  (not independently browser-verified this phase - see the same disclosure pattern
  as Phase 8's completion doc).

## Known limitations / deferred

* **Only one bug pattern class is recognized** (unguarded division) - by design, this
  mock AI provider scope; a real `ClaudeAIProvider` would generalize root-cause
  analysis and patch proposal without touching the deterministic scaffolding
  (validation, ranking, verification) built this phase.
* **Static validation's banned-construct scan and line-count cap are the same ones
  Phase 8 built for generated tests** (`testing/_safety.py`) - reused as-is, not
  patch-specific hardening beyond the Minimal Patch Principle's line cap.
* **Incident memory (Phase 10) is not implemented** - a `VERIFIED` patch is the end
  of this phase's responsibility; nothing is recorded as an `Incident` yet, and
  `RECORDING_INCIDENT`/`MODERNIZING` remain unwired stages.
* **Human-approval UI beyond the read-only Patch Verification panel** (accept/apply
  actions) is out of scope - the spec is explicit that a patch is exported as a
  diff artifact for review, never auto-applied, and no such action exists yet.
