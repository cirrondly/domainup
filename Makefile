SHELL := /bin/bash
ENV ?= .env
include $(ENV)
export

.PHONY: init up down reload cert renew logs status test install-cron uninstall-cron

init:
	@echo "[init] Creating dirs and docker network..."
	mkdir -p www/certbot letsencrypt nginx/conf.d /var/log/nginx || true
	docker network create proxy_net || true
	@echo "[init] Done. Now: make up"

up:
	@echo "[up] Starting nginx & certbot containers..."
	docker compose up -d

reload:
	@echo "[reload] Reloading nginx..."
	docker exec nginx_proxy nginx -s reload || docker restart nginx_proxy

down:
	@echo "[down] Stopping stack..."
	docker compose down

cert:
	@echo "[cert] Obtaining certificates via webroot..."
	docker run --rm \
	  -v "$$PWD/www/certbot:/var/www/certbot" \
	  -v "$$PWD/letsencrypt:/etc/letsencrypt" \
	  certbot/certbot certonly --webroot -w /var/www/certbot \
	  -d $(DOMAIN_BACK) -d $(DOMAIN_OTLP) -d $(DOMAIN_WEBHOOKS) -d $(DOMAIN_GRAFANA) \
	  --agree-tos -m $(LE_EMAIL) --no-eff-email --deploy-hook "nginx -s reload" || true
	@echo "[cert] Restarting nginx to load certs..."
	docker restart nginx_proxy

renew:
	@echo "[renew] Running certbot renew..."
	docker run --rm \
	  -v "$$PWD/www/certbot:/var/www/certbot" \
	  -v "$$PWD/letsencrypt:/etc/letsencrypt" \
	  certbot/certbot renew --webroot -w /var/www/certbot || true
	docker restart nginx_proxy

logs:
	docker logs -f nginx_proxy

status:
	@echo "[status] DNS check (requires dig/curl on host)"
	-@dig +short A $(DOMAIN_BACK)
	-@dig +short AAAA $(DOMAIN_BACK)
	-@dig +short A $(DOMAIN_OTLP)
	-@dig +short AAAA $(DOMAIN_OTLP)
	-@curl -I https://$(DOMAIN_BACK)/health || true
	-@curl -I https://$(DOMAIN_OTLP)/v1/metrics || true

test:
	@echo "[test] Running pytest in project venv (.venv)"
	. .venv/bin/activate && python -m pytest -q

install-cron:
	@echo "[cron] Installing daily renew cron @ 03:00..."
	( crontab -l 2>/dev/null; echo "0 3 * * * cd $$PWD && make renew" ) | crontab -

uninstall-cron:
	@echo "[cron] Removing renew cron..."
	crontab -l | sed '/make renew/d' | crontab -