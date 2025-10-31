import typer


def deploy_cmd():
    """Deprecated legacy command. Use: domainup deploy (config-driven)."""
    raise typer.Exit(code=1)