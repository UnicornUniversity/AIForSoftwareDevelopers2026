# FAQ — Databases

**Audience:** Customers using Managed PostgreSQL.
**Owner:** Miroslav B.
**Last updated:** 2025-01-30

---

### Which PostgreSQL versions do you support?

- **PostgreSQL 15** — default for new instances (as of Feb 2025, 15.6)
- **PostgreSQL 14** — supported for existing instances
- **PostgreSQL 13** — end-of-life reaches November 2025; you must migrate before then
- **PostgreSQL 12** — EOL upstream. We can't offer new 12 instances. A few
  legacy 12 instances still exist and are on a migration plan.

We don't support versions older than 12.

### How do I connect to my database?

Connection string is in the portal. It looks like:

```
postgres://<user>:<password>@pg-<yourtenant>-primary.pchosting.cz:5432/<dbname>?sslmode=require
```

SSL is required — plain-text connections are rejected.

### What's the default connection limit?

- **PG-Starter:** 50 connections
- **PG-Pro:** 200 connections
- **PG-Business:** 500 connections (also gets a PgBouncer sidecar by default)

If you're bumping into the limit, we recommend PgBouncer in transaction
pooling mode. Some ORMs (e.g. long-transaction ones like older Rails
default behavior) don't play nicely with transaction pooling — read the
PgBouncer docs.

### Can I do point-in-time recovery?

Yes — on Pro and Business plans. Retention is 14 days by default.

To trigger PITR, open a support ticket with:
- Target timestamp (with timezone!)
- Whether to restore over the existing instance or into a new one

Turnaround: usually within 1 hour during business hours, 3 hours off-hours.

### How do I take my own backup?

You can `pg_dump` at any time from anywhere with network access:

```
pg_dump --format=custom -h pg-<tenant>-primary.pchosting.cz \
        -U <user> -d <db> -f mybackup.dump
```

We also automatically manage base backups + WAL — see
[runbooks/backup-procedures.md](../runbooks/backup-procedures.md).

### My queries are slow

Enable `pg_stat_statements` (already enabled on all managed instances) and
query it:

```sql
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

If a specific query is slow, `EXPLAIN (ANALYZE, BUFFERS)` it. If you can't
find the culprit yourself, open a ticket — we do query-tuning consulting
for Pro and Business customers.

### Can I get superuser access?

No. Managed instances run their own superuser (`postgres`). You get a
`<tenant>_admin` role with broad privileges but not `SUPERUSER` — this is
non-negotiable for security.

If you need extension `X` installed and it requires superuser to install,
open a ticket. We install extensions on request from a curated allowlist.

### What extensions are available?

Common ones enabled by default:
- `pg_stat_statements`
- `pgcrypto`
- `uuid-ossp`
- `citext`
- `postgis` (on request)
- `pgvector` (on request; PG 14+)
- `pg_trgm`

Full list: ask support or check `pg_available_extensions` on your instance.

### Related FAQ

- [Technical FAQ](technical.md)
- [Postgres admin docs](../docs/06-postgres-administration.md)
- [Postgres known issues](../known_issues/postgres-issues.md)
