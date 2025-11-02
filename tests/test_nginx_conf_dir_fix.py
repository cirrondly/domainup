from pathlib import Path
from domainup.config import Config
from domainup.renderers.nginx import render_all


def test_renderer_auto_renames_nginx_conf_dir(tmp_path: Path):
    # Create a conflicting directory where a file should be written
    (tmp_path / "nginx" / "nginx.conf").mkdir(parents=True, exist_ok=True)

    cfg = Config.model_validate({
        "version": 1,
        "email": "contact@cirrondly.com",
        "engine": "nginx",
        "cert": {"method": "webroot", "webroot_dir": "./www/certbot"},
        "network": "proxy_net",
        "domains": [
            {
                "host": "example.com",
                "upstreams": [{"name": "app", "target": "app:8000"}],
                "paths": [{"path": "/", "upstream": "app"}],
                "tls": {"enabled": True},
            }
        ],
    })

    render_all(cfg, cwd=tmp_path)

    # Now we should have a file at nginx/nginx.conf and a backup directory
    nginx_conf = tmp_path / "nginx" / "nginx.conf"
    assert nginx_conf.exists() and nginx_conf.is_file()

    backups = list((tmp_path / "nginx").glob("nginx.conf.backup-*"))
    assert backups, "Expected a backup directory to be created for the old nginx.conf dir"
    assert backups[0].is_dir()
