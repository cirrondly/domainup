from domainup.dns_providers.cloudflare import ensure_dns_records_cloudflare


class DummyResp:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def test_cloudflare_upsert(monkeypatch):
    calls = {"get": [], "post": [], "put": []}

    def fake_get(url, headers=None, params=None, timeout=15):
        calls["get"].append((url, params))
        if url.endswith("/zones"):
            # simulate zone lookup by name
            name = params.get("name")
            if name == "example.com":
                return DummyResp(200, {"result": [{"id": "z1", "name": "example.com"}]})
            return DummyResp(200, {"result": []})
        if "/dns_records" in url:
            # no existing records
            return DummyResp(200, {"result": []})
        raise AssertionError("unexpected GET")

    def fake_post(url, headers=None, json=None, timeout=15):
        calls["post"].append((url, json))
        return DummyResp(200, {"result": {"id": "r1"}})

    def fake_put(url, headers=None, json=None, timeout=15):
        calls["put"].append((url, json))
        return DummyResp(200, {"result": {"id": "r1"}})

    import domainup.dns_providers.cloudflare as cf
    monkeypatch.setattr(cf.requests, "get", fake_get)
    monkeypatch.setattr(cf.requests, "post", fake_post)
    monkeypatch.setattr(cf.requests, "put", fake_put)

    ensure_dns_records_cloudflare("token", "api.example.com", "203.0.113.10", None)

    # A record created
    assert any("/dns_records" in url for url, _ in calls["post"])  # created
    created_payloads = [j for _, j in calls["post"]]
    assert any(p["type"] == "A" and p["name"] == "api.example.com" and p["content"] == "203.0.113.10" for p in created_payloads)
