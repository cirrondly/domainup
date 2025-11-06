from __future__ import annotations

import subprocess
from pathlib import Path
import shutil
import os
from rich import print
from .config import Config


PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net"}


def _preflight_checks(hosts: list[str], webroot: Path, cwd: Path) -> None:
	"""Run pre-flight checks before certificate issuance."""
	issues = []
	
	# Check 1: ACME challenge directory exists and is writable
	acme_dir = webroot / ".well-known" / "acme-challenge"
	if not acme_dir.exists():
		try:
			acme_dir.mkdir(parents=True, exist_ok=True)
			print(f"  [green]✔[/green] Created ACME challenge directory: {acme_dir}")
		except Exception as e:
			issues.append(f"Cannot create ACME directory {acme_dir}: {e}")
	
	# Check 2: Test file write to webroot
	test_file = acme_dir / ".domainup-test"
	try:
		test_file.write_text("test")
		test_file.unlink()
		print(f"  [green]✔[/green] Webroot is writable")
	except Exception as e:
		issues.append(f"Webroot not writable at {acme_dir}: {e}")
	
	# Check 3: DNS resolution for all hosts
	import socket
	for host in hosts:
		try:
			socket.gethostbyname(host)
			print(f"  [green]✔[/green] DNS resolves: {host}")
		except socket.gaierror:
			issues.append(f"DNS does not resolve for {host}")
			print(f"  [red]✗[/red] DNS does not resolve: {host}")
	
	# Check 4: Nginx container is running
	nginx_check = subprocess.run(
		["docker", "ps", "--filter", "name=nginx_proxy", "--format", "{{.Status}}"],
		capture_output=True,
		text=True,
	)
	if nginx_check.returncode == 0 and "Up" in nginx_check.stdout:
		print(f"  [green]✔[/green] nginx_proxy container is running")
	else:
		issues.append("nginx_proxy container is not running")
		print(f"  [red]✗[/red] nginx_proxy not running")
	
	# Check 5: Port 80 is accessible (check if nginx is listening)
	import socket
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.settimeout(2)
		result = sock.connect_ex(("127.0.0.1", 80))
		sock.close()
		if result == 0:
			print(f"  [green]✔[/green] Port 80 is listening")
		else:
			issues.append("Port 80 is not listening")
			print(f"  [yellow]⚠[/yellow] Port 80 not listening")
	except Exception:
		issues.append("Cannot check port 80")
	
	if issues:
		print(f"\n[yellow]Pre-flight warnings ({len(issues)} issue(s)):[/yellow]")
		for issue in issues:
			print(f"  • {issue}")
		print("\n[yellow]Certificate issuance may fail. Fix issues above first.[/yellow]")
		print("Run: domainup diagnose --domain <host> for detailed diagnostics")
		import typer
		if not typer.confirm("\nContinue anyway?", default=False):
			raise typer.Exit(code=1)


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
	
	# Pre-flight checks before attempting certificate issuance
	print("[cyan]→ Running pre-flight checks...[/]")
	_preflight_checks(issue_hosts, webroot, cwd)
	
	# If dummy cert dirs exist, remove them to avoid certbot writing into -0001 suffixed dirs
	live_root = le_dir / "live"
	for h in issue_hosts:
		base_dir = live_root / h
		marker = base_dir / ".domainup-dummy"
		try:
			if marker.exists():
				shutil.rmtree(base_dir)
		except Exception:
			pass

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
		print("[red]Certificate issuance failed[/red]")
		print(f"\n{msg}\n")
		
		# Provide actionable troubleshooting based on error patterns
		if "forbidden by policy" in msg or "too many certificates" in msg:
			print("[yellow]Troubleshooting:[/yellow]")
			print("  • Let's Encrypt rate limit hit or policy violation")
			print("  • Ensure domains are not example.com/localhost")
			print("  • Wait 1 hour if you've hit the rate limit")
			print("  • Use --staging flag in domainup.yaml: cert.staging: true")
		elif "Connection refused" in msg or "Invalid response" in msg or "Timeout" in msg:
			print("[yellow]Troubleshooting:[/yellow]")
			print("  • ACME HTTP-01 validation failed")
			print("  • Ensure port 80 is accessible from the internet")
			print("  • Check firewall rules: sudo ufw allow 80/tcp")
			print("  • Verify nginx is running: docker ps | grep nginx_proxy")
			print("  • Test webroot: curl http://<domain>/.well-known/acme-challenge/test")
			print("\n[cyan]Quick test:[/cyan]")
			print(f"  echo 'test' > {webroot}/.well-known/acme-challenge/test")
			print("  curl http://<your-domain>/.well-known/acme-challenge/test")
		elif "DNS problem" in msg or "NXDOMAIN" in msg:
			print("[yellow]Troubleshooting:[/yellow]")
			print("  • DNS does not resolve to this server")
			print("  • Verify DNS records: dig +short A <domain>")
			print("  • Ensure A/AAAA records point to your server IP")
			print("  • Wait for DNS propagation (can take up to 24h)")
		elif "timeout" in msg.lower():
			print("[yellow]Troubleshooting:[/yellow]")
			print("  • Let's Encrypt servers cannot reach your server")
			print("  • Check if port 80 is open: telnet <your-ip> 80")
			print("  • Verify no firewall blocking: sudo iptables -L")
		else:
			print("[yellow]General troubleshooting:[/yellow]")
			print("  • Run diagnostics: domainup diagnose")
			print("  • Check nginx logs: docker logs nginx_proxy")
			print(f"  • Verify webroot mounted: docker inspect nginx_proxy | grep {webroot}")
		
		raise SystemExit(proc.returncode)
	else:
		print("[green]✔ Certificates issued successfully[/green]")
		# Reconcile potential -000N live directories: ensure /live/<host> resolves to the newest one
		try:
			for h in issue_hosts:
				# Find all suffixed dirs
				suffixed = []
				if live_root.exists():
					for name in os.listdir(live_root):
						if name == h or not name.startswith(h + "-"):
							continue
						# parse numeric suffix if possible
						tail = name.removeprefix(h + "-")
						try:
							num = int(tail)
						except ValueError:
							continue
						dpath = live_root / name
						if dpath.is_dir():
							suffixed.append((num, dpath))

				# Choose newest by highest suffix number
				best = max(suffixed, key=lambda x: x[0])[1] if suffixed else None
				base_dir = live_root / h
				# If base dir missing but a suffixed exists, link base -> best
				if best and not base_dir.exists():
					try:
						os.symlink(best.name, base_dir)
						print(f"  [green]✔[/green] Linked {base_dir.name} → {best.name}")
					except Exception:
						# Fallback: copy files
						try:
							base_dir.mkdir(parents=True, exist_ok=True)
							for fname in ("fullchain.pem", "privkey.pem"):
								src = best / fname
								dst = base_dir / fname
								if src.exists():
									shutil.copy2(src, dst)
						except Exception:
							pass
				# If base exists and a better suffixed exists, and base has dummy marker, replace base with symlink
				marker = base_dir / ".domainup-dummy"
				if best and base_dir.exists() and marker.exists():
					try:
						shutil.rmtree(base_dir)
						os.symlink(best.name, base_dir)
						print(f"  [green]✔[/green] Replaced dummy cert: {base_dir.name} → {best.name}")
					except Exception:
						# Best effort: copy files over
						try:
							base_dir.mkdir(parents=True, exist_ok=True)
							for fname in ("fullchain.pem", "privkey.pem"):
								src = best / fname
								dst = base_dir / fname
								if src.exists():
									shutil.copy2(src, dst)
						except Exception:
							pass
		except Exception:
			# Non-fatal reconciliation issues shouldn't break success path
			pass
		
		print("\n[cyan]Next steps:[/cyan]")
		print("  domainup reload    # Reload nginx with new certificates")
