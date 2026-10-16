# UNIQLO CZ — Customer Profiles for AI Shopping Consultant Exercises

**Document:** UQ-CUP-v1.0.md
**Version:** 1.0
**Published:** 2026-01-25
**Status:** Active (educational use only)

> **Educational simulation notice.** All profiles are fictional personas designed for the UNIQLO AI Shopping Consultant training exercise. Any resemblance to real individuals is coincidental.

---

## Purpose

Six personas spanning age, gender, geography, lifestyle, and budget. Each profile includes sizing hints, color and material preferences, lifestyle context, and a monthly clothing budget — enough context for an AI consultant to make seasonal recommendations, budget-constrained outfit plans, and change-request handling.

Profiles are referenced from the style guides (`UQ-SS26-STG-v1.0.md`, `UQ-AW26-STG-v1.0.md`) and from the practice prompts (p0–p6).

---

## CP-01 — Markéta Dvořáková

- **Age:** 28
- **Gender:** Woman
- **City:** Prague
- **Occupation:** Marketing specialist, hybrid work (3 days office, 2 days home)
- **Household:** Lives alone in a Vinohrady flat
- **Sizing:** Tops S, Trousers S, Jeans W28/L30, Shoe EU 38
- **Measurements:** Bust 87 cm, Waist 68 cm, Hip 94 cm
- **Color preferences:** Neutrals — off-white, beige, black, navy. Occasional burgundy.
- **Avoids:** Yellow, bright pink, loud prints.
- **Material preferences:** Cotton, linen, wool. Dislikes synthetic-only fabrics on skin.
- **Lifestyle notes:** Office business-casual on-site days; minimalist weekend style. Takes two short city breaks per year.
- **Monthly clothing budget:** 2 500 Kč.
- **Priority goals:** Build a small, interchangeable wardrobe. Prefers one quality item over several cheap ones.

---

## CP-02 — Tomáš Novotný

- **Age:** 35
- **Gender:** Man
- **City:** Brno
- **Occupation:** IT consultant, mostly remote with occasional client visits
- **Household:** Partner, no children
- **Sizing:** Tops L, Trousers L, Jeans W34/L32, Shoe EU 44
- **Measurements:** Chest 102 cm, Waist 90 cm, Inseam 82 cm
- **Color preferences:** Navy, olive, grey, charcoal. Earth tones in autumn.
- **Avoids:** Pink, pastels.
- **Material preferences:** Technical fabrics for outdoor; cotton and merino for daily wear.
- **Lifestyle notes:** Weekend hiker (Moravian Karst, Krkonoše); needs one smart-casual outfit for client dinners. Owns a bicycle used for city commuting.
- **Monthly clothing budget:** 3 500 Kč.
- **Priority goals:** Durable outdoor layering + one presentable work outfit.

---

## CP-03 — Lenka Procházková

- **Age:** 42
- **Gender:** Woman
- **City:** Prague
- **Occupation:** Part-time administrator at a primary school
- **Household:** Partner, two children (ages 7 and 10)
- **Sizing:** Tops M, Trousers M, Jeans W30/L30, Shoe EU 39
- **Measurements:** Bust 93 cm, Waist 75 cm, Hip 99 cm
- **Color preferences:** Navy, beige, grey, off-white. Pink and burgundy as accents.
- **Avoids:** Dry-clean-only items.
- **Material preferences:** Easy-care cotton, cotton blends, jersey. Values machine-washable.
- **Lifestyle notes:** School runs, playground time, family weekends outdoors. Needs clothing that layers quickly and tolerates frequent washing.
- **Monthly clothing budget:** 2 000 Kč.
- **Priority goals:** Low-maintenance pieces that look polished during the school day and allow movement with children.

---

## CP-04 — David Horák

- **Age:** 24
- **Gender:** Man
- **City:** Ostrava
- **Occupation:** University student (Master's in Economics)
- **Household:** Shared student flat
- **Sizing:** Tops S, Trousers S, Jeans W30/L32, Shoe EU 42
- **Measurements:** Chest 90 cm, Waist 78 cm, Inseam 82 cm
- **Color preferences:** Black, navy, grey, olive. Occasional white or burgundy accent.
- **Avoids:** Pastels, floral prints.
- **Material preferences:** Cotton for daily wear, fleece or synthetics for cold commute.
- **Lifestyle notes:** Trend-aware, follows streetwear-adjacent styles. Commutes by tram and bike year-round. Occasional part-time café shifts (requires presentable but washable clothes).
- **Monthly clothing budget:** 1 500 Kč.
- **Priority goals:** Maximum style per koruna; prioritizes a few core pieces that work across weeks.

---

## CP-05 — Eva Marková

- **Age:** 55
- **Gender:** Woman
- **City:** Pilsen
- **Occupation:** Secondary school teacher (Czech language and literature)
- **Household:** Partner, two adult children living separately
- **Sizing:** Tops L, Trousers L, Jeans W32/L30, Shoe EU 40
- **Measurements:** Bust 99 cm, Waist 82 cm, Hip 106 cm
- **Color preferences:** Classic — charcoal, navy, burgundy, beige, off-white.
- **Avoids:** Overly short lengths, logos.
- **Material preferences:** Wool, cashmere, cotton, viscose. Values natural fibers and refined finishes.
- **Lifestyle notes:** Classroom all week; concert and theatre visits on weekends. Appreciates investment pieces that last several seasons.
- **Monthly clothing budget:** 3 000 Kč.
- **Priority goals:** Quality over quantity; one or two refined items per quarter.

---

## CP-06 — Honza Beneš

- **Age:** 31
- **Gender:** Man
- **City:** Prague
- **Occupation:** Senior software engineer, fully remote
- **Household:** Lives alone
- **Sizing:** Tops M, Trousers M, Jeans W32/L32, Shoe EU 43
- **Measurements:** Chest 96 cm, Waist 84 cm, Inseam 82 cm
- **Color preferences:** Monochrome — charcoal, black, off-white, occasional navy. Avoids bright colors by default.
- **Avoids:** Prints, mixed colors in one outfit.
- **Material preferences:** Merino, cashmere, cotton. Open to technical fabrics for travel.
- **Lifestyle notes:** Minimalist capsule wardrobe (around 25 pieces). Travels to a tech conference twice a year — needs one presentable travel outfit. Walks or runs daily.
- **Monthly clothing budget:** 2 500 Kč.
- **Priority goals:** Fewer, better pieces. Prefers tonal outfits in 2–3 colors only.

---

## Profile-Level Interaction Hints for the AI Consultant

| Persona | Preferred interaction style | Red flags to watch for |
|---------|----------------------------|------------------------|
| CP-01 Markéta | Concise recommendations, 1–2 options per request | Don't suggest bright colors or loud prints |
| CP-02 Tomáš | Technical specifications, fabric performance details | Don't suggest pastels or dry-clean-only pieces for outdoor use |
| CP-03 Lenka | Highlight washability and ease-of-care up front | Don't recommend dry-clean-only garments |
| CP-04 David | Price-first framing; always mention total under budget | Don't exceed 1 500 Kč/month unless user explicitly agrees |
| CP-05 Eva | Emphasize material quality and durability | Don't suggest short dresses or logo prints |
| CP-06 Honza | Minimalist, 2–3 color palettes only | Don't suggest more than one color accent per outfit |

---

## Cross-Reference to Style Guides

- Markéta appears in **Scenarios 4.2, 4.3** (SS26) and **5.1** (AW26).
- Tomáš appears in **Scenarios 4.1, 4.4** (SS26) and **5.2, 5.3** (AW26).
- Lenka appears in **Scenario 5.4** (AW26).
- David appears in **Scenario 4.5** (SS26) and **5.5** (AW26).
- Eva appears in **Scenario 4.6** (SS26) and **5.6** (AW26).
- Honza appears in **Scenario 5.7** (AW26).

---

*End of document.*
