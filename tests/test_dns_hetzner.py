from typing import Any

from domainup.dns_providers.hetzner import ensure_dns_records_hetzner


class DummyResp:
    def __init__(self, status_code: int, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def test_hetzner_upsert(monkeypatch):
    calls = {"get": [], "post": [], "put": []}

    def fake_get(url, headers=None, params=None, timeout=15):
        calls["get"].append((url, params))
        if url.endswith("/zones"):
            return DummyResp(200, {"zones": [{"id": "z1", "name": "example.com"}]})
        if url.endswith("/records"):
            # no existing records
            return DummyResp(200, {"records": []})
        raise AssertionError("unexpected GET")

    def fake_post(url, headers=None, json=None, timeout=15):
        calls["post"].append((url, json))
        return DummyResp(201, {"record": {"id": "r1"}})

    def fake_put(url, headers=None, json=None, timeout=15):
        calls["put"].append((url, json))
        return DummyResp(200, {"record": {"id": "r1"}})

    import domainup.dns_providers.hetzner as hz
    monkeypatch.setattr(hz.requests, "get", fake_get)
    monkeypatch.setattr(hz.requests, "post", fake_post)
    monkeypatch.setattr(hz.requests, "put", fake_put)

    ensure_dns_records_hetzner("token", "api.example.com", "203.0.113.10", None)

    # should have created one A record under label 'api'
    assert any("/records" in url for url, _ in calls["post"])  # created
    created_payloads = [j for _, j in calls["post"]]
    assert any(p["type"] == "A" and p["name"] == "api" and p["value"] == "203.0.113.10" for p in created_payloads)
