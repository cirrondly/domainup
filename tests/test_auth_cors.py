from pathlib import Path
from domainup.config import Config
from domainup.renderers.nginx import render_all


def test_basic_auth_and_cors_render(tmp_path: Path):
    cfg = Config.model_validate({
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "nginx",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "domains": [
            {
                "host": "secure.example.com",
                "upstreams": [{"name": "app", "target": "app:8000"}],
                "paths": [{"path": "/", "upstream": "app"}],
                "security": {
                    "basic_auth": {"enabled": True, "users": ["admin:{SHA}deadbeef"]}
                },
                "cors_passthrough": True,
                "tls": {"enabled": True},
            }
        ],
    })
    render_all(cfg, cwd=tmp_path)

    vhost_file = tmp_path / "nginx" / "conf.d" / "secure.example.com.conf"
    assert vhost_file.exists()
    text = vhost_file.read_text()
    assert "auth_basic \"Restricted\";" in text
    assert "auth_basic_user_file /etc/nginx/htpasswd/secure.example.com.htpasswd;" in text
    assert "Access-Control-Allow-Origin" in text

    hp = tmp_path / "nginx" / "htpasswd" / "secure.example.com.htpasswd"
    assert hp.exists()
    assert "admin:{SHA}deadbeef" in hp.read_text()
