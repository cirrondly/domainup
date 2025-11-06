import typer
import json
import yaml
from rich.console import Console
from rich import print
from pathlib import Path

from .config import load_config, write_sample_config
from .renderers.nginx import render_all as render_nginx
from .renderers.traefik import render_all as render_traefik
from .docker_ops import compose_up, nginx_reload, discover_network_targets
from .commands.discover_cmd import discover_services as discover_published_services
from .commands.discover_cmd import interactive_map as discover_interactive_map
from .commands.discover_cmd import merge_into_config as discover_merge_into_config
from .commands.discover_cmd import detect_unmapped_services
from .certs import obtain_certs_webroot
from .checks import run_checks
from .dns_providers import ensure_dns_records_hetzner, ensure_dns_records_cloudflare
from .local_certs import setup_local_certs


app = typer.Typer(help="DomainUp – generic domain + HTTPS for Docker services (config-driven)")
console = Console()


@app.command("init")
def init_cmd(
	email: str = typer.Option(..., "--email", help="Let's Encrypt email"),
	interactive: bool = typer.Option(False, "--interactive", "-i", help="Discover Docker apps and map domains → upstreams"),
	network: str = typer.Option("proxy_net", "--network", help="Docker network to discover apps on"),
	domain: str | None = typer.Option(None, "--domain", help="Quick mode: FQDN (e.g., api.example.com)"),
	upstream: str | None = typer.Option(None, "--upstream", help="Quick mode: upstream target host:port (e.g., service:8000 or host.docker.internal:8000)"),
):
	"""Create a skeleton domainup.yaml. Use --interactive to discover Docker apps and build a tailored config."""
	path = Path.cwd() / "domainup.yaml"
	if path.exists() and interactive:
		if not typer.confirm("domainup.yaml exists. Overwrite?", default=False):
			print("[yellow]Aborting init; file exists.[/]")
			return
		# User opted to overwrite: remove existing file so discovery starts from a clean slate
		try:
			path.unlink()
		except Exception:
			# If unlink fails for any reason, we'll fall back to truncating on write later
			pass
	elif path.exists():
		print("[yellow]domainup.yaml already exists; not overwriting.[/]")
		return

	# Quick mode: create a minimal config for a single domain without discovery
	if not interactive and domain and upstream:
		try:
			up_host, up_port = upstream.split(":", 1)
			up_port_i = int(up_port)
		except Exception:
			raise typer.BadParameter("--upstream must be in the form host:port")
		config = {
			"version": 1,
			"email": email,
			"engine": "nginx",
			"cert": {"method": "webroot", "webroot_dir": "./www/certbot", "staging": False},
			"network": network,
			"runtime": {"http_port": 80, "https_port": 443},
			"domains": [{
				"host": domain,
				"upstreams": [{"name": "app", "target": f"{up_host}:{up_port_i}", "weight": 1}],
				"paths": [{"path": "/", "upstream": "app", "websocket": True, "strip_prefix": False}],
				"tls": {"enabled": True},
			}],
		}
		path.write_text(yaml.safe_dump(config, sort_keys=False))
		print(f"[green]✔ Created quick config[/] {path}")
		return

	if not interactive:
		write_sample_config(path, email=email)
		print(f"[green]✔ Created[/] {path}")
		return

	# Interactive flow using published-port discovery with guided mapping
	print(f"[cyan]→ Discovering Docker apps with published ports (network hint: {network})[/]")
	try:
		services = discover_published_services()
	except Exception as e:
		print(f"[yellow]Discovery failed:[/] {e}\nFalling back to manual prompts.")
		services = []

	if services:
		mappings = discover_interactive_map(services, cwd=Path.cwd())
		if mappings:
			out = discover_merge_into_config(mappings, cwd=Path.cwd())
			# Ensure email and network are set
			cfg = load_config(out)
			cfg.email = email
			cfg.network = network
			payload = yaml.safe_dump(json.loads(cfg.model_dump_json()), sort_keys=False)
			Path(out).write_text(payload)
			print(f"[green]✔ Created interactive config[/] {out}")
			return

	# Manual fallback if nothing discovered or user skipped
	print("[yellow]No discoverable services found; entering manual setup.[/]")
	host = typer.prompt("FQDN (e.g., api.example.com)")
	hostname = typer.prompt("Enter upstream host (service name or host.docker.internal)")
	port = int(typer.prompt("Enter upstream port", default=8000))
	ws = typer.confirm("Enable websocket for this route?", default=True)
	config = {
		"version": 1,
		"email": email,
		"engine": "nginx",
		"cert": {"method": "webroot", "webroot_dir": "./www/certbot", "staging": False},
		"network": network,
		"runtime": {"http_port": 80, "https_port": 443},
		"domains": [{
			"host": host,
			"upstreams": [{"name": "app", "target": f"{hostname}:{port}", "weight": 1}],
			"paths": [{"path": "/", "upstream": "app", "websocket": ws, "strip_prefix": False}],
			"tls": {"enabled": True},
		}],
	}
	path.write_text(yaml.safe_dump(config, sort_keys=False))
	print(f"[green]✔ Created interactive config[/] {path}")


@app.command("plan")
def plan_cmd():
	"""Parse config, validate schema, show a plan (hosts, upstreams, engine)."""
	cfg = load_config(Path.cwd() / "domainup.yaml")
	print("[bold]Plan:[/]")
	print(f"- engine: {cfg.engine}")
	print(f"- email: {cfg.email}")
	print(f"- network: {cfg.network}")
	print("- domains:")
	for d in cfg.domains:
		ups = ", ".join([f"{u.name}->{u.target}" for u in d.upstreams])
		print(f"  • {d.host}  upstreams: [{ups}]  tls: {d.tls.enabled}")


@app.command("render")
def render_cmd():
	"""Generate reverse-proxy configs based on selected engine."""
	cfg = load_config(Path.cwd() / "domainup.yaml")
	if cfg.engine == "nginx":
		render_nginx(cfg, cwd=Path.cwd())
	elif cfg.engine == "traefik":
		render_traefik(cfg, cwd=Path.cwd())
	else:
		raise typer.BadParameter("engine must be 'nginx' or 'traefik'")
	print("[green]✔ Rendered configuration[/]")


@app.command("up")
def up_cmd(
	http_port: int | None = typer.Option(None, "--http-port", help="Override host HTTP port (default from config)"),
	https_port: int | None = typer.Option(None, "--https-port", help="Override host HTTPS port (default from config)"),
):
	"""Bring up reverse-proxy stack (nginx by default). Optionally override host ports."""
	config_path = Path.cwd() / "domainup.yaml"
	
	# Auto-init if config doesn't exist
	if not config_path.exists():
		print("[yellow]No domainup.yaml found. Running auto-discovery...[/]")
		print("[dim]Tip: Run 'domainup init --email your@email.com' first for more control[/]\n")
		
		# Try to discover services
		services = discover_published_services()
		if services:
			mappings = discover_interactive_map(services, cwd=Path.cwd())
			if mappings:
				discover_merge_into_config(mappings, cwd=Path.cwd())
			else:
				print("[yellow]No services mapped. Creating minimal config...[/]")
				email = typer.prompt("Email for Let's Encrypt", default="admin@example.com")
				write_sample_config(config_path, email=email)
		else:
			print("[yellow]No Docker services found. Creating minimal config...[/]")
			email = typer.prompt("Email for Let's Encrypt", default="admin@example.com")
			write_sample_config(config_path, email=email)
		
		print(f"[green]✔ Created {config_path}[/green]\n")
	
	cfg = load_config(config_path)
	# Auto-discovery wizard if no domains defined
	if not cfg.domains:
		print("[cyan]No domains in config. Launching auto-discovery wizard...[/]")
		services = discover_published_services()
		if services:
			mappings = discover_interactive_map(services, cwd=Path.cwd())
			if mappings:
				discover_merge_into_config(mappings, cwd=Path.cwd())
				cfg = load_config(Path.cwd() / "domainup.yaml")
		else:
			print("[yellow]No containers with published ports found. Continuing without discovery.[/]")
	else:
		# Detect new unmapped services and offer to add them quickly
		try:
			services = discover_published_services()
			new_svcs = detect_unmapped_services(cfg, services)
			if new_svcs:
				if typer.confirm(f"Detected {len(new_svcs)} new services with published ports. Add them now?", default=True):
					mappings = discover_interactive_map(new_svcs, cwd=Path.cwd())
					if mappings:
						discover_merge_into_config(mappings, cwd=Path.cwd())
						cfg = load_config(Path.cwd() / "domainup.yaml")
		except Exception:
			pass
	if http_port is not None:
		print(f"[dim]Override HTTP port:[/] {http_port}")
	if https_port is not None:
		print(f"[dim]Override HTTPS port:[/] {https_port}")
	compose_up(engine=cfg.engine, cwd=Path.cwd(), network=cfg.network, http_port=http_port, https_port=https_port)


@app.command("cert")
def cert_cmd(
	local: bool = typer.Option(False, "--local", help="Generate local development certificates using mkcert instead of Let's Encrypt")
):
	"""Run certbot webroot for all hosts with tls.enabled=true, or generate local certs with --local."""
	cfg = load_config(Path.cwd() / "domainup.yaml")
	
	if local:
		# Generate local development certificates using mkcert
		tls_hosts = [d.host for d in cfg.domains if d.tls.enabled]
		
		if not tls_hosts:
			print("[yellow]No domains with TLS enabled in domainup.yaml[/]")
			print("Enable TLS for domains by setting: tls.enabled: true")
			return
		
		print(f"[cyan]Generating local certificates for {len(tls_hosts)} domain(s)...[/]")
		for host in tls_hosts:
			print(f"  • {host}")
		print()
		
		success = setup_local_certs(tls_hosts, cwd=Path.cwd())
		
		if success:
			print("\n[green]✔ Local certificates ready![/]")
			print("\n[cyan]Next steps:[/cyan]")
			print("  1. Ensure domains are in /etc/hosts (e.g., 127.0.0.1 cirrondly.local)")
			print("  2. Set tls.acme: false in domainup.yaml for local domains")
			print("  3. Run: domainup render")
			print("  4. Run: domainup reload")
			print("  5. Visit https://<domain> in your browser")
		else:
			print("[red]Failed to generate local certificates[/]")
			raise typer.Exit(code=1)
	else:
		# Standard Let's Encrypt certificate issuance
		if cfg.cert.method != "webroot":
			print("[yellow]Only webroot cert method is implemented; dns01 is TODO.[/]")
		obtain_certs_webroot(cfg, cwd=Path.cwd())


@app.command("reload")
def reload_cmd():
	"""Reload nginx."""
	nginx_reload()


@app.command("deploy")
def deploy_cmd():
	"""render -> up -> cert -> reload"""
	render_cmd()
	up_cmd()
	cert_cmd()
	reload_cmd()


@app.command("check")
def check_cmd(domain: str = typer.Option(..., "--domain", help="FQDN to check")):
	run_checks(domain)


@app.command("dns")
def dns_cmd(
	provider: str = typer.Option("", "--provider", help="hetzner|vercel|cloudflare"),
	token: str = typer.Option("", "--token", help="API token (stub)"),
	ipv4: str = typer.Option("", "--ipv4"),
	ipv6: str = typer.Option("", "--ipv6"),
):
	"""Manage DNS records for all TLS-enabled hosts. With --provider hetzner and --token, upserts A/AAAA; otherwise prints instructions."""
	cfg = load_config(Path.cwd() / "domainup.yaml")
	if provider.lower() == "hetzner" and token:
		if not ipv4 and not ipv6:
			raise typer.BadParameter("Provide at least --ipv4 or --ipv6")
		for d in cfg.domains:
			if d.tls.enabled:
				print(f"[cyan]→ Hetzner upsert[/] {d.host} A={ipv4 or '-'} AAAA={ipv6 or '-'}")
				ensure_dns_records_hetzner(token, d.host, ipv4 or None, ipv6 or None)
		print("[green]✔ DNS records ensured in Hetzner[/]")
	elif provider.lower() == "cloudflare" and token:
		if not ipv4 and not ipv6:
			raise typer.BadParameter("Provide at least --ipv4 or --ipv6")
		for d in cfg.domains:
			if d.tls.enabled:
				print(f"[cyan]→ Cloudflare upsert[/] {d.host} A={ipv4 or '-'} AAAA={ipv6 or '-'}")
				ensure_dns_records_cloudflare(token, d.host, ipv4 or None, ipv6 or None)
		print("[green]✔ DNS records ensured in Cloudflare[/]")
	else:
		print("[bold]Add these DNS records in your provider:[/]")
		for d in cfg.domains:
			if d.tls.enabled:
				print(f"- {d.host}  →  A {ipv4}  |  AAAA {ipv6}")
		if provider:
			print(f"[dim]{provider} automation not implemented yet. Provide --provider hetzner --token to auto-update in Hetzner DNS.[/]")


@app.command("doctor")
def doctor_cmd(
	framework: str = typer.Option("", "--framework", help="Framework to check (django, fastapi, express, flask)"),
):
	"""Framework-specific health checks and configuration validation.
	
	Checks common framework issues like ALLOWED_HOSTS, CORS settings, static files, etc.
	"""
	import subprocess
	from pathlib import Path
	
	cfg = load_config(Path.cwd() / "domainup.yaml")
	
	print(f"[bold cyan]DomainUp Doctor[/bold cyan]")
	if framework:
		print(f"Framework: {framework}\n")
	else:
		print("General checks (use --framework for specific checks)\n")
	
	issues = []
	
	# General checks for all frameworks
	print("[bold]General Configuration[/bold]")
	
	# Check if domains are using example.com
	example_domains = [d.host for d in cfg.domains if "example.com" in d.host or "localhost" in d.host]
	if example_domains:
		issues.append(f"Using placeholder domains: {', '.join(example_domains)}")
		print(f"  [yellow]⚠[/yellow] Placeholder domains detected: {', '.join(example_domains)}")
		print("    [dim]Update domainup.yaml with real domain names[/dim]")
	else:
		print("  [green]✔[/green] No placeholder domains")
	
	# Check if TLS is enabled
	no_tls = [d.host for d in cfg.domains if not d.tls.enabled]
	if no_tls:
		print(f"  [yellow]⚠[/yellow] TLS disabled for: {', '.join(no_tls)}")
	else:
		print("  [green]✔[/green] TLS enabled for all domains")
	
	# Check if websocket is enabled for domains that might need it
	ws_candidates = []
	for d in cfg.domains:
		has_ws = any(p.websocket for p in d.paths)
		if not has_ws and ("chat" in d.host or "socket" in d.host or "ws" in d.host):
			ws_candidates.append(d.host)
	if ws_candidates:
		print(f"  [yellow]⚠[/yellow] WebSocket not enabled but domain suggests it: {', '.join(ws_candidates)}")
		print("    [dim]Set websocket: true in paths if needed[/dim]")
	
	# Framework-specific checks
	if framework.lower() == "django":
		print("\n[bold]Django-Specific Checks[/bold]")
		# Check for settings.py
		settings_paths = list(Path.cwd().glob("**/settings.py"))
		if settings_paths:
			print(f"  [green]✔[/green] Found Django settings: {settings_paths[0]}")
			# Check ALLOWED_HOSTS
			settings_file = settings_paths[0].read_text()
			if "ALLOWED_HOSTS = []" in settings_file or "ALLOWED_HOSTS=[]" in settings_file:
				issues.append("Django ALLOWED_HOSTS is empty")
				print("  [red]✗[/red] ALLOWED_HOSTS is empty")
				print(f"    [yellow]Add:[/yellow] ALLOWED_HOSTS = {[d.host for d in cfg.domains]}")
			else:
				print("  [green]✔[/green] ALLOWED_HOSTS configured")
			
			# Check CSRF_TRUSTED_ORIGINS for https
			if any(d.tls.enabled for d in cfg.domains):
				if "CSRF_TRUSTED_ORIGINS" not in settings_file:
					issues.append("CSRF_TRUSTED_ORIGINS not set")
					print("  [yellow]⚠[/yellow] CSRF_TRUSTED_ORIGINS not found")
					origins = [f"https://{d.host}" for d in cfg.domains if d.tls.enabled]
					print(f"    [yellow]Add:[/yellow] CSRF_TRUSTED_ORIGINS = {origins}")
			
			# Check for X-Forwarded-Proto handling
			if "USE_X_FORWARDED_HOST" not in settings_file:
				print("  [yellow]⚠[/yellow] USE_X_FORWARDED_HOST not set")
				print("    [yellow]Add:[/yellow] USE_X_FORWARDED_HOST = True")
				print("    [yellow]Add:[/yellow] SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')")
		else:
			print("  [yellow]⚠[/yellow] No Django settings.py found")
	
	elif framework.lower() == "fastapi":
		print("\n[bold]FastAPI-Specific Checks[/bold]")
		# Check for main.py or app.py
		fastapi_files = list(Path.cwd().glob("**/main.py")) + list(Path.cwd().glob("**/app.py"))
		if fastapi_files:
			print(f"  [green]✔[/green] Found FastAPI app: {fastapi_files[0]}")
			app_content = fastapi_files[0].read_text()
			
			# Check CORS middleware
			if "CORSMiddleware" not in app_content:
				print("  [yellow]⚠[/yellow] CORS middleware not configured")
				print("    [yellow]Tip:[/yellow] Add CORSMiddleware if your API is accessed from browsers")
			else:
				print("  [green]✔[/green] CORS middleware present")
			
			# Check if uvicorn is configured properly
			if "host=" in app_content and "0.0.0.0" not in app_content:
				print("  [yellow]⚠[/yellow] Uvicorn may not be listening on all interfaces")
				print("    [yellow]Fix:[/yellow] uvicorn main:app --host 0.0.0.0 --port 8000")
		else:
			print("  [yellow]⚠[/yellow] No FastAPI app found (main.py or app.py)")
	
	elif framework.lower() == "express" or framework.lower() == "node":
		print("\n[bold]Express/Node.js-Specific Checks[/bold]")
		# Check for package.json
		pkg_json = Path.cwd() / "package.json"
		if pkg_json.exists():
			print("  [green]✔[/green] Found package.json")
			# Check common Express patterns
			index_files = list(Path.cwd().glob("**/index.js")) + list(Path.cwd().glob("**/server.js"))
			if index_files:
				server_content = index_files[0].read_text()
				if "trust proxy" not in server_content:
					print("  [yellow]⚠[/yellow] Express trust proxy not configured")
					print("    [yellow]Add:[/yellow] app.set('trust proxy', true)")
				else:
					print("  [green]✔[/green] Trust proxy configured")
		else:
			print("  [yellow]⚠[/yellow] No package.json found")
	
	elif framework.lower() == "flask":
		print("\n[bold]Flask-Specific Checks[/bold]")
		# Check for app.py or main.py
		flask_files = list(Path.cwd().glob("**/app.py")) + list(Path.cwd().glob("**/main.py"))
		if flask_files:
			print(f"  [green]✔[/green] Found Flask app: {flask_files[0]}")
			app_content = flask_files[0].read_text()
			
			# Check if running in production mode
			if "debug=True" in app_content:
				issues.append("Flask running in debug mode")
				print("  [red]✗[/red] Debug mode enabled in production")
				print("    [yellow]Fix:[/yellow] Remove debug=True or set FLASK_ENV=production")
			
			# Check for ProxyFix
			if "ProxyFix" not in app_content:
				print("  [yellow]⚠[/yellow] ProxyFix not configured for reverse proxy")
				print("    [yellow]Add:[/yellow] from werkzeug.middleware.proxy_fix import ProxyFix")
				print("    [yellow]Add:[/yellow] app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)")
		else:
			print("  [yellow]⚠[/yellow] No Flask app found")
	
	# Summary
	print(f"\n[bold]{'='*60}[/bold]")
	if issues:
		print(f"[bold yellow]⚠ Found {len(issues)} issue(s)[/bold yellow]")
		for issue in issues:
			print(f"  • {issue}")
	else:
		print("[bold green]✔ No major issues detected[/bold green]")
	print(f"[bold]{'='*60}[/bold]")


@app.command("add-user")
def add_user_cmd(
	domain: str = typer.Option(..., "--domain", help="Domain to add user for"),
	username: str = typer.Option(..., "--username", help="Username for basic auth"),
):
	"""Add a user to htpasswd file for basic authentication.
	
	Prompts for password securely and updates the htpasswd file for the domain.
	"""
	import subprocess
	from pathlib import Path
	import typer
	
	cfg = load_config(Path.cwd() / "domainup.yaml")
	
	# Check if domain exists
	domain_cfg = None
	for d in cfg.domains:
		if d.host == domain:
			domain_cfg = d
			break
	
	if not domain_cfg:
		print(f"[red]Domain {domain} not found in config[/red]")
		raise typer.Exit(code=1)
	
	# Check if basic_auth is enabled
	if not domain_cfg.security.basic_auth.enabled:
		print(f"[yellow]Basic auth not enabled for {domain}[/yellow]")
		print("Enable it in domainup.yaml:")
		print(f"  domains:")
		print(f"    - host: {domain}")
		print(f"      security:")
		print(f"        basic_auth:")
		print(f"          enabled: true")
		if not typer.confirm("\nContinue anyway and enable basic auth?", default=False):
			raise typer.Exit(code=1)
	
	# Prompt for password
	password = typer.prompt(f"Password for {username}", hide_input=True)
	password_confirm = typer.prompt("Confirm password", hide_input=True)
	
	if password != password_confirm:
		print("[red]Passwords don't match[/red]")
		raise typer.Exit(code=1)
	
	# Create htpasswd directory
	htpasswd_dir = Path.cwd() / "nginx" / "htpasswd"
	htpasswd_dir.mkdir(parents=True, exist_ok=True)
	
	htpasswd_file = htpasswd_dir / f"{domain}.htpasswd"
	
	# Use htpasswd command (or fallback to python implementation)
	try:
		# Try using htpasswd command
		mode = "-c" if not htpasswd_file.exists() else ""
		proc = subprocess.run(
			["htpasswd", "-b", mode, str(htpasswd_file), username, password] if mode else ["htpasswd", "-b", str(htpasswd_file), username, password],
			capture_output=True,
			text=True,
		)
		if proc.returncode == 0:
			print(f"[green]✔ Added user {username} to {htpasswd_file}[/green]")
		else:
			raise Exception(proc.stderr or "htpasswd failed")
	except (FileNotFoundError, Exception):
		# Fallback: use Python's crypt if htpasswd not available
		try:
			import crypt
			import secrets
			salt = crypt.mksalt(crypt.METHOD_SHA512)
			hashed = crypt.crypt(password, salt)
			entry = f"{username}:{hashed}\n"
			
			# Append or create
			if htpasswd_file.exists():
				# Check if user already exists
				content = htpasswd_file.read_text()
				lines = content.split("\n")
				new_lines = [line for line in lines if not line.startswith(f"{username}:")]
				new_lines.append(entry.strip())
				htpasswd_file.write_text("\n".join(new_lines))
			else:
				htpasswd_file.write_text(entry)
			
			print(f"[green]✔ Added user {username} to {htpasswd_file}[/green]")
		except Exception as e:
			print(f"[red]Failed to create htpasswd entry: {e}[/red]")
			print("\nManual alternative:")
			print(f"  docker run --rm httpd:alpine htpasswd -nb {username} <password> >> {htpasswd_file}")
			raise typer.Exit(code=1)
	
	# Remind to reload nginx
	print("\n[cyan]Next steps:[/cyan]")
	print("  domainup reload    # Reload nginx to apply changes")


@app.command("discover")
def discover_cmd():
	"""Auto-discover Docker containers with published ports and interactively map them to domains.

	This writes/updates domainup.yaml idempotently.
	"""
	services = discover_published_services()
	if not services:
		print("[yellow]No containers with published TCP ports detected.[/]")
		raise typer.Exit(code=0)
	mappings = discover_interactive_map(services, cwd=Path.cwd())
	if not mappings:
		print("[yellow]No mappings selected.[/]")
		raise typer.Exit(code=0)
	out = discover_merge_into_config(mappings, cwd=Path.cwd())
	print(f"[green]✔ Updated config[/] {out}")
	print("Next: domainup render && domainup up && domainup cert && domainup reload")


@app.command("diagnose")
def diagnose_cmd(
	domain: str | None = typer.Option(None, "--domain", help="Specific domain to diagnose (default: all TLS domains)"),
):
	"""Comprehensive diagnostics for DomainUp deployment.
	
	Checks DNS, ports, ACME webroot, certificates, backend connectivity, and proxy network.
	Provides actionable copy-paste fixes for common issues.
	"""
	import subprocess
	import socket
	from pathlib import Path
	
	cfg = load_config(Path.cwd() / "domainup.yaml")
	
	# Determine domains to check
	check_domains = []
	if domain:
		# Check if domain exists in config
		found = False
		for d in cfg.domains:
			if d.host == domain:
				check_domains.append(d)
				found = True
				break
		if not found:
			print(f"[red]Domain {domain} not found in config[/]")
			raise typer.Exit(code=1)
	else:
		# Check all TLS-enabled domains
		check_domains = [d for d in cfg.domains if d.tls.enabled]
	
	if not check_domains:
		print("[yellow]No TLS-enabled domains to diagnose[/]")
		raise typer.Exit(code=0)
	
	print(f"[bold cyan]DomainUp Diagnostics[/bold cyan]")
	print(f"Checking {len(check_domains)} domain(s)...\n")
	
	all_ok = True
	
	# Check 1: Docker daemon
	print("[bold]1. Docker Daemon[/bold]")
	docker_proc = subprocess.run(["docker", "info"], capture_output=True, text=True)
	if docker_proc.returncode == 0:
		print("  [green]✔[/green] Docker daemon is running")
	else:
		print("  [red]✗[/red] Docker daemon not accessible")
		print("  [yellow]Fix:[/yellow] Start Docker Desktop, Colima, or OrbStack")
		all_ok = False
	
	# Check 2: Proxy network
	print(f"\n[bold]2. Proxy Network ({cfg.network})[/bold]")
	net_proc = subprocess.run(["docker", "network", "inspect", cfg.network], capture_output=True, text=True)
	if net_proc.returncode == 0:
		print(f"  [green]✔[/green] Network {cfg.network} exists")
		# Check containers on network
		try:
			net_data = json.loads(net_proc.stdout)
			containers = (net_data[0].get("Containers", {}) if net_data else {})
			if containers:
				print(f"  [green]✔[/green] {len(containers)} container(s) connected")
				for cid, cinfo in list(containers.items())[:3]:  # Show first 3
					print(f"    - {cinfo.get('Name', 'unknown')}")
			else:
				print("  [yellow]⚠[/yellow] No containers connected to network")
		except Exception:
			pass
	else:
		print(f"  [red]✗[/red] Network {cfg.network} does not exist")
		print(f"  [yellow]Fix:[/yellow] docker network create {cfg.network}")
		all_ok = False
	
	# Check 3: Nginx container
	print("\n[bold]3. Nginx Container[/bold]")
	nginx_proc = subprocess.run(["docker", "ps", "--filter", "name=nginx_proxy", "--format", "{{.Status}}"], capture_output=True, text=True)
	if nginx_proc.returncode == 0 and nginx_proc.stdout.strip():
		status = nginx_proc.stdout.strip()
		if "Up" in status:
			print(f"  [green]✔[/green] nginx_proxy is running ({status})")
		else:
			print(f"  [yellow]⚠[/yellow] nginx_proxy exists but not running: {status}")
			print("  [yellow]Fix:[/yellow] domainup up")
			all_ok = False
	else:
		print("  [red]✗[/red] nginx_proxy container not found")
		print("  [yellow]Fix:[/yellow] domainup up")
		all_ok = False
	
	# Check 4: Host ports
	print(f"\n[bold]4. Host Ports ({cfg.runtime.http_port}/tcp, {cfg.runtime.https_port}/tcp)[/bold]")
	for port in [cfg.runtime.http_port, cfg.runtime.https_port]:
		try:
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			sock.settimeout(1)
			result = sock.connect_ex(("127.0.0.1", port))
			sock.close()
			if result == 0:
				print(f"  [green]✔[/green] Port {port} is listening")
			else:
				print(f"  [yellow]⚠[/yellow] Port {port} not listening")
				all_ok = False
		except Exception as e:
			print(f"  [red]✗[/red] Cannot check port {port}: {e}")
			all_ok = False
	
	# Per-domain checks
	for d in check_domains:
		print(f"\n[bold]5. Domain: {d.host}[/bold]")
		
		# Check DNS
		print(f"  [dim]DNS resolution...[/dim]")
		dns_proc = subprocess.run(["dig", "+short", "A", d.host], capture_output=True, text=True)
		if dns_proc.returncode == 0 and dns_proc.stdout.strip():
			ips = dns_proc.stdout.strip().split("\n")
			print(f"  [green]✔[/green] DNS A records: {', '.join(ips)}")
		else:
			print(f"  [red]✗[/red] No DNS A records found for {d.host}")
			print(f"  [yellow]Fix:[/yellow] Add A record pointing to your server's IP")
			all_ok = False
		
		# Check certificate
		cert_path = Path.cwd() / "letsencrypt" / "live" / d.host / "fullchain.pem"
		if cert_path.exists():
			print(f"  [green]✔[/green] Certificate exists: {cert_path}")
			# Check if dummy
			dummy_marker = cert_path.parent / ".domainup-dummy"
			if dummy_marker.exists():
				print(f"  [yellow]⚠[/yellow] Certificate is a dummy self-signed cert")
				print(f"  [yellow]Fix:[/yellow] domainup cert")
				all_ok = False
			else:
				# Check expiry
				cert_proc = subprocess.run(
					["openssl", "x509", "-in", str(cert_path), "-noout", "-enddate"],
					capture_output=True,
					text=True,
				)
				if cert_proc.returncode == 0:
					print(f"  [green]✔[/green] {cert_proc.stdout.strip()}")
		else:
			print(f"  [red]✗[/red] Certificate not found: {cert_path}")
			print(f"  [yellow]Fix:[/yellow] domainup cert")
			all_ok = False
		
		# Check ACME webroot
		webroot = Path(cfg.cert.webroot_dir)
		if not webroot.is_absolute():
			webroot = Path.cwd() / cfg.cert.webroot_dir
		acme_path = webroot / ".well-known" / "acme-challenge"
		if acme_path.exists():
			print(f"  [green]✔[/green] ACME webroot accessible: {acme_path}")
		else:
			print(f"  [yellow]⚠[/yellow] ACME challenge directory does not exist")
			print(f"  [yellow]Fix:[/yellow] mkdir -p {acme_path}")
		
		# Check backend connectivity
		for upstream in d.upstreams:
			target = upstream.target
			hostname = target.split(":")[0] if ":" in target else target
			port = int(target.split(":")[1]) if ":" in target else 80
			
			# Skip if host.docker.internal
			if "host.docker.internal" in hostname:
				print(f"  [dim]Upstream {upstream.name}: {target} (host mode, skipping)[/dim]")
				continue
			
			# Try to resolve via Docker DNS by checking if container is on network
			docker_inspect = subprocess.run(
				["docker", "network", "inspect", cfg.network],
				capture_output=True,
				text=True,
			)
			if docker_inspect.returncode == 0:
				try:
					net_data = json.loads(docker_inspect.stdout)
					containers = net_data[0].get("Containers", {}) if net_data else {}
					found = False
					for cid, cinfo in containers.items():
						cname = cinfo.get("Name", "")
						# Check if name matches hostname or contains it
						if hostname in cname or cname == hostname:
							found = True
							print(f"  [green]✔[/green] Backend {upstream.name} ({target}) found on {cfg.network}")
							break
					
					if not found:
						print(f"  [red]✗[/red] Backend {upstream.name} ({target}) not on {cfg.network}")
						print(f"  [yellow]Fix:[/yellow] docker network connect {cfg.network} <container_name>")
						print(f"         Or ensure your backend compose has: networks: [{cfg.network}]")
						all_ok = False
				except Exception:
					pass
	
	# Summary
	print(f"\n[bold]{'='*60}[/bold]")
	if all_ok:
		print("[bold green]✔ All checks passed![/bold green]")
		print("\nYour DomainUp deployment looks healthy.")
	else:
		print("[bold yellow]⚠ Some issues detected[/bold yellow]")
		print("\nReview the fixes above and re-run: domainup diagnose")
	print(f"[bold]{'='*60}[/bold]")
