import typer


def dns_cmd(ipv4: str = typer.Option("", "--ipv4"), ipv6: str = typer.Option("", "--ipv6")):
    """Deprecated legacy command. Use: domainup dns ... (new config-driven flow)."""
    raise typer.Exit(code=1)