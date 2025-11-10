import json
from pathlib import Path
from domainup.commands.discover_cmd import discover_services


class _Res:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_discover_services_cli_fallback(monkeypatch, tmp_path):
    # Force SDK import failure by shadowing import inside0 module
    import domainup.commands.discover_cmd as mod
    mod._try_import_docker = lambda: None

    # Mock subprocess.run for `docker ps` and `docker inspect`
    def fake_run(args, capture_output=False, text=False):
        if args[:2] == ["docker", "ps"]:
            out = (
                "abc123\tweb_1\tmyrepo/web:latest\n"
                "def456\tgrafana\tgrafana/grafana:10\n"
            )
            return _Res(0, out, "")
        if args[:2] == ["docker", "inspect"]:
            cid = args[2]
            if cid == "abc123":
                obj = [{
                    "Config": {"Image": "myrepo/web:latest"},
                    "NetworkSettings": {
                        "Ports": {
                            "8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}],
                            "9000/udp": None,
                        }
                    }
                }]
            else:
                obj = [{
                    "Config": {"Image": "grafana/grafana:10"},
                    "NetworkSettings": {
                        "Ports": {
                            "3000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3000"}],
                        }
                    }
                }]
            return _Res(0, json.dumps(obj), "")
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr("subprocess.run", fake_run)

    services = discover_services()
    names = [s["name"] for s in services]
    assert "web_1" in names
    assert "grafana" in names
    web = next(s for s in services if s["name"] == "web_1")
    assert web["published"] == [("8000/tcp", "0.0.0.0", "8000")]
