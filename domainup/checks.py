from __future__ import annotations

import subprocess
from rich import print


def run_checks(domain: str) -> None:
    print(f"[cyan]→ Checking DNS A/AAAA for[/] {domain}")
    subprocess.run(["bash", "-lc", f"dig +short A {domain} || true"], check=False)
    subprocess.run(["bash", "-lc", f"dig +short AAAA {domain} || true"], check=False)

    print("[cyan]→ curl -I https://domain[/]")
    subprocess.run(["bash", "-lc", f"curl -Is https://{domain} | head -n1 || true"], check=False)

    print("[cyan]→ TLS dates[/]")
    subprocess.run(["bash", "-lc", f"openssl s_client -connect {domain}:443 -servername {domain} </dev/null 2>/dev/null | openssl x509 -noout -dates"], check=False)
