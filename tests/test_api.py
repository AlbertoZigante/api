from tests.conftest import panel


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_materials(client):
    r = client.get("/v1/catalog/materials")
    assert r.status_code == 200
    assert r.json()[0]["sheetWidthMm"] == 2440


def test_bom_camel_case_roundtrip(client):
    body = {"panels": [panel("A", 400, 700, groupId="g", isBoxPanel=True, bandedEdges=["left"])]}
    r = client.post("/v1/bom", json=body)
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert row["widthMm"] == 400 and row["assembly"] == "Box 1" and row["bandedEdgesLabel"] == "L"


def test_nesting(client):
    r = client.post("/v1/nesting", json={"panels": [panel("A", 400, 700), panel("B", 400, 700)]})
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["totals"]["sheetsUsed"] == 1
    assert j["results"][0]["sheets"][0]["placements"][0]["finishedWidthMm"] in (400, 700)


def test_bad_payload_422(client):
    assert client.post("/v1/bom", json={"panels": [{"id": "x"}]}).status_code == 422


def test_bom_assembly_kind_and_index(client):
    body = {"panels": [
        panel("A", 400, 700, groupId="g1", isBoxPanel=True),
        panel("B", 300, 200, groupId="g2", isDrawerFront=True),
        panel("C", 100, 100, groupId="g3"),
        panel("D", 50, 50),
    ]}
    rows = {r["pieceNames"][0]: r for r in client.post("/v1/bom", json=body).json()["rows"]}
    assert (rows["A"]["assemblyKind"], rows["A"]["assemblyIndex"], rows["A"]["assembly"]) == ("box", 1, "Box 1")
    assert (rows["B"]["assemblyKind"], rows["B"]["assemblyIndex"]) == ("drawer", 1)
    assert (rows["C"]["assemblyKind"], rows["C"]["assemblyIndex"]) == ("group", 1)
    assert (rows["D"]["assemblyKind"], rows["D"]["assemblyIndex"]) == ("none", None)


def test_validation_error_has_code(client):
    r = client.post("/v1/bom", json={"panels": [{"id": "x"}]})
    assert r.status_code == 422 and r.json()["code"] == "validation_error" and isinstance(r.json()["detail"], list)


def test_invalid_api_key_has_code(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("API_KEYS", "secret")
    get_settings.cache_clear()
    try:
        r = client.post("/v1/bom", json={"panels": []}, headers={"X-API-Key": "nope"})
        assert r.status_code == 401
        assert r.json() == {"detail": "Invalid or missing API key", "code": "invalid_api_key"}
    finally:
        monkeypatch.delenv("API_KEYS")
        get_settings.cache_clear()


def test_invalid_nesting_option_has_code(client):
    r = client.post("/v1/nesting", json={"panels": [panel("A", 400, 700)], "options": {"kerfMm": -1}})
    assert r.status_code == 422 and "code" in r.json()
