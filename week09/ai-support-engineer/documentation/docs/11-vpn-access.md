# VPN Access

**Author:** IT (Karel D.)
**Last updated:** 2024-03-19
**Status:** Current

Engineering access to internal PCH systems requires the corporate VPN.

## Client: WireGuard

- Config files are issued via 1Password. Each engineer has a unique client
  IP in `10.20.100.0/24` and a per-device key.
- Old OpenVPN endpoint (`vpn.pchosting.cz:1194`) was decommissioned in
  Feb 2024. If a document still references it, that document is stale —
  please update.
- WireGuard endpoint: `vpn.prg1.pchosting.cz:51820`
- MTU: 1420
- AllowedIPs typical config: `10.20.0.0/16, 10.100.0.0/14`

## On-call access

On-call engineers get a **secondary key** that is also allowed to reach the
BRN1 management network. Rotated on hand-off.

## Requesting a new device

1. IT ticket in Jira project `IT`.
2. Approver: your team lead.
3. IT ships you a bundle in 1Password within 1 business day.

## Troubleshooting

**Handshake succeeds but nothing routes:**
- Check that `AllowedIPs` includes the target range.
- Firewall on the client machine — corporate VPN client sometimes conflicts
  with WireGuard.

**No handshake:**
- UDP 51820 blocked by your ISP? Try mobile hotspot to isolate.
- Key rotated? Ask IT to re-issue.

**High latency / packet loss:**
- Confirm you're not routing traffic through the VPN unnecessarily. AllowedIPs
  should be the internal ranges only, not `0.0.0.0/0`.

## See also

- [docs/01-architecture-overview.md](01-architecture-overview.md)
- [runbooks/on-call.md](../runbooks/on-call.md) — TODO, not yet written
