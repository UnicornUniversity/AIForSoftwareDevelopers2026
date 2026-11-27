# Runbook: Maintenance Windows

**Owner:** Tomáš H., then Petra N. (from 2025)
**Last verified:** 2025-01-08
**Cadence:** Second Sunday of every month, 02:00–04:00 CET

Rules of the road for planned maintenance.

## Communication

- **T-14 days:** Draft change ticket in Jira project `OPS`.
- **T-7 days:** Customer notification via email + status page banner
  (Comms handles the customer email).
- **T-24h:** Reminder banner on the customer portal.
- **T-1h:** Slack `#status-updates` heads-up.

## During the window

1. Announce start in `#ops-active`.
2. Pin an "IC-in-window" role — this person makes go/no-go calls.
3. Execute changes from the ticket, in order.
4. Verify after each step.
5. Roll back at the first sign of customer-visible regression.
6. Announce end. Update the ticket with outcomes.

## Post-window

- **Within 24h:** Summary email to customers if anything ran long or misfired.
- **Within 3 business days:** Post-mortem for any incident during the window
  (yes, an incident inside a maintenance window is still an incident).

## Do NOT

- Do not extend the window beyond 04:00 CET without exec approval. We've
  learned the hard way that fatigued eng teams cause secondary incidents.
- Do not merge unrelated changes into a maintenance window to "save a window".
- Do not skip customer notifications, even for "invisible" changes — the
  status page is our covenant with customers.

## Historical exceptions

- **2024-05-12 emergency window (Postgres 15.3 → 15.4 CVE):** ~48h notice
  instead of 7 days, due to CVE-2024-10979 exposure. Approved by CTO,
  documented in change ticket OPS-2431.

## See also

- [runbooks/monitoring.md](monitoring.md)
- [docs/12-incident-response.md](../docs/12-incident-response.md)
