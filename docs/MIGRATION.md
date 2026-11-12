# Migration from 3d_modeler

## Moved to the API (done in this repo)
| modeller | api |
|---|---|
| `src/engine/bom.js` (computeBom, computeMaterialSummary) | `app/services/bom.py` |
| `src/engine/nesting.js` (nestPieces, nestCutList, summarizeNestingResult) | `app/services/nesting.py` |
| `public/data/materials.csv` + `loadMaterialCatalog` | `app/catalog/` + `GET /v1/catalog/materials` |

## Next to move (not yet)
- `HINGE_CATALOG`, `RUNNER_CATALOG`, `PANEL_CONNECTOR_CATALOG` from `engine/hardware.js` → catalog data (YAML/Postgres), served by API. The selection logic stays client-side until the catalog endpoint exists.
- Quotes / pricing / suppliers (future).

## Stays in the modeller (real-time, geometry/constraint graph)
snap.js/resolveConstraints, joints, clearance, validator, quotes, spacing, assembly, ergonomics, hardware plan, all pdfExport-*.js (they only consume rows/results).

## Rules chain (in progress — see migration plan)
- Phase 1–2 done: error envelope, limits, `/v1/version`, `X-Rules-Version`, `openapi.json` contract, TS types in the modeller.
- `POST /v1/joints | /v1/hardware-plan | /v1/assembly` accept the RAW panel graph and answer **501** until the Python port
  (phases 8–9). Response models are frozen from the JS goldens (`app/schemas/engine.py`).
- Open decision for phase 8: port `resolveConstraints` (snap.js) to Python so the server resolves the raw graph itself (recommended).
