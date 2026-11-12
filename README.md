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

JSON is camelCase on the wire (same field names as the modeller).

## Structure
```
app/main.py            app factory, CORS, lifespan (loads catalog once)
app/config.py          env settings
app/deps.py            catalog + optional X-API-Key auth
app/routers/           health, catalog, bom, nesting
app/services/          bom.py, nesting.py  (ports of engine/bom.js, engine/nesting.js)
app/schemas/           pydantic models
app/catalog/           loader.py + data/materials.csv
tests/                 pytest (nesting verified identical to the JS reference)
Dockerfile             container deploy (reads $PORT)
```

## Deploy
Any container host (Fly.io, Render, Cloud Run): build the `Dockerfile`, set env vars from `.env.example`
(`CORS_ORIGINS` = site + modeller origins, `API_KEYS` for beta). Custom domain e.g. `api.<domain>`.


## Languages (en / fr / it)

The API is deliberately **locale-neutral**: it never translates. Clients (site, 3D modeller) translate.

- Every error body is `{ "detail": <English text>, "code": <stable code> }` — codes: `invalid_api_key`,
  `validation_error`, `invalid_input`. Translate by `code`.
- BOM rows keep the English `label` / `assembly` (stable: used for sorting and nesting ids) and add
  `assemblyKind` (`none | box | drawer | group`) and `assemblyIndex` so clients can render
  "Tiroir 2" / "Cassetto 2" themselves. Use `bandedEdges` (not `bandedEdgesLabel`) to localise edge letters.
- Material names come from the catalog (`app/catalog/data/materials.csv`) and are shown as-is.
