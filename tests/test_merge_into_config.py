from pathlib import Path
import yaml
from domainup.commands.discover_cmd import merge_into_config
from domainup.config import load_config


def test_merge_into_config_idempotent(tmp_path: Path):
    cfg_path = tmp_path / "domainup.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "nginx",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "runtime": {"http_port": 80, "https_port": 443},
        "domains": [],
    }, sort_keys=False))

    mapping = [{
        "host": "api.example.com",
        "upstreams": [{"name": "back_web_1", "target": "back_web_1:8000", "weight": 1}],
        "paths": [{"path": "/", "upstream": "back_web_1", "websocket": True, "strip_prefix": False}],
        "headers": {"hsts": True, "extra": {}},
        "security": {"basic_auth": {"enabled": False, "users": []}, "allow_ips": [], "rate_limit": {"enabled": False, "requests_per_minute": 600}},
        "tls": {"enabled": True},
        "gzip": True,
        "cors_passthrough": False,
        "lb": "round_robin",
        "sticky_cookie": None,
    }]

    merge_into_config(mapping, cwd=tmp_path)
    merge_into_config(mapping, cwd=tmp_path)  # run twice to assert idempotency

    cfg = load_config(cfg_path)
    assert len(cfg.domains) == 1
    d = cfg.domains[0]
    # upstream not duplicated
    assert len(d.upstreams) == 1
    assert d.upstreams[0].target == "back_web_1:8000"
    # path not duplicated
    assert len(d.paths) == 1
    assert d.paths[0].websocket is True
