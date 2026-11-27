# Runbook: Backup Procedures

**Owner:** Miroslav B. (Postgres), Tomáš H. (everything else)
**Last verified:** 2025-02-04 by Miroslav B.
**Frequency of use:** Continuous (automation) + monthly restore drills

Authoritative reference for what gets backed up, where, and how to restore.

## Scope

- Managed PostgreSQL instances (base backups + WAL)
- VPS block storage (LVM snapshots)
- Customer-visible K8s persistent volumes (Velero + Ceph snapshots)
- Configuration state (git-backed, snapshotted daily)

## Retention

| Data class          | Local (hot) | BRN1 (warm) | Off-region (cold) |
|---------------------|-------------|-------------|-------------------|
| Postgres base + WAL | 3 days      | 14 days     | 90 days           |
| VPS snapshots       | 7 days      | 30 days     | —                 |
| K8s PVs             | 3 days      | 14 days     | —                 |
| Config repos        | git         | mirror      | quarterly to Hetzner |

Off-region cold storage is a manual monthly copy to a Hetzner Storage Box in
Falkenstein. **Yes, this needs to be automated** — tracked in
[known_issues/pending-projects.md](../known_issues/pending-projects.md).

## Automation

- Postgres: `pgbackrest` timers on each DB VM (see
  [configs/pgbackrest.conf](../configs/pgbackrest.conf))
- VPS snapshots: `pch-lvm-snap.sh` in cron on each hypervisor
- K8s: Velero daily schedule
- Verification: monthly restore drill (see below). **This is not optional.**

Complete schedule: [configs/backup-schedule.yml](../configs/backup-schedule.yml)

## Restore drill (monthly)

Run on the first Tuesday of each month.

1. Pick a random Pro-tier customer DB (`select 1 from anonymized_pool`).
2. Restore latest base backup + WAL to a scratch instance in BRN1.
3. Verify `SELECT count(*)` matches the current primary within a small delta.
4. Log the drill in the `restore-drills.md` runbook (not yet split out from
   this doc — TODO).

Last three drills:

- 2025-01-06: OK (pg-acme-01 → scratch-drill-01, 42 min end-to-end)
- 2024-12-03: OK (pg-mediastar-02 → scratch-drill-01, 55 min)
- 2024-11-05: FAILED — WAL archive gap between 03:12 and 03:28. Root cause:
  archive_command intermittently failed to auth against the object store.
  See [runbooks/incident-2024-11-05-wal-gap.md](incident-2024-11-05-wal-gap.md).

## Manual restore procedures

### Postgres PITR to specific timestamp

On a new host with pgbackrest installed and the stanza configured:

```
pgbackrest --stanza=<stanza> --type=time \
   --target="2025-02-01 14:00:00 CET" restore
```

Then start Postgres in recovery mode. Verify with:

```sql
SELECT pg_is_in_recovery();      -- t during replay
SELECT pg_last_xact_replay_timestamp();
```

### VPS snapshot restore

Snapshots are LVM. To restore into a new logical volume:

```
lvcreate -s -n <newname> -L 20G /dev/vg0/<snapshot>
```

Attach to a new VPS or replace the existing LV (with the customer notified
and the VPS shut down).

## Gotchas

- `pg_dump`-based nightly is **deprecated** but still runs on 2 shared-tenant
  clusters. See [known_issues/postgres-backup-legacy.md](../known_issues/postgres-backup-legacy.md).
- **Wal-e was retired in 2022.** Some scripts on old hosts still reference
  `wal-e` — those hosts have been migrated to `pgbackrest` and the wal-e
  cron entries are dead weight, safe to delete.

## See also

- [runbooks/disaster-recovery.md](disaster-recovery.md)
- [docs/06-postgres-administration.md](../docs/06-postgres-administration.md)
- [configs/backup-schedule.yml](../configs/backup-schedule.yml)
