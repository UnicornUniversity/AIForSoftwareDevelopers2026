# Legacy Plan Migration Guide

**Author:** Jana Š. (Sales) with input from Tomáš H.
**Last updated:** 2023-04-11
**Status:** Slightly stale but broadly still accurate — the plan mapping
holds; the customer counts do not.

## Scope

Prior to 2023, PCH sold plans under the names "Basic", "Business",
"Enterprise". These were retired on **2023-01-15** in favor of the current
"Micro / Small / Medium / Large / XL" plans (see [docs/02-hosting-plans.md](02-hosting-plans.md)).

**Grandfathered customers keep their old plan pricing and specs.** Do not
force migration; offer it opportunistically.

## Old → New mapping

| Old plan (pre-2023) | Closest new plan | Notes                                |
|---------------------|------------------|--------------------------------------|
| Basic               | Small            | Old Basic = 2 vCPU, 4 GB, 100 GB    |
| Business            | Medium           | Old Business also included a "free wildcard" — see [docs/09b-ssl-legacy.md](09b-ssl-legacy.md) |
| Enterprise          | Large            | Old Enterprise included managed backups (still included in Large) |

## What migration entails

1. Check current usage — is the customer actually using the resources?
2. Offer the equivalent new plan at the current price. If cheaper, they win.
3. Snapshot current VPS (free, part of standard operations).
4. Provision new VPS on the new plan tier.
5. Move data via `rsync -aHAX` over the internal VLAN.
6. DNS cutover (60s TTL prep the day before).
7. Retain old VPS for 7 days (safety), then destroy.

## Do NOT

- Change plan names mid-cycle without emailing the customer first.
- Migrate an Enterprise customer without explicitly re-confirming their
  wildcard SSL is Let's Encrypt now (some are still on RapidSSL —
  [docs/09b-ssl-legacy.md](09b-ssl-legacy.md)).

## Current status

The migration project has stalled. Roughly ~40 legacy accounts remain as of
April 2023 (this number is likely lower now, but no one has audited).

## See also

- [docs/02-hosting-plans.md](02-hosting-plans.md)
- [docs/09b-ssl-legacy.md](09b-ssl-legacy.md)
- [faq/billing.md](../faq/billing.md)
