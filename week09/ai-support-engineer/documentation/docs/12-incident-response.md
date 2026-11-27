# Incident Response Overview

**Author:** Petra N.
**Last updated:** 2024-09-08
**Status:** Current

How PCH runs an incident. Detailed runbooks live in `runbooks/`, and
post-mortems in `runbooks/incident-*.md`.

## Severities

| Sev | Impact                                              | Response          |
|-----|-----------------------------------------------------|-------------------|
| 1   | Customer-facing outage across a region              | Page immediately  |
| 2   | Customer-facing degradation, or partial region loss | Page during work hours; on-call within 15 min |
| 3   | Non-customer-visible degradation, redundancy loss   | Ticket, next day  |
| 4   | Cosmetic, docs, tracking                            | Backlog           |

## Roles during an incident

- **Incident Commander (IC)** — decides. Usually on-call. Never the person
  hands-on with the fix.
- **Comms** — updates status page and #status-updates on Slack every 15 min.
- **Scribe** — timeline in the incident doc.
- **Fixers** — do the work.

For sev-1 the IC MUST NOT also be a fixer. This is a rule from the 2023-08-14
incident — see [runbooks/incident-2023-08-14.md](../runbooks/incident-2023-08-14.md).

## Communication

- Internal: `#incident-active` Slack channel (spun up per-incident since 2024)
- External: status.pchosting.cz — updated by Comms role, not automated
- Customer email: only for sev-1 with > 30 min duration

## Post-mortem

- Blameless. Focus on process, not people.
- Draft within 3 business days.
- Reviewed at the next Ops weekly.
- Stored in `runbooks/incident-YYYY-MM-DD-<short-slug>.md`.

## See also

- [runbooks/disaster-recovery.md](../runbooks/disaster-recovery.md)
- [runbooks/postgres-failover.md](../runbooks/postgres-failover.md)
- Individual post-mortems in `runbooks/`
