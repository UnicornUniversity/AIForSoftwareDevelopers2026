# UNIQLO CZ — Glossary and Catalog Conventions

**Document:** UQ-GLO-v1.0.md
**Version:** 1.0
**Published:** 2026-01-20
**Applies to:** SS26, AW26
**Status:** Active

> **Educational simulation notice.** This document is part of a fictional training corpus for the UNIQLO AI Shopping Consultant exercise. All product data, pricing, policies, and company information herein are invented and must not be treated as authentic UNIQLO content.

---

## 1. Purpose

Defines shared conventions for all catalog documents in the UNIQLO CZ corpus: identifiers, categories, colors, sizes, prices, availability, and cross-references. All catalog, price, data sheet, size, care, style, and customer-profile documents must comply.

---

## 2. Product Identifier and SKU

### 2.1 Product ID
Format: `UQ-{SEASON}-{CAT}-{SEQ}`

- `UQ` — UNIQLO prefix.
- `SEASON` — collection code (see §4).
- `CAT` — 2-letter category code (see §3).
- `SEQ` — 3-digit zero-padded sequence number, unique per category per season.

Example: `UQ-SS26-TS-001`.

### 2.2 SKU (full variant)
Format: `UQ-{SEASON}-{CAT}-{SEQ}-{COLOR}-{SIZE}`

- `COLOR` — 3-letter color code (see §6).
- `SIZE` — size value (see §5).

Example: `UQ-SS26-TS-001-WHT-M`.

---

## 3. Category Codes

| Code | Category |
|------|----------|
| TS | T-shirts & Tops |
| SH | Shirts & Blouses |
| TR | Trousers & Shorts |
| JN | Jeans |
| DR | Dresses & Skirts |
| KN | Knitwear |
| LJ | Lightweight Jackets |
| CJ | Coats & Insulated Jackets |
| TH | Thermal Base Layers (ThermaCore line) |
| AC | Accessories |

---

## 4. Seasonal Collection Codes

| Code | Collection | Theme | Publication | In-store from |
|------|-----------|-------|-------------|---------------|
| SS26 | Spring–Summer 2026 | Open Air | 2026-02 | 2026-03-01 |
| AW26 | Autumn–Winter 2026 | Winter Warm Core | 2026-08 | 2026-09-01 |

---

## 5. Size System

### 5.1 Apparel sizes
`XS, S, M, L, XL, XXL` — used for tops, shirts, dresses, knitwear, trousers (non-jeans), outerwear.

### 5.2 Jeans sizes
Waist × inseam notation: `W{waist}/L{inseam}` where waist is in inches (28–38) and inseam in inches (30, 32, 34). Example: `W32/L32`.

### 5.3 Accessory sizes
- `ONE` — one size fits most.
- `S/M`, `L/XL` — two-step sizing used for gloves.

### 5.4 Measurement units
Body and garment measurements are given in **centimeters** (cm). Fabric or fill weights are given in **grams** (g). Full charts live in `UQ-SIZ-MEN-v1.0.md` and `UQ-SIZ-WOM-v1.0.md`.

---

## 6. Controlled Color List

| Code | Name | Code | Name |
|------|------|------|------|
| WHT | White | OLI | Olive |
| OFW | Off-White | BRG | Burgundy |
| BLK | Black | BLU | Light Blue |
| NVY | Navy | PNK | Pink |
| GRY | Grey | YLW | Yellow |
| CHA | Charcoal | ORG | Orange |
| BEI | Beige | GRN | Green |
| KHA | Khaki | BRN | Brown |

Each product lists only the colors in which it is actually produced; the full list is reserved as a controlled vocabulary.

---

## 7. Price Format and Policy

- **Currency:** CZK (Kč) only; no foreign-currency equivalents.
- **Format:** integer amount, thin space as thousands separator, trailing `Kč`. Example: `1 499 Kč`.
- **VAT:** Czech standard VAT 21% is already included in the shelf price.
- **Price tiers:**

| Tier | Range |
|------|-------|
| Basic | 199 – 699 Kč |
| Standard | 700 – 1 499 Kč |
| Premium | 1 500 – 3 499 Kč |
| Outerwear | 3 500 – 7 999 Kč |

- **Markdown policy:** end-of-season clearance applies −30% on remaining SS26 stock from 2026-08-01 and on remaining AW26 stock from 2027-02-01. The canonical price list always shows full price; markdowns are described in prose only.

---

## 8. Material Composition and Care Tokens

### 8.1 Material composition
Expressed as percentages that must sum to 100. Example: `98% cotton, 2% elastane`.

### 8.2 Standard material families
Cotton, linen, polyester, nylon, elastane, wool, merino wool, cashmere, down fill (90/10 duck down–feather by default), fleece, viscose, rayon, acrylic.

### 8.3 Care tokens
Textual tokens used in product data sheets. See `UQ-CAR-v1.0.md` for the full legend.

| Token | Meaning |
|-------|---------|
| WASH_30 | Machine wash cold (max 30 °C) |
| WASH_40 | Machine wash warm (max 40 °C) |
| NO_BLEACH | Do not bleach |
| TUMBLE_LOW | Tumble dry on low heat |
| IRON_LOW | Iron on low heat (max 110 °C) |
| IRON_MED | Iron on medium heat (max 150 °C) |
| DRY_FLAT | Dry flat |
| DRY_CLEAN_ONLY | Professional dry cleaning only |

---

## 9. Availability Status

Each product has exactly one status per season:

| Status | Meaning |
|--------|---------|
| Available | Fully stocked in stores and online |
| Online Only | Stocked online only |
| In-Store Only | Stocked in physical stores only |
| Pre-Order | Launching soon; order ahead |
| End of Season | Clearance; limited sizes/colors |

Stock quantities are not published.

---

## 10. ThermaCore Technology Line

**ThermaCore** is the in-catalog name for the thermal base-layer technology used across the TH category and selected lined garments (e.g., `UQ-AW26-JN-010`, `UQ-AW26-AC-011`, `UQ-AW26-CJ-003`). Two warmth levels exist:

- **ThermaCore Standard** — rayon/acrylic/polyester/elastane blend; everyday warmth.
- **ThermaCore Extra Warm** — same family with higher acrylic ratio; added warmth for sub-zero conditions.

---

## 11. Cross-Document Product References

- Prose must reference products by **Product ID** and short name on first mention: *UQ-SS26-TS-001 Basic Cotton Crew Tee*.
- After the first mention, the short name alone is acceptable.
- **Full SKUs** (color + size) appear only in product data sheets and price lists where variant-level detail is needed.
- Any product mentioned anywhere in the corpus must exist in the canonical master data table with identical name, materials, colors, sizes, and price.

---

## 12. Document Naming Convention

Format: `UQ-{SEASON}-{DOCTYPE}-v{MAJOR}.{MINOR}.md`

| Doctype | Document |
|---------|----------|
| CAT | Seasonal catalog |
| PDS | Product data sheet (per category or per season) |
| PRL | Price list |
| SIZ | Size chart |
| STG | Style guide |
| CAR | Care guide |
| COL | Color reference guide |
| CSP | Customer service policy |
| CUP | Customer profiles |
| IMG | Visual asset plan & image prompt manifest |
| GLO | Glossary & conventions |
| MAN | Corpus manifest |

Season-independent documents (GLO, CAR, COL, CSP, CUP, IMG, MAN, SIZ) omit the `{SEASON}` segment.

---

## 13. Change Control

Minor edits (typos, formatting) increment the minor version. Any change to canonical product data (name, materials, colors, sizes, price, status) requires a new minor version and must be reflected across all dependent documents on the same day.

---

*End of document.*
