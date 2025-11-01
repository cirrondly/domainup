from pathlib import Path
from domainup.config import Config
from domainup.renderers.traefik import render_all


def test_traefik_advanced_headers(tmp_path: Path):
    cfg = Config.model_validate({
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "traefik",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "domains": [
            {
                "host": "headers.example.com",
                "upstreams": [{"name": "app", "target": "app:8000"}],
                "paths": [{"path": "/", "upstream": "app"}],
                "headers": {
                    "hsts": True,
                    "extra": {
                        "X-Frame-Options": "DENY",
                        "X-Content-Type-Options": "nosniff"
                    }
                },
                "tls": {"enabled": True},
            }
        ],
    })
    render_all(cfg, cwd=tmp_path)

    yml = (tmp_path / "traefik" / "dynamic" / "headers.example.com.yml").read_text()

    # Router includes the headers middleware
    assert "middlewares:" in yml and "headers_example_com_headers" in yml

    # Middleware definition includes custom response headers
    assert "customResponseHeaders:" in yml
    assert "X-Frame-Options" in yml and "DENY" in yml
    assert "X-Content-Type-Options" in yml and "nosniff" in yml

    # HSTS fields present
    assert "stsSeconds: 15768000" in yml
    assert "stsIncludeSubdomains: true" in yml
    assert "stsPreload: true" in yml
