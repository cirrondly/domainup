from pathlib import Path
from domainup.config import Config
from domainup.renderers.traefik import render_all


def test_render_traefik_middlewares(tmp_path: Path):
    cfg = Config.model_validate({
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "traefik",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "domains": [
            {
                "host": "secure.example.com",
                "upstreams": [{"name": "app", "target": "app:8000"}],
                "paths": [{"path": "/", "upstream": "app"}],
                "security": {
                    "basic_auth": {"enabled": True, "users": ["admin:{SHA}cafebabe"]}
                },
                "cors_passthrough": True,
                "tls": {"enabled": True},
            }
        ],
    })
    render_all(cfg, cwd=tmp_path)

    host_yaml = tmp_path / "traefik" / "dynamic" / "secure.example.com.yml"
    assert host_yaml.exists()
    text = host_yaml.read_text()
    # router must reference auth and cors middlewares (order/content may include others)
    assert "secure_example_com_auth" in text and "secure_example_com_cors" in text
    # middlewares definitions present
    assert "basicAuth:" in text and "usersFile:" in text
    assert "/etc/traefik/htpasswd/secure.example.com.htpasswd" in text
    assert "headers:" in text and "accessControlAllowOriginList" in text

    hp = tmp_path / "traefik" / "htpasswd" / "secure.example.com.htpasswd"
    assert hp.exists()
    assert "admin:{SHA}cafebabe" in hp.read_text()
