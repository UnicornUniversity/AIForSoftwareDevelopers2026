# Known Issues — Nginx & SSL

**Owner:** Anežka K.
**Last updated:** 2024-12-19

---

## KI-NGX-001 — 2024-02-11 outage from missing `nginx -t` before reload

**Discovered:** 2024-02-11 (incident)
**Status:** Runbook updated; not fully preventable
**Severity:** High when it happens

An engineer edited an `include` snippet, ran `systemctl reload nginx`, and
Nginx refused to reload. The service continued running on the old config,
but a subsequent `restart` (during a routine maintenance script) failed
because the new config was invalid. Public traffic hit 100% 502 for 6 min.

**Prevention:** ALWAYS run `nginx -t` before reload/restart. The habit is
so important it's now in [docs/04-nginx-configuration.md](../docs/04-nginx-configuration.md).
CI validates edge configs, but per-VPS edits are still by-hand.

---

## KI-NGX-002 — Let's Encrypt HTTP-01 challenge broken behind Cloudflare (proxied)

**Discovered:** 2022-08 (recurring)
**Status:** Documented workaround
**Severity:** Low but frequent support ticket

If a customer proxies through Cloudflare with SSL mode "Flexible" or "Full",
the HTTP-01 challenge over port 80 can fail because Cloudflare terminates
TLS and forwards over HTTPS, and Nginx isn't listening properly.

**Workarounds:**
- Switch the DNS record to "DNS only" (grey cloud) during renewal.
- Or use DNS-01 challenge via Certbot's Cloudflare plugin.

Some customers repeatedly hit this because they don't remember to disable
the proxy every 60 days. Suggestion (not implemented): switch them to DNS-01
permanently.

---

## KI-NGX-003 — `nginx_upstream_check_module` breaks with Nginx 1.24+

**Discovered:** 2023-12
**Status:** Deprecated internally
**Severity:** Low (only affected 2 internal services)

The patched Nginx build with `nginx_upstream_check_module` no longer compiles
against Nginx 1.24. We've been recommending against it since 2023 in favor
of HAProxy or Nginx Plus.

Any customer doc referencing this module is outdated. See
[docs/07-reverse-proxy-setup.md](../docs/07-reverse-proxy-setup.md) for the
current recommendation.

---

## KI-NGX-004 — HTTP/2 with `proxy_pass` occasionally drops long-idle connections

**Discovered:** 2024-05
**Status:** Kernel-level tuning applied on edges
**Severity:** Low

Long-idle HTTP/2 connections to upstream drop after ~ 5 minutes despite
`keepalive_timeout` being higher. Root cause: net.ipv4.tcp_keepalive_time
on the host defaults to 7200s, and stateful firewalls in the path expire
NAT entries first.

**Fix:** on edge hosts,
```
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 6
```

Also set `proxy_socket_keepalive on;` in Nginx.

Applied to `edge-01`, `edge-02` in Aug 2024.

---

## KI-NGX-005 — Certbot post-renew hook fires before Nginx config validated

**Discovered:** 2024-10
**Status:** Open — needs a hook script rewrite
**Severity:** Low

Certbot's default deploy hook does `systemctl reload nginx` regardless of
whether the new cert is compatible with the existing Nginx config. If a
misconfigured `ssl_ecdh_curve` (from an old vhost) exists, reload can fail
silently.

**Workaround:** custom post-renew hook that does `nginx -t` first and pages
on failure. Script has been drafted but not deployed everywhere as of Q4 2024.

---

## See also

- [docs/04-nginx-configuration.md](../docs/04-nginx-configuration.md)
- [docs/09-ssl-certificates.md](../docs/09-ssl-certificates.md)
- [logs/nginx-error.log](../logs/nginx-error.log)
