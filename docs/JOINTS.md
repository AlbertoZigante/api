# Joint detection (`detectJoints` / `detectFeatureJoints` port)

`app/services/joints.py` = the modeller's `src/engine/joints.js` (detection half). `POST /v1/joints` takes the RAW panel
graph, resolves it server-side (`docs/RESOLVER.md`) and returns `{ joints, collisions, featureJoints }`. Client-supplied
joints / relations are dropped, never trusted.

## Contact joints (`joints`, `collisions`)
Every pair of VISIBLE resolved panels is treated as two axis-aligned boxes; the tightest valid contact axis wins.
All thresholds are the JS ones (mm): touching = gap within 0.05; `near_contact` up to 3 mm; a footprint overlap under
5 mm is a corner graze and ignored; real overlap of 1 mm or more on EVERY axis is a collision, not a joint.

| type | meaning |
|---|---|
| `face_to_face` | both panels' thickness axis is the contact axis |
| `corner_butt` / `t_butt` | exactly one is flat to the contact; the other meets it edge-first at its boundary (within 0.5 mm) / mid-span |
| `edge_to_edge` | neither is flat to the contact (`status: "unhandled"`) |
| `near_contact` | within 3 mm along the axis but not touching |

## Feature joints (`featureJoints`)
Door hinges and drawer slides are CONSTRUCTION INTENT read from the RAW flags (`isDoor`, `hinge`, `boundaryIds`,
`isDrawerFront`, `isDrawerBoxPanel`, `drawerBoxFrontId`, `drawerBoxRole`, `normalAxis`), not rediscovered from contact
(a drawer side usually does not touch its carcass). Geometry (the hinge/slide line, `lengthMm`, the slide's measured
`clearanceMm`) comes from the resolved panels. Skipped, as in the JS: lid-style doors (`normalAxis: y`), doors without a
hinge side or boundary, references to panels that do not exist. `clearanceMm` is present only on drawer slides.

Deliberate difference: a drawer front with no `normalAxis` makes the JS emit a coordinate named "undefined"; the port skips it.
The client keeps its own copy of detection for live snapping/UX; this is the server copy the rules chain runs on.

## How it is verified
1. Goldens (`tests/test_golden.py`, stages `joints` + `featureJoints`): the 20 furniture designs plus 4 hand-placed
   fixtures aimed at every threshold and branch (`joints_thresholds`, `joints_corner_vs_t`, `joints_edge_to_edge`,
   `joints_features_synthetic`).
2. **Frozen JS corpus (`tests/test_golden_corpus.py`, `tests/golden/corpus.jsonl.gz`): 703 designs and what the original JS engine answered for each — random layouts at every joint-tolerance boundary, furniture with drawers / doors, cabinets, constraint graphs. It replaced the live JS-vs-Python differential fuzz of the migration (the JS was deleted in phase 12; see docs/ARCHITECTURE.md).**
