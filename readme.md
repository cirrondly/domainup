# Repository: cirrondly-proxy-nginx
### Purpose: One-command deployment of Nginx reverse-proxy + Let's Encrypt (webroot) for


monitoring.cirrondly.com, otlp.cirrondly.com, webhooks.cirrondly.com, grafana.cirrondly.com

### Usage:   

1) Copy this repo to your server (git clone or scp),
2) cp .env.example .env && edit,
3) make init && make up && make cert


(certs auto-renew via cron with `make install-cron`)