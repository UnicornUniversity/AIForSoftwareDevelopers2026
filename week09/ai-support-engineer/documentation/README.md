# Prague Cloud Hosting — Internal Knowledge Base

Welcome to the PCH engineering knowledge base. This repository is the source
of truth for our on-call runbooks, deployment procedures, and post-mortems.

> Maintained since **March 2021**. Curated (loosely) by whoever was on-call
> when a page fired.

## Layout

| Folder            | Purpose                                                        |
|-------------------|----------------------------------------------------------------|
| `docs/`           | Long-form guides: architecture, deployments, tools             |
| `runbooks/`       | Step-by-step operational procedures                            |
| `faq/`            | Customer-facing FAQ (used by first-line support)               |
| `known_issues/`   | Open bugs, workarounds, and quirks per subsystem               |
| `logs/`           | Sanitized example logs used for training and pattern matching  |
| `configs/`        | Reference configuration files (redacted)                       |

## Contributing

1. Don't delete outdated docs. **Add a "SUPERSEDED BY" header** at the top and
   link the replacement. We got burned in 2022 when someone wiped the pre-Terraform
   deployment guide and we couldn't roll back the legacy hosts.
2. Every runbook must state its **last verified date** and the on-call who
   verified it.
3. If a doc contradicts another doc, that's a signal — file a `known_issues/`
   note pointing at both and let #ops-triage figure it out.

## Who owns what

- **Platform & Kubernetes** — Tomáš H. (until end of 2024, then Petra N.)
- **Databases (Postgres)** — Miroslav B.
- **Networking / Nginx / SSL** — Anežka K.
- **On-call rotation** — see `runbooks/on-call-rotation.md` (TODO: someone needs to write that)

## Quick links

- [Architecture overview](docs/01-architecture-overview.md)
- [Deployment guide (current)](docs/03-deployment-guide.md)
- [Docker troubleshooting](docs/05-docker-troubleshooting.md)
- [Disaster recovery](runbooks/disaster-recovery.md)
- [Customer FAQ index](faq/general.md)
