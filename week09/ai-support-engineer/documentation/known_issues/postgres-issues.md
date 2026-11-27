# Known Issues — PostgreSQL

**Owner:** Miroslav B.
**Last updated:** 2025-02-14

---

## KI-PG-001 — Connection storms from serverless customers exhausting `max_connections`

**Discovered:** 2023-11
**Status:** Recommend PgBouncer; not enforced
**Severity:** Medium

Customers deploying serverless / edge functions (Vercel, Cloudflare Workers)
open a fresh Postgres connection per request. On PG-Pro (200 connections),
even modest traffic saturates.

**Recommendation:** Business plan (PgBouncer sidecar included) or self-host
PgBouncer in front of the DB. If self-hosting, use transaction pooling mode
and confirm your ORM/session-based features still work.

---

## KI-PG-002 — Slow query on `pg_stat_activity` when many idle transactions

**Discovered:** 2024-04
**Status:** Upstream; will improve in PG 17
**Severity:** Low

On instances with hundreds of idle-in-transaction connections,
`SELECT * FROM pg_stat_activity` can take 1–2 seconds. This shows up as
health-check flapping on some external monitoring tools.

**Workaround:** Filter server-side, e.g.
`SELECT * FROM pg_stat_activity WHERE state != 'idle in transaction'`.

---

## KI-PG-003 — PITR window shows RPO of 16 min on `pg-mediastar-02` for 2024-11-05

**Discovered:** 2024-11-05 during restore drill
**Status:** Fixed going forward; historical gap unrecoverable
**Severity:** High (RPO violation)

A 16-minute WAL archive gap exists on this specific instance for this
specific timestamp. Cause: IAM policy rotation. Full post-mortem:
[runbooks/incident-2024-11-05-wal-gap.md](../runbooks/incident-2024-11-05-wal-gap.md).

**Impact today:** if a customer requests PITR into that window, we must
serve the nearest available WAL segment, which may be up to 16 minutes off.

---

## KI-PG-004 — `pg_dump` from a standby occasionally fails with lock timeout

**Discovered:** 2023-08
**Status:** Workaround
**Severity:** Low

`pg_dump` against a standby can conflict with WAL replay and time out.

**Workaround:** either dump from the primary (higher load but reliable), or
set `hot_standby_feedback = on` on the standby (already default on our
managed instances since 2024-Q1).

---

## KI-PG-005 — Two customer instances still on PG 12 as of 2025-02

**Discovered:** ongoing awareness
**Status:** Open — migration required
**Severity:** Medium

PostgreSQL 12 reached upstream EOL in November 2024. Two customer instances
(`pg-legacy-a`, `pg-legacy-b` — internal names) remain on 12. Migration to
15 is scheduled for Q2 2025 but has slipped twice.

**Impact:** No security patches. We've mitigated with network isolation and
temporary WAF rules, but this is not a durable solution.

**See also:** [docs/06-postgres-administration.md](../docs/06-postgres-administration.md),
[known_issues/pending-projects.md](pending-projects.md).

---

## KI-PG-006 — `search_path` change in PG 15 breaks some customer apps

**Discovered:** 2023-05 (during 14 → 15 migrations)
**Status:** Documented
**Severity:** Low, but recurring

PG 15 tightened default `search_path` and removed public schema write
privileges for non-owners. Customers whose apps assumed the pre-15 laxity
see "permission denied for schema public" errors.

**Fix:** grant explicitly:

```sql
GRANT CREATE ON SCHEMA public TO <role>;
```

Or (better) create a dedicated schema for the app.

---

## See also

- [docs/06-postgres-administration.md](../docs/06-postgres-administration.md)
- [faq/database.md](../faq/database.md)
- [runbooks/postgres-failover.md](../runbooks/postgres-failover.md)
