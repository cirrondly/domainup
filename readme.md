🚀 DomainUp 0.1.2 just released – turn your Docker services into HTTPS domains in 1 minute.

# DomainUp

*Config-driven reverse proxy for Docker apps that ships production-ready **HTTPS** Nginx automation from a single **YAML**.*


[![PyPI](https://img.shields.io/pypi/v/domainup?color=3775A9&label=PyPI&logo=python)](https://pypi.org/project/domainup/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/cirrondly/domainup)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/cirrondly/domainup?style=social)](https://github.com/cirrondly/domainup/stargazers)

## Table of Contents
- [Why DomainUp](#why-domainup)
- [Features](#features)
- [Quickstart](#quickstart)
- [Requirements](#requirements)
- [Installation](#installation)
- [Example: domainup.yaml → rendered Nginx](#example-domainupyaml-rendered-nginx)
- [Configuration](#configuration)
- [Configuration Options](#configuration-options)
- [Usage Examples](#usage-examples)
- [Files Generated](#files-generated)
- [DomainUp vs Hetzner DNS – Complementary Tools](#domainup-vs-hetzner-dns--complementary-tools)
- [How It Works](#how-it-works)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [Star & Support](#star-support)
- [License](#license)

## Why DomainUp

Every self-hosted DevOps sprint looked the same: log into a Hetzner box, wire up a reverse proxy, massage Nginx blocks, request Let’s Encrypt certs, and cross fingers that Docker endpoints still spoke **HTTPS**.

DomainUp turns that loop into a repeatable automation by reading one **YAML** map and emitting trusted templates for proxies and DNS orchestration.

- Save late-night pager time with https-ready domains launched in under a minute.
- Keep self-hosted Docker fleets tidy with versioned yaml and repeatable proxy steps.
- Give devops teammates confidence that Let’s Encrypt renewals, security headers, and monitoring hooks run on schedule.

## Features
- ⚡ Single **YAML** manifest defines every edge domain across Docker upstreams.
- 🔐 Built-in **HTTPS** termination with Let’s Encrypt webroot renewals and optional HSTS.
- 🔁 Smart automation for DevOps teams with templated Nginx and Traefik renderers.
- 🧰 Self-hosted friendly: headers, websockets, basic auth, rate limits, sticky cookies, and path routing.
- 📦 Works with multiple Docker services, health checks, and per-domain overrides.
- FinOps-friendly: **YAML**-as-source-of-truth, predictable **HTTPS** automation, reproducible across environments.

## Quickstart

⭐ If this project saves you time, please consider **starring** the repo — it helps more self-hosters find it.

Get up and running on a fresh self-hosted node with the CLI in minutes.

Install the CLI (see also [Installation](#installation)):

```bash
pipx install domainup    # or: pip install domainup
```

If you haven’t installed the CLI yet, see [Installation](#installation))

Run this minimal flow to validate the yaml stack, render Nginx, bring up the reverse proxy, and request Let’s Encrypt certs for https endpoints:

```bash
domainup init --email contact@cirrondly.com   # creates domainup.yaml skeleton
domainup plan                                 # validate + print plan
domainup render                               # generate Nginx configs from yaml
domainup up                                   # start Nginx gateway
domainup cert                                 # obtain certs (webroot)
domainup reload                               # reload Nginx
domainup deploy                               # render -> up -> cert -> reload
domainup check --domain api.example.com       # quick diagnostics
```

This automation works equally well on local **Docker Compose** or remote hosts.

Local testing tips:
- If ports 80/443 are busy, either:
	- Override at runtime: `domainup up --http-port 8080 --https-port 8443` (no file edits), or
	- Make it permanent: set `runtime.http_port`/`runtime.https_port` in `domainup.yaml`, then `domainup up`.
- For HTTPS locally, use `mkcert` and place certs under `./letsencrypt/live/<host>/`.

## Example: domainup.yaml → rendered Nginx

Here’s the central **YAML** manifest that DomainUp consumes to manage multiple domains:

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
				target: app:8000
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

The renderer outputs an Nginx server block with upstreams and https wiring:

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    include snippets/headers.conf;

    location / {
        proxy_pass http://app1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Requirements
- Linux VM or local machine with **Docker** and **Docker Compose v2**
- Ports **80** and **443** available (for HTTP-01 / HTTPS)
- A writable directory for Let’s Encrypt assets (e.g. `./letsencrypt/`)

## Installation

**From PyPI**
```bash
# user-wide (pipx) – recommandé pour les CLIs
pipx install domainup

# ou via pip (virtualenv/venv)
pip install domainup
```

With Docker (no Python needed)

```bash
docker run --rm -it \
  -v $PWD:/work \
  -v $PWD/letsencrypt:/work/letsencrypt \
  -p 80:80 -p 443:443 \
  ghcr.io/cirrondly/domainup:latest domainup --help
```

## Configuration

DomainUp reads the `domainup.yaml` file for these options:

```yaml
version: 1
email: contact@cirrondly.com
engine: nginx   # Nginx | traefik (poc)
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
				target: app:8000
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

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `engine` | Selects the renderer (`Nginx` or `traefik`) for the edge gateway. | `Nginx` |
| `cert.method` | Chooses certificate strategy (`webroot` today, `dns01` planned) via Let’s Encrypt. | `webroot` |
| `network` | Docker network name used to wire containers behind the gateway container. | `proxy_net` |
| `runtime.http_port` / `runtime.https_port` | Host ports exposed for http/https listeners. | `80` / `443` |
| `domains[].paths[].websocket` | Enables websocket upgrade support per route. | `false` |
| `domains[].security.basic_auth` | Configures htpasswd or inline users for protected paths. | `false` |
| `domains[].security.rate_limit` | Simple rate limiting (requests per minute) for DevOps safeguards. | `600` |

## Usage Examples

Generate configs for the running proxy stack:

```bash
domainup render && domainup up
```

Obtain certificates through Let’s Encrypt and reload the edge:

```bash
domainup cert && domainup reload
```

Check DNS and TLS quickly during automation runs:

```bash
domainup check --domain api.example.com
```

## Auto-discovery mode (zero-config)

`domainup up` can scan running Docker containers, list published ports, and guide you to map each service to a domain without touching YAML.

```bash
domainup up   # discover → ask domains → write domainup.yaml → render+up+cert+reload

# Or run discovery alone:
domainup discover

# Typical guided flow
Found 4 containers with published ports:

[1] back_web_1      → 8000/tcp → 0.0.0.0:8000
[2] otel            → 4318/tcp → 0.0.0.0:4318
[3] grafana         → 3000/tcp → 0.0.0.0:3000
[4] stripe_worker   → 8080/tcp → 0.0.0.0:8080

Choose domain for back_web_1 (suggest: back_web_1.example.com): monitoring.cirrondly.com
Enable websockets? [y/N]: y

Choose domain for otel (suggest: otel.example.com): otlp.cirrondly.com
Large body (20m) for OTLP? [Y/n]: y

Choose domain for grafana (suggest: grafana.example.com): grafana.cirrondly.com
Protect with Basic Auth? [y/N]: n

Choose domain for stripe_worker (suggest: stripe_worker.example.com): webhooks.cirrondly.com
```

This will:

1. Detect containers with published TCP ports.
2. Let you pick a FQDN per service (with smart defaults).
3. Write/update domainup.yaml (idempotent).
4. Optionally start Nginx, issue certs, and reload.


Print DNS records for your provider (Hetzner, Cloudflare, Vercel) before you flip traffic:

```bash
domainup dns --ipv4 203.0.113.10 --ipv6 2001:db8::10
```

## Files Generated

### Nginx engine
- `nginx/nginx.conf`
- `nginx/conf.d/00-redirect.conf` (http→https + ACME webroot for all TLS hosts)
- `nginx/conf.d/<host>.conf` per domain
- `runtime/docker-compose.nginx.yml` to run the proxy

### Traefik engine
- `traefik/traefik.yml` (static)
- `traefik/dynamic/<host>.yml` per domain with middlewares
- `traefik/htpasswd/<host>.htpasswd` when basic auth enabled
- `runtime/docker-compose.traefik.yml` to run the proxy

## DomainUp vs Hetzner DNS – Complementary Tools

Developers sometimes ask: “If Hetzner DNS already exists, why would I need DomainUp?” Good question — they serve two different layers of the stack.

| Purpose | Hetzner DNS | DomainUp |
|---------|-------------|-----------|
| Manage DNS zones & records | ✅ Yes – creates A/AAAA/CNAME, etc. | ✅ Yes (via provider APIs, e.g. Hetzner, Cloudflare, Vercel) |
| Configure reverse proxy (Nginx / Traefik) | ❌ | ✅ Generates and reloads configs automatically |
| Obtain & renew Let's Encrypt certificates | ❌ | ✅ Full automation (HTTP-01 webroot today, DNS-01 soon) |
| Deploy and reload Dockerized edge | ❌ | ✅ domainup up, domainup reload, domainup deploy |
| Handle websockets, headers, auth, rate-limit, gzip | ❌ | ✅ Config-driven per domain |
| Provide a single CLI to set up new domains | ❌ | ✅ One-command automation |

### How they fit together
• Hetzner DNS is the authoritative DNS service that tells browsers “where to go”. It maps *.example.com → 91.98.141.137 (your server).

• DomainUp runs on that server and makes sure that, once traffic arrives, it’s routed to the right container, secured with HTTPS, and kept alive.

You can (and should) use both:

1. Keep Hetzner DNS as your DNS provider (fast, reliable, free API).
2. Use DomainUp to automate everything after DNS — proxy, certs, reloads.
3. Or let DomainUp call Hetzner’s API directly to create/update A/AAAA records automatically:

```bash
domainup dns --provider hetzner --token $HETZNER_DNS_TOKEN \
  --record monitoring A 91.98.141.137 \
  --record monitoring AAAA 2a01:4f8:1c1c:5d0e::1
```

### Override ports at runtime (no file edits)

If your machine already uses 80/443, you can override host ports just for this run:

```bash
domainup up --http-port 8080 --https-port 8443
```

You can still make it permanent by editing `domainup.yaml` under `runtime:` and re-running `domainup up`.

## Troubleshooting

### Ports 80/443 already in use

Symptoms:

```
Failed: ports 80/443 already in use on host.
```

Fix it in one of these ways:

- Quick (one-off):

```bash
domainup up --http-port 8080 --https-port 8443
```

- Permanent (edit config): in `domainup.yaml` set:

```yaml
runtime:
	http_port: 8080
	https_port: 8443
```

Then run:

```bash
domainup up
```

Or free the default ports by stopping whatever binds to 80/443 and try again.

### Docker daemon is not running

Symptoms:

```
Cannot connect to the Docker daemon ... Is the docker daemon running?
```

Start your Docker engine on macOS, then retry:

```bash
open -a Docker          # Docker Desktop
# or
colima start            # Colima
# or
open -a OrbStack        # OrbStack
```

The CLI detects this scenario and prints a helpful hint if Docker isn’t up.

### nginx: host not found in upstream

Symptoms in logs:

```
nginx: [emerg] host not found in upstream "back_web_1:8000" in /etc/nginx/conf.d/<host>.conf:2
```

What it means:
- Nginx tried to resolve the upstream host at startup and couldn’t find it via Docker DNS.
- Common causes: the backend container isn’t on the same Docker network as the proxy, or the target uses a container instance name instead of the Compose service name.

How to fix:
1) Ensure the backend service joins the same network as DomainUp (default `proxy_net`). In your backend compose file:

```yaml
services:
	app:
		image: your/image
		networks: [proxy_net]

networks:
	proxy_net:
		external: true
```

2) Use the Compose service name, not a container instance name. For a service named `app` listening on 8000:

```yaml
upstreams:
	- name: app1
		target: app:8000
```

3) If the backend is running on the host (not in Docker), you can use `host.docker.internal:PORT` on macOS.

Verify connectivity:

```bash
docker network inspect proxy_net | jq '.[0].Containers | keys'
```

You should see both `nginx_proxy` and your backend service listed on `proxy_net`.

### 🔧 Typical setup

1. Create your DNS zone on Hetzner DNS or keep it on Vercel — both work.
2. Add A/AAAA records for each subdomain pointing to your Hetzner server.
3. On the server, run this chained deployment:

```bash
domainup render && domainup up && domainup cert && domainup reload
```

4. Optionally: `domainup dns hetzner --token …` to automate record creation next time.

## How It Works
- CLI parses the **YAML** spec and builds an in-memory model of domains, upstreams, and security rules.
- Template engine renders **Nginx** or **Traefik** configs, staging **Let’s Encrypt** assets where needed.
- **Docker Compose** files spin up the proxy containers with mounted certificates.
- Scheduled automation handles renewals, reloads, and optional DNS provider updates for DevOps teams.

## Roadmap

- DNS provider API integration: Vercel
- ACME DNS-01 support

Delivered from roadmap in this release:
- Hetzner DNS automation (A/AAAA upsert) via `domainup dns --provider hetzner --token ...`
- Cloudflare DNS automation (A/AAAA upsert) via `domainup dns --provider cloudflare --token ...`
- Optional htpasswd file generation for basic auth (render-time)
- Better CORS passthrough controls
- Traefik middlewares: BasicAuth + CORS + RateLimit + Sticky cookie
- Traefik advanced headers: HSTS + custom response headers (from `headers.hsts` and `headers.extra`)

## Contributing

Set up the dev environment with editable dependencies and tests:

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

## Star & Support

If DomainUp saves you time with proxy automation across Docker and Let’s Encrypt, ⭐ star the repo if it helped you! Share it with fellow self-hosted devops teams rolling out https services on yaml-first stacks.

## License

MIT License. See [LICENSE](LICENSE) for details.

Created with ❤️ by [Cirrondly](https://www.cirrondly.com) — a tiny startup by José MARIN.
