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
