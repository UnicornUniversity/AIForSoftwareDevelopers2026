# Runbook: Disaster Recovery (PRG1 loss)

**Owner:** Petra N.
**Last verified:** 2024-11-18 (tabletop, not real failover)
**Trigger:** Complete loss of PRG1 datacenter (fire, extended power outage,
             building-level network isolation > 2h)

## RTO / RPO targets

- **RTO:** 4 hours for customer-visible services on the Business/Pro tier
- **RPO:** 5 minutes (WAL shipping cadence)

These are targets, not guarantees. The last real full-region drill was in
Oct 2022 and took 6h 40min (see incident report in Confluence).

## Prerequisites (should already be true)

- Warm Postgres standbys in BRN1 for every managed instance
- Object storage replicated PRG1 → BRN1 (async, ~30s lag typical)
- DNS: authoritative NS at Cloudflare, TTL 300s for all customer-facing hostnames
- BRN1 has enough spare compute to run the "critical services" set

## Procedure

### Phase 1 — Assess (target: 15 min)

1. IC declares incident sev-1.
2. Confirm PRG1 is truly down — check smokeping from multiple external points.
   Rule out a network island (BGP flap, upstream ISP).
3. Notify: exec team, status page ("major outage, investigating"), key customers.

### Phase 2 — Failover Postgres (target: 60 min)

For each managed Postgres cluster:

1. On the BRN1 standby, verify replication position vs last known primary:
   ```
   SELECT pg_last_wal_replay_lsn(), pg_last_xact_replay_timestamp();
   ```
2. Fence the primary (impossible if PRG1 gone; skip, but note in log).
3. Promote:
   ```
   pg_ctl promote -D /var/lib/postgresql/15/main
   ```
4. Update the internal DNS record `pg-<tenant>-primary.pch` → BRN1 IP.
5. Reload connection poolers (PgBouncer) that pin the primary.

### Phase 3 — Bring up edge in BRN1 (target: 30 min)

1. Ansible: `deploy-edge` playbook targeting `edge-brn1-01`, `edge-brn1-02`.
2. Update Cloudflare edge → BRN1 anycast (`185.242.10.10`, `185.242.10.11`).
3. Verify: `curl -I https://<canary-customer>.example.cz` from external.

### Phase 4 — K8s workloads (target: 90 min)

1. If PCH-K8s BRN1 is healthy: Velero restore of the `prod-*` namespaces
   from the latest backup.
2. Otherwise: rebuild PCH-K8s BRN1 from Terraform + install workloads. This
   is the slow path and blows the RTO. See mitigation in
   [known_issues/pending-projects.md](../known_issues/pending-projects.md)
   ("BRN1 K8s hot standby").
3. Ingress: point BRN1 edge Nginx to the BRN1 K8s LB.

### Phase 5 — Communicate (continuous)

- Status page update every 15 min while impaired
- Customer email once all customer-facing services back
- Post-mortem started within 24h

## Do NOT

- Do not promote a Postgres standby without confirming the primary is
  actually unreachable. Split-brain in the DB tier caused the 2023-08-14
  incident.
- Do not update Cloudflare DNS without IC confirmation. We had two engineers
  trying to fail over simultaneously in 2022 and reverted each other's changes.

## After PRG1 comes back

**Do not** fail back automatically. Once PRG1 is healthy:

1. Reconfigure it as the standby (streaming FROM BRN1).
2. Wait 24h with clean replication.
3. Schedule a planned failback during a maintenance window
   ([runbooks/maintenance-window.md](maintenance-window.md)).

## See also

- [runbooks/postgres-failover.md](postgres-failover.md) — the isolated
  DB-only failover procedure, used in less catastrophic scenarios
- [runbooks/backup-procedures.md](backup-procedures.md)
- [docs/12-incident-response.md](../docs/12-incident-response.md)
