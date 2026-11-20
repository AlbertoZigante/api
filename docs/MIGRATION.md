# Migration JS -> Python backend, thin client: record

Status: **complete through phase 12.** Next: phase 13 (deployment). Rollback: tag `pre-phase12` (JS engine still present, flags
`VITE_USE_API_*`) and `pre-python-migration` (before anything).

| phase | what | where it lives now |
|---|---|---|
| 0-3 | safety net, golden fixtures, FastAPI skeleton, contract + validation, golden harness | `tests/golden/`, `app/schemas/`, `tests/golden_harness.py` |
| 4 | catalog + BOM | `app/services/bom.py`, `app/catalog/` |
| 5, 7 | client -> API for BOM / nesting (cut list) | modeller `src/ui/cutlist.js`, `src/api/` |
| 6 | nesting | `app/services/nesting.py`, `docs/NESTING.md` |
| 8 | constraint resolver + joints (server copy) | `app/services/resolve.py`, `joints.py`, `docs/RESOLVER.md`, `docs/JOINTS.md` |
| 9a | hardware plan | `app/rules/hardware.py`, `app/services/hardware.py`, `docs/HARDWARE.md` |
| 9b | assembly plan | `app/rules/assembly/`, `docs/ASSEMBLY.md` |
| 10 | structured steps + client i18n (en / fr / it) | `StepVerb` enums, modeller `src/i18n/steps.js` |
| 11 | auth, rate limits, logs, nesting workers | `app/auth.py`, `app/ratelimit.py`, `app/nesting_runner.py`, `docs/SECURITY.md` |
| 12 | JS business logic removed, migration scaffolding removed, browser E2E, bundle guard | `docs/ARCHITECTURE.md` |

## Phase 12, what was removed
- Modeller: `engine/assembly.js` + `engine/assembly/*` (except `manual/`, which only renders), `engine/ergonomics.js`, the hardware PLAN
  and runner catalog in `engine/hardware.js`, `scripts/golden/*` (generators, runners, legacy BOM / nesting oracles), the `VITE_USE_API_*` flags and the JS
  paths behind them, the legacy `engine/pdfExport.js` and `pdfExport-assembly.js`, template / prototype leftovers (`App.jsx`, `counter.js`, `main.js`, empty stubs), the accidental
  `add` / `package-lock.json` dependencies.
- API: the four differential test modules (live JS-vs-Python), the migration phase / `ported` / xfail machinery of the golden harness, `scripts/dump_golden.py`.
- Kept as data: `fixtures/golden` (modeller) and `tests/golden` (api) — the frozen JS answers.
- Replaced by: `tests/test_golden_corpus.py` (703 frozen designs), `tests/test_collation.py` (frozen ICU results), `tests/layouts.py` (the generators, kept as test inputs).

## Known, accepted leftovers
- `engine/hardware.js` keeps the hinge and connector selection for live clearance checks (duplicate of `app/rules/hardware.py`).
- `engine/joints.js`, `engine/clearance.js`, `engine/validator.js`, `engine/spacing.js`, `engine/quotes.js` and the constraint resolver stay in the client by design (instant feedback while dragging).
- The legacy English prose of the steps is still returned next to the structured fields (fallback, and the golden contract).
