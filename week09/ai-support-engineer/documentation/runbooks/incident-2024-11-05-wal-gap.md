# Post-mortem: 2024-11-05 — WAL archive gap during monthly restore drill

**Severity:** 3 (no customer impact, but violates our RPO guarantee)
**Discovered during:** monthly restore drill on `pg-mediastar-02`
**Duration of gap:** 16 minutes (03:12 – 03:28 CET, 2024-11-05)
**Author:** Miroslav B.
**Reviewed:** 2024-11-11 at Ops weekly

## TL;DR

During the monthly restore drill we discovered a 16-minute gap in shipped
WAL segments for one customer's Postgres instance. The gap was caused by
transient auth failures against the BRN1 object storage bucket, combined
with `archive_command` giving up after the default retries.

**Impact:** if a real DR event had occurred during that window, we would
have lost up to 16 minutes of writes for that one customer instead of the
5-minute RPO we advertise.

## Timeline

- **2024-11-05, 03:12** — object-storage endpoint returned 403 Forbidden to
  the pgbackrest archive process on `pg-mediastar-02`. Cause: an S3
  policy rotation earlier that night dropped the archive service's IAM role
  from the bucket write policy.
- **2024-11-05, 03:14 → 03:28** — `archive_command` exit non-zero → Postgres
  retries with backoff, eventually gives up per default settings.
- **2024-11-05, 03:29** — a subsequent policy sync (unrelated) reattached the
  role. Archiving resumed automatically.
- **2024-11-05, 06:00** — no alert fired because our
  `PostgresWalArchiveFallingBehind` alert had a 30-minute `for` clause and
  the gap self-healed just before the threshold.
- **2024-11-05, 10:20** — drill on `pg-mediastar-02` fails at target
  timestamp. Miroslav investigates.

## Root cause

The archive endpoint IAM policy is edited by hand in the console (yes) and
was reordered in a way that dropped the archive role — this was a config
management gap, not a code bug.

## Contributing factors

- Alert `for: 30m` was too loose; the gap self-healed in 16 min.
- No monitoring on IAM policy drift.
- Manual object-storage policy edits are still normal practice, despite the
  Terraform migration project being open since Q3 2023.

## Corrective actions

- [x] Reduce `PostgresWalArchiveFallingBehind` `for` clause to 5 min
- [x] Add end-to-end drill on the *previous* month's data as a monthly cron
      (was previously ad-hoc)
- [ ] Migrate object-storage IAM policy management to Terraform (blocked on
      approval from InfoSec — tracked in
      [known_issues/pending-projects.md](../known_issues/pending-projects.md))
- [ ] Alert on any `archive_command` non-zero exit, not just accumulated gap

## Lessons

- Alerts with long `for` clauses hide transient failures that still matter
  for durability.
- A 16-minute gap is not a "false alarm" just because it self-healed. RPO
  is about the worst case, not the average.

## See also

- [runbooks/backup-procedures.md](backup-procedures.md)
- [docs/06-postgres-administration.md](../docs/06-postgres-administration.md)
- [known_issues/postgres-issues.md](../known_issues/postgres-issues.md)
