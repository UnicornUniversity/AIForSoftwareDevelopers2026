# Runbook: PostgreSQL Failover (single-cluster)

**Owner:** Miroslav B.
**Last verified:** 2025-01-14 on `pg-devlab-01` (non-prod)
**Trigger:** Primary DB unresponsive or degraded, standby healthy

This runbook is for a **planned or forced failover of a single Postgres cluster**,
not the region-level DR (see [disaster-recovery.md](disaster-recovery.md)).

## Pre-flight

Confirm the standby is caught up:

```sql
-- on standby
SELECT pg_is_in_recovery();     -- t
SELECT pg_last_wal_replay_lsn();
SELECT pg_last_xact_replay_timestamp();
```

Compare replay LSN to the primary's current WAL LSN. Lag > 5 MB → hold off
unless the primary is actually dead.

## Procedure

### Planned failover

1. Announce in `#db-ops` and on the customer's status page (if any).
2. On the primary:
   - `SELECT pg_switch_wal();` (force one final WAL flush)
   - Pause application writes if you can (throttle in PgBouncer)
   - `pg_ctl -D /var/lib/postgresql/15/main -m fast stop`
3. Wait for standby to fully replay:
   ```sql
   SELECT pg_last_wal_replay_lsn();
   ```
4. Promote standby:
   ```
   pg_ctl promote -D /var/lib/postgresql/15/main
   ```
5. Update internal DNS record `pg-<tenant>-primary.pch` (TTL 30s) to standby IP.
6. Reload PgBouncer.
7. Verify writes work; confirm no long transactions from before the switch
   still open.

### Forced failover (primary is dead)

1. **Fence the primary.** If VM still exists, `virsh destroy` it. If it's
   truly gone (host failure), verify it's not just isolated — you do not want
   a zombie primary later.
2. Steps 4–7 from the planned procedure.
3. Log data loss window in the incident doc if the standby was lagging.

## Reconfiguring the old primary as the new standby

Once the old primary comes back:

```
pg_basebackup -h <new-primary> -U replicator -D /var/lib/postgresql/15/main \
   -Fp -Xs -R -P
```

Start Postgres. It should attach as a streaming replica. Verify:

```sql
-- on new primary
SELECT * FROM pg_stat_replication;
```

## Common failure modes

- **Replication slot on new primary not created for the old primary.**
  You'll get WAL retention issues within hours. Create it:
  ```sql
  SELECT pg_create_physical_replication_slot('standby_old_primary');
  ```
- **`recovery.conf` legacy references.** In PG 12+, recovery settings moved
  into `postgresql.auto.conf`. Old docs sometimes still say to edit
  `recovery.conf`; ignore.
- **PgBouncer connections stuck to the old primary.** `RELOAD` PgBouncer,
  or in extremis `KILL <pid>` the pool workers.

## See also

- [runbooks/disaster-recovery.md](disaster-recovery.md)
- [docs/06-postgres-administration.md](../docs/06-postgres-administration.md)
- [known_issues/postgres-issues.md](../known_issues/postgres-issues.md)
