from __future__ import annotations

import subprocess
from pathlib import Path
from rich import print


def compose_up(engine: str, cwd: Path, network: str) -> None:
    if engine == "nginx":
        compose_file = cwd / "runtime" / "docker-compose.nginx.yml"
        # Always ensure compose file reflects current network
        _ensure_runtime_compose(cwd, network)
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
        _ensure_traefik_runtime_compose(cwd, network)
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


def nginx_reload() -> None:
    print("[cyan]→ docker exec nginx_proxy nginx -s reload[/]")
    subprocess.run(["docker", "exec", "nginx_proxy", "nginx", "-s", "reload"], check=False)


def _ensure_runtime_compose(cwd: Path, network: str) -> None:
    runtime_dir = cwd / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    compose_file = runtime_dir / "docker-compose.nginx.yml"
    # Read config to get host ports
    from .config import load_config
    cfg = load_config(cwd / "domainup.yaml")
    http_port = cfg.runtime.http_port
    https_port = cfg.runtime.https_port
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


def _ensure_traefik_runtime_compose(cwd: Path, network: str) -> None:
        runtime_dir = cwd / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        compose_file = runtime_dir / "docker-compose.traefik.yml"
        from .config import load_config
        cfg = load_config(cwd / "domainup.yaml")
        http_port = cfg.runtime.http_port
        https_port = cfg.runtime.https_port
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
        subprocess.run(["docker", "network", "create", name], check=True)
