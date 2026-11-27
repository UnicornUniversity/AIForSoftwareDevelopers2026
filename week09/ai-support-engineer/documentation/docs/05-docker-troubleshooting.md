# Docker Troubleshooting

**Author:** Tomáš H. (initial), Petra N. (updated)
**Last updated:** 2025-02-18
**Status:** Current

Symptoms, causes, and fixes for the Docker issues we hit most often on PCH hosts.

## 1. "Cannot connect to the Docker daemon"

```
Cannot connect to the Docker daemon at unix:///var/run/docker.sock.
Is the docker daemon running?
```

**Checks:**

1. `systemctl status docker` — is it active?
2. `journalctl -u docker --since "10 min ago"` — panics, permission errors?
3. `ls -l /var/run/docker.sock` — should be `srw-rw---- root docker`.
4. Is your user in the `docker` group? `id` to confirm.

**Common causes:**

- Daemon exited due to OOM. Check `dmesg | grep -i oom`.
- `/var/lib/docker` filled the disk. See section 3.
- Corrupt storage driver metadata after unclean shutdown — usually needs
  `systemctl stop docker && rm -rf /var/lib/docker/tmp/* && systemctl start docker`.

## 2. Container keeps restarting (CrashLoopBackOff on K8s, restart loop on VPS)

```
docker logs --tail 100 <container>
```

If the last line is `exited with code 137` → OOM killed. Bump the memory
limit or fix the leak.

If the last line is `exited with code 139` → segfault. Check for glibc mismatches
between the image (e.g. Alpine vs Debian base) and any native modules.

Exit code 143 → SIGTERM (usually intentional).

Exit code 1 → application-level. Read the actual logs.

## 3. "No space left on device"

Almost always `/var/lib/docker` bloated by dangling images or logs.

```
df -h /var/lib/docker
docker system df
```

Prune (safe on non-prod first):

```
docker system prune -a --volumes         # nuclear
docker image prune -a --filter "until=168h"   # older than 7 days
docker builder prune -a --filter "until=48h"  # BuildKit cache
```

**Container log rotation.** By default, JSON file logs grow unbounded.
Every PCH host should have this in `/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" }
}
```

Check with `docker info | grep -A2 "Logging Driver"`.

## 4. Networking: containers can't reach the internet

- Check `iptables -L -n | head -50`. If `DOCKER-USER` chain has a customer
  firewall rule dropping egress, that's it.
- `docker network ls` — did someone create a network with an overlapping CIDR?
  We had this in Sep 2024 when a customer used `172.17.0.0/16` on their VPN.
- MTU issues on tunneled links (e.g., Wireguard). Standard MTU on our
  bridge is 1500; on VPN-backed hosts we drop it to 1420. See
  [configs/docker-daemon.json](../configs/docker-daemon.json).

## 5. "Failed to allocate network resources" / "address already in use"

```
docker: Error response from daemon: Address already in use.
```

- Port collision — `ss -tulpn | grep <port>`.
- Docker forgot to release the port after a hard restart —
  `systemctl restart docker` usually clears the leak.

## 6. Image pull failures

```
Error response from daemon: pull access denied for registry.prg1.pchosting.internal/...
```

- Registry auth expired? `docker login registry.prg1.pchosting.internal`.
- Certificate on the registry rotated? Check
  [known_issues/registry.md](../known_issues/registry-cert.md).

**External registries (Docker Hub) rate-limited:**

Since Nov 2020 Docker Hub imposes 100 pulls / 6h for anonymous IPs.
On busy hosts we use our own mirror `mirror.prg1.pchosting.internal`.
Configure in `daemon.json`:

```json
{ "registry-mirrors": ["https://mirror.prg1.pchosting.internal"] }
```

## See also

- [known_issues/docker-issues.md](../known_issues/docker-issues.md)
- [configs/docker-daemon.json](../configs/docker-daemon.json)
- [logs/docker-daemon.log](../logs/docker-daemon.log) (sample)
