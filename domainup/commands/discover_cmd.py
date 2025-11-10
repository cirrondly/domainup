from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import subprocess
import re
import yaml

from ..config import load_config, Config, DomainConfig, Upstream, PathRoute
from ..localhost_discovery import discover_localhost_services


# Types
ServiceInfo = Dict[str, Any]
MappingEntry = Dict[str, Any]


def _try_import_docker():
    try:
        import docker  # type: ignore
        return docker
    except Exception:
        return None


def discover_services(include_network_only: bool = True, include_localhost: bool = True) -> List[ServiceInfo]:
    """Detect running containers that either publish TCP ports OR are on proxy_net, plus localhost services.

        Returns a list of dicts with keys:
      - name: container name or localhost service name
      - image: image name (empty for localhost services)
      - published: list of tuples (container_port, host_ip, host_port) as strings
      - networks: list of network names this container is attached to (empty for localhost)
      - exposed: list of exposed ports (if no published ports but on proxy network)
      - localhost: boolean flag (True for localhost services, False/missing for Docker)

    Uses Docker SDK if available; falls back to `docker ps` + `docker inspect`.
    Filters: TCP only; published ports OR on proxy_net; excludes nginx_proxy, certbot.
    
    Args:
        include_network_only: If True, also includes containers on proxy_net without published ports
        include_localhost: If True, also scans for localhost services on common dev ports
    """
    # Get Docker services
    docker_services = _discover_docker_services(include_network_only)
    
    # Get localhost services if requested
    localhost_services = []
    if include_localhost:
        try:
            localhost_services_raw = discover_localhost_services()
            # Convert localhost services to the same format as Docker services
            for service in localhost_services_raw:
                localhost_services.append({
                    "name": service["name"],
                    "image": "",  # No image for localhost services
                    "published": [(f"{service['port']}/tcp", "127.0.0.1", str(service['port']))],
                    "networks": [],  # No networks for localhost services
                    "exposed": [],
                    "localhost": True,  # Mark as localhost service
                    "type": "localhost",  # Add type field for identification
                    "port": service["port"],
                    "process": service.get("process", "unknown")
                })
        except Exception:
            # If localhost discovery fails, continue with just Docker services
            pass
    
    # Combine and return both types
    return docker_services + localhost_services


def _discover_docker_services(include_network_only: bool = True) -> List[ServiceInfo]:
    """Internal function to discover Docker services only."""
    EXCLUDE = {"nginx_proxy", "certbot"}
    PROXY_NETWORKS = {"proxy_net", "proxy-net", "proxy_network"}

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
                    if bindings and "/tcp" in str(container_port):
                        for b in bindings or []:
                            host_ip = (b or {}).get("HostIp")
                            host_port = (b or {}).get("HostPort")
                            if host_port:
                                published.append((str(container_port), str(host_ip or "0.0.0.0"), str(host_port)))
                
                # Collect networks
                networks = list(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys())
                
                # Get exposed ports (even if not published)
                exposed_ports = list((info.get("Config") or {}).get("ExposedPorts", {}).keys())
                exposed = [p.split("/")[0] for p in exposed_ports if "/tcp" in p]
                
                # Include if: has published ports OR (on proxy network AND has exposed ports)
                on_proxy_net = include_network_only and any(net in PROXY_NETWORKS for net in networks)
                if published or (on_proxy_net and exposed):
                    results.append({
                        "name": c.name,
                        "image": (info.get("Config") or {}).get("Image", ""),
                        "published": published,
                        "networks": networks,
                        "exposed": exposed if not published else [],
                        "localhost": False,  # Mark as Docker service
                    })
            return results
        except Exception:
            # Fall through to CLI fallback
            results = []

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
                if bindings and "/tcp" in str(container_port):
                    for b in bindings or []:
                        host_ip = (b or {}).get("HostIp")
                        host_port = (b or {}).get("HostPort")
                        if host_port:
                            published.append((str(container_port), str(host_ip or "0.0.0.0"), str(host_port)))
            
            # Get exposed ports (even if not published)
            exposed_ports = list((info.get("Config") or {}).get("ExposedPorts", {}).keys())
            exposed = [p.split("/")[0] for p in exposed_ports if "/tcp" in p]
            
            # Include if: has published ports OR (on proxy network AND has exposed ports)
            on_proxy_net = include_network_only and any(net in PROXY_NETWORKS for net in networks)
            if published or (on_proxy_net and exposed):
                out.append({
                    "name": name,
                    "image": image,
                    "published": published,
                    "networks": networks,
                    "exposed": exposed if not published else [],
                    "localhost": False,  # Mark as Docker service
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

    docker_count = len([s for s in services if not s.get("localhost", False)])
    localhost_count = len([s for s in services if s.get("localhost", False)])
    
    print("Found {} service(s):\n".format(len(services)))
    if docker_count > 0:
        print(f"  Docker containers: {docker_count}")
    if localhost_count > 0:
        print(f"  Localhost services: {localhost_count}")
    print()
    
    for idx, s in enumerate(services, start=1):
        pubs = s.get("published", []) or []
        exposed = s.get("exposed", []) or []
        is_localhost = s.get("localhost", False)
        
        if pubs:
            # Deduplicate by (container_port, host_port), prefer IPv4 if both exist
            seen_pairs = set()
            deduped = []
            for cp, hip, hp in pubs:
                key = (cp, hp)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                deduped.append((cp, hip, hp))
            for cp, hip, hp in deduped:
                service_type = "[localhost]" if is_localhost else "[docker]  "
                print(f"[{idx}] {service_type} {s['name']:<15} → {cp:<8} → {hip}:{hp}")
        elif exposed:
            # Show exposed ports (on proxy network but not published)
            nets = ", ".join(s.get("networks", []))
            print(f"[{idx}] [docker]   {s['name']:<15} → expose: {'/'.join(exposed)} on [{nets}]")

    mappings: List[MappingEntry] = []

    for s in services:
        pubs = s.get("published", []) or []
        exposed = s.get("exposed", []) or []
        if not pubs and not exposed:
            continue
        # Ask if user wants to add this service
        add_q = questionary.confirm(f"Add service {s['name']}?", default=True)
        add_it = bool(add_q.ask()) if hasattr(add_q, "ask") else bool(add_q)
        if not add_it:
            continue
        
        container_port: str = ""
        host_port: str = ""
        use_docker_dns = False
        is_localhost = s.get("localhost", False)
        
        if pubs:
            # Has published ports
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
        elif exposed:
            # Only exposed ports (on proxy network) - use Docker DNS
            use_docker_dns = True
            if len(exposed) == 1:
                container_port = exposed[0]
            else:
                import questionary
                container_port = questionary.select(
                    f"Select exposed port for {s['name']}", choices=exposed
                ).ask() or exposed[0]
            host_port = container_port
        
        # Ensure container_port is set for localhost services
        if not container_port and is_localhost:
            container_port = str(s.get("port", 80))
            host_port = container_port
            
        defaults = _heuristic_defaults(s["name"], container_port)

        suggested = _suggest_host(s["name"], base_domain or "example.com")
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
        
        # Choose target based on service type
        proxy_net = (cfg.network if cfg else "proxy_net")
        if is_localhost:
            # For localhost services, always route via host.docker.internal
            target = f"host.docker.internal:{int(host_port)}"
        elif use_docker_dns or proxy_net in (set(s.get("networks") or [])):
            # Use Docker DNS (service name directly accessible on network)
            target = f"{s['name']}:{int(str(container_port).split('/')[0])}"
        else:
            # Use host.docker.internal for published ports
            target = f"host.docker.internal:{int(host_port)}"
            
        # Guard against routing to host ports 80/443 which likely loop back to DomainUp itself
        if not is_localhost:  # Only apply this check for Docker services
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
