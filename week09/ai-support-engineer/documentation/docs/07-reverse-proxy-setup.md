# Reverse Proxy Setup

**Author:** Anežka K.
**Last updated:** 2024-08-30
**Status:** Current

How to set up a reverse proxy in front of a customer application on PCH.
This is the pattern our first-line support walks customers through when they
call about "my app is on port 3000, how do I get HTTPS on port 443".

## Prerequisites

- A VPS or K8s workload listening on some internal port
- A DNS A/AAAA record for the customer domain pointing at the VPS public IP
  (or at the shared edge IPs for K8s: `195.181.144.10` and `195.181.144.11`)
- Nginx installed on the VPS (Ubuntu: `apt install nginx`) — or use the
  managed edge for K8s

## Minimal vhost

```
server {
    listen 80;
    server_name app.customerdomain.cz;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name app.customerdomain.cz;

    ssl_certificate     /etc/letsencrypt/live/app.customerdomain.cz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.customerdomain.cz/privkey.pem;

    # Modern intermediate profile
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:...';
    ssl_prefer_server_ciphers off;

    location / {
        proxy_pass         http://127.0.0.1:3000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

## For customers behind Cloudflare

If a customer already fronts their site with Cloudflare, they will typically
turn on "Full (strict)" SSL. Two important notes:

1. The origin cert must be valid — Let's Encrypt is fine, so is a
   Cloudflare Origin Cert. **Don't self-sign.**
2. Real client IP: use the `set_real_ip_from` block with Cloudflare's IP
   ranges. Snippet: `snippets/cloudflare-realip.conf`. Update quarterly —
   Cloudflare adds ranges occasionally.

## Load balancing multiple backends

Use an `upstream` block. See the pattern in
[docs/04-nginx-configuration.md](04-nginx-configuration.md).

Health checks in open-source Nginx are passive only (retries after failure).
For active checks we recommend HAProxy or paying for Nginx Plus. We used to
suggest `nginx_upstream_check_module` (patched build) — do NOT anymore, it
breaks with Nginx 1.24+.

## Common mistakes

- **Missing `Host` header.** Backend receives `127.0.0.1` as the Host and
  gets confused. Always set `proxy_set_header Host $host`.
- **Wrong client IP.** Add `X-Forwarded-For` and configure the backend to
  trust it (Django `USE_X_FORWARDED_HOST`, Rails `config.action_dispatch.trusted_proxies`, etc.).
- **HTTPS redirect loop.** Backend sees `http` (because Nginx proxies over
  plain HTTP) and redirects to HTTPS, which lands on Nginx, which proxies
  as HTTP again. Fix: `proxy_set_header X-Forwarded-Proto $scheme` and make
  the backend honor it.

## See also

- [docs/04-nginx-configuration.md](04-nginx-configuration.md)
- [docs/09-ssl-certificates.md](09-ssl-certificates.md)
- [faq/technical.md](../faq/technical.md)
