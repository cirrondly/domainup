from __future__ import annotations

import subprocess
from pathlib import Path
import os
import json
from rich import print
from .config import load_config


def compose_up(
    engine: str,
    cwd: Path,
    network: str,
    http_port: int | None = None,
    https_port: int | None = None,
) -> None:
    _require_docker_daemon()
    # Ensure dummy self-signed certs exist so Nginx can start before Let's Encrypt issuance
    try:
        cfg = load_config(cwd / "domainup.yaml")
        _ensure_dummy_certs(cwd, cfg)
    except Exception as e:
        # Non-fatal; certificate generation is a best-effort convenience
        print(f"[dim]Skipping dummy cert preparation:[/] {e}")
    if engine == "nginx":
        compose_file = cwd / "runtime" / "docker-compose.nginx.yml"
        # Always ensure compose file reflects current network
        _ensure_runtime_compose(cwd, network, http_port=http_port, https_port=https_port)
        _ensure_docker_network(network)
        print("[cyan]→ docker compose up -d (nginx)[/]")
        proc = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            msg = proc.stderr or proc.stdout or "unknown error"
            if "port is already allocated" in msg:
                print("[red]Failed: ports 80/443 already in use on host.[/]")
                print("Tip: set custom host ports in domainup.yaml under 'runtime:http_port/https_port' and re-run 'domainup render' then 'domainup up'.")
            else:
                print(msg)
            raise SystemExit(proc.returncode)
    elif engine == "traefik":
        compose_file = cwd / "runtime" / "docker-compose.traefik.yml"
        _ensure_traefik_runtime_compose(cwd, network, http_port=http_port, https_port=https_port)
        _ensure_docker_network(network)
        print("[cyan]→ docker compose up -d (traefik)[/]")
        proc = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "unknown error")
            raise SystemExit(proc.returncode)
    else:
        raise ValueError("unknown engine")


def _ensure_dummy_certs(cwd: Path, cfg) -> None:
    """Create short-lived self-signed certs for TLS hosts that lack files.

    This allows Nginx to start before Let's Encrypt certs are issued. Certs are
    generated under ./letsencrypt/live/<host> (same path certbot uses), with
    1-day validity and only for bootstrapping.
    """
    le_root = cwd / "letsencrypt" / "live"
    for d in getattr(cfg, "domains", []) or []:
        try:
            if not getattr(d.tls, "enabled", True):
                continue
        except Exception:
            continue
        host = d.host
        target_dir = le_root / host
        fullchain = target_dir / "fullchain.pem"
        privkey = target_dir / "privkey.pem"
        if fullchain.exists() and privkey.exists():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        # Use openssl to generate a self-signed cert quickly
        cmd = [
            "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
            "-days", "1", "-subj", f"/CN={host}",
            "-keyout", str(privkey), "-out", str(fullchain),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            # Clean up partial files on failure
            try:
                if fullchain.exists():
                    fullchain.unlink()
                if privkey.exists():
                    privkey.unlink()
            except Exception:
                pass
            print("[yellow]openssl not available or failed; Nginx may fail until certs are issued via domainup cert.[/]")


def nginx_reload() -> None:
    print("[cyan]→ docker exec nginx_proxy nginx -s reload[/]")
    subprocess.run(["docker", "exec", "nginx_proxy", "nginx", "-s", "reload"], check=False)


def _ensure_runtime_compose(cwd: Path, network: str, *, http_port: int | None = None, https_port: int | None = None) -> None:
    runtime_dir = cwd / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    compose_file = runtime_dir / "docker-compose.nginx.yml"
    # Read config to get host ports
    from .config import load_config
    cfg = load_config(cwd / "domainup.yaml")
    http_port = http_port if http_port is not None else cfg.runtime.http_port
    https_port = https_port if https_port is not None else cfg.runtime.https_port
    # NOTE: Keep indentation in this YAML template exact; Docker's YAML parser is strict.
    content = f"""
services:
    nginx:
        image: nginx:1.25
        container_name: nginx_proxy
        restart: unless-stopped
        ports: ["{http_port}:80", "{https_port}:443"]
        volumes:
            - ../nginx/conf.d:/etc/nginx/conf.d:ro
            - ../nginx/nginx.conf:/etc/nginx/nginx.conf:ro
            - ../nginx/htpasswd:/etc/nginx/htpasswd:ro
            - ../www/certbot:/var/www/certbot
            - ../letsencrypt:/etc/letsencrypt
            - ../var/log/nginx:/var/log/nginx
        networks: [{network}]

networks:
    {network}:
        external: true
""".lstrip()
    compose_file.write_text(content)


def _ensure_traefik_runtime_compose(cwd: Path, network: str, *, http_port: int | None = None, https_port: int | None = None) -> None:
    runtime_dir = cwd / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    compose_file = runtime_dir / "docker-compose.traefik.yml"
    from .config import load_config
    cfg = load_config(cwd / "domainup.yaml")
    http_port = http_port if http_port is not None else cfg.runtime.http_port
    https_port = https_port if https_port is not None else cfg.runtime.https_port
    content = f"""
services:
    traefik:
        image: traefik:v3.0
        container_name: traefik_proxy
        restart: unless-stopped
        command:
            - --providers.file.directory=/etc/traefik/dynamic
            - --providers.file.watch=true
            - --entrypoints.web.address=:80
            - --entrypoints.websecure.address=:443
        ports: ["{http_port}:80", "{https_port}:443"]
        volumes:
            - ../traefik/traefik.yml:/etc/traefik/traefik.yml:ro
            - ../traefik/dynamic:/etc/traefik/dynamic:ro
            - ../traefik/htpasswd:/etc/traefik/htpasswd:ro
            - ../letsencrypt:/letsencrypt
        networks: [{network}]

networks:
    {network}:
        external: true
""".lstrip()
    compose_file.write_text(content)


def _ensure_docker_network(name: str) -> None:
    # Create external network if missing
    inspect = subprocess.run(["docker", "network", "inspect", name], capture_output=True)
    if inspect.returncode != 0:
        print(f"[cyan]→ docker network create {name}[/]")
        try:
            subprocess.run(["docker", "network", "create", name], check=True)
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or b"" ) if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or "")
            text = msg.decode() if isinstance(msg, (bytes, bytearray)) else str(msg)
            if "Cannot connect to the Docker daemon" in (text or ""):
                _print_docker_not_running_help()
            raise


def _require_docker_daemon() -> None:
    """Ensure we can talk to Docker; print actionable help if not."""
    proc = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if proc.returncode == 0:
        return
    msg = (proc.stderr or proc.stdout or "").strip()
    if "Cannot connect to the Docker daemon" in msg or "Is the docker daemon running" in msg:
        _print_docker_not_running_help()
    # Exit nicely instead of later stacktrace
    raise SystemExit(1)


def _print_docker_not_running_help() -> None:
    dh = os.environ.get("DOCKER_HOST", "")
    if dh:
        print(f"[yellow]Docker seems unreachable. DOCKER_HOST is set to[/] [dim]{dh}[/].")
    print("[red]Cannot connect to Docker daemon.[/]")
    print("Try one of the following on macOS:")
    print("- Start Docker Desktop: open -a Docker")
    print("- If you use Colima: colima start")
    print("- If you use OrbStack: open -a OrbStack")
    print("Then re-run: domainup up")


def discover_network_targets(network: str) -> list[dict]:
    """Discover containers attached to a Docker network and their internal ports.

    Returns a list of dict entries with keys: id, name, service, project, aliases, ports (list[int]).
    Ports are container-internal exposed ports (from Config.ExposedPorts), suitable for upstream targets.
    """
    # Inspect network to get container IDs and aliases
    proc = subprocess.run(["docker", "network", "inspect", network], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or f"Failed to inspect network {network}")
    data = json.loads(proc.stdout)
    if not data:
        return []
    containers = data[0].get("Containers") or {}
    results: list[dict] = []
    for cid, cinfo in containers.items():
        name = cinfo.get("Name")
        # fetch more details
        insp = subprocess.run(["docker", "inspect", cid], capture_output=True, text=True)
        if insp.returncode != 0:
            continue
        arr = json.loads(insp.stdout)
        cfg = (arr[0].get("Config") or {}) if arr else {}
        labels = cfg.get("Labels") or {}
        service = labels.get("com.docker.compose.service") or ""
        project = labels.get("com.docker.compose.project") or ""
        exposed = cfg.get("ExposedPorts") or {}
        ports: list[int] = []
        for k in exposed.keys():
            try:
                p = int(str(k).split("/")[0])
                ports.append(p)
            except Exception:
                pass
        # Collect aliases (including the container's attached network alias, if any)
        # From network inspect we can get only the container's name; aliases require container inspect
        net_settings = (arr[0].get("NetworkSettings") or {}) if arr else {}
        aliases: list[str] = []
        networks = net_settings.get("Networks") or {}
        if network in networks:
            aliases = (networks[network].get("Aliases") or [])
        results.append({
            "id": cid,
            "name": name,
            "service": service,
            "project": project,
            "aliases": aliases,
            "ports": sorted(set(ports)),
        })
    return results
