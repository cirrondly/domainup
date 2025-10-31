import typer


def check_cmd(domain: str = typer.Option(..., "--domain")):
    """Deprecated legacy command. Use: domainup check --domain ..."""
    raise typer.Exit(code=1)
