# Nesting (cut optimisation)

`POST /v1/nesting` = BOM + guillotine packing per (material, thickness) + cost summary.
Implementation: `app/services/nesting.py`, a faithful port of the modeller's original `nesting.js`.

## Decision: keep the port, do not switch to rectpack (yet)

|                         | this port (guillotine, best-area-fit) | rectpack MaxRects |
|-------------------------|---------------------------------------|-------------------|
| Output vs original JS   | **identical on all 20 golden designs** | different layouts |
| Cuts feasible on a panel saw | **yes** (every cut edge-to-edge)  | not guaranteed (non-guillotine) |
| Saw kerf                | modelled exactly                      | only by inflating pieces |
| Grain (no rotation)     | supported                             | supported         |
| Sheets used (random furniture-sized sets, `scripts/bench_nesting.py`) | baseline | ~2–6 % fewer |
| Speed                   | 0.3 ms (20 pieces) – 25 ms (250)      | similar           |

rectpack saves a few percent of sheets on random instances, but its layouts cannot always be cut on a
panel saw, and it would break the exact parity that proves the migration changed nothing.
Better packing is a product decision for AFTER the migration (bump `RULES_VERSION`; the invariant tests below
are the safety net for any new algorithm).

## Guard rails (both configurable, see `.env.example`)
- `NESTING_TIMEOUT_S` (default 10): cooperative deadline checked inside the packing loops.
  Pure-Python CPU work cannot be killed from outside a thread, so the algorithm checks the clock itself.
  Over budget -> `503 {"code": "nesting_timeout"}`.
- `MAX_CONCURRENT_NESTINGS` (default 4): non-blocking cap. Full -> `503 {"code": "busy"}` + `Retry-After: 1`
  (fail fast instead of queueing threads that would all slow each other down).
- Input is already bounded by the contract (max 500 panels, 2 MB). Worst case measured locally:
  500 pieces of 10-60 mm (many free rectangles) ~1.3 s.

## Invariants (`tests/nesting_invariants.py`)
Checked on every golden design AND on random instances (hypothesis, 250 examples x 3 properties):
inside the sheet; no two pieces closer than the kerf; rotated only if the material allows; every piece
placed XOR unplaced (none lost/duplicated); "unplaced" pieces really do not fit; areas/utilisation/summary
consistent; deterministic (same input -> same output, also across `PYTHONHASHSEED`); input never mutated.
The checker itself is tested against tampered results.
