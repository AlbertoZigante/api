# Hardware plan (`/v1/hardware-plan`)

Port of the modeller's `src/engine/hardware.js`. `POST /v1/hardware-plan` takes the RAW panel graph, resolves it
server-side (`docs/RESOLVER.md`), detects joints and feature joints itself (`docs/JOINTS.md`) and answers
`{ summary, hinges, runners, fasteners, unmatched }`. Client-supplied joints / hardware / relations are dropped, never trusted.

Layout: `app/rules/hardware.py` = catalogs + pure selectors (plain numbers / joint dicts in, no panels);
`app/services/hardware.py` = the orchestration (`build_hardware_plan`), reused by the assembly stage in phase 9b.
Catalog entries are plain camelCase dicts echoed verbatim in each response's `hardware`.

## Rules (all mm)
| piece | rule |
|---|---|
| Hinge (CLIP top BLUMOTION 110° / 170°) | first catalog entry whose door-thickness range 16–24 contains the door's thickness; none = `unmatched` |
| Hinge count | height ≤ 900 → 2, ≤ 1600 → 3, ≤ 2200 → 4, else 5 (rule of thumb, not a Blum number) |
| Hinge positions | outer hinges inset 10 % of the door height, clamped to [80, 160]; the rest evenly between |
| Runner (TANDEM / LEGRABOX) | TANDEM only for 11–16 drawer sides, LEGRABOX always a candidate; the built side clearance must be 21 ± 1; nominal length = largest catalog length ≤ the box depth |
| Fastener (generic confirmat 7×50) | corner_butt / t_butt only, thinner panel ≥ 16; 50 from each end, spacing ≤ 150 (`ceil(usable / 150)` gaps); a seam too short for both offsets gets one centred fastener |

Anything that matches nothing is reported in `unmatched` (`kind` hinge / runner / fastener; fasteners also carry `jointId` / `jointType`).
`displayId`s are `HG001…`, `RN001…`, `FS001…`. The JS `generatedAt` timestamp is deliberately not part of the contract
(the plan is deterministic). The rules version is in the `X-Rules-Version` header and `GET /v1/version`.

## Verification
1. Goldens (`tests/test_golden.py`, stage `hardware`): 20 designs, JS output frozen in `tests/golden/*/hardware.json`.
2. `tests/test_hardware_unit.py`: every catalog boundary, placement maths, `unmatched` bookkeeping, determinism, trust boundary.
3. `tests/test_hardware_differential.py` against the REAL JS (needs node + `npm ci` in `3d_modeler`):
   selector fuzz at every boundary (`scripts/golden/hardware-runner.mjs`), plus whole-plan fuzz on random layouts and on
   furniture layouts (carcass + drawers at random gap / thickness / depth + doors) so TANDEM, LEGRABOX and every
   `unmatched` kind are reached. `FUZZ_N=3000` for a long run.
4. Mutation-tested: boundary flips (`<=` → `<`, ceil → floor, tolerance, clamp, thickness range) are all caught.
