# SSL Certificates (Current)

**Author:** Anežka K.
**Last updated:** 2024-10-05
**Supersedes:** [docs/09b-ssl-legacy.md](09b-ssl-legacy.md)
**Status:** Current

Standard procedure for issuing and renewing SSL certificates on PCH-managed
edges and customer VPS.

## TL;DR

- **Public certs:** Let's Encrypt via `certbot` (recommended) or `acme.sh`.
- **Internal certs:** private CA, `pch-internal-ca`. Certs valid 1 year,
  automated via HashiCorp Vault PKI.
- **Wildcards:** DNS-01 challenge only (Let's Encrypt requirement).

## Renewal

`certbot renew` runs twice daily via systemd timer:

```
$ systemctl list-timers | grep certbot
Sun 2025-03-09 07:12:00 CET  certbot.timer  certbot.service
```

Renews any cert with fewer than 30 days remaining. Post-renew hook reloads
Nginx (`systemctl reload nginx`).

Manual renewal:

```
sudo certbot renew --dry-run             # test first!
sudo certbot renew
```

If renewal fails, check:

1. Port 80 open (HTTP-01 challenge) — see [known_issues/nginx-ssl.md](../known_issues/nginx-ssl.md)
2. DNS records unchanged
3. Rate limits — Let's Encrypt allows 50 certs / registered domain / week
4. Nginx config valid (`nginx -t`)

## Issuing a new cert

### HTTP-01 (single host, port 80 reachable)

```
sudo certbot --nginx -d app.customerdomain.cz
```

Certbot edits the vhost automatically. Review the diff before reload.

### DNS-01 (wildcards, or port 80 blocked)

```
sudo certbot certonly --manual --preferred-challenges dns \
     -d '*.customerdomain.cz' -d customerdomain.cz
```

You'll be prompted to add TXT records. Automate with the DNS plugin if the
customer uses Cloudflare / Route53 / Gandi.

## Cert file layout

Certbot places files at:

```
/etc/letsencrypt/live/<primary-domain>/
    ├── fullchain.pem       -> ../../archive/<...>/fullchainN.pem
    ├── privkey.pem         -> ../../archive/<...>/privkeyN.pem
    ├── cert.pem
    └── chain.pem
```

Always reference `fullchain.pem` and `privkey.pem` in Nginx (the live symlinks).
Do **not** reference the archive files directly — they'll go stale on renewal.

## Monitoring expiry

Prometheus `blackbox_exporter` scrapes every managed endpoint and exports
`probe_ssl_earliest_cert_expiry`. Alert fires at 21 days remaining.
See [configs/prometheus.yml](../configs/prometheus.yml).

## See also

- [docs/04-nginx-configuration.md](04-nginx-configuration.md)
- [docs/09b-ssl-legacy.md](09b-ssl-legacy.md) (for legacy free-wildcard customers)
- [known_issues/nginx-ssl.md](../known_issues/nginx-ssl.md)
- [faq/technical.md](../faq/technical.md)
