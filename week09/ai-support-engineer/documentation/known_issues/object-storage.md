# Known Issues — Object Storage (PCH Object / MinIO)

**Owner:** Tomáš H., now Petra N.
**Last updated:** 2024-11-04

---

## KI-OBJ-001 — Presigned URLs limited to 7 days despite public docs saying 30

**Discovered:** 2023-06 (customer report)
**Status:** Docs mismatch, fix pending
**Severity:** Medium (customer-visible papercut)

MinIO caps presigned URL validity at 7 days (`MaxExpiry` in the SDK). The
customer-facing FAQ on our website still says "up to 30 days".

**Workaround:** For long-lived shareable links, generate a new presigned
URL from a cron. Don't attempt > 7 day expiry — the API accepts it but the
URL will 403 after day 7.

**Fix:** Documentation update. Nobody has done it because the wording is on
the marketing site which requires two approvals. Ticket OPS-2611.

---

## KI-OBJ-002 — Path-style vs. virtual-hosted-style addressing

**Discovered:** 2022 (ongoing)
**Status:** Path-style only
**Severity:** Recurring support tickets

Some customer tools (esp. older AWS SDK versions and Terraform's `s3`
backend when using bucket-as-subdomain) assume virtual-hosted-style
addressing (`https://<bucket>.s3.prg1.pchosting.cz`).

**We only support path-style** (`https://s3.prg1.pchosting.cz/<bucket>/<key>`).

Configure customer tools accordingly:
- boto3: `s3 = boto3.client('s3', endpoint_url='...', config=Config(s3={'addressing_style': 'path'}))`
- Terraform: `force_path_style = true`
- AWS CLI: `--endpoint-url=https://s3.prg1.pchosting.cz`

---

## KI-OBJ-003 — Async replication PRG1 → BRN1 occasionally falls behind under load

**Discovered:** 2024-08
**Status:** Monitored; tuning ongoing
**Severity:** Medium (DR-relevant)

During peak upload periods, replication to BRN1 has been observed to fall
30+ minutes behind. Given our 5-minute RPO promise, this is an
issue for the DR posture.

**Mitigation:** we alert at 10 min lag. During the last event (2024-08-22)
we throttled the offending customer's uploads to let replication catch up.
Better solution: add BRN1 capacity. On the roadmap
([known_issues/pending-projects.md](pending-projects.md)).

---

## KI-OBJ-004 — Cross-region replication doesn't cover versioning history

**Discovered:** 2024-03
**Status:** Documented
**Severity:** Low (subtle, rare)

Only current object versions replicate to BRN1. If a customer relies on
S3-style versioning for compliance, older versions exist only in PRG1.
DR to BRN1 would lose them.

**Recommendation:** don't rely on our object storage for compliance-grade
versioning history.

---

## See also

- [docs/08-storage.md](../docs/08-storage.md)
- [runbooks/disaster-recovery.md](../runbooks/disaster-recovery.md)
