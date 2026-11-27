# Deployment Guide (LEGACY — pre-ArgoCD)

**Author:** Tomáš H.
**Last updated:** 2022-11-08
**Status:** SUPERSEDED BY [docs/03-deployment-guide.md](03-deployment-guide.md)

> ⚠️ **Do not use this procedure for new services.** This is preserved for
> reference only — a handful of legacy VPS control-plane services (billing-api,
> old-portal) are still deployed this way as of early 2025 and will migrate
> "eventually".

## Overview

Legacy services are deployed as bare Docker containers on the two
`legacy-app-*` VMs (legacy-app-01.prg1, legacy-app-02.prg1). There is no
Kubernetes involved. Ansible pushes new images.

## Flow

1. SSH to `legacy-app-01.prg1` (jump host `bastion.prg1.pchosting.internal`).
2. Run the deploy playbook:

   ```
   cd /opt/pch-ansible
   ansible-playbook -i inventories/legacy deploy.yml -e "service=billing-api tag=v1.42.0"
   ```

3. The playbook does the following on each host in sequence:
   - `docker pull registry.prg1.pchosting.internal/<service>:<tag>`
   - Stops the old container
   - `docker run -d --name <service> ...` with the config baked into `/etc/pch/<service>.env`
   - Waits for the health check on `http://127.0.0.1:<port>/healthz`
   - Removes the old container

4. Nginx reload (edge-01, edge-02) is triggered separately if routing changed:

   ```
   ansible-playbook -i inventories/edge reload-nginx.yml
   ```

## Rollback (legacy)

Set the previous tag in the playbook and re-run. There is no "one-click"
rollback. Keep the last three image tags on the host — the cleanup cron in
[configs/backup-schedule.yml](../configs/backup-schedule.yml) preserves them.

## Gotchas

- `legacy-app-02` was rebuilt in Feb 2024 and is running Docker 24; `legacy-app-01`
  is still on Docker 20.10. Some `docker compose` v2 syntax fails on -01.
  See [known_issues/docker-issues.md](../known_issues/docker-issues.md).
- Do NOT use `docker stop` manually — the playbook expects to control lifecycle.
- The `/etc/pch/<service>.env` files are hand-edited. There is no source of
  truth. Yes, this is bad. It's on the tech-debt list.

## Migration

New services should always use the current guide:
[docs/03-deployment-guide.md](03-deployment-guide.md).

Migration plan for remaining legacy services is tracked in
[known_issues/pending-projects.md](../known_issues/pending-projects.md).
