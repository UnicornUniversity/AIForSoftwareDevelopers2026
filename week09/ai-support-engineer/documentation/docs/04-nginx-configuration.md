# Nginx Configuration

**Author:** Anežka K.
**Last updated:** 2024-11-22
**Status:** Current

Standard reverse-proxy and TLS-termination setup for edge nodes (edge-01, edge-02)
and per-tenant Nginx instances used by customers on VPS plans.

## File layout

```
/etc/nginx/
├── nginx.conf                # main config
├── conf.d/                   # per-service upstreams
│   ├── api.conf
│   ├── portal.conf
│   └── static.conf
├── sites-available/          # per-vhost
├── sites-enabled/            # symlinks into sites-available
├── snippets/
│   ├── ssl-modern.conf       # TLS 1.2+ ciphers (Mozilla "modern")
│   ├── ssl-intermediate.conf # TLS 1.2+ (broader compat)
│   ├── proxy-defaults.conf   # timeouts, buffers
│   └── security-headers.conf # HSTS, X-Content-Type-Options, etc.
└── ssl/                      # certs + keys (chmod 640, root:ssl-cert)
```

The reference `nginx.conf` is in [configs/nginx.conf](../configs/nginx.conf).

## Common patterns

### Reverse proxy to an upstream

```
server {
    listen 443 ssl http2;
    server_name portal.example.cz;

    include snippets/ssl-modern.conf;
    ssl_certificate     /etc/nginx/ssl/example.cz/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/example.cz/privkey.pem;

    include snippets/security-headers.conf;

    location / {
        proxy_pass         http://portal_upstream;
        include            snippets/proxy-defaults.conf;
    }
}

upstream portal_upstream {
    server 10.100.5.11:8080;
    server 10.100.5.12:8080 backup;
    keepalive 32;
}
```

### WebSocket upstream

Add these to the `location` block:

```
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 3600s;
```

## Reload vs restart

- `nginx -s reload` — zero-downtime, use for config changes.
- `systemctl restart nginx` — only after upgrading the binary or when reload
  refuses (rare, but happens after certain SSL config changes).

Always run `nginx -t` first. Yes, always. See
[known_issues/nginx-ssl.md](../known_issues/nginx-ssl.md) for the 2024-02 outage
caused by skipping this.

## Rate limiting

Default zones defined in `nginx.conf`:

- `req_limit_per_ip` — 10 r/s, burst 20, applied to `/api/`
- `login_limit_per_ip` — 3 r/s, burst 5, applied to `/api/auth/login`

Tune per service in `conf.d/<service>.conf`.

## See also

- [docs/07-reverse-proxy-setup.md](07-reverse-proxy-setup.md)
- [docs/09-ssl-certificates.md](09-ssl-certificates.md)
- [known_issues/nginx-ssl.md](../known_issues/nginx-ssl.md)
