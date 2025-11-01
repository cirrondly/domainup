import typer


def init_cmd(email: str = typer.Option(..., "--email", help="Let's Encrypt email")):
    """Deprecated legacy command. Use: domainup init --email ... (new config-driven flow)."""
    raise typer.Exit(code=1)