# Known Issues — Docker

**Owner:** Tomáš H.
**Last updated:** 2025-02-06

---

## KI-DOCK-001 — Docker 20.10 on legacy-app-01 doesn't understand `--platform`

**Discovered:** 2023-04
**Status:** Open — workaround in place
**Severity:** Low (internal only)

`legacy-app-01.prg1` still runs Docker 20.10. Any `docker compose` file using
the `platform:` key at the service level fails with "unknown option".

**Workaround:** Don't set `platform:` in compose files targeting
`legacy-app-01`. Build multi-arch images and let the daemon pick.

**Real fix:** Migrate `legacy-app-01` to Docker 24 (planned for the same
migration project as
[known_issues/pending-projects.md](pending-projects.md)).

---

## KI-DOCK-002 — Rate limits on Docker Hub anonymous pulls

**Discovered:** 2020-11
**Status:** Mitigated with mirror
**Severity:** Medium

Docker Hub imposes 100 pulls / 6 hours for anonymous IPs. On CI-heavy hosts
we hit this within an hour.

**Mitigation:** Use `mirror.prg1.pchosting.cz` as a pull-through cache
(configured on all internal hosts). Customer VPS can opt in — see the
[Docker FAQ](../faq/docker.md).

---

## KI-DOCK-003 — Bridge network overlap with customer VPNs

**Discovered:** 2024-09
**Status:** Documented; per-host fix
**Severity:** Medium

Default Docker bridge uses `172.17.0.0/16`, which overlaps with a common
choice for customer VPN CIDRs. Symptom: containers can reach some, but not
all, of the customer's internal network.

**Fix:** Change the bridge CIDR in `/etc/docker/daemon.json`:

```json
{ "bip": "10.99.0.1/16" }
```

Restart Docker. Note: this deletes existing user-defined networks unless
you're careful. See [docs/05-docker-troubleshooting.md](../docs/05-docker-troubleshooting.md)
section 4.

---

## KI-DOCK-004 — `docker system prune -a` on Business VPS killing customer's data volumes

**Discovered:** 2024-06 (customer ticket #48812)
**Status:** Documentation updated
**Severity:** High when it happens

Customers occasionally run `docker system prune -a --volumes` on production
VPS to free space, then discover it removed volumes that had customer data
they cared about (they had built ephemeral-looking Compose files).

**Prevention:** We've updated the [Docker FAQ](../faq/docker.md) with a
big warning. But there's no way to prevent a customer from doing this on
their own VPS.

**Recovery:** Restore from the daily snapshot (up to 24h data loss).

---

## KI-DOCK-005 — Log driver `json-file` growing unbounded on default installs

**Discovered:** 2022 (recurring)
**Status:** Docs, not enforced
**Severity:** Recurring

Fresh Docker installs default to unbounded `json-file` logging. Customers
report disk full; investigation reveals 40 GB of container stdout in
`/var/lib/docker/containers/*/*.log`.

**Fix:** Set log rotation in `/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" }
}
```

**Note:** this only applies to *new* containers. Existing containers keep
their old logging config until recreated.

---

## See also

- [docs/05-docker-troubleshooting.md](../docs/05-docker-troubleshooting.md)
- [faq/docker.md](../faq/docker.md)
- [configs/docker-daemon.json](../configs/docker-daemon.json)
