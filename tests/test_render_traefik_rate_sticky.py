from pathlib import Path
from domainup.config import Config
from domainup.renderers.traefik import render_all


def test_traefik_rate_limit_and_sticky(tmp_path: Path):
    cfg = Config.model_validate({
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "traefik",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "domains": [
            {
                "host": "throttle.example.com",
                "upstreams": [{"name": "app", "target": "app:8000"}],
                "paths": [{"path": "/", "upstream": "app"}],
                "security": {"rate_limit": {"enabled": True, "requests_per_minute": 120}},
                "sticky_cookie": "SESSIONID",
                "tls": {"enabled": True},
            }
        ],
    })
    render_all(cfg, cwd=tmp_path)

    yml = (tmp_path / "traefik" / "dynamic" / "throttle.example.com.yml").read_text()
    assert "_ratelimit:" in yml and "rateLimit:" in yml
    assert "average: 2" in yml  # 120 rpm -> 2 rps
    assert "sticky:" in yml and "cookie:" in yml and "SESSIONID" in yml
