# Hosting Plans

**Author:** Sales Engineering (Jana Š.)
**Last updated:** 2025-01-10
**Status:** Current

This document is intended for customer-facing support. Prices are in CZK
(monthly, VAT excluded). See internal margin sheet in Confluence for GP.

## VPS ("Cloud Server") plans

| Plan       | vCPU | RAM   | SSD    | Traffic   | Price (CZK/mo) |
|------------|------|-------|--------|-----------|----------------|
| Micro      | 1    | 2 GB  | 40 GB  | 2 TB      | 249            |
| Small      | 2    | 4 GB  | 80 GB  | 4 TB      | 499            |
| Medium     | 4    | 8 GB  | 160 GB | 8 TB      | 999            |
| Large      | 8    | 16 GB | 320 GB | 12 TB     | 1899           |
| XL         | 16   | 32 GB | 640 GB | 20 TB     | 3599           |

All plans:
- Ubuntu 22.04, Debian 12, Rocky 9, or bring-your-own ISO
- IPv4 + IPv6 (/64)
- Full root access
- Free daily snapshot retained 7 days (see [runbooks/backup-procedures.md](../runbooks/backup-procedures.md))

## Managed Postgres

| Plan       | vCPU | RAM   | Storage | Connections | Price (CZK/mo) |
|------------|------|-------|---------|-------------|----------------|
| PG-Starter | 2    | 4 GB  | 50 GB   | 50          | 899            |
| PG-Pro     | 4    | 16 GB | 200 GB  | 200         | 2499           |
| PG-Business| 8    | 32 GB | 500 GB  | 500         | 4999           |

Managed Postgres includes PITR (point-in-time recovery) with 14-day WAL retention.

## Managed Kubernetes ("PCH-K8s")

Priced per node. Control plane is free for clusters ≤ 3 worker nodes,
otherwise **199 CZK/mo per cluster**.

- Worker node: same pricing as VPS plans above
- Ingress: shared Cloudflare-fronted or dedicated LB (+499 CZK/mo)
- Persistent volumes: Ceph-backed RBD (see [docs/08-storage.md](08-storage.md))

## What is NOT included

- SSL certificates for custom domains are self-service via Let's Encrypt
  (see [docs/09-ssl-certificates.md](09-ssl-certificates.md)).
  We used to include a free wildcard cert until 2022 but discontinued it —
  see [docs/09b-ssl-legacy.md](09b-ssl-legacy.md) if a customer complains.
- Email hosting (retired 2022).
- Windows Server (retired 2023 — see FAQ).

## Legacy plans (grandfathered)

Some customers are still on the pre-2023 plan names ("Basic", "Business",
"Enterprise"). Do not offer these to new customers. Migration guide:
[docs/14-legacy-plan-migration.md](14-legacy-plan-migration.md).
