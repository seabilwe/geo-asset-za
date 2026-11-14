"""The public API: answers from the api schema, validates input and exposes no write operations."""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_kpis(client):
    k = client.get("/api/kpis").json()
    assert k["total_assets"] > 10000 and k["open_work_orders"] >= 0


def test_assets_filtered_by_class_and_condition(client):
    fc = client.get("/api/assets", params={"class": "LIGHT", "condition": 5}).json()
    assert fc["type"] == "FeatureCollection"
    assert all(f["properties"]["t"] == "STREETLIGHT" and f["properties"]["g"] == 5 for f in fc["features"])


def test_assets_bbox(client):
    fc = client.get("/api/assets", params={"bbox": "28.230,-25.755,28.240,-25.745", "limit": 50}).json()
    assert 0 < len(fc["features"]) <= 50


def test_asset_detail_and_history(client):
    code = client.get("/api/assets", params={"type": "STREETLIGHT", "limit": 1}).json()["features"][0]["properties"]["c"]
    a = client.get(f"/api/assets/{code}").json()
    assert a["asset_code"] == code and "lamp_type" in a["details"] and a["history"]


def test_unknown_asset_is_404(client):
    assert client.get("/api/assets/XX-000000").status_code == 404


@pytest.mark.parametrize("params", [{"bbox": "1,2,3"}, {"condition": 9}, {"class": "roads; drop table"}, {"limit": 999999}])
def test_bad_input_rejected(client, params):
    assert client.get("/api/assets", params=params).status_code == 422


def test_no_write_methods(client):
    assert client.post("/api/assets", json={}).status_code in (404, 405)
    assert client.delete("/api/assets/SL-000001").status_code in (404, 405)
