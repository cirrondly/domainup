from __future__ import annotations

import subprocess
from pathlib import Path
from rich import print
from .config import Config


PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net"}


def obtain_certs_webroot(cfg: Config, cwd: Path) -> None:
    webroot = Path(cfg.cert.webroot_dir)
    if not webroot.is_absolute():
        webroot = cwd / cfg.cert.webroot_dir
    le_dir = cwd / "letsencrypt"
    webroot.mkdir(parents=True, exist_ok=True)
    le_dir.mkdir(parents=True, exist_ok=True)

    # Build domain list, skip placeholders and obvious non-public hosts
    issue_hosts = []
    skipped = []
    for d in cfg.domains:
        if not d.tls.enabled:
            continue
        host = d.host.strip()
        if host.endswith(".example.com") or host.endswith(".example.org") or host.endswith(".example.net") or host in PLACEHOLDER_HOSTS or host in {"localhost"}:
            skipped.append(host)
            continue
        issue_hosts.append(host)

    if skipped:
        print(f"[yellow]Skipping non-issuable placeholder hosts:[/] {', '.join(skipped)}")

    if not issue_hosts:
        print("[red]No valid public domains to issue. Update domainup.yaml with real FQDNs that point to this server.[/]")
        return

    domains_args = sum(( ["-d", h] for h in issue_hosts ), [])

    print("[cyan]→ certbot certonly --webroot[/]")
    args = [
        "docker", "run", "--rm",
        "-v", f"{webroot}:/var/www/certbot",
        "-v", f"{le_dir}:/etc/letsencrypt",
        "certbot/certbot", "certonly", "--webroot", "-w", "/var/www/certbot",
        *domains_args,
        "--agree-tos", "-m", cfg.email, "--no-eff-email",
    ]
    if cfg.cert.staging:
        args.append("--staging")

    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = proc.stderr or proc.stdout or "certbot failed"
        if "forbidden by policy" in msg:
            print("[red]Let's Encrypt refused to issue for one or more domains. Ensure you're not using example.com and that DNS points to this server.[/]")
        elif "Connection refused" in msg or "Invalid response" in msg:
            print("[red]ACME HTTP-01 validation failed. Port 80 must be reachable from the internet to the Nginx container's port 80.[/]")
            print("Hint: free host port 80 or use DNS-01 (roadmap) if port 80 cannot be opened.")
        else:
            print(msg)
        raise SystemExit(proc.returncode)
