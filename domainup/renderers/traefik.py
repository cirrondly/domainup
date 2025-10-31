from __future__ import annotations

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from ..config import Config
from rich import print


def _templates_dir() -> Path:
    return Path(__file__).parent.parent / "templates" / "traefik"


def render_all(cfg: Config, cwd: Path) -> None:
    out_root = cwd / "traefik"
    dyn = out_root / "dynamic"
    htpasswd_dir = out_root / "htpasswd"
    out_root.mkdir(parents=True, exist_ok=True)
    dyn.mkdir(parents=True, exist_ok=True)
    htpasswd_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(_templates_dir())),
        autoescape=select_autoescape(disabled_extensions=(".j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # static traefik.yml (minimal)
    traefik_t = env.get_template("traefik.yml.j2")
    (out_root / "traefik.yml").write_text(traefik_t.render())

    # per-host dynamic
    host_t = env.get_template("host.yml.j2")
    for d in cfg.domains:
        (dyn / f"{d.host}.yml").write_text(host_t.render(domain=d))
        # htpasswd support if basic auth is enabled
        try:
            if getattr(d.security.basic_auth, "enabled", False):
                users = list(getattr(d.security.basic_auth, "users", []) or [])
                hp_file = htpasswd_dir / f"{d.host}.htpasswd"
                if users:
                    hp_file.write_text("\n".join(users) + "\n")
                else:
                    hp_file.touch(exist_ok=True)
                    print(f"[yellow]Traefik: basic_auth enabled for {d.host} but no users provided. Populate traefik/htpasswd/{d.host}.htpasswd[/]")
        except Exception as e:
            print(f"[red]Traefik: failed to write htpasswd for {d.host}:[/] {e}")
