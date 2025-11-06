from __future__ import annotations

from pathlib import Path
from datetime import datetime
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
    nginx_conf_path = out_root / "nginx.conf"
    if nginx_conf_path.exists() and nginx_conf_path.is_dir():
        # Defensive auto-fix: rename the directory to a timestamped backup and proceed.
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = out_root / f"nginx.conf.backup-{ts}"
        try:
            nginx_conf_path.rename(backup_dir)
            print(f"[yellow]Renamed directory[/] {nginx_conf_path} → {backup_dir}")
        except Exception as e:
            raise IsADirectoryError(
                f"Found a directory at {nginx_conf_path} and could not rename it automatically: {e}.\n"
                "Please remove or rename it so DomainUp can write nginx.conf as a file."
            )
    nginx_conf_path.write_text(
        nginx_conf_t.render(client_max_body="20m")
    )

    # 00-redirect (only create if there are TLS-enabled domains)
    tls_hosts = [d.host for d in cfg.domains if d.tls.enabled]
    redirect_file = conf_d / "00-redirect.conf"
    if tls_hosts:
        redirect_t = env.get_template("00-redirect.conf.j2")
        redirect_file.write_text(redirect_t.render(domains=tls_hosts))
    elif redirect_file.exists():
        # Remove the file if it exists but there are no TLS domains
        redirect_file.unlink()
        print("[dim]Removed 00-redirect.conf (no TLS-enabled domains)[/]")

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
