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
- `POST /v1/joints | /v1/hardware-plan | /v1/assembly` accept the RAW panel graph; `/v1/joints` (8b), `/v1/hardware-plan` (9a) and
  `/v1/assembly` (9b) are all live. Response models are frozen from the JS goldens (`app/schemas/engine.py`).
- Phase 8a done: `resolveConstraints` is ported (`app/services/resolve.py`, see `docs/RESOLVER.md`): the server resolves the RAW graph itself.
- Phase 8b done: `POST /v1/joints` is live (`app/services/joints.py`, see `docs/JOINTS.md`).
- Phase 9a done: `POST /v1/hardware-plan` is live (`app/rules/hardware.py` + `app/services/hardware.py`, see `docs/HARDWARE.md`);
  `RULES_VERSION` is 0.2.0.
- Phase 9b done: `POST /v1/assembly` is live (`app/rules/assembly/`, see `docs/ASSEMBLY.md`); `RULES_VERSION` is 0.3.0.
  Wording is the LEGACY prose, byte for byte; structured verbs + warning codes come with phase 10 (client i18n).
- Phase 10 done (server): structured wording on every step (verb + params, warning / tool codes, component and
  sub-assembly references), `RULES_VERSION` 0.4.0; goldens unchanged (new keys are additive). Client side: see the modeller's
  VERSIONS.md (RENDER module en / fr / it, `VITE_USE_API_HARDWARE` / `VITE_USE_API_ASSEMBLY`).
- Phase 11 done: API key + per-user JWT, slowapi rate limits (61st request/minute -> 429), structured logs + request ids,
  nesting in worker processes; see `docs/SECURITY.md`. Client: `setAuthTokenProvider`, `Retry-After`, new error codes (fr / it).
  Next: phase 12 — remove the JS business logic from the client (only after phases 5-10 have run stably with the flags on).
