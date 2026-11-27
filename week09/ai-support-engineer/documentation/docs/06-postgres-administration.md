# PostgreSQL Administration

**Author:** Miroslav B.
**Last updated:** 2024-12-11
**Status:** Current

Managed Postgres runs on dedicated VMs (`pg-<tenant>-<n>`) with streaming
replication to a warm standby in BRN1. This doc covers day-to-day admin.

## Versions

| Version | Status                                     |
|---------|--------------------------------------------|
| 15.6    | Default for new instances                  |
| 14.x    | Existing customer instances, LTS-ish       |
| 13.x    | **End-of-life** (upstream EOL Nov 2025) — must be migrated by Q3 2025 |
| 12.x    | EOL. Two customer instances still exist as of 2025-02 — see [known_issues/postgres-eol.md](../known_issues/postgres-eol.md) |

## Standard file locations

```
/etc/postgresql/15/main/postgresql.conf   # main config
/etc/postgresql/15/main/pg_hba.conf       # auth
/var/lib/postgresql/15/main               # PGDATA
/var/log/postgresql/                      # logs (also to syslog)
/var/lib/postgresql/backups               # local base backups (before WAL ship)
```

Reference configs: [configs/postgresql.conf](../configs/postgresql.conf) and
[configs/pg_hba.conf](../configs/pg_hba.conf).

## Common operations

### Connect

```
sudo -u postgres psql
psql -h pg-acme-01.prg1 -U app_user -d acme
```

### List slow queries (from `pg_stat_statements`)

```sql
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

### Check replication

```sql
SELECT client_addr, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
FROM pg_stat_replication;
```

Lag > 50 MB sustained → page on-call. See
[runbooks/postgres-failover.md](../runbooks/postgres-failover.md).

### Bloat

`pg_stat_user_tables.n_dead_tup` growing without `autovacuum` catching up.
Usually a runaway long transaction. Find it:

```sql
SELECT pid, age(clock_timestamp(), query_start), state, query
FROM pg_stat_activity
WHERE state <> 'idle'
ORDER BY query_start ASC
LIMIT 10;
```

## Backups

- Base backup: nightly via `pg_basebackup` to BRN1 object storage.
- WAL: continuous shipping via `pgbackrest` (14-day retention on Pro plan).
- PITR: possible to any point within retention window.

See [runbooks/backup-procedures.md](../runbooks/backup-procedures.md) for the
authoritative procedure. The old `pg_dump`-based nightly is deprecated but
still runs on a couple of shared-tenant instances —
[known_issues/postgres-backup-legacy.md](../known_issues/postgres-backup-legacy.md).

## Autovacuum tuning

Default `autovacuum` is too conservative for our write-heavy Pro workloads.
Overrides applied on all Pro+ instances:

```
autovacuum_vacuum_scale_factor = 0.05
autovacuum_analyze_scale_factor = 0.02
autovacuum_naptime = 30s
autovacuum_max_workers = 6
```

## Connections

- `max_connections` = 100 (Starter), 200 (Pro), 500 (Business).
- PgBouncer sidecar deployed on Business plan by default; optional on Pro
  (customer-requested).

## See also

- [runbooks/postgres-failover.md](../runbooks/postgres-failover.md)
- [runbooks/backup-procedures.md](../runbooks/backup-procedures.md)
- [known_issues/postgres-issues.md](../known_issues/postgres-issues.md)
- [logs/postgresql.log](../logs/postgresql.log)
