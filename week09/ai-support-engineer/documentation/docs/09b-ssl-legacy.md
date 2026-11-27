# SSL Certificates — Legacy Free Wildcard Program

**Author:** Anežka K.
**Last updated:** 2022-05-20
**Status:** ⚠️ DEPRECATED — program discontinued 2022-06-30.
**Superseded by:** [docs/09-ssl-certificates.md](09-ssl-certificates.md)

> This document is preserved because a small number of legacy "Business" plan
> customers were promised a "free wildcard cert for life" during the 2019–2022
> promotion. Handle these carefully in support — see the "Handling grandfathered
> customers" section below.

## What was the program?

From 2019 through mid-2022, PCH included a **free RapidSSL wildcard certificate**
for one customer domain on all Business-tier plans. Certs were manually issued
by the ops team and pushed to the customer's Nginx.

## Why was it discontinued?

- RapidSSL retail pricing rose ~ 3x
- Let's Encrypt wildcards became universally available (DNS-01 support since 2018)
- Manual renewals were error-prone — we caused two customer outages in 2021
  from missed renewals (see incident reports in Confluence)

## Handling grandfathered customers

As of the last audit (2023), **11 customer accounts** were still on the
free-wildcard program. Some of them have not been informed.

**If a customer complains their "free wildcard" wasn't renewed:**

1. Check the account tag `legacy-ssl-wildcard=true` in the CRM.
2. If present, honor the promise this year — issue a Let's Encrypt wildcard
   (see [docs/09-ssl-certificates.md](09-ssl-certificates.md), DNS-01 section)
   and note in the ticket.
3. Log an entry in the CRM: `Deprecation notice sent YYYY-MM-DD, expiring next
   renewal cycle.`
4. Escalate to Jana Š. (Sales) if the customer pushes back.

We are still not consistent about telling customers this is winding down.
Migration plan is on Petra's Q3 2025 roadmap.

## Do NOT

- Offer a free wildcard to new customers.
- Issue new RapidSSL certs — we don't have an active reseller account since 2022.
- Renew certs that are more than 30 days past their expected renewal window
  without checking with a team lead.

## See also

- [docs/09-ssl-certificates.md](09-ssl-certificates.md)
- [faq/billing.md](../faq/billing.md)
