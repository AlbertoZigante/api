# Architecture (after the migration, phase 12)

## Who does what
| | `3d_modeler` (browser) | `api` (this repo, FastAPI) |
|---|---|---|
| Role | **thin client**: draw, drag, snap, validate live, render | **all business rules** that decide *what to build and how* |
| Owns | 3D scene, constraint resolver (`snap.js`), live joint detection for snapping, clearance checks, validator, quotes, spacing, PDF / manual rendering, i18n | BOM, nesting, constraint resolution, joints, hardware plan, assembly plan (sequence, tools, ergonomics), catalog, auth, limits |
| Trust | never trusted: the server re-resolves the RAW graph and re-detects joints itself | trusts nothing the client sends beyond the raw panels |

The browser sends only RAW panels (`POST` body `{panels: [...]}`, mm); every plan comes back computed. Nothing about hardware,
assembly order, tools or ergonomics exists in the client bundle (`npm run test:bundle` fails if it does).
The few duplicated rules left in the client (`engine/hardware.js`: hinge / connector selection for *live clearance*) are listed
in that file's header and in `docs/HARDWARE.md`.

## Endpoints
`GET /health`, `GET /v1/version` (open) · `GET /v1/catalog/materials` · `POST /v1/bom` · `POST /v1/nesting` · `POST /v1/joints` ·
`POST /v1/hardware-plan` · `POST /v1/assembly`. Auth, limits, errors: `docs/SECURITY.md`. Contract: `openapi.json` (+ the modeller's `schema.d.ts`).

## Code layout
```
app/
  main.py config.py auth.py ratelimit.py logs.py middleware.py errors.py deps.py concurrency.py nesting_runner.py
  schemas/      Pydantic models = the contract (panels in; bom, nesting, joints, hardware, assembly out)
  routers/      thin: validate -> call a service -> return
  services/     pure logic, no FastAPI: bom, nesting, resolve, geometry, joints, hardware (plan)
  rules/        data-driven rule layers: hardware.py (catalogs + selectors), assembly/ (roles, clusters, scoring,
                stages, emitter, human wording, ergonomics), collation.py, js.py (JS semantics the ports reproduce)
  catalog/      materials data
tests/          see below            scripts/   export_openapi, export_steps_fixtures, update_golden, loadtest, issue_token
docs/           one page per layer: RESOLVER JOINTS HARDWARE ASSEMBLY NESTING SECURITY MIGRATION
```

## How it is tested (what protects what)
| layer | where | protects |
|---|---|---|
| frozen JS answers, 20 designs x 8 stages | `tests/golden/*`, `test_golden.py` | the contract inherited from the original JS engine |
| frozen JS corpus, 703 designs | `tests/golden/corpus.jsonl.gz`, `test_golden_corpus.py` | the same, at fuzz scale (every joint tolerance, hardware boundary, plinth / drawer / door variant) |
| unit + invariants | `test_*_unit.py`, `test_assembly_structured.py` | rules at their boundaries, step order, prose <-> structured wording, determinism, trust boundary |
| contract | `test_contract.py`, `test_openapi_snapshot.py`, modeller `api:types:check` | request / response shapes, error envelope |
| security | `test_auth.py`, `test_rate_limit.py` | JWT / API key / limits / logs |
| runtime | `test_nesting_runner.py`, `scripts/loadtest.py` | worker processes, timeouts, health under load |
| browser | modeller `tests/e2e/smoke.mjs` | the real app in Chromium against the real API |

## Changing a rule (checklist)
1. Change `app/rules/*` or `app/services/*`, with a unit test for the new behaviour.
2. Bump `RULES_VERSION` (`app/rules/__init__.py`): clients drop cached plans when it changes.
3. If a golden / corpus expectation changes ON PURPOSE: `python scripts/update_golden.py --stage <stage>` and review the diff. (The corpus is
   frozen JS output: for an intentional change, edit the expectation by regenerating that part from the API and say why in the commit.)
4. Assembly wording or codes: `python scripts/export_steps_fixtures.py --out ../3d_modeler/fixtures/api-steps`, add the translation in
   the modeller's `src/i18n/stepStrings.js` (a test fails until fr and it exist), `python scripts/export_openapi.py` + `npm run api:types`.

## The JS engine is gone — and how to get it back
The original client-side engine (BOM, nesting, hardware plan, assembly, ergonomics, and the golden generators / differential tests that ran
Python against it) is in git history: tag `pre-phase12` in both repos (`git checkout pre-phase12`). The differential tests were replaced by the frozen corpus above.
