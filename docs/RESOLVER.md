# Constraint resolver (`resolveConstraints` port)

`app/services/resolve.py` = the modeller's `src/modeller/snap.js`, ported to Python (geometry helpers in
`app/services/geometry.py`). It turns the RAW panel graph (literal values + constraints) into the resolved
graph (concrete width / height / position per panel). The rules chain (joints, hardware, assembly) will run
on this server-side result, so the API never trusts geometry computed by the browser.

## What it supports (all four constraint types, same semantics as the JS)
| type | sets | needs |
|---|---|---|
| `spansBetween` | a dimension (and centres the panel on that axis) | `field`, `from`, `to` (a face, or a literal `{mm}` snapshot) |
| `attachedTo` | a position, flush to a face (+ offset) | `field`, `myFace`, `from` |
| `distance` | a position: the clear gap of a user quote | `field`, `myFace`, `from`, `value` |
| `equalSpacing` | positions of a set of shelves so every gap is equal | `field`, `from`, `to`, `members`, `spacingId` |

Panel `rotation` is in DEGREES (three.js Euler, order XYZ). A face counts as axis-aligned within ~11.5 degrees
(`|cos| >= 0.98`); angled joinery is unsupported and reported, never guessed.

## Failure handling = the JS's
A constraint that cannot be applied never raises: it becomes a WARNING on that panel (same text as the JS —
the UI shows them). Cycles (including a panel referring to itself) are not resolved: each member keeps its
literal values and gets a warning; panels depending on them still resolve. A reference to a panel that no longer
exists is a warning, not a request error. `spansBetween` runs before the other types on the same node.

## Deliberate differences (inputs the JS would crash on)
Rejected at the contract with `422 validation_error` instead of a TypeError-text warning: a known constraint type
missing a required part (e.g. `spansBetween` without `to`), or a `field` outside
`width|height|thickness|positionX|positionY|positionZ`. `resizeProxy` (UI-only gizmo state) is not part of the
contract and is always `null` in the output. `thicknessAxis`, when absent, is derived from the rotation.

## How it is verified (the JS stays the oracle until the migration ends)
1. **Goldens** (`tests/test_golden.py`, stage `resolved`): 32 frozen JS results — the 20 furniture designs plus 12
   resolver fixtures built with the real feature functions or by hand (each constraint type, every failure
   warning, cycles, JS-style rounding of `30.5`, literal anchors, 3-axis rotations, ordering).
2. **Differential fuzz** (`tests/test_resolve_differential.py`): random graphs go through the REAL JS resolver
   (`3d_modeler/scripts/golden/resolve-runner.mjs`) and through the port; every number, flag and warning text must
   agree (1e-6). Needs `node` and the modeller checkout next to this repo (or `MODELLER_DIR`); skipped otherwise.
   `FUZZ_N=20000 FUZZ_SEED=7 pytest tests/test_resolve_differential.py` for a long run. Mutation-tested: a flipped
   sign, a wrong tolerance, a reordered constraint, a dropped lock... each fails the goldens and/or the fuzz.
3. **Unit/robustness** (`tests/test_resolve_unit.py`): geometry, ordering, cycles, purity, determinism, never raises.

One known, accepted gap: an explicit JSON `null` node/face prints as `null` in the JS warning text and as
`undefined` here (the modeller never sends one; absent keys behave identically).
