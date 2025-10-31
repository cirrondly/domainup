# Contributing to DomainUp

Thanks for helping improve DomainUp! This project aims to make domain + HTTPS setup for Docker services dead simple, especially for Hetzner servers.

## Development setup

1. Create and activate a virtual environment (or use pyenv/uv/pipx)
2. Install in editable mode with dev extras:

```bash
pip install -e .[dev]
```

3. Run tests:

```bash
pytest -q
```

## Code style and quality

- Format with Black
- Lint with Ruff
- Type-check with Mypy

Optionally run:

```bash
ruff check .
black --check .
mypy .
```

## Making changes

- Keep changes focused and include tests (unit or snapshot) when public behavior changes
- If you change configuration shape, update Pydantic models, README, and add tests
- For new features in renderers, add minimal coverage (happy path + 1 edge)

## Submitting a PR

- Include a short description and motivation
- Mention any breaking changes and migration path
- Confirm tests pass (CI or local)

## Security and secrets

- Do not commit credentials or secrets
- Prefer environment variables or secret stores
- For auth, prefer htpasswd files (feature TODO) or secrets mounted at runtime

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
