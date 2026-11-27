# FAQ — Billing

**Audience:** Customers.
**Owner:** Finance + Sales.
**Last updated:** 2024-11-15

---

### What are your prices?

See [docs/02-hosting-plans.md](../docs/02-hosting-plans.md) or the pricing page.
All prices are in CZK per month, VAT excluded.

### How are invoices issued?

Monthly, on the anniversary of your account creation. Invoices arrive by
email and are available in the portal.

We are a VAT-registered Czech company (IČO 27XXX XXX, DIČ CZ27XXX XXX).
Reverse-charge VAT is applied for EU business customers with a valid VAT ID.

### What payment methods do you accept?

- Bank transfer (CZK, EUR)
- Credit card (Visa, Mastercard) via Stripe
- Direct debit (SEPA) for annual plans, EU customers only

We stopped accepting PayPal in 2022.

### Can I pay annually for a discount?

Yes — annual plans get 2 months free (~ 16.6% discount). Contact sales.

### I was charged for a plan I already cancelled — what do I do?

Open a support ticket with the invoice number. If you cancelled in the portal
and still got charged, our system will issue an automatic credit within
2 business days. If you cancelled by email only, please forward that email
so we can locate it — email-only cancellation is deprecated but still honored.

### I'm a legacy Business plan customer. What does that mean?

You're on our pre-2023 plan pricing. You keep your current pricing indefinitely
as long as you don't downgrade. Some legacy Business accounts also include a
"free wildcard SSL certificate" — this program was retired in 2022 but
grandfathered accounts are still honored. See internal doc if you're staff:
[docs/09b-ssl-legacy.md](../docs/09b-ssl-legacy.md).

### I want to upgrade / downgrade my plan. What happens to my data?

- **Upgrade:** Live, no downtime. Additional resources are attached to your
  existing VPS.
- **Downgrade:** Requires a plan-change window (usually same day) — we
  provision a new VPS at the smaller size, migrate, and cut over. We announce
  the cutover time.

For managed Postgres, plan changes involve a short (~ 30s) restart in most
cases; the standby is switched to the new plan first, then failed over.

### What happens if I don't pay?

- Day 1: reminder email
- Day 7: portal warning banner
- Day 14: services suspended (VMs stopped, data preserved)
- Day 30: data deletion warning
- Day 60: data deleted

We do not sell to debt collectors. Suspended services can be reactivated
by paying the outstanding invoice.

### Related FAQ

- [General FAQ](general.md)
- [Legacy plan migration (staff)](../docs/14-legacy-plan-migration.md)
