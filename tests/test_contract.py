"""Phase 2: the contract + trust boundary (validation, limits, error codes)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.rules import CONTRACT_VERSION, RULES_VERSION
from app.schemas.engine import (
    AssemblyResponse,
    Collision,
    FeatureJoint,
    HardwarePlanResponse,
    Joint,
    JointsResponse,
)
from app.schemas.limits import MAX_PANELS
from app.schemas.panels import PanelSet, RawPanelNode, ResolvedPanel
from tests.conftest import panel

GOLDEN = Path(__file__).parent / "golden"
DESIGNS = sorted(p.name for p in GOLDEN.iterdir() if p.is_dir())
ENGINE_ROUTES = ["/v1/joints", "/v1/hardware-plan", "/v1/assembly"]
NOT_PORTED_ROUTES: list[str] = []  # every engine route is live since phase 9b


def golden(design: str, stage: str):
    return json.loads((GOLDEN / design / f"{stage}.json").read_text(encoding="utf-8"))


def raw_node(id="a", **kw):
    return {"id": id, "name": id, "material": "Melamine White 18mm", "width": 400, "height": 700, "thickness": 18, **kw}


# ------------------------------------------------------------------ goldens fit the contract
@pytest.mark.parametrize("design", DESIGNS)
def test_raw_goldens_parse_and_lose_no_field(design):
    raw = golden(design, "raw")
    PanelSet.model_validate({"panels": raw})
    known = {f.alias or n for n, f in RawPanelNode.model_fields.items()}
    for node in raw:
        assert set(node) <= known, f"{design}: contract misses fields {set(node) - known}"


@pytest.mark.parametrize("design", DESIGNS)
def test_resolved_goldens_fit_resolved_model(design):
    for node in golden(design, "resolved"):
        ResolvedPanel.model_validate(node)


@pytest.mark.parametrize("design", [d for d in DESIGNS if (GOLDEN / d / "joints.json").is_file()])
def test_joints_goldens_fit_response_models(design):
    j = golden(design, "joints")
    fj = golden(design, "featureJoints")
    JointsResponse.model_validate({**j, "featureJoints": fj})
    [Joint.model_validate(x) for x in j["joints"]]
    [Collision.model_validate(x) for x in j["collisions"]]
    [FeatureJoint.model_validate(x) for x in fj]


@pytest.mark.parametrize("design", [d for d in DESIGNS if (GOLDEN / d / "hardware.json").is_file()])
def test_hardware_golden_and_live_assembly_fit_response_models(client, design):
    HardwarePlanResponse.model_validate(golden(design, "hardware"))
    # the assembly golden is the frozen LEGACY JS output (prose only); the contract now also requires the structured
    # wording (phase 10), so the model is checked against the live response, which must also pass its own response_model
    r = client.post("/v1/assembly", json={"panels": golden(design, "raw")})
    assert r.status_code == 200
    AssemblyResponse.model_validate(r.json())


# ------------------------------------------------------------------ limits & hostile input
@pytest.mark.parametrize("path", ["/v1/bom", "/v1/nesting"] + ENGINE_ROUTES)
@pytest.mark.parametrize(
    "bad",
    [
        {"width": -1}, {"width": 0}, {"height": 99999}, {"thickness": 0}, {"thickness": 1e6},
        {"id": "x" * 500}, {"material": "m" * 500},
    ],
)
def test_bad_dimensions_422(client, path, bad):
    body_node = (panel("A", 400, 700) | bad) if path in ("/v1/bom", "/v1/nesting") else raw_node(**bad)
    r = client.post(path, json={"panels": [body_node]})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_nan_and_infinity_rejected(client):
    body = b'{"panels":[{"id":"a","name":"a","material":"m","width":NaN,"height":700,"thickness":18}]}'
    r = client.post("/v1/joints", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_too_many_panels_422(client):
    r = client.post("/v1/joints", json={"panels": [raw_node(f"p{i}") for i in range(MAX_PANELS + 1)]})
    assert r.status_code == 422
    r = client.post("/v1/bom", json={"panels": [panel(f"p{i}", 100, 100) for i in range(MAX_PANELS + 1)]})
    assert r.status_code == 422


def test_max_panels_accepted(client):
    r = client.post("/v1/bom", json={"panels": [panel(f"p{i}", 100, 100) for i in range(MAX_PANELS)]})
    assert r.status_code == 200


def test_duplicate_ids_422(client):
    r = client.post("/v1/joints", json={"panels": [raw_node("a"), raw_node("a")]})
    assert r.status_code == 422


def test_constraint_to_unknown_panel_is_a_warning_not_a_request_error(client):
    c = {"id": "c1", "type": "spansBetween", "field": "width",
         "from": {"node": "ghost", "face": "front", "offset": 0}, "to": {"node": "ghost", "face": "back", "offset": 0}}
    assert client.post("/v1/joints", json={"panels": [raw_node("a", constraints=[c])]}).status_code == 200  # accepted
    from app.services.resolve import resolve_constraints

    (r,) = resolve_constraints(PanelSet.model_validate({"panels": [raw_node("a", constraints=[c])]}).panels)
    assert r["warnings"] == ['references missing panel "ghost"']


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "spansBetween", "field": "width"},                       # needs from + to
        {"type": "attachedTo", "field": "positionX"},                     # needs from
        {"type": "distance", "from": {"node": "a", "face": "top"}},       # needs field
        {"type": "equalSpacing", "field": "positionY", "from": {"node": "a", "face": "top"}},  # needs to
        {"type": "spansBetween", "field": "bogus", "from": {"node": "a"}, "to": {"node": "a"}},  # unknown field
    ],
)
def test_incomplete_constraints_are_rejected(client, bad):
    r = client.post("/v1/joints", json={"panels": [raw_node("a", constraints=[bad])]})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_validation_error_does_not_echo_input(client):
    r = client.post("/v1/joints", json={"panels": [raw_node("a", width="SECRET-VALUE")]})
    assert r.status_code == 422
    assert "SECRET-VALUE" not in r.text


def test_oversize_body_413(client):
    big = json.dumps({"panels": [], "pad": "x" * 2_100_000}).encode()
    r = client.post("/v1/bom", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"


def test_oversize_chunked_body_413(client):
    def chunks():
        yield b'{"panels": [], "pad": "'
        for _ in range(25):
            yield b"x" * 100_000
        yield b'"}'

    r = client.post("/v1/bom", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ------------------------------------------------------------------ rules-chain
@pytest.mark.parametrize("path", ENGINE_ROUTES)
def test_client_supplied_joints_are_ignored_not_trusted(client, path):
    body = {"panels": [raw_node("a", relations=[{"kind": "joint"}])],
            "joints": [{"id": "evil"}], "hardware": [{"id": "evil"}]}
    r = client.post(path, json=body)
    assert r.status_code == (501 if path in NOT_PORTED_ROUTES else 200)  # accepted-and-dropped, never a 422
    assert "evil" not in r.text, "client-supplied joints/hardware must never reach the response"
    assert "joints" not in PanelSet.model_validate(body).model_dump()
    assert not hasattr(RawPanelNode.model_validate(body["panels"][0]), "relations")


def test_joints_endpoint_is_live_and_resolves_the_raw_graph_itself(client):
    """Two touching panels given only as RAW nodes: the server resolves them and finds the joint."""
    a = raw_node("a", width=400, height=400, rotation={"x": 0, "y": 0, "z": 0})
    b = raw_node("b", width=400, height=400, rotation={"x": 0, "y": 0, "z": 0}, basePosition={"x": 0, "y": 0, "z": 18})
    r = client.post("/v1/joints", json={"panels": [a, b]})
    assert r.status_code == 200
    body = r.json()
    assert [j["type"] for j in body["joints"]] == ["face_to_face"] and body["collisions"] == [] and body["featureJoints"] == []
    assert body["joints"][0]["id"] == "a:b:z" and (body["joints"][0]["faceA"], body["joints"][0]["faceB"]) == ("front", "back")


# ------------------------------------------------------------------ auth + versioning
def test_api_key_error_has_stable_code(client):
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys="k1")
    try:
        r = client.post("/v1/bom", json={"panels": []})
        assert r.status_code == 401 and r.json()["code"] == "invalid_api_key"
        assert client.post("/v1/bom", json={"panels": []}, headers={"X-API-Key": "k1"}).status_code == 200
        assert client.post("/v1/joints", json={"panels": []}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_version_endpoint_and_header(client):
    r = client.get("/v1/version")
    assert r.status_code == 200
    assert r.json() == {"apiVersion": "0.1.0", "rulesVersion": RULES_VERSION, "contractVersion": CONTRACT_VERSION}
    assert r.headers["x-rules-version"] == RULES_VERSION
    assert client.post("/v1/bom", json={"panels": []}).headers["x-rules-version"] == RULES_VERSION


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/v1/nope")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_cors_allows_modeller_origin_and_exposes_rules_version():
    with TestClient(app) as c:
        r = c.options("/v1/bom", headers={"Origin": "http://localhost:5173",
                                          "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type,x-api-key"})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
        g = c.get("/health", headers={"Origin": "http://localhost:5173"})
        assert "x-rules-version" in g.headers["access-control-expose-headers"].lower()
