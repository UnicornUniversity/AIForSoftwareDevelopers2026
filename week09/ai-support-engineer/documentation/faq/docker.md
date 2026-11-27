# FAQ — Docker & Containers

**Audience:** Customers running Docker on VPS or PCH-K8s.
**Owner:** Support engineering.
**Last updated:** 2024-12-01

---

### Can I run Docker on a Micro plan?

Yes, technically, but 2 GB of RAM is tight for anything beyond hello-world.
We recommend the **Small** plan or larger for serious Docker workloads.

### Which Docker version comes preinstalled?

None. Docker is not preinstalled on any of our VPS images (as of 2024).
Install it yourself:

```
curl -fsSL https://get.docker.com | sh
```

Or use our provided cloud-init template ("Ubuntu 22.04 + Docker") when
creating a VPS.

### My container was killed with exit code 137. What happened?

That's the OOM killer. The container tried to use more memory than allowed.

- No memory limit set? Then the host OOM-killer got it — probably the whole
  VPS was memory-pressured.
- Memory limit set? Bump it, or find and fix the leak.

See [docs/05-docker-troubleshooting.md](../docs/05-docker-troubleshooting.md)
section 2.

### `docker: no space left on device`

Almost always Docker's own storage on `/var/lib/docker` filled up.
Free it up:

```
docker system prune -a --volumes
```

**Warning:** this removes ALL stopped containers, unused images, and unused
volumes. Read the docs first if you have data in volumes you care about.

Prevent recurrence by rotating container logs
([docs/05-docker-troubleshooting.md](../docs/05-docker-troubleshooting.md)
section 3).

### Can I use Docker Compose?

Yes — install with:

```
apt install docker-compose-plugin
```

Note: `docker-compose` (v1, hyphenated) is deprecated. Use `docker compose`
(v2, spaced). Some legacy tutorials still reference v1 syntax; most is
compatible but a few directives changed.

### Are my Docker volumes backed up?

Only if you configure it. Our default VPS snapshot captures the *whole disk*
including `/var/lib/docker/volumes`, so if you never enabled anything special,
you do have snapshot-based backups (7 days retention).

For point-in-time volume backups, run `restic` or `borg` from cron.

### How do I use your internal image registry?

You don't — the internal registry `registry.prg1.pchosting.internal` is for
PCH's own services. Customers should use Docker Hub, GHCR, or their own
registry.

We provide a **Docker Hub pull-through mirror** at
`mirror.prg1.pchosting.cz` to avoid Docker Hub rate limits. To use it, add
to `/etc/docker/daemon.json`:

```json
{ "registry-mirrors": ["https://mirror.prg1.pchosting.cz"] }
```

Restart Docker after editing.

### My container can't reach the internet

Usual suspects:

1. Docker network CIDR overlaps with your VPN/private network — pick a
   different `bip` in `/etc/docker/daemon.json`.
2. MTU issues — set `"mtu": 1420` on Wireguard-connected hosts.
3. iptables rules dropping egress from `DOCKER-USER` — check with
   `iptables -L DOCKER-USER -n`.

Full troubleshooting: [docs/05-docker-troubleshooting.md](../docs/05-docker-troubleshooting.md)
section 4.

### Related FAQ

- [Technical FAQ](technical.md)
- [Docker troubleshooting docs](../docs/05-docker-troubleshooting.md)
- [Docker known issues](../known_issues/docker-issues.md)
