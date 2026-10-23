# Kickoff Summary — Hartwood Furniture Management Software

**Meeting:** 3 June 2026, 10:00–12:45, Conference Room B / hybrid (Greg dialing in from Prague)
**Participants:** Joanne Carter (Project Manager), Greg Thompson (Lead Developer), Mike Rodriguez (Sales Manager)
**Purpose:** Kick off planning, agree the technology stack and core features, and leave with action items, owners, and dates.

---

## Executive Summary

- The team kicked off planning for new management software to replace Hartwood Furniture's current setup: three spreadsheets, a paper ledger, and an Access database nobody can maintain, with no single source of truth.
- Stock is spread across the city-centre showroom, the Stockport warehouse, and an airport overflow warehouse, so salespeople cannot answer basic availability questions without phoning the warehouse and having someone physically check the shelf; this has cost confirmed sales.
- The stack was decided: Django REST Framework on the backend, React with TypeScript on the frontend, PostgreSQL for the database, with Metabase pencilled in for reporting pending the owner's sign-off.
- Feature scope was mapped across four areas — inventory, sales tracking, reporting, and UI/UX — plus crosscutting concerns of data accuracy, real-time visibility, reduced manual reconciliation, and auditability.
- Inventory scope covers multi-location real-time stock, variants, barcode scanning, transfers, returns, and document attachments; sales tracking covers all channels, commissions, deposits and instalments, quotes, discount approvals, and trade pricing.
- Data migration from the spreadsheets and Access database was recognised as a substantial project phase in its own right, and change management (training, parallel run, user champions) was added as a workstream.
- Action items were assigned to all three participants, with a follow-up meeting on 17 June 2026 at 2.5 hours, joined by warehouse staff Dave and Steve.

---

## Key Decisions

- **Django REST Framework for the backend.** Chosen for its mature ORM (the inventory/reporting joins are exactly its strength), the Django admin giving a back-office UI almost for free, the Python data and reporting ecosystem, built-in security, and a stable ecosystem. Node.js was explicitly considered and rejected: its event-loop advantage does not matter for a CRUD and reporting workload, and its ecosystem churns.
- **React with TypeScript for the frontend.** Separates the frontend decision from the backend one and answers the concern that Django means dated server-rendered pages; staff get a modern, app-like interface.
- **PostgreSQL as the database.** "Full stop" — nothing in the requirements pushes toward anything else; strong JSON support, full-text search, robust transactions, and mature tooling.
- **Metabase as the BI tool** (pencilled in, subject to the owner's sign-off). The owner's questions are investigative and cannot all be anticipated, so an off-the-shelf BI tool with a point-and-click builder beats building a custom report builder; no SQL required. Joanne will demo it to the owner.
- **Split the stack decision from the frontend framework decision.** Joanne's intervention reframed "Python versus JavaScript" as a backend question, with the frontend orthogonal — which is what unlocked agreement.
- **UI kit plus light bespoke design for key screens.** A kit buys speed for an internal tool; bespoke work is reserved for the dashboard, login, and other visible screens. Final choice (kit, freelancer, or hybrid) goes to the owner.
- **Responsive web, tablet-first, no native app for v1.** Showroom iPads are the main device; phone use for warehouse scanning and dashboard glances must be first-class. Native iOS/Android is a later investment only if demand justifies it.
- **Document attachments promoted to v1**, tightly scoped to upload, view, link to product/order/goods receipt, and simple metadata. The fire-safety certificate filing cabinet is a liability if audited.
- **Goods receipt and purchase orders deferred to v1.5/v2.** Receiving implies supplier-side PO tracking, which is ERP territory and its own complexity; noted but not blocking.
- **Commission handling: standard rules in v1.** Furniture at 6% of margin, accessories at 3% of revenue, senior salespeople plus 0.5%, and split-sale credit across salespeople with weights summing to 100%. Promotional commission doubling is rare enough for Mike to adjust manually until v1.5. Within-30-day refund clawback is automated, with a manager override for discretionary cases.
- **Deposits and instalments designed in from day one.** An order is a series of payments against a fulfilment lifecycle (quoted, deposit taken, in production, ready for delivery, delivered, complete). Retrofitting payment plans onto a single-transaction model is painful.
- **Basic delivery date capture in v1; scheduling in v2.** Route optimisation, driver assignment, and capacity management are a separate problem.
- **Quotes modelled as order-like records with an expiry date, convertible to orders.** Email acceptance via a unique link was added to v1 because phone tag on quote acceptance is a real cost.
- **Audit trail as a system-wide change log on key entities**, capturing who created or modified a record, when, and the previous values.
- **Data retention: seven years for transactional data, shorter for marketing data.** Aligns with HMRC requirements and GDPR.
- **At least two, ideally three, admin accounts**, with destructive actions requiring confirmation and irreversible deletions requiring a second admin. Prevents the owner being a single point of failure.
- **Internationalization baked in from the start, English-only in v1.** Templates externalized, dates and currencies formatted correctly, UTF-8 throughout — so French later is a translation job, not an engineering one.
- **Accessibility built in from the start.** Contrast, scalable text, keyboard navigation, and screen-reader support, driven by two known staff members who need it (bifocals, colour blindness).
- **Website refresh kept out of scope.** Squarespace order ingestion can be handled by a scheduled pull; replacing the e-commerce side is a separate conversation.
- **Data migration treated as an explicit project phase**, with a data audit in the second sprint and a default rule of migrating records while preserving cleaned originals in a "legacy" field.
- **Change management added as a workstream**, including training, a parallel run, a communication plan, and named user champions (Steve in the warehouse, Priya in the showroom).
- **Cutover provisionally targeted at the August bank holiday weekend**, when no sales are being taken.
- **Next meeting extended to 2.5 hours on 17 June 2026**, with Dave and Steve joining.

---

## Open Questions

- **Hosting and deployment** — deferred until expected load, data-residency requirements, and budget are known.
- **Data residency** — does customer data have to stay in the UK? This constrains hosting.
- **Budget** — Joanne has only a verbal range from the owner; firm numbers promised for the next meeting.
- **Hiring** — whether to hire locally in Manchester or open up to remote candidates; tabled to a separate staffing discussion.
- **Design approach** — freelancer versus UI kit versus hybrid; Joanne will present two or three options with costs and tradeoffs to the owner.
- **Metabase** — needs the owner's demo and sign-off before it is treated as decided.
- **Commission leaderboard** — Mike wants time to think about whether a leaderboard motivates or demotivates; v1 shows each salesperson their own number only.
- **Payment terminal integration** — whether the in-showroom terminal provider exposes an API; flagged for the next meeting.
- **Squarespace integration** — scheduled pull of orders versus replacing the site's e-commerce; the latter is out of scope for now.
- **GDPR specifics** — retention periods, what self-service erasure to expose, and where data is stored all need confirmation with the owner; Mike will forward last year's consultant report.
- **Compliance beyond fire safety** — country-of-origin labelling and other supplier-side obligations were raised but not answered.
- **CRM scope** — whether customer history stays a lightweight customer record or becomes a full CRM module was left open ("might be a v2 thing").
- **Disaster recovery** — whether the showroom can keep selling if the office network is down; explicitly not v1, but flagged for the next meeting.
- **Training and adoption details** — the shape of the parallel run and communication plan is Joanne's to draft.

---

## Risks and Concerns

- **Lost sales from poor stock visibility.** Mike cited a couple who walked out and bought from a competitor because the shop could not confirm an Ashbourne three-seater in oak with linen upholstery was available.
- **Double-selling the same unit.** Separate channel spreadsheets allow the showroom and warehouse to sell the same physical item; discrepancies have already been found during Friday reconciliation.
- **Unreliable reporting.** Reconciliation errors mean Mike sometimes presents numbers he knows are slightly off, and the owner has noticed.
- **Hiring difficulty in Manchester.** The last local developer hire took four months; Greg accepted this is a fair concern but noted Python is widely used and remote openness is the real lever.
- **Poor data quality in the Access database.** Free text in date fields ("Greg said he'd pay next Tuesday"), surnames in first-name fields, sales with no salesperson, and a Notes column used for everything including a 2019 lunch order. Migration will need careful decisions per record.
- **Staff adoption.** The previous Access rollout failed because nobody was trained and staff kept working the old way; the mitigation is training, a parallel run, and early user champions.
- **Fire-safety documentation exposure.** Certificates live in a poorly organised filing cabinet; failing to produce one quickly in an audit would be serious.
- **GDPR exposure.** Last year's consultant flagged issues; the paper card index is uncontrolled — anyone can pull a card, photograph it, and walk away. Breach reporting is a process problem as well as a technical one.
- **Barcode labelling on upholstery.** Stickers fall off fabric tags; proposed mitigations are hang tags for hard goods and barcode-on-wrapping for upholstered items, piloted with Dave and Steve.
- **Scope creep.** Goods receipt, delivery scheduling, website replacement, and native mobile apps were all consciously pushed out of v1.
- **Key-person and continuity risk.** Addressed by requiring multiple admin accounts and dual approval on destructive actions.
- **Disaster recovery gap.** A flood or office-network outage would currently stop the showroom selling; no redundancy or recovery-time objective has been agreed.
