# api

FastAPI backend — one of 3 repos: `site`, `3d_modeler`, `api`.
Stateless: BOM, nesting and catalog served to the modeller. See `docs/MIGRATION.md`.

## Run (PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
uvicorn app.main:app --reload
pytest
```
Docs: http://localhost:8000/docs

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/v1/catalog/materials` | material catalog (replaces `public/data/materials.csv`) |
| POST | `/v1/bom` | `{panels:[resolved panels]}` → `{rows, materialSummary}` |
| POST | `/v1/nesting` | `{panels, options}` → `{bom, results, summary}` |
| GET | `/v1/version` | `{apiVersion, rulesVersion, contractVersion}` |
| POST | `/v1/joints` | RAW `{panels}` → joints + collisions + feature joints (door hinges, drawer slides) — see `docs/JOINTS.md` |
| POST | `/v1/hardware-plan` | RAW `{panels}` → hinges / runners / fasteners + `unmatched` — see `docs/HARDWARE.md` |
| POST | `/v1/assembly` | RAW `{panels}` → ordered steps + clusters + tools (**501: contract only**) |

Every response carries `X-Rules-Version`. Errors are always `{"code": "<stable>", "detail": ...}`
(`invalid_api_key` 401, `validation_error` 422, `payload_too_large` 413, `not_implemented` 501).

JSON is camelCase on the wire (same field names as the modeller).

## Contract & trust boundary
- Request bodies are validated and bounded (`app/schemas/limits.py`: max 500 panels, dimensions, coordinates,
  string lengths; body cap `MAX_BODY_BYTES`). NaN/Infinity rejected, duplicate ids and dangling constraints rejected.
- The rules chain takes the RAW panel graph (`app/schemas/panels.py`) and resolves it server-side; client-supplied
  joints/relations/positions are dropped, never trusted.
- `openapi.json` is the committed contract. After ANY schema/route change:
  `python scripts/export_openapi.py` and commit it (CI + `tests/test_openapi_snapshot.py` fail otherwise).
  The modeller generates its TS types from it (`npm run api:types` in 3d_modeler).
- Quality gates: `ruff check .`, `mypy`, `pytest`.

## Constraint resolver
`app/services/resolve.py` ports the modeller's `resolveConstraints` (the server resolves the RAW graph itself). Scope,
failure handling, deliberate differences and how it is verified (goldens + differential fuzz against the real JS) are
in `docs/RESOLVER.md`.

## Joint detection
`app/services/joints.py` ports `detectJoints` / `detectFeatureJoints`; `POST /v1/joints` resolves the RAW graph itself and
returns contact joints, collisions and door-hinge / drawer-slide joints. Scope, thresholds and verification: `docs/JOINTS.md`.

## Security
API key and / or per-user JWT, rate limits, structured logs, nesting in worker processes: `docs/SECURITY.md`.
`ENV=production` refuses to start without auth configured.

## Assembly plan
`app/rules/assembly/` ports `engine/assembly/*` + `engine/ergonomics.js`; `POST /v1/assembly` resolves, detects joints,
plans hardware and returns ordered `steps`, `clusters`, `toolsSummary` — see `docs/ASSEMBLY.md`.

## Hardware plan
`app/rules/hardware.py` (catalogs + selectors) and `app/services/hardware.py` (orchestration) port `engine/hardware.js`;
`POST /v1/hardware-plan` resolves the RAW graph and computes the joints itself. Rules, boundaries and verification:
`docs/HARDWARE.md`.

## Golden fixtures + parity with the original JS engine
`tests/test_golden.py` runs every (stage x design) of the frozen goldens (`tests/golden_harness.py`):
BOM and nesting must equal the ORIGINAL JS engine's output (`legacyBom/legacyNesting.json`, produced by the modeller's
`npm run golden:legacy` from the pre-migration code). Stages not ported yet (sequence, assembly) are
strict xfails: when a port starts passing, flip `ported=True` in the harness. The run prints a per-stage report.

Nesting guard rails (`NESTING_TIMEOUT_S`, `MAX_CONCURRENT_NESTINGS` -> `503 nesting_timeout` / `503 busy`), the
decision to keep the guillotine port instead of rectpack, and the invariant tests are in `docs/NESTING.md`.

`GET /v1/catalog/materials` sends an `ETag` + `Cache-Control: no-cache`; `If-None-Match` -> 304.
`tests/golden/<design>/` = frozen output of the original JS engine (from `3d_modeler/fixtures/golden`) + BOM/nesting
baselines. Refresh with `python scripts/dump_golden.py ..\3d_modeler\fixtures\golden`.

## Structure
```
app/main.py            app factory, CORS, lifespan (loads catalog once)
app/config.py          env settings
app/deps.py            catalog + optional X-API-Key auth
app/routers/           health, catalog, bom, nesting
app/services/          bom.py, nesting.py  (ports of engine/bom.js, engine/nesting.js)
app/schemas/           pydantic models (panels.py = raw request, engine.py = rules-chain responses, limits.py)
app/rules/             RULES_VERSION / CONTRACT_VERSION (rules themselves land here in phases 8-9)
app/errors.py          error envelope + handlers
app/middleware.py      body-size limit (413), X-Rules-Version header
scripts/               dump_golden.py, export_openapi.py
app/catalog/           loader.py + data/materials.csv
tests/                 pytest (nesting verified identical to the JS reference)
Dockerfile             container deploy (reads $PORT)
```

## Deploy
Any container host (Fly.io, Render, Cloud Run): build the `Dockerfile`, set env vars from `.env.example`
(`CORS_ORIGINS` = site + modeller origins, `API_KEYS` for beta). Custom domain e.g. `api.<domain>`.
