# Security Baseline

**Author:** Anežka K. (Networking), reviewed by Karel D. (IT)
**Last updated:** 2024-07-01
**Status:** Current

Minimum expected security posture on every PCH-managed host.

## SSH

- Password authentication: **disabled**
- Root login: `PermitRootLogin prohibit-password` (key only, and only from bastion)
- Port: 22 on bastion, moved to 2222 on legacy internal hosts (historical, do not "fix")
- MFA on the bastion via Duo (integration installed 2023-11)

## Firewall

- `ufw` on VPS hosts, `iptables + Docker chains` on Docker hosts.
- Default deny inbound.
- Baseline allow: 22 (bastion source only), 80/443 (edges only), 51820 (VPN endpoints)
- **Never** open Postgres (5432) to public. Even for "just a demo".

## Patching

- Unattended-upgrades enabled for security updates.
- Kernel: livepatch (Canonical) on Ubuntu 22.04 hosts.
- Major upgrades: quarterly maintenance windows (see
  [runbooks/maintenance-window.md](../runbooks/maintenance-window.md)).

## Secrets

- Vault (HashiCorp) is the source of truth for internal secrets.
- Never commit secrets to git. `pre-commit` runs `git-secrets` and `gitleaks`.
- Customer-provided secrets stay in customer-managed environments; PCH support
  should never receive them via email — always via the encrypted upload portal.

## Logging & audit

- All shell sessions on production hosts recorded via `sudo I/O` logging.
- Retained 90 days in the `pch-audit` bucket.
- Access reviewed monthly by IT.

## Certificate management

See [docs/09-ssl-certificates.md](09-ssl-certificates.md).

## See also

- [docs/11-vpn-access.md](11-vpn-access.md)
- [runbooks/maintenance-window.md](../runbooks/maintenance-window.md)
