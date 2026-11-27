# FAQ — General

**Audience:** Customers via support portal.
**Owner:** Jana Š. (Sales), reviewed quarterly by Support Lead.
**Last updated:** 2025-01-28

---

### What is Prague Cloud Hosting?

Prague Cloud Hosting (PCH) is a Czech infrastructure provider offering
managed VPS, managed PostgreSQL, and managed Kubernetes ("PCH-K8s"), out
of two data centers in Prague and Brno.

We've been operating since 2015. Our team is based in Prague.

### Where are your data centers?

- **PRG1** — Prague, TTC Teleport (Nagano building), primary
- **BRN1** — Brno, STRV data center, secondary

A third region in Vienna (**VIE1**) has been on our roadmap since 2023 but
is currently deferred. We'll announce when we're ready to open sign-ups.

### What operating systems do you support?

For VPS: Ubuntu 22.04, Ubuntu 20.04 (until April 2025), Debian 12, Debian 11,
Rocky Linux 9, AlmaLinux 9. You can also install your own ISO — see the
customer portal.

We do **not** support Windows Server. We supported it from 2018 through
2023 but discontinued it due to low demand.

### Do you offer email hosting?

No. We retired our email hosting product in 2022. We recommend
[MXroute](https://mxroute.com/) or your domain registrar's built-in email.

### What is your uptime SLA?

- **VPS:** 99.95% monthly
- **Managed Postgres:** 99.95% monthly on Pro and Business plans; 99.9% on Starter
- **Managed Kubernetes:** 99.9% on the control plane

Credits are issued automatically to your account balance if we miss.

### Can I get support in Czech?

Yes — support is available in Czech and English. Response time on the
Business plan is 1 business hour during Czech business hours, 4 hours
otherwise. See the SLA doc in your portal for exact numbers.

### How do I contact support?

- Portal ticket (preferred): https://portal.pchosting.cz
- Email: support@pchosting.cz
- Phone (Business/Pro only): +420 224 XXX XXX during business hours

### Can I bring my own domain?

Yes — set your DNS to point at your VPS or use our shared edge IPs for K8s
customers. See [docs/07-reverse-proxy-setup.md](../docs/07-reverse-proxy-setup.md)
for the technical setup (or ask support).

### Do you provide SSL certificates?

Yes — via Let's Encrypt, self-service. See
[docs/09-ssl-certificates.md](../docs/09-ssl-certificates.md).

If you're a legacy Business customer from before 2022, you may still be on
our free-wildcard program — check with support.

### Related FAQ

- [Billing questions](billing.md)
- [Technical questions](technical.md)
- [Docker & containers](docker.md)
- [Database questions](database.md)
