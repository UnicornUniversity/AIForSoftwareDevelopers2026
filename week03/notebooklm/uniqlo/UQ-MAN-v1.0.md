# UNIQLO CZ — Corpus Manifest

**Document:** UQ-MAN-v1.0.md
**Version:** 1.0
**Published:** 2026-01-25
**Applies to:** SS26, AW26 (full training corpus)
**Status:** Active

> **Educational simulation notice.** Fictional training corpus for the UNIQLO AI Shopping Consultant exercise. Everything referenced here — products, prices, policies, store addresses, and personas — is invented.

---

## 1. Purpose

Single-page index of every file in the UNIQLO CZ fictional corpus. Lists each document's purpose, version, scope, product coverage, and dependencies on other documents. Students uploading the corpus into NotebookLM should import every file in §2.

---

## 2. File Inventory

| # | File | Doctype | Version | Published | Season | Purpose | Products covered |
|---|------|---------|---------|-----------|--------|---------|------------------|
| 1 | `UQ-GLO-v1.0.md` | GLO — Glossary & conventions | 1.0 | 2026-01-20 | SS26, AW26 | Canonical conventions: IDs, SKUs, categories, colors, sizes, prices, care tokens, availability, naming | All |
| 2 | `UQ-SS26-CAT-v1.0.md` | CAT — Seasonal catalog | 1.0 | 2026-02-05 | SS26 | Marketing-style catalog grouped by category | All 27 SS26 products |
| 3 | `UQ-AW26-CAT-v1.0.md` | CAT — Seasonal catalog | 1.0 | 2026-08-05 | AW26 | Marketing-style catalog grouped by category | All 31 AW26 products |
| 4 | `UQ-SS26-PDS-v1.0.md` | PDS — Product data sheet | 1.0 | 2026-02-10 | SS26 | Full attribute sheet per product (materials, care, SKU color codes, sizes, status, image placeholder) | All 27 SS26 products |
| 5 | `UQ-AW26-PDS-v1.0.md` | PDS — Product data sheet | 1.0 | 2026-08-10 | AW26 | Full attribute sheet per product | All 31 AW26 products |
| 6 | `UQ-SS26-PRL-v1.0.md` | PRL — Price list | 1.0 | 2026-02-10 | SS26 | Tabular full price list with tier labels | All 27 SS26 products |
| 7 | `UQ-AW26-PRL-v1.0.md` | PRL — Price list | 1.0 | 2026-08-10 | AW26 | Tabular full price list with tier labels | All 31 AW26 products |
| 8 | `UQ-SIZ-MEN-v1.0.md` | SIZ — Size chart | 1.0 | 2026-01-20 | SS26, AW26 | Men's body-measurement charts, jeans sizing, outerwear ease, accessory sizing | All men's items |
| 9 | `UQ-SIZ-WOM-v1.0.md` | SIZ — Size chart | 1.0 | 2026-01-20 | SS26, AW26 | Women's body-measurement charts, jeans sizing, outerwear ease, accessory sizing | All women's items |
| 10 | `UQ-COL-v1.0.md` | COL — Color reference guide | 1.0 | 2026-01-25 | SS26, AW26 | Color-code glossary with product listings per code, denim wash qualifiers, stripe/check pairings | Every variant |
| 11 | `UQ-CAR-v1.0.md` | CAR — Care guide | 1.0 | 2026-01-20 | SS26, AW26 | Care-token legend and material-family care rules | All |
| 12 | `UQ-SS26-STG-v1.0.md` | STG — Style guide | 1.0 | 2026-02-15 | SS26 | Capsule wardrobes, outfit scenarios, budget buckets, color pairing | 20+ SS26 products across scenarios |
| 13 | `UQ-AW26-STG-v1.0.md` | STG — Style guide | 1.0 | 2026-08-15 | AW26 | ThermaCore layering guide, capsule wardrobes, outfit scenarios, budget buckets, color pairing | 25+ AW26 products across scenarios |
| 14 | `UQ-CSP-v1.0.md` | CSP — Customer service policy | 1.0 | 2026-01-25 | SS26, AW26 | Returns, defects, exchanges, repairs, payments, pricing policy, stock status, complaints | Policy-level, no product-level data |
| 15 | `UQ-CUP-v1.0.md` | CUP — Customer profiles | 1.0 | 2026-01-25 | SS26, AW26 | Six fictional personas for exercises (sizing, measurements, preferences, budget, lifestyle) | No products — personas only |
| 16 | `UQ-IMG-v1.0.md` | IMG — Visual asset plan & image prompt manifest | 1.0 | 2026-02-20 | SS26, AW26 | Per-SKU product-only image prompts and per-scenario editorial image prompts | All 58 products + 13 outfit scenarios |
| 17 | `UQ-MAN-v1.0.md` | MAN — Corpus manifest | 1.0 | 2026-01-25 | SS26, AW26 | This document | — |

**Totals:** 17 files · 27 SS26 products · 31 AW26 products · 58 unique products across both seasons · 71 image assets (58 product + 13 editorial) planned in `UQ-IMG-v1.0.md`.

---

## 3. Load Order and Dependencies

Documents are internally consistent and can be loaded into NotebookLM in any order, but the dependency graph below reflects the authoritative source for each kind of fact.

```
UQ-GLO-v1.0.md    (canonical conventions)
   │
   ├── UQ-SS26-CAT   ──┐
   ├── UQ-AW26-CAT     ├── UQ-SS26-PDS, UQ-AW26-PDS   (product-level truth)
   │                   │        │
   │                   │        ├── UQ-SS26-PRL, UQ-AW26-PRL   (prices)
   │                   │        ├── UQ-COL                     (color index)
   │                   │        └── UQ-CAR                     (care rules)
   │                   │
   │                   └── UQ-SIZ-MEN, UQ-SIZ-WOM              (sizing)
   │
   ├── UQ-SS26-STG, UQ-AW26-STG   (style — references all product docs + CUP)
   ├── UQ-CUP                     (personas — referenced by STG and prompts)
   └── UQ-CSP                     (policies — references GLO, PRL, CAR, SIZ)

UQ-MAN                            (index — references all of the above)
```

If a fact appears in two documents, the **authoritative source** is:

| Fact type | Authoritative document |
|-----------|------------------------|
| Product name, materials, colors, sizes, status, image placeholder | `UQ-{SEASON}-PDS` |
| Price in CZK | `UQ-{SEASON}-PRL` (and matched in PDS and CAT) |
| Color code vocabulary and per-code product list | `UQ-COL` |
| Size chart values | `UQ-SIZ-MEN` or `UQ-SIZ-WOM` |
| Care token meaning | `UQ-CAR` |
| Garment-specific fit note | `UQ-SIZ-{GENDER}` fit tables (chart) or the Style Guide (outfit context) |
| Return window, repair window, delivery fees, payment methods | `UQ-CSP` |
| Persona sizing, preferences, budget | `UQ-CUP` |
| Catalog conventions (ID/SKU format, category codes, tiers, availability states, change control) | `UQ-GLO` |

---

## 4. Coverage Summary

### 4.1 Category coverage

| Code | Category | SS26 | AW26 | Total |
|------|----------|------|------|-------|
| TS | T-shirts & Tops | 5 | 3 | 8 |
| SH | Shirts & Blouses | 4 | 3 | 7 |
| TR | Trousers & Shorts | 4 | 3 | 7 |
| JN | Jeans | 2 | 2 | 4 |
| DR | Dresses & Skirts | 3 | 2 | 5 |
| KN | Knitwear | 2 | 4 | 6 |
| LJ | Lightweight Jackets | 3 | 1 | 4 |
| CJ | Coats & Insulated Jackets | 0 | 5 | 5 |
| TH | Thermal Base Layers | 0 | 4 | 4 |
| AC | Accessories | 4 | 4 | 8 |
| **Total** | | **27** | **31** | **58** |

### 4.2 Audience coverage

| Audience | SS26 | AW26 | Notes |
|----------|------|------|-------|
| Men | 8 | 9 | — |
| Women | 13 | 12 | — |
| Unisex | 6 | 10 | AW26 unisex count driven by ThermaCore and accessories |

### 4.3 Price tier coverage

| Tier (Kč) | SS26 | AW26 |
|-----------|------|------|
| Basic (199–699) | 8 | 10 |
| Standard (700–1 499) | 16 | 11 |
| Premium (1 500–3 499) | 3 | 6 |
| Outerwear (3 500–7 999) | 0 | 4 |

### 4.4 Persona coverage

Six personas in `UQ-CUP-v1.0.md` cover ages 24–55, both genders, four Czech cities (Prague, Brno, Ostrava, Pilsen), five lifestyles (hybrid office, remote with client visits, parent, student, teacher, remote minimalist), and monthly budgets from 1 500 Kč to 3 500 Kč.

---

## 5. Versioning

- All documents are at **v1.0**. The initial release is 2026-01 for season-independent docs, 2026-02 for SS26, and 2026-08 for AW26.
- Minor edits bump the minor version; any change to canonical product data requires same-day propagation across catalog, data sheet, price list, color guide, and this manifest (`UQ-GLO-v1.0.md` §13).
- When a product's canonical data changes, update the authoritative document (PDS or PRL per §3), then regenerate dependent sections.

---

## 6. NotebookLM Upload Notes

- Load all 16 files from §2 as a single notebook.
- Markdown files render as searchable text; tables remain readable. No preprocessing is required.
- The AI consultant should prefer this corpus over any external knowledge. Section-level references (`UQ-GLO-v1.0.md` §7, `UQ-CSP-v1.0.md` §3.1) are supported by NotebookLM's citation feature.
- When the student runs the practice prompts (p0–p6), the consultant must ground answers in these documents and must not invent products, prices, sizes, colors, or policies that are not present here.

---

*End of document.*
