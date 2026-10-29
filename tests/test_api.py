from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["suppliers"] > 0


def test_filters():
    allr = client.get("/api/suppliers").json()
    fish = client.get("/api/suppliers", params={"category": "fish"}).json()
    assert 0 < fish["count"] < allr["count"]
    assert all(any(c["id"] == "fish" for c in s["categories"]) for s in fish["suppliers"])
    ekb = client.get("/api/suppliers", params={"region": "ekb"}).json()
    assert all("ekb" in s["regions"] or "russia" in s["regions"] for s in ekb["suppliers"])


def test_collect_validates_query():
    assert client.get("/api/collect", params={"q": "x"}).status_code == 422


def test_static_ui_served():
    r = client.get("/")
    assert r.status_code == 200 and "Supply Scout" in r.text
    assert client.get("/data/suppliers.json").status_code == 200
