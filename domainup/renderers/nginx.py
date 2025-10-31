from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from jinja2 import Environment, FileSystemLoader, select_autoescape
from ..config import Config, DomainConfig
from rich import print


def _templates_dir() -> Path:
    return Path(__file__).parent.parent / "templates" / "nginx"


def render_all(cfg: Config, cwd: Path) -> None:
    out_root = cwd / "nginx"
    conf_d = out_root / "conf.d"
    htpasswd_dir = out_root / "htpasswd"
    out_root.mkdir(parents=True, exist_ok=True)
    conf_d.mkdir(parents=True, exist_ok=True)
    htpasswd_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(_templates_dir())),
        autoescape=select_autoescape(disabled_extensions=(".j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # nginx.conf
    nginx_conf_t = env.get_template("nginx.conf.j2")
    (out_root / "nginx.conf").write_text(
        nginx_conf_t.render(client_max_body="20m")
    )

    # 00-redirect
    redirect_t = env.get_template("00-redirect.conf.j2")
    tls_hosts = [d.host for d in cfg.domains if d.tls.enabled]
    (conf_d / "00-redirect.conf").write_text(
        redirect_t.render(domains=tls_hosts)
    )

    # vhosts
    vhost_t = env.get_template("vhost.conf.j2")
    for d in cfg.domains:
        # write vhost
        (conf_d / f"{d.host}.conf").write_text(_render_vhost(vhost_t, d))
        # write htpasswd if basic auth is enabled
        try:
            if getattr(d.security.basic_auth, "enabled", False):
                users = list(getattr(d.security.basic_auth, "users", []) or [])
                hp_file = htpasswd_dir / f"{d.host}.htpasswd"
                if users:
                    # Users are expected to be htpasswd-formatted lines (e.g., user:{SHA}hash)
                    hp_file.write_text("\n".join(users) + "\n")
                else:
                    # Create empty file but warn
                    hp_file.touch(exist_ok=True)
                    print(f"[yellow]basic_auth enabled for {d.host} but no users provided. Populate nginx/htpasswd/{d.host}.htpasswd[/]")
        except Exception as e:
            print(f"[red]Failed to write htpasswd for {d.host}:[/] {e}")


def _render_vhost(template, d: DomainConfig) -> str:
    upstream_by_name = {u.name: u for u in d.upstreams}
    ctx: Dict[str, Any] = {
        "host": d.host,
        "upstreams": d.upstreams,
        "paths": d.paths,
        "headers": d.headers,
        "security": d.security,
        "tls": d.tls,
        "gzip": d.gzip,
        "cors_passthrough": d.cors_passthrough,
        "lb": d.lb,
        "sticky_cookie": d.sticky_cookie,
        "upstream_by_name": upstream_by_name,
    }
    return template.render(**ctx)
