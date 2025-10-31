from pathlib import Path
import yaml
from domainup.config import load_config, Config


def test_load_and_validate_tmp(tmp_path: Path):
    cfg_data = {
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "nginx",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "domains": [
            {
                "host": "api.example.com",
                "upstreams": [{"name": "app", "target": "app:8000"}],
                "paths": [{"path": "/", "upstream": "app", "websocket": True}],
                "tls": {"enabled": True},
            }
        ],
    }
    p = tmp_path / "domainup.yaml"
    p.write_text(yaml.safe_dump(cfg_data))
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.domains[0].paths[0].websocket is True
