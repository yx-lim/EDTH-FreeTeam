"""Switching the area of operations while running: POST /zone swaps map, tracker and nets, and back again."""
from fastapi.testclient import TestClient

import backend.app as app_module
from backend import zone


def test_switch_to_irpin_and_back():
    client = TestClient(app_module.app)
    names = [z["name"] for z in client.get("/state").json()["zones"]]
    assert names[0] == "paris" and "irpin" in names
    try:
        assert client.post("/zone", json={"name": "irpin"}).json()["lang"] == "uk"
        state = client.get("/state").json()
        assert state["zone"]["name"] == "irpin" and round(state["centre"][1]) == 51   # Irpin, not Paris (48.85)
        assert app_module.gaz.find("Центрального ринку")[0].name == "Центральний ринок"
        assert {c["name"] for c in state["custom_places"]} >= {"Ромашка", "Водокачка"}
    finally:
        client.post("/zone", json={"name": "paris"})
    assert zone.NAME == "paris" and app_module.gaz.find("Panthéon")[0].name == "Panthéon"


def test_unknown_zone_is_refused():
    client = TestClient(app_module.app)
    assert client.post("/zone", json={"name": "atlantis"}).status_code == 400
    assert zone.NAME == "paris"
