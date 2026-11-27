# Storage

**Author:** Tomáš H.
**Last updated:** 2023-09-04
**Status:** Mostly current (Ceph section slightly stale — see note)

Overview of the storage stack across PCH.

## VPS block storage

Local NVMe on the hypervisor, replicated to a partner host in the same rack
via DRBD (async). Snapshots via LVM every 24h, retained 7 days.

- **IOPS ceiling** per VPS: 6000 read / 3000 write (best effort)
- **Latency target:** p99 < 5ms

## K8s persistent volumes

Two storage classes:

- `pch-rbd` (default) — Ceph RBD, replicated 3×, cross-rack. Suitable for
  databases, stateful workloads.
- `pch-rbd-fast` — Ceph RBD backed by NVMe pool. 2× replication only. **Do not
  use for irreplaceable data** — one of the nodes runs consumer-grade drives
  (yes, still, as of 2023). Fine for caches, indexes that can be rebuilt.

> ℹ️ **2024 update note (added by Petra N., 2024-05):** the consumer-grade
> drives in the `-fast` pool were finally replaced during the Q1 2024
> hardware refresh. `pch-rbd-fast` is now safe for durable data, but we
> haven't updated the pricing page yet.

## Managed Postgres storage

Dedicated NVMe on the DB VM; WAL shipped to object storage in BRN1.

Storage growth is monitored, and a soft alert fires at 75% used —
see [runbooks/monitoring.md](../runbooks/monitoring.md).

## Object storage ("PCH Object")

S3-compatible, backed by MinIO in a 4-node erasure-coded cluster in PRG1
with async replication to BRN1.

- Endpoint: `s3.prg1.pchosting.cz`
- Signature version: v4
- Path-style addressing (virtual-hosted style not fully supported)

**Known gotcha:** presigned URLs longer than 7 days silently fail — that's a
MinIO-imposed limit. Document says "up to 7 days" but customer-facing FAQ
still incorrectly says "up to 30 days". See
[known_issues/object-storage.md](../known_issues/object-storage.md).

## Backup destinations

- Local: `/var/lib/backups` on each host (short-term)
- Regional: object storage bucket `pch-backups` in BRN1
- Off-region: monthly full snapshot to a Hetzner Storage Box in Falkenstein

See [runbooks/backup-procedures.md](../runbooks/backup-procedures.md).

## See also

- [docs/06-postgres-administration.md](06-postgres-administration.md)
- [runbooks/backup-procedures.md](../runbooks/backup-procedures.md)
