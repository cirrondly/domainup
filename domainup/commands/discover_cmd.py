from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import subprocess
import re
import yaml

from ..config import load_config, Config, DomainConfig, Upstream, PathRoute


# Types
ServiceInfo = Dict[str, Any]
MappingEntry = Dict[str, Any]


def _try_import_docker():
    try:
        import docker  # type: ignore
        return docker
    except Exception:
        return None


def discover_services() -> List[ServiceInfo]:
    """Detect running containers that publish TCP ports on the host.

        Returns a list of dicts with keys:
      - name: container name
      - image: image name
      - published: list of tuples (container_port, host_ip, host_port) as strings
            - networks: list of network names this container is attached to

    Uses Docker SDK if available; falls back to `docker ps` + `docker inspect`.
    Filters: only TCP; only published ports; excludes nginx_proxy, certbot by default.
    """
    EXCLUDE = {"nginx_proxy", "certbot"}

    docker = _try_import_docker()
    results: List[ServiceInfo] = []

    if docker is not None:
        try:
            cli = docker.from_env()
            for c in cli.containers.list():
                if c.name in EXCLUDE:
                    continue
                info = c.attrs or {}
                ports = (info.get("NetworkSettings") or {}).get("Ports") or {}
                published: List[Tuple[str, str, str]] = []
                for container_port, bindings in ports.items():
                    if not bindings:
                        continue
                    if "/tcp" not in str(container_port):
                        continue
                    for b in bindings or []:
                        host_ip = (b or {}).get("HostIp")
                        host_port = (b or {}).get("HostPort")
                        if host_port:
                            published.append((str(container_port), str(host_ip or "0.0.0.0"), str(host_port)))
                # collect networks
                networks = list(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys())
                if published:
                    results.append({
                        "name": c.name,
                        "image": (info.get("Config") or {}).get("Image", ""),
                        "published": published,
                        "networks": networks,
                    })
            return results
        except Exception:
            # Fall through to CLI fallback
            pass

    # CLI fallback
    try:
        ps = subprocess.run([
            "docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"
        ], capture_output=True, text=True)
        if ps.returncode != 0:
            return []
        out: List[ServiceInfo] = []
        for line in (ps.stdout or "").strip().splitlines():
            if not line:
                continue
            cid, name, image = line.split("\t")
            if name in EXCLUDE:
                continue
            insp = subprocess.run(["docker", "inspect", cid], capture_output=True, text=True)
            if insp.returncode != 0:
                continue
            arr = json.loads(insp.stdout or "[]")
            if not arr:
                continue
            info = arr[0]
            ns = (info.get("NetworkSettings") or {})
            ports = (ns.get("Ports") or {})
            networks = list((ns.get("Networks") or {}).keys())
            published: List[Tuple[str, str, str]] = []
            for container_port, bindings in ports.items():
                if not bindings:
                    continue
                if "/tcp" not in str(container_port):
                    continue
                for b in bindings or []:
                    host_ip = (b or {}).get("HostIp")
                    host_port = (b or {}).get("HostPort")
                    if host_port:
                        published.append((str(container_port), str(host_ip or "0.0.0.0"), str(host_port)))
            if published:
                out.append({
                    "name": name,
                    "image": image,
                    "published": published,
                    "networks": networks,
                })
        return out
    except Exception:
        return []


def _infer_base_domain(cfg: Optional[Config]) -> str:
    if cfg and cfg.domains:
        # Take first domain and drop the first label
        try:
            host = cfg.domains[0].host
            parts = host.split(".")
            if len(parts) >= 2:
                return ".".join(parts[1:])
        except Exception:
            pass
    return "example.com"


def _heuristic_defaults(name: str, container_port: str) -> Dict[str, Any]:
    port_num = int(str(container_port).split("/")[0]) if container_port else 0
    return {
        "websocket": bool(re.search(r"\bweb|ws\b", name, re.IGNORECASE)),
        "body_size": "20m" if port_num == 4318 else None,
        "basic_auth": bool(re.search(r"grafana", name, re.IGNORECASE)),
    }


def _suggest_host(name: str, base_domain: str) -> str:
    # Ensure name is a valid DNS label
    safe = re.sub(r"[^a-z0-9-]", "-", name.lower())
    safe = re.sub(r"-+", "-", safe).strip("-") or "app"
    return f"{safe}.{base_domain}"


def interactive_map(services: List[ServiceInfo], *, base_domain: Optional[str] = None, cwd: Optional[Path] = None) -> List[MappingEntry]:
    """Ask the user to map each service to a domain and options.

    Returns a list of mapping entries to merge into config. Each entry is:
      { host, upstreams: [...], paths: [...], tls: {enabled: True}, security: {...} }
    """
    # Lazy import so tests do not require the dependency
    import questionary  # type: ignore

    cwd = cwd or Path.cwd()
    cfg: Optional[Config]
    try:
        cfg = load_config(cwd / "domainup.yaml")
    except Exception:
        cfg = None

    base_domain = base_domain or _infer_base_domain(cfg)
    base_domain = questionary.text("Base domain (for suggestions)", default=base_domain).ask() or base_domain

    print("Found {} containers with published ports:\n".format(len(services)))
    for idx, s in enumerate(services, start=1):
        # Deduplicate by (container_port, host_port), prefer IPv4 if both exist
        seen_pairs = set()
        deduped = []
        for cp, hip, hp in s.get("published", []) or []:
            key = (cp, hp)
            if key in seen_pairs:
                # prefer IPv4 over IPv6 display
                continue
            seen_pairs.add(key)
            deduped.append((cp, hip, hp))
        for cp, hip, hp in deduped:
            print(f"[{idx}] {s['name']:<15} → {cp:<8} → {hip}:{hp}")

    mappings: List[MappingEntry] = []

    for s in services:
        pubs = s.get("published") or []
        if not pubs:
            continue
        # Ask if user wants to add this service
        add_q = questionary.confirm(f"Add service {s['name']}?", default=True)
        add_it = bool(add_q.ask()) if hasattr(add_q, "ask") else bool(add_q)
        if not add_it:
            continue
        choice: Tuple[str, str, str]
        # Deduplicate choices by (container_port, host_port)
        seen = {}
        for cp, hip, hp in pubs:
            key = (cp, hp)
            # prefer IPv4 over IPv6 if duplicates
            if key not in seen or (seen[key][1].startswith("::") and not str(hip).startswith("::")):
                seen[key] = (cp, hip, hp)
        options_list = list(seen.values())
        if len(options_list) == 1:
            choice = options_list[0]
        else:
            # Present choices like "8000/tcp → 0.0.0.0:8000"
            import questionary  # local
            options = [f"{cp} → {hip}:{hp}" for (cp, hip, hp) in options_list]
            pick = questionary.select(
                f"Select port for {s['name']}", choices=options
            ).ask()
            idx = options.index(pick)
            choice = options_list[idx]

        container_port, _host_ip, host_port = choice
        defaults = _heuristic_defaults(s["name"], container_port)

        suggested = _suggest_host(s["name"], base_domain)
        fqdn = questionary.text(
            f"Choose domain for {s['name']} (suggest: {suggested})",
            default=suggested,
        ).ask() or suggested

        ws = questionary.confirm("Enable websockets?", default=bool(defaults["websocket"]))
        ws_val = bool(ws.ask()) if hasattr(ws, "ask") else bool(ws)

        # body_size for OTLP
        body_size: Optional[str] = None
        if defaults["body_size"]:
            bs = questionary.confirm("Large body (20m) for OTLP?", default=True)
            use_bs = bool(bs.ask()) if hasattr(bs, "ask") else bool(bs)
            body_size = "20m" if use_bs else None

        # Basic auth suggestion for grafana
        basic = False
        if defaults["basic_auth"]:
            ba = questionary.confirm("Protect with Basic Auth?", default=False)
            basic = bool(ba.ask()) if hasattr(ba, "ask") else bool(ba)

        up_name = re.sub(r"[^a-z0-9_\-]", "_", s["name"].lower()) or "app"
        # Choose target: if service is on proxy network, use container name + container_port.
        # Otherwise, route via host published port using host.docker.internal.
        proxy_net = (cfg.network if cfg else "proxy_net")
        networks = set(s.get("networks") or [])
        if proxy_net in networks:
            target = f"{s['name']}:{int(str(container_port).split('/')[0])}"
        else:
            target = f"host.docker.internal:{int(host_port)}"
            # Guard against routing to host ports 80/443 which likely loop back to DomainUp itself
            try:
                hp = int(host_port)
            except Exception:
                hp = 0
            if hp in {80, 443}:
                warn = questionary.confirm(
                    f"Upstream {target} uses host port {hp}. This may loop with DomainUp (listening on {hp}). Proceed?",
                    default=False,
                )
                proceed = bool(warn.ask()) if hasattr(warn, "ask") else bool(warn)
                if not proceed:
                    print(
                        "[skip] Skipping service due to potential loop. Attach it to the proxy network and re-run discovery."
                    )
                    continue
        upstream = {
            "name": up_name,
            "target": target,
            "weight": 1,
        }
        path_entry = {
            "path": "/",
            "upstream": up_name,
            "websocket": ws_val,
            "strip_prefix": False,
        }
        if body_size:
            path_entry["body_size"] = body_size

        security = {
            "basic_auth": {
                "enabled": bool(basic),
                "users": [],
            },
            "allow_ips": [],
            "rate_limit": {"enabled": False, "requests_per_minute": 600},
        }

        mappings.append({
            "host": fqdn,
            "upstreams": [upstream],
            "paths": [path_entry],
            "headers": {"hsts": True, "extra": {}},
            "security": security,
            "tls": {"enabled": True},
            "gzip": True,
            "cors_passthrough": False,
            "lb": "round_robin",
            "sticky_cookie": None,
        })

    return mappings


def _merge_domain(existing: DomainConfig, new: MappingEntry) -> DomainConfig:
    # Upstreams: upsert by name
    up_by = {u.name: u for u in existing.upstreams}
    for u in new.get("upstreams", []) or []:
        nm = u["name"]
        if nm in up_by:
            up_by[nm].target = u.get("target", up_by[nm].target)
            up_by[nm].weight = int(u.get("weight", up_by[nm].weight))
        else:
            existing.upstreams.append(Upstream.model_validate(u))

    # Paths: ensure one path per path+upstream pair; update flags/body_size if provided
    existing_pairs = {(p.path, p.upstream): p for p in existing.paths}
    for p in new.get("paths", []) or []:
        key = (p.get("path", "/"), p.get("upstream"))
        if key in existing_pairs:
            ep = existing_pairs[key]
            ep.websocket = bool(p.get("websocket", ep.websocket))
            ep.strip_prefix = bool(p.get("strip_prefix", ep.strip_prefix))
            if p.get("body_size"):
                ep.body_size = str(p["body_size"])
        else:
            existing.paths.append(PathRoute.model_validate(p))

    # tls stays enabled by default; basic auth merging: if either enables, enable
    try:
        if new.get("security", {}).get("basic_auth", {}).get("enabled"):
            existing.security.basic_auth.enabled = True
    except Exception:
        pass

    return existing


def merge_into_config(mappings: List[MappingEntry], *, cwd: Optional[Path] = None) -> Path:
    """Load domainup.yaml and upsert provided domain mappings idempotently.

    Returns path to the updated config file.
    """
    cwd = cwd or Path.cwd()
    path = cwd / "domainup.yaml"

    # Load existing or create minimal skeleton if missing
    cfg: Optional[Config] = None
    if path.exists():
        cfg = load_config(path)
    else:
        # Minimal viable config; ask nothing (interactive flow should have asked email earlier if needed)
        data = {
            "version": 1,
            "email": "contact@example.com",
            "engine": "nginx",
            "cert": {"method": "webroot", "webroot_dir": "./www/certbot", "staging": False},
            "network": "proxy_net",
            "runtime": {"http_port": 80, "https_port": 443},
            "domains": [],
        }
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        cfg = load_config(path)

    domains_by_host = {d.host: d for d in cfg.domains}
    for m in mappings:
        host = m["host"]
        if host in domains_by_host:
            updated = _merge_domain(domains_by_host[host], m)
            domains_by_host[host] = updated
        else:
            cfg.domains.append(DomainConfig.model_validate(m))

    # Write back
    payload = json.loads(cfg.model_dump_json())
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return path


def detect_unmapped_services(cfg: Config, services: List[ServiceInfo]) -> List[ServiceInfo]:
    """Return services whose container name is not referenced in any upstream target."""
    existing_targets = []
    for d in cfg.domains:
        for u in d.upstreams:
            try:
                host = str(u.target).split(":")[0]
                if host:
                    existing_targets.append(host)
            except Exception:
                pass
    existing_set = set(existing_targets)
    return [s for s in services if s.get("name") not in existing_set]
