# FAQ — Technical

**Audience:** Customers.
**Owner:** Support engineering team.
**Last updated:** 2025-02-12

---

### How do I connect to my VPS?

SSH with the key you uploaded during provisioning:

```
ssh root@<your-vps-ip>
```

The initial key is emailed to you, or if you provided your own public key,
that one is authorized. Password authentication is disabled by default.

### I lost my SSH key. What do I do?

Open a ticket. We'll boot your VPS into rescue mode and let you paste a
new public key. This takes ~15 minutes end-to-end.

### How do I set up HTTPS?

See [docs/09-ssl-certificates.md](../docs/09-ssl-certificates.md).
Short version: install Nginx, install `certbot`, run
`sudo certbot --nginx -d yourdomain.cz`. Certbot handles renewal automatically.

### Why is my SSL certificate not renewing?

The most common cause is port 80 being blocked (Let's Encrypt HTTP-01 challenge
requires port 80). Check that:

- Your firewall allows inbound 80 from `0.0.0.0/0`
- Nginx is serving the `/.well-known/acme-challenge/` path
- The DNS record still points at your VPS

If you use Cloudflare, temporarily switch the record to "DNS only" (grey cloud)
during renewal, or use DNS-01 challenge instead.

Second-most-common cause: you hit the Let's Encrypt rate limit (50 certs per
registered domain per week). Wait a week or use staging while you debug.

### How do I set up a reverse proxy?

See [docs/07-reverse-proxy-setup.md](../docs/07-reverse-proxy-setup.md).
This is the most common support request from customers new to VPS.

### How do I forward ports?

For a single VPS: it's your VPS, use `iptables` or `ufw`. We don't proxy on
your behalf (except for Cloudflare-fronted setups you configure).

For PCH-K8s: use a `Service` of type `LoadBalancer` (creates a Cloudflare
front) or `NodePort` (opens a high-numbered port on the worker).

### Where are my logs?

- **VPS:** SSH in and read `/var/log/`
- **PCH-K8s:** Grafana → Explore → Loki (only visible if you enabled log
  shipping when you created the cluster)

### My server is slow. What do I check?

1. `top` / `htop` — CPU pressure?
2. `free -h` — swapping?
3. `iotop` — disk I/O saturated?
4. `ss -s` — connection count?
5. `dmesg` — hardware or kernel issues?

If none of the above show anything obvious, it might be network. Check
[Prague-side ping](https://looking-glass.pchosting.cz) or open a ticket.

### How do I schedule automated backups?

- **VPS:** daily snapshots are included (retained 7 days). You can trigger
  extras from the portal. For custom backups, we recommend
  [restic](https://restic.net/) or [BorgBackup](https://www.borgbackup.org/)
  to our object storage.
- **Managed Postgres:** backups are automatic; you can trigger a manual
  base backup via the portal.

### Related FAQ

- [Docker FAQ](docker.md)
- [Database FAQ](database.md)
- [Reverse proxy docs](../docs/07-reverse-proxy-setup.md)
