import typer


def add_cmd(
    domain: str = typer.Option(..., "--domain", help="Deprecated"),
    upstream: str = typer.Option(..., "--upstream", help="Deprecated"),
    type: str = typer.Option("api", "--type", help="Deprecated"),
):
    """Deprecated legacy command. Manage domains via domainup.yaml (no hardcoded types)."""
    raise typer.Exit(code=1)
