from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Literal, Optional
import yaml
from pydantic import BaseModel, Field, field_validator


Engine = Literal["nginx", "traefik"]
CertMethod = Literal["webroot", "dns01"]
LBStrategy = Literal["round_robin", "least_conn"]


class Upstream(BaseModel):
    name: str
    target: str
    weight: int = 1


class PathRoute(BaseModel):
    path: str
    upstream: str
    websocket: bool = False
    strip_prefix: bool = False
    body_size: Optional[str] = None


class Headers(BaseModel):
    hsts: bool = True
    extra: Dict[str, str] = Field(default_factory=dict)


class RateLimit(BaseModel):
    enabled: bool = False
    requests_per_minute: int = 600


class BasicAuth(BaseModel):
    enabled: bool = False
    users: List[str] = Field(default_factory=list)


class Security(BaseModel):
    basic_auth: BasicAuth = Field(default_factory=BasicAuth)
    allow_ips: List[str] = Field(default_factory=list)
    rate_limit: RateLimit = Field(default_factory=RateLimit)


class TLS(BaseModel):
    enabled: bool = True


class DomainConfig(BaseModel):
    host: str
    upstreams: List[Upstream]
    paths: List[PathRoute] = Field(default_factory=list)
    headers: Headers = Field(default_factory=Headers)
    security: Security = Field(default_factory=Security)
    tls: TLS = Field(default_factory=TLS)
    gzip: bool = True
    cors_passthrough: bool = False
    lb: LBStrategy = "round_robin"
    sticky_cookie: Optional[str] = None  # cookie name if sticky enabled

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, v, info):
        # ensure path upstream references exist
        upstream_names = {u.name for u in info.data.get("upstreams", [])}
        for p in v:
            if p.upstream not in upstream_names:
                raise ValueError(f"path.upstream '{p.upstream}' is not defined in upstreams")
        return v


class CertConfig(BaseModel):
    method: CertMethod = "webroot"
    webroot_dir: str = "./www/certbot"
    staging: bool = False


class Runtime(BaseModel):
    http_port: int = 80
    https_port: int = 443


class Config(BaseModel):
    version: int = 1
    email: str
    engine: Engine = "nginx"
    cert: CertConfig = Field(default_factory=CertConfig)
    network: str = "proxy_net"
    domains: List[DomainConfig] = Field(default_factory=list)
    # Optional runtime options (e.g., host ports). Defaults to 80/443.
    runtime: Runtime = Field(default_factory=Runtime)


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    data = yaml.safe_load(path.read_text())
    return Config.model_validate(data)


SAMPLE_CONFIG_TEMPLATE = """
# domainup.yaml - generic reverse proxy config
version: 1
email: {email}
engine: nginx  # nginx | traefik (poc)
cert:
  method: webroot   # webroot | dns01 (todo)
  webroot_dir: ./www/certbot
  staging: false    # set true to use Let's Encrypt staging for tests
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
    tls:
      enabled: true
    gzip: true
    cors_passthrough: false

  - host: console.example.com
    upstreams:
      - name: console
        target: console:3000
    paths:
      - path: /
        upstream: console
    security:
      basic_auth:
        enabled: true
        users: ["admin:{SHA}..."]  # TODO: support htpasswd files
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
""".lstrip()


def write_sample_config(path: Path, email: str) -> None:
  # Avoid str.format because the YAML sample contains many literal braces `{}`.
  # We only replace the {email} token explicitly.
  path.write_text(SAMPLE_CONFIG_TEMPLATE.replace("{email}", email))
