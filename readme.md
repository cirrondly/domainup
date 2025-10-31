
## DomainUp – config-driven reverse proxy for Docker

DomainUp turns a simple YAML file into a running reverse-proxy with HTTPS for your Docker services. It renders Nginx (by default) and obtains Let’s Encrypt certificates via webroot. A Traefik renderer (POC) is included; DNS-01 is planned.

## Overview

Why this exists: I kept repeating the same steps when provisioning a server on Hetzner — creating a reverse-proxy, wiring domains, getting HTTPS, and keeping things maintainable. DomainUp captures that workflow in a single, reproducible tool so any developer deploying on Hetzner (or any Docker host) can set up domains with minimal friction and no headaches.

Key ideas:
- Single `domainup.yaml` governs everything.
- Arbitrary number of domains; each maps to one or more Docker upstreams.
- Generic Jinja2 templates for Nginx vhosts (and Traefik dynamic files with basic middlewares).
- Let’s Encrypt via webroot (DNS-01 coming), HSTS optional.
- Per-domain options: websockets, path routes, headers, basic auth (htpasswd files supported), allow-list, simple rate-limit, gzip, CORS passthrough, LB strategy, sticky cookie.
- No hardcoded “types” like monitoring/otlp — fully generic.

## Quick Start

Install (editable for local development):
```bash
pipx install -e .
```

Minimal flow:
```bash
domainup init --email contact@cirrondly.com   # creates domainup.yaml skeleton
domainup plan                                 # validate + print plan
domainup render                               # generate Nginx configs from YAML
domainup up                                   # start Nginx reverse proxy
domainup cert                                 # obtain certs (webroot)
domainup reload                               # reload Nginx
domainup deploy                               # render -> up -> cert -> reload
domainup check --domain api.example.com       # quick diagnostics
```

Local testing tips:
- If ports 80/443 are busy, adjust host ports in `domainup.yaml` under `runtime.http_port`/`https_port` then `render` + `up`.
- For HTTPS locally, use `mkcert` and place certs under `./letsencrypt/live/<host>/`.

## Configuration (domainup.yaml)

```yaml
version: 1
email: contact@cirrondly.com
engine: nginx   # nginx | traefik (poc)
cert:
	method: webroot   # webroot | dns01 (todo)
	webroot_dir: ./www/certbot
	staging: false    # true to test with LE staging
network: proxy_net
runtime:
	http_port: 80
	https_port: 443
domains:
	- host: api.example.com
		upstreams:
			- name: app1
				target: back_web_1:8000
				weight: 1
		paths:
			- path: /
				upstream: app1
				websocket: true
				strip_prefix: false
		headers:
			hsts: true
			extra:
				X-Frame-Options: DENY
				X-Content-Type-Options: nosniff
		security:
			basic_auth:
				enabled: false
				users: []
			allow_ips: []
			rate_limit:
				enabled: false
				requests_per_minute: 600
		tls: { enabled: true }
		gzip: true
		cors_passthrough: false

	- host: console.example.com
		upstreams:
			- name: console
				target: console:3000
		paths:
			- path: "/"
				upstream: console
		security:
			basic_auth:
				enabled: true
				users: ["admin:{SHA}..."]
		tls: { enabled: true }

	- host: data.example.com
		upstreams:
			- name: otel
				target: otel:4318
		paths:
			- path: "~* ^/(v1/|otlp/v1/)(traces|logs|metrics)"
				upstream: otel
				body_size: 20m
		tls: { enabled: true }
```

## Usage Examples

- Generate configs for Nginx and start the proxy:
```bash
domainup render && domainup up
```

- Obtain certificates (webroot):
```bash
domainup cert && domainup reload
```

- Check DNS and TLS quickly:
```bash
domainup check --domain api.example.com
```

- Print DNS records to create in your provider (e.g., Hetzner DNS, Vercel DNS, Cloudflare):
```bash
domainup dns --ipv4 203.0.113.10 --ipv6 2001:db8::10
```

## Files generated (Nginx engine)
- `nginx/nginx.conf`
- `nginx/conf.d/00-redirect.conf` (http→https + ACME webroot for all TLS hosts)
- `nginx/conf.d/<host>.conf` per domain
- `runtime/docker-compose.nginx.yml` to run the proxy

## Files generated (Traefik engine)
- `traefik/traefik.yml` (static)
- `traefik/dynamic/<host>.yml` per domain with middlewares
- `traefik/htpasswd/<host>.htpasswd` when basic auth enabled
- `runtime/docker-compose.traefik.yml` to run the proxy

## Contributing

Set up dev environment:
```bash
pip install -e .[dev]
pytest -q
```

Coding standards:
- Format: black, lint: ruff, types: mypy
- Tests: pytest; add unit tests for new behaviors
- PRs: include a brief description, motivation (what problem you solved), and tests

## Security

- Don’t expose Basic Auth user/passwords in the repo; use htpasswd files or safe secret storage.
- HTTP-01 requires port 80. If you can’t open it, prefer DNS-01 (on roadmap).
- Review Nginx config before going to production; adjust rate limits and headers as needed for your threat model.

## License & Branding

MIT License. See LICENSE for details.

Created by Cirrondly (cirrondly.com) — a tiny startup by José MARIN.

## Roadmap

- DNS provider API integrations (Vercel, Cloudflare)
- ACME DNS-01 support
- Traefik middlewares parity (rate-limit, sticky, advanced headers)

Delivered from roadmap in this release:
- Hetzner DNS automation (A/AAAA upsert) via `domainup dns --provider hetzner --token ...`
- Optional htpasswd file generation for basic auth (render-time)
- Better CORS passthrough controls
- Traefik basic middlewares: BasicAuth + CORS