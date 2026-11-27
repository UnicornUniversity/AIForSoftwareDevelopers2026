# Known Issues — Legacy Postgres Backup (pg_dump nightly)

**Owner:** Miroslav B.
**Last updated:** 2023-11-02
**Status:** Deprecated — do not enable for new instances.

---

## Background

Before the pgBackRest rollout in 2022, PCH used a home-grown `pg_dump`-based
nightly backup: a cron job dumped each database to `/var/lib/postgresql/backups/`,
gzipped it, then rsync'd to BRN1.

This produced logical backups only. **No PITR, no WAL, best-case RPO 24h.**

## Where it still runs

- `pg-shared-01` (small multi-tenant instance, being retired)
- `pg-shared-02` (small multi-tenant instance, being retired)

Both are on the migration list to per-tenant managed instances with modern
pgBackRest-based backups.

## Warning to on-call

If you get paged for **"Backup script failed on pg-shared-*"**, that's this
legacy script. It fires from `/etc/cron.d/pg-legacy-backup` on the box.
Common failures:

- Out of disk on `/var/lib/postgresql/backups`
- rsync SSH key expired against BRN1 backup host
- One of the customer databases has a lock that prevents `pg_dump` from
  proceeding (long ANALYZE, or a customer taking a big lock at 03:00)

## Recovery from legacy backups

- Dumps are gzipped, format is `pg_dump -Fc` (custom).
- Restore with `pg_restore -d <db> <file>.dump.gz` (after `gunzip`).
- **RPO of a legacy restore is 24h.** Customers on `pg-shared-*` do not have
  a PITR guarantee. This is documented in their old contracts but not in
  the current SLA page — worth flagging if a customer complains.

## Retirement plan

Both instances are on the migration list — see
[known_issues/pending-projects.md](pending-projects.md) KI-PROJ-006.

Once migrated, `/etc/cron.d/pg-legacy-backup` should be deleted from those
hosts.

## See also

- [runbooks/backup-procedures.md](../runbooks/backup-procedures.md)
- [docs/06-postgres-administration.md](../docs/06-postgres-administration.md)
