# Runbook: Monitoring Stack Operations

**Owner:** Petra N.
**Last verified:** 2025-01-20
**Frequency of use:** Weekly

Day-to-day tasks for the monitoring stack described in
[docs/10-monitoring-stack.md](../docs/10-monitoring-stack.md).

## Adding a new alert

1. Edit `configs/prometheus-rules.yml` in the `pch-infra` repo.
2. Test locally: `promtool check rules prometheus-rules.yml`.
3. PR, review, merge. ArgoCD syncs Prometheus config within 2 min.
4. Verify in Prometheus UI → Status → Rules that the new rule is loaded.
5. Fire it in dry-run using `amtool alert add ...` and confirm routing.

## Silencing an alert

- Via Alertmanager UI (`alertmanager.prg1.pchosting.internal`).
- Silences require a comment and an expiry. **Do not silence longer than
  4 hours without a follow-up ticket.**

## Adding a new dashboard

- Grafana → New dashboard. Save to the `PCH` folder.
- Export as JSON, commit to `pch-dashboards` repo.
- Grafana provisioning reloads dashboards from the repo every 5 min.

## Common issues

### "Prometheus is missing scrapes"

- Check `up{}` for the target. If 0, target is unreachable.
- Firewall / VPN? Node exporter default port is 9100 — must be reachable
  from the Prometheus pod.
- Target labels changed? Prometheus deduplicates by label set. If a rename
  drops the old target, expect a gap.

### "Grafana shows no data"

- Datasource healthy? Configuration → Data sources → test.
- Time range: you'd be surprised how often this is the answer.
- Loki-backed panels: log volume too high → query timeout. Narrow the range
  or add a label filter.

### Alertmanager sending duplicates

- Two Alertmanager replicas running with mismatched cluster peers. Verify
  with `amtool cluster show`.
- We had this in Feb 2024 after a partial upgrade. Post-mortem:
  [runbooks/incident-2024-02-11-alertmanager-split.md](incident-2024-02-11-alertmanager-split.md).

## Retention housekeeping

Once a quarter, review Loki storage — old debug labels sometimes explode
cardinality and blow through the storage budget.

## See also

- [docs/10-monitoring-stack.md](../docs/10-monitoring-stack.md)
- [configs/prometheus.yml](../configs/prometheus.yml)
- [configs/alertmanager.yml](../configs/alertmanager.yml)
