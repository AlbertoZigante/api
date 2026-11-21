# Assembly plan (`/v1/assembly`)

Port of `engine/assembly/*` + `engine/ergonomics.js`. `POST /v1/assembly` takes the RAW panel graph, resolves it
server-side, detects joints / feature joints, plans the hardware (`docs/HARDWARE.md`) and answers
`{ steps, clusters, toolsSummary }`. Client-supplied joints / hardware / steps are dropped, never trusted.

## Layout (`app/rules/assembly/`)
| file | what |
|---|---|
| `roles.py` | panel role from feature flags, else from the NAME / piece code; stage and orientation priorities |
| `clusters.py` | rigid sub-assemblies (structural joints only) + the order of panels inside one |
| `scoring.py` | heuristic ergonomic score (reach, tool access, support, weight, posture, two-person, reposition) |
| `context.py` | everything computed once: joints, hardware plan, clusters, hardware to pre-install |
| `emitter.py` | partial step -> full step (ids, wording, ergonomics, orientation tracking) |
| `stages.py` | the six stages, drawer units (identical drawers once, x N) |
| `human.py` | legacy prose, prerequisites, "set it aside" boundaries |
| `ergonomics.py` | tools per step, weight / two-person / flip annotation |
| `sequence.py` | `build_assembly_sequence`, `build_assembly_plan` |
| `../collation.py` | JS `localeCompare` (ICU) for the tie-breaks |

## Build order (always)
doors + handles, drawers (guides, sides, back, bottom, handle), carcass-side guides, plinth, carcass
(bottom, verticals, shelves, back, top), integration (plinth fitted, drawers slid in, doors hung — hinges last).
Hard rules first (role priority, pre-install before a panel's first joint, back before top, integration only when both
sides are built); the ergonomic score only breaks ties.

## Faithful to the JS, on purpose
- Prose strings are the legacy ones (replaced by verb + warning codes + client i18n in phase 10).
- Size thresholds in `scoring.py` read like metres but receive millimetres (every real panel counts as large).
- A drawer front's attachment to its box is not modelled (only through its handle); twin drawers appear once, `repeatCount` N.
- Python gotchas reproduced: `localeCompare` (not `<`), `Math.round` (half up), plain float accumulation (NOT `sum()`:
  Python 3.12 sums floats with compensation and an exact `x.x5` weight tie rounds the other way).

## Structured wording (phase 10)
Every human string has a structured twin, so the client can render it in the user's language (the legacy English prose is
kept: JS path and fallback). Additive fields on each step: `verb` + `instructionVerb` + `params` (description / instruction
templates), `warningCodes`, `hardwareIds`, `order`, `component` (title / subtitle), `subassemblyRef` (name),
`completionRef`, `toolCodes`, `toolNoteCodes`; clusters carry `ordinal`; the plan carries `toolsSummaryCodes`. The codes are
OpenAPI enums (`StepVerb`, `WarningCode`, `ToolCode`...): the modeller's tests fail if one has no fr / it translation.
`tests/test_assembly_structured.py` holds the English reference templates and proves they rebuild the planner's prose
byte for byte on every golden and 300 random cabinets. `scripts/export_steps_fixtures.py` exports the API's output for the
modeller's i18n tests (and a test here fails if the exported copy is stale).

## Contract notes
`subassemblyId`, `subassemblyName`, `clusterKind`, `componentTitle` are nullable (a hidden panel belongs to no cluster).
Optional step fields (`jointObjects`, `repeatHardware`, `completionInstruction`...) are absent, not null (`exclude_unset`).
The rules version is in `X-Rules-Version` and `GET /v1/version`.

## Verification
1. Goldens: stages `sequence` and `assembly`, 20 designs each.
2. `tests/test_assembly_unit.py`: required stage order, carcass closure order, plan invariants (every golden + a full
   cabinet), determinism, trust boundary, repeat counts, helpers.
3. **Frozen JS corpus (`tests/test_golden_corpus.py`, `tests/golden/corpus.jsonl.gz`): 703 designs and what the original JS engine answered for each — random layouts at every joint-tolerance boundary, furniture with drawers / doors, cabinets, constraint graphs. It replaced the live JS-vs-Python differential fuzz of the migration (the JS was deleted in phase 12; see docs/ARCHITECTURE.md). `tests/test_collation.py` replays 2500 `localeCompare` results frozen from node's ICU.**

4. Mutation-tested (order flips, comparator flips, weights, thresholds, collation, fallbacks).
