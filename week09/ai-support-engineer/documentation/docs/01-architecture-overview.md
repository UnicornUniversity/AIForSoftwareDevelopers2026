# Architecture Overview

**Author:** Tomáš H.
**Last updated:** 2024-06-14
**Status:** Current

## About Prague Cloud Hosting

Prague Cloud Hosting (PCH) operates managed VPS, managed Kubernetes ("PCH-K8s"),
and managed PostgreSQL offerings out of two data centers:

- **PRG1** — Prague, primary. TTC Teleport, Nagano building. 10 racks.
- **BRN1** — Brno, secondary. STRV data center. 4 racks, mostly cold standby
  and backup targets.

A third region (**VIE1**, Vienna) has been on the roadmap since 2023 but is
currently deferred (see [known_issues/pending-projects.md](../known_issues/pending-projects.md)).

## High-level topology

```
                     ┌─────────────────────────┐
   Public traffic ──▶│  Cloudflare (WAF + DDoS)│
                     └────────────┬────────────┘
                                  │
                     ┌────────────▼───────────┐
                     │  Edge Nginx (edge-01,  │  <- L7 reverse proxy
                     │  edge-02 in PRG1)      │     TLS termination
                     └────────────┬───────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
        ┌──────────┐        ┌──────────┐        ┌──────────┐
        │ K8s PRG1 │        │ VPS pool │        │ Managed  │
        │ (5 nodes)│        │ (KVM)    │        │ Postgres │
        └────┬─────┘        └──────────┘        └──────────┘
             │
             └─▶ etcd, Prometheus, Loki, internal registry
```

## Core components

| Component      | Version (as of 2024-06) | Notes                                   |
|----------------|--------------------------|-----------------------------------------|
| Ubuntu (host)  | 22.04 LTS               | Migrating remaining 20.04 hosts in Q3   |
| Docker Engine  | 24.0.7                  | Some legacy hosts still on 20.10 (!)    |
| Kubernetes     | 1.28                    | Upgrade to 1.29 planned Q4              |
| PostgreSQL     | 15.6                    | v14 still on customer-managed instances |
| Nginx          | 1.24 (stable)           | edge-01 rebuilt 2024-04                 |
| Prometheus     | 2.48                    | Loki 2.9 for logs                       |

## Network

- Public IPv4: `195.181.144.0/22` (PRG1), `185.242.10.0/24` (BRN1)
- Internal management VLAN: `10.20.0.0/16`
- Customer VLANs: `10.100.0.0/14` (per-tenant /24)
- BGP peering with NIX.CZ and AMS-IX Prague

## See also

- [docs/02-hosting-plans.md](02-hosting-plans.md) — customer-facing plan matrix
- [docs/06-postgres-administration.md](06-postgres-administration.md)
- [runbooks/disaster-recovery.md](../runbooks/disaster-recovery.md)
