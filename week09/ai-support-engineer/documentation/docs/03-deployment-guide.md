# Deployment Guide (Current)

**Author:** Petra N.
**Last updated:** 2025-03-02
**Supersedes:** [docs/03b-deployment-guide-legacy.md](03b-deployment-guide-legacy.md)
**Status:** Current

This guide describes the **current** deployment process for internal services
running on PCH-K8s. Customer-facing deployments (customer's own apps) follow a
similar pattern but are documented in the customer portal.

## Prerequisites

- `kubectl` v1.28+, `helm` v3.14+
- Access to the internal registry: `registry.prg1.pchosting.internal`
- VPN connected (Wireguard config from IT)
- Membership in the `platform-deploy` group

## Flow

1. **Build** — GitHub Actions runs on push to `main`. Image is built and
   pushed to `registry.prg1.pchosting.internal/<service>:<git-sha>`.
2. **Promote** — Merge to `release/*` branch triggers promotion to staging.
   Staging namespace: `stg-<service>`.
3. **Deploy** — After smoke tests, ArgoCD auto-syncs the production namespace
   `prod-<service>`. Manual sync required for control-plane services.
4. **Verify** — Check Grafana dashboard `PCH / Service Overview` for the
   service. SLO regressions page the on-call within 5 minutes.

## Deploying a hotfix

1. Cut a branch from `main`: `hotfix/<short-desc>`.
2. Push → GHA builds a tagged image.
3. In ArgoCD, override the image tag on the prod app (do NOT edit git yet).
4. Once verified, cherry-pick the fix back to `main` and delete the override.

**Never** `kubectl edit deployment` in prod. We had a nasty rollback issue in
Aug 2023 when someone did that and ArgoCD reverted the fix mid-incident.
See [runbooks/incident-2023-08-14.md](../runbooks/incident-2023-08-14.md).

## Environment variables and secrets

- Non-secret config: `ConfigMap` synced from the `pch-config` git repo.
- Secrets: **Sealed Secrets** (Bitnami controller). Never commit plaintext.
- Database credentials: rotated monthly by the `db-rotator` CronJob.

## Rollback

ArgoCD keeps the last 10 sync states. Roll back via UI or:

```
argocd app rollback <app-name> <revision>
```

If ArgoCD itself is down, fall back to:

```
kubectl rollout undo deployment/<name> -n prod-<service>
```

## See also

- [docs/04-nginx-configuration.md](04-nginx-configuration.md)
- [docs/05-docker-troubleshooting.md](05-docker-troubleshooting.md)
- [runbooks/maintenance-window.md](../runbooks/maintenance-window.md)
