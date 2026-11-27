# Known Issues — Pending Projects & Tech Debt

**Owner:** Petra N. (as of 2025)
**Last updated:** 2025-02-20

Everything below is on the internal roadmap but has not been done. This list
exists so that support and on-call know the state of the world when a
customer asks "when will you ..."

---

## KI-PROJ-001 — VIE1 Vienna region

**Since:** 2023 Q2
**State:** Deferred indefinitely
**Blocker:** Peering costs + regulatory review not complete

We do NOT have a public commitment on a Vienna region date. If a customer
asks about a Vienna region, say "we are considering it but do not have a
public timeline".

---

## KI-PROJ-002 — BRN1 K8s hot standby

**Since:** 2023 Q4
**State:** Planned for 2025
**Blocker:** Hardware budget + Ceph capacity in BRN1

Currently the K8s DR plan requires rebuilding PCH-K8s in BRN1 from
Terraform. This blows our 4h RTO. A permanent warm-standby K8s cluster in
BRN1 would fix this. Priority raised after the 2024-11-05 restore drill
findings.

---

## KI-PROJ-003 — Terraform-managed object-storage IAM policies

**Since:** 2023 Q3
**State:** In review with InfoSec (stalled)
**Blocker:** InfoSec has not signed off on the plan submitted in 2024-06

Directly caused KI-PG-003 / the 2024-11-05 WAL gap. Manual IAM edits are
still normal. Ticket OPS-2178.

---

## KI-PROJ-004 — Retire Docker 20.10 hosts

**Since:** 2022 Q1 (recurrent)
**State:** Legacy-app-02 done in 2024; legacy-app-01 still on 20.10
**Blocker:** billing-api still runs there; migration during maintenance
             window requires customer notification and hasn't been
             scheduled.

See [docs/03b-deployment-guide-legacy.md](../docs/03b-deployment-guide-legacy.md)
and [known_issues/docker-issues.md](docker-issues.md).

---

## KI-PROJ-005 — Off-region backup automation

**Since:** 2022 Q3
**State:** Manual monthly copy, not automated
**Blocker:** Hetzner API + scheduling ownership

Off-region cold backups go to a Hetzner Storage Box in Falkenstein.
Currently the copy is a script run by hand on the first of each month.
We've been meaning to automate this since 2022. See
[runbooks/backup-procedures.md](../runbooks/backup-procedures.md).

---

## KI-PROJ-006 — Migration of remaining PG 12 customer instances

**Since:** 2024 Q3
**State:** Scheduled for 2025 Q2 (has slipped twice)
**Blocker:** Customer coordination — one customer's app is unmaintained
             and any incompatibility surfaces late.

See [known_issues/postgres-issues.md](postgres-issues.md) KI-PG-005.

---

## KI-PROJ-007 — Sunset the free-wildcard SSL grandfathered program

**Since:** 2022 Q3 (program end)
**State:** ~11 accounts still on it, ongoing case-by-case
**Blocker:** Sales team hasn't sent the final "your program is ending"
             email. Kept getting deprioritized.

See [docs/09b-ssl-legacy.md](../docs/09b-ssl-legacy.md).

---

## KI-PROJ-008 — On-call rotation runbook

**Since:** 2024 Q4
**State:** Referenced in `README.md` but not written

There is no `runbooks/on-call-rotation.md`. Yes, the README links to it.
No, it doesn't exist. If you're on-call and want to know what to do, ask
your team lead or read [docs/12-incident-response.md](../docs/12-incident-response.md)
instead.

---

## See also

- All incident post-mortems in `runbooks/`
- [README.md](../README.md)
