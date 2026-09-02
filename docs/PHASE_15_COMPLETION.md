# Phase 15 — Core hardening & de-duplication — Completion Record

Per `docs/ROADMAP.md` Phase 15. Removes the mechanical duplication the review flagged
and closes two small robustness/honesty seams. **No behaviour change** — the scoring
numbers are pinned bit-for-bit by the existing unit tests and by
`test_scoring_properties.py` (Phase 14).

## Scope delivered

| Change | Effect |
|---|---|
| `analysis/scoring/_base.py` (new) | one `norm()`, one `weighted_score()`, one `ScoreResult` — `legacy_risk` / `hotspot` / `change_safety` import them (`_norm` was copy-pasted ×3, the weighted-sum reduction ×3, `ScoreResult` ×2) |
| `analysis/scoring/_reuse.py` (new) | `prior_run_over_snapshot(session, run, snapshot_id, model)` — the identical "is there a prior run over this snapshot" lookup, was duplicated in `legacy_dna.py` + `hotspots.py` |
| `domain/enums.py::enum_value(x)` | the canonical `x.value if isinstance(x, Enum) else str(x)` — replaces the three private `_cat()` copies in `comparison/differ.py` (×8 call sites) and `modernization/planner.py` (×5) |
| `modernization/planner.py` | `comp_by_id` dict replaces an O(n·m) `next((c for c in comps ...))` scan inside the tech-debt-findings loop |
| `core/logging.py` | redaction now scrubs `sk-ant-…` (Anthropic), `sk-…` (OpenAI-style), `AKIA…` (AWS), `github_pat_…`, `Bearer <token>`, and JWTs — not just GitHub PATs |
| `pipeline/orchestrator.py` | the stage `if/elif` chain gained a terminal `else: raise ArchonError(INTERNAL, …)`; the module docstring's "resumption is well-defined" claim was corrected to describe what the code actually does (start-of-plan; recovery is by requeue) |
| docstring sweep | `legacy_dna.py` / `change_safety_run.py` / `enums.py` "NOT YET REAL DATA (Phase 8)" / "wired up in later phases" comments refreshed — Phase 8/9 landed; real coverage/failure feedback is Phase 16 |

### Key design decisions

**`_base.weighted_score` returns a *raw* score.** Hotspot applies its overlap bonus
*after* the base score and rounds once at the end; legacy-risk / change-safety round
immediately. So the shared helper returns the unrounded weighted mean and each caller
rounds — this keeps Hotspot's numbers bit-identical (it was `round(min(base*bonus,100),
2)` over an unrounded `base`).

**`_clone_from_prior` / `_write_artifact` were left per-engine.** They copy
model-specific columns and write model-specific artifact schemas; a generic version
would take ~6 parameters and read worse than the ~30 lines it replaced. Only the truly
identical `_prior_run_id` was lifted.

**Hotspot keeps its own `ScoreResult`** (`classification` / `reasons`, not `category` /
`factor_breakdown`) — its runner and `test_hotspot_scoring.py` depend on those attribute
names, and the shape is genuinely different.

## Deferred (with rationale)

- **Orchestrator `dict[Stage, _StageSpec]` dispatch table** (plan target ≤450 lines;
  currently 721). The ~12 pure wrappers have varying signatures (`workspace` or not),
  two do extra work (`_graph` emits cycle evidence, `_analyzing_tests` adds the
  candidate count), and the ~10 stateful stages thread `clone_result` /
  `execution_summary` / `verification_summary` between each other. A safe table needs
  the stage bodies touched too — best folded into Phase 16 (which edits the scoring
  stages) / Phase 19 (which adds `RunMode.INCREMENTAL`). The **terminal `else: raise`**
  (the correctness half) is done now.
- **Resume-from-checkpoint** — needs the clone workspace reconstructed from
  `snapshot.workspace_ref` on re-entry; it's a Phase 20 operability item (whose
  acceptance bar is "kill the worker mid-run and restart resumes to COMPLETED"). The
  docstring now states the real behaviour instead of overclaiming.
- **`Field(ge=0.0, le=1.0)` on the response-DTO `confidence` floats** — assessed and
  *not* done: Pydantic validates on construction, so a hypothetical float-rounding
  error (`1.0001`) would turn into a `500` on a read endpoint. `test_scoring_properties.py`
  already proves every engine keeps `confidence ∈ [0, 1]` at the source.

## Tests

`ruff check archon tests alembic` clean.

| Tier | Result |
|---|---|
| `test_{legacy_risk,hotspot,change_safety,repository_understanding}_scoring.py` | green — identical numbers |
| `test_scoring_properties.py` (Phase 14) | green — bounds + monotonicity still hold via `_base` |
| `test_comparison_differ.py`, `test_modernization_planner.py` + their `*_api.py` | green — `enum_value` behaviour matches the old `_cat` |
| `test_errors_and_redaction.py` | green + 1 new test covering the non-GitHub credential shapes (nested `extra_fields` included) |
| full `tests/unit` | green |

## Known limitations

* Orchestrator is still ~720 lines — the dispatch-table refactor is deferred (above).
* `_reuse.py` only holds the one genuinely-shared helper; the per-engine clone/artifact
  code remains.
