from pathlib import Path
from domainup.config import Config
from domainup.renderers.nginx import render_all


def test_render_vhost_snapshot(tmp_path: Path):
    cfg = Config.model_validate({
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "nginx",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "domains": [
            {
                "host": "data.example.com",
                "upstreams": [{"name": "otel", "target": "otel:4318"}],
                "paths": [{
                    "path": "~* ^/(v1/|otlp/v1/)(traces|logs|metrics)",
                    "upstream": "otel",
                    "body_size": "20m",
                }],
                "tls": {"enabled": True},
            }
        ],
    })
    render_all(cfg, cwd=tmp_path)
    vhost_file = tmp_path / "nginx" / "conf.d" / "data.example.com.conf"
    assert vhost_file.exists()
    text = vhost_file.read_text()
    assert "server_name data.example.com;" in text
    assert "client_max_body_size 20m;" in text
