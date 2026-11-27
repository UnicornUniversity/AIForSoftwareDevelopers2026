# Monitoring Stack

**Author:** Tomáš H., updated by Petra N.
**Last updated:** 2025-01-22
**Status:** Current

## Components

| Tool           | Role                             | Version |
|----------------|----------------------------------|---------|
| Prometheus     | Metrics scraping and storage     | 2.48    |
| Alertmanager   | Alert routing (Slack, PagerDuty) | 0.27    |
| Grafana        | Dashboards                       | 10.3    |
| Loki           | Log aggregation                  | 2.9     |
| Promtail       | Log shipper                      | 2.9     |
| Blackbox exp.  | External probes (HTTP, TCP, ICMP)| 0.24    |
| Node exporter  | Host metrics                     | 1.7     |
| cAdvisor       | Container metrics                | 0.47    |

Deployment: Helm chart `kube-prometheus-stack` in the `monitoring` namespace
on PCH-K8s PRG1. Grafana URL (internal): `https://grafana.prg1.pchosting.internal`.

## Metrics retention

- Local Prometheus: **15 days**
- Long-term (via Thanos to object storage): **13 months**

## Standard dashboards

- **PCH / Overview** — top-line SLOs across all services
- **PCH / Nginx** — edge request rate, 4xx/5xx, TLS handshake latency
- **PCH / Postgres** — TPS, replication lag, cache hit ratio, WAL rate
- **PCH / Docker Host** — per-host container count, disk, CPU pressure
- **PCH / Blackbox** — external HTTPS probe status per customer endpoint

## Alerts (severity 1 examples)

| Alert                             | Rule                                       |
|-----------------------------------|--------------------------------------------|
| EdgeNginxDown                     | `up{job="nginx-edge"} == 0 for 2m`         |
| PostgresReplicationLagHigh        | `pg_replication_lag_bytes > 5e7 for 5m`    |
| DiskFillPredicted6h               | predicted full within 6h via `predict_linear` |
| CertExpiryImminent                | `<21d until expiry` |
| KubeletDown                       | `up{job="kubelet"} == 0 for 5m`            |

Full rule set: [configs/prometheus-rules.yml](../configs/prometheus-rules.yml).

## Logging

Promtail on every host ships to Loki. Filters at the promtail level drop
health-check noise (see [configs/promtail-config.yml](../configs/promtail-config.yml)).

Retention: 30 days on hot storage; older logs archived to `pch-logs` bucket
for 1 year.

## Access

- Grafana: SSO via internal Keycloak. Roles: `viewer`, `editor`, `admin`.
- Prometheus/Alertmanager UIs: behind VPN, no public access.

## See also

- [runbooks/monitoring.md](../runbooks/monitoring.md)
- [configs/prometheus.yml](../configs/prometheus.yml)
- [configs/grafana-datasources.yaml](../configs/grafana-datasources.yaml)
