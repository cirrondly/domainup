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


app = typer.Typer(help="DomainUp – generic domain + HTTPS for Docker services (config-driven)")
console = Console()


@app.command("init")
def init_cmd(
	email: str = typer.Option(..., "--email", help="Let's Encrypt email"),
	interactive: bool = typer.Option(False, "--interactive", "-i", help="Discover Docker apps and map domains → upstreams"),
	network: str = typer.Option("proxy_net", "--network", help="Docker network to discover apps on"),
):
	"""Create a skeleton domainup.yaml. Use --interactive to discover Docker apps and build a tailored config."""
	path = Path.cwd() / "domainup.yaml"
	if path.exists() and interactive:
		if not typer.confirm("domainup.yaml exists. Overwrite?", default=False):
			print("[yellow]Aborting init; file exists.[/]")
			return
	elif path.exists():
		print("[yellow]domainup.yaml already exists; not overwriting.[/]")
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
	cfg = load_config(Path.cwd() / "domainup.yaml")
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
def cert_cmd():
	"""Run certbot webroot for all hosts with tls.enabled=true."""
	cfg = load_config(Path.cwd() / "domainup.yaml")
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
