import typer
from rich.console import Console
from rich import print
from pathlib import Path

from .config import load_config, write_sample_config
from .renderers.nginx import render_all as render_nginx
from .renderers.traefik import render_all as render_traefik
from .docker_ops import compose_up, nginx_reload
from .certs import obtain_certs_webroot
from .checks import run_checks
from .dns_providers import ensure_dns_records_hetzner


app = typer.Typer(help="DomainUp – generic domain + HTTPS for Docker services (config-driven)")
console = Console()


@app.command("init")
def init_cmd(email: str = typer.Option(..., "--email", help="Let's Encrypt email")):
	"""Create a skeleton domainup.yaml if missing (with comments)."""
	path = Path.cwd() / "domainup.yaml"
	if path.exists():
		print("[yellow]domainup.yaml already exists; not overwriting.[/]")
		return
	write_sample_config(path, email=email)
	print(f"[green]✔ Created[/] {path}")


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
def up_cmd():
	"""Bring up reverse-proxy stack (nginx by default)."""
	cfg = load_config(Path.cwd() / "domainup.yaml")
	compose_up(engine=cfg.engine, cwd=Path.cwd(), network=cfg.network)


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
	else:
		print("[bold]Add these DNS records in your provider:[/]")
		for d in cfg.domains:
			if d.tls.enabled:
				print(f"- {d.host}  →  A {ipv4}  |  AAAA {ipv6}")
		if provider:
			print(f"[dim]{provider} automation not implemented yet. Provide --provider hetzner --token to auto-update in Hetzner DNS.[/]")
