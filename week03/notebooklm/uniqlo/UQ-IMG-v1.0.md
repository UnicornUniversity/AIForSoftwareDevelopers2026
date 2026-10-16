# UNIQLO CZ — Visual Asset Plan & Image Prompt Manifest

**Document:** UQ-IMG-v1.0.md
**Version:** 1.0
**Published:** 2026-02-20
**Applies to:** SS26, AW26
**Status:** Active (educational use only)

> **Educational simulation notice.** Fictional training corpus. All products, images, and visual assets are invented for the UNIQLO AI Shopping Consultant exercise. These prompts are intended for a generic image-generation tool. **Do not reproduce official product photographs, do not imply the generated images are authentic UNIQLO brand assets, and do not include brand logos, text, watermarks, or invented labels in the images.** No real-person likenesses.

---

## 1. Purpose and Scope

Defines the complete image asset plan for the fictional UNIQLO CZ corpus. Each row describes one image asset, pairs it with the canonical SKU (`UQ-GLO-v1.0.md` §2), and gives the exact prompt required to regenerate it.

Two asset classes are produced:

- **Product-only** — one image per canonical product (58 total). For insertion into the seasonal catalogs (`UQ-SS26-CAT-v1.0.md`, `UQ-AW26-CAT-v1.0.md`) and the product data sheets (`UQ-SS26-PDS-v1.0.md`, `UQ-AW26-PDS-v1.0.md`).
- **Editorial outfit** — one image per style-guide scenario (13 total; 6 SS26 + 7 AW26). For insertion into the style guides (`UQ-SS26-STG-v1.0.md`, `UQ-AW26-STG-v1.0.md`).

Image files have not been generated in this document. Where image generation is available, use the prompts below in manageable batches and save each file under its listed filename.

---

## 2. Global Visual Style (applies to every image)

Every prompt in §4 and §5 inherits the following style directives. Do not repeat these inside each row; apply them at generation time.

- **Medium:** realistic retail catalog photography, high-resolution digital capture.
- **Background:** clean seamless studio background in neutral off-white or very light grey (`#F2F2F2 – #FAFAFA`). No props unless specified.
- **Lighting:** soft, diffused, even studio lighting; no deep shadows; neutral white balance; no color cast on the garment.
- **Garment presentation:** clear silhouette; wrinkle-free except where fabric characteristic requires otherwise (linen: natural, light creasing). Realistic fabric texture.
- **Framing:** consistent camera distance within a category (see §3 framing matrix); garment centered; small, even margin above and below.
- **Composition:** minimal visual clutter; no decorative elements; no secondary garments or accessories unless the row explicitly lists them.
- **Color accuracy:** garment color must match the controlled color list (`UQ-GLO-v1.0.md` §6) and the specific color code listed for the SKU in the canonical catalog.
- **Prohibitions:** no visible brand logos; no text, numbers, barcodes, watermarks, swing tags, or invented labels; no mannequin faces visible on close-ups; no real-person likenesses; no stylized art, no illustration, no cartoon rendering; no HDR glow; no shallow-depth bokeh that obscures the garment; no studio equipment visible.

---

## 3. Framing Matrix (per category)

Chosen to keep product-only images visually consistent across both seasons.

| Category | Default view | Default composition |
|----------|--------------|---------------------|
| TS — T-shirts & Tops | Flat lay, straight-on top-down | Full garment visible, sleeves spread naturally |
| SH — Shirts & Blouses | Flat lay, straight-on top-down | Collar at top, placket centered, sleeves spread |
| TR — Trousers & Shorts | Flat lay, straight-on top-down | Waistband at top, legs straight, no stacking |
| JN — Jeans | Flat lay, straight-on top-down | Waistband at top, five-pocket construction visible on front |
| DR — Dresses | Flat lay, straight-on top-down | Shoulders at top, hem at bottom, slight natural drape |
| DR — Skirts | Flat lay, straight-on top-down | Waistband at top, full hem visible |
| KN — Knitwear | Flat lay, straight-on top-down | Shoulder seam visible, cuffs flat, ribbing visible |
| LJ — Lightweight Jackets | Flat lay, straight-on top-down | Jacket closed, sleeves slightly out |
| CJ — Coats & Insulated Jackets | 3/4 front on invisible mannequin (ghost mannequin) | Garment held in natural wearing shape, no visible stand |
| TH — Thermal Base Layers | Flat lay, straight-on top-down | Minimal styling, fabric texture visible |
| AC — Accessories (hats, caps, beanies, earmuffs) | 3/4 front, isolated | Centered, no face |
| AC — Scarves | Flat lay, folded in a loose rectangle | Fabric drape and weave visible |
| AC — Gloves | Flat lay, side by side, palms down | Natural finger relaxation |
| AC — Sunglasses | Flat lay, 3/4 angle | Lenses visible, no reflections of a scene |

Editorial outfit images (§5) use styled on-figure photography with full outfit visible, framed head-crop to mid-thigh or full body depending on scenario; faces are turned, cropped, or softly out of focus.

---

## 4. Product-Only Image Manifest

**Filename convention:** `{PRODUCT-ID}.png` (e.g., `UQ-SS26-TS-001.png`).
**Hero color:** one canonical color per SKU, chosen for photographic clarity and category variety across the manifest. The chosen hero color is always listed in the PDS color set for that SKU (`UQ-SS26-PDS-v1.0.md`, `UQ-AW26-PDS-v1.0.md`) and is called out as **Garment color** in each row. All other canonical colorways remain valid for the product; the manifest shoots one hero color per SKU to keep the asset count manageable.

### 4.1 SS26 — T-shirts & Tops

#### UQ-SS26-TS-001 — Basic Cotton Crew Tee
- **Filename:** `UQ-SS26-TS-001.png`
- **Garment color:** WHT (White).
- **Garment type / silhouette:** Unisex short-sleeve crew-neck T-shirt in 100% cotton. Round neckline, straight hem, reinforced shoulder tape faintly visible.
- **View / composition:** Flat-lay top-down, full garment centered, sleeves spread flat.
- **Background / lighting:** Light-grey seamless studio background; soft even top light.
- **Consistency attributes:** Pure white fabric; natural cotton texture; no logo, no chest print, no pocket.
- **Prompt:** "Flat-lay studio photograph of a plain pure-white 100% cotton short-sleeve crew-neck unisex T-shirt, straight hem, reinforced shoulder tape, no logos, no prints, no text, no tags; soft even studio lighting on a light-grey seamless background; realistic cotton texture, slight natural fabric weight; retail catalog photography."

#### UQ-SS26-TS-002 — DryFlex Workout Tee
- **Filename:** `UQ-SS26-TS-002.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Men's short-sleeve athletic tee in moisture-wicking polyester-elastane. Flat seams, mesh underarm panels, slim athletic cut.
- **View / composition:** Flat-lay top-down, full garment, sleeves spread.
- **Background / lighting:** Light-grey background; soft lighting with slight sheen highlight on synthetic fabric.
- **Consistency attributes:** Technical performance appearance; mesh ventilation panels visible under the arms; no logos; no reflective trim.
- **Prompt:** "Flat-lay studio photograph of a black men's short-sleeve athletic T-shirt in matte polyester-elastane fabric; flat-stitched seams; black mesh ventilation panels visible under the sleeves; slim athletic cut, straight hem; no logos, no prints, no labels; soft studio light on light-grey seamless background; realistic technical fabric texture."

#### UQ-SS26-TS-003 — Breeze Linen Tank
- **Filename:** `UQ-SS26-TS-003.png`
- **Garment color:** WHT (White).
- **Garment type / silhouette:** Women's lightweight sleeveless tank in linen-viscose. Relaxed fit, scooped neckline, dropped armhole, straight hem.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft natural-feeling studio light.
- **Consistency attributes:** Light airy linen appearance with slight natural creasing; translucency hint on fabric edges; no logo; no lace trim.
- **Prompt:** "Flat-lay studio photograph of a white women's sleeveless tank top in a linen-viscose blend; relaxed cut, scooped neckline, dropped armhole, straight hem; slight natural linen creasing; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic linen weave texture."

#### UQ-SS26-TS-004 — Striped Pocket Tee
- **Filename:** `UQ-SS26-TS-004.png`
- **Garment color:** NVY/WHT (Navy and white horizontal stripes).
- **Garment type / silhouette:** Unisex breton-style short-sleeve T-shirt in 100% cotton. Even horizontal navy and white stripes; contrasting solid-navy chest pocket on the left.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft even light to keep stripe contrast true.
- **Consistency attributes:** Stripes continuous and even; chest pocket solid navy (contrasts the striped body); no graphic prints.
- **Prompt:** "Flat-lay studio photograph of a unisex short-sleeve cotton breton T-shirt with evenly spaced horizontal navy and white stripes; a small solid-navy chest pocket on the left side contrasts with the striped body; round neckline, straight hem; no logos, no text; soft diffuse studio light on light-grey seamless background; realistic cotton knit texture."

#### UQ-SS26-TS-005 — UV-Shield Long Sleeve
- **Filename:** `UQ-SS26-TS-005.png`
- **Garment color:** GRY (Grey).
- **Garment type / silhouette:** Unisex long-sleeve technical top in nylon-elastane. Fitted athletic cut, cuffs with thumbholes.
- **View / composition:** Flat-lay top-down with cuffs rotated to show the thumbholes.
- **Background / lighting:** Light-grey background; soft lighting with light sheen on synthetic fabric.
- **Consistency attributes:** Thumbholes visible; smooth technical fabric; no reflective detail; no logos.
- **Prompt:** "Flat-lay studio photograph of a grey unisex long-sleeve athletic top in smooth nylon-elastane; fitted athletic cut; cuffs rotated to show small thumbhole openings; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic technical fabric texture with subtle sheen."

### 4.2 SS26 — Shirts & Blouses

#### UQ-SS26-SH-001 — Oxford Short Sleeve Shirt
- **Filename:** `UQ-SS26-SH-001.png`
- **Garment color:** BLU (Light Blue).
- **Garment type / silhouette:** Men's short-sleeve Oxford shirt, 100% cotton. Button-down collar, left chest pocket, straight hem, front placket with six buttons.
- **View / composition:** Flat-lay top-down, collar at top, placket centered, sleeves spread.
- **Background / lighting:** Light-grey background; soft even lighting.
- **Consistency attributes:** Classic light-blue Oxford texture; buttons tonal (not contrasting); chest pocket plain, no monogram.
- **Prompt:** "Flat-lay studio photograph of a men's light-blue short-sleeve Oxford shirt in 100% cotton; button-down collar, plain chest pocket on the left, straight hem, tonal buttons; no logos, no text; soft diffuse studio light on light-grey seamless background; realistic Oxford-weave texture."

#### UQ-SS26-SH-002 — Linen Camp Collar Shirt
- **Filename:** `UQ-SS26-SH-002.png`
- **Garment color:** OLI (Olive).
- **Garment type / silhouette:** Men's short-sleeve holiday shirt in 100% linen. Open camp collar, two chest pockets, boxy relaxed fit, straight hem.
- **View / composition:** Flat-lay top-down, collar laid open at top, pockets symmetrical.
- **Background / lighting:** Light-grey background; soft lighting; slight natural linen creasing permitted.
- **Consistency attributes:** Camp (notch) collar laid flat and open; two matching chest pockets; no graphic print; natural linen slubs.
- **Prompt:** "Flat-lay studio photograph of a men's olive-green short-sleeve camp-collar shirt in 100% linen; open notch collar laid flat, two symmetrical chest pockets, boxy relaxed fit, straight hem; slight natural linen creasing; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic linen slub texture."

#### UQ-SS26-SH-003 — Chiffon Blouse
- **Filename:** `UQ-SS26-SH-003.png`
- **Garment color:** OFW (Off-White).
- **Garment type / silhouette:** Women's long-sleeve blouse in polyester chiffon. Mandarin collar, concealed placket, buttoned cuffs. Fluid drape.
- **View / composition:** Flat-lay top-down with gentle fabric drape visible along the hem.
- **Background / lighting:** Light-grey background; soft lighting that preserves fabric translucency.
- **Consistency attributes:** Mandarin collar (short standing), concealed placket (no visible buttons on front), small tonal buttons at cuffs; subtle sheen typical of chiffon; no lace or embroidery.
- **Prompt:** "Flat-lay studio photograph of a women's off-white long-sleeve chiffon blouse; short mandarin standing collar, concealed front placket (no front buttons visible), small tonal buttoned cuffs; fluid drape with slight translucency; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic chiffon fabric texture."

#### UQ-SS26-SH-004 — Cotton Shirtdress Shirt
- **Filename:** `UQ-SS26-SH-004.png`
- **Garment color:** WHT (White).
- **Garment type / silhouette:** Women's elongated long-sleeve cotton shirt that doubles as a short shirtdress. Point collar, buttoned front, side slits at the hem.
- **View / composition:** Flat-lay top-down, elongated length clearly visible, side slits at hem shown.
- **Background / lighting:** Light-grey background; soft even light.
- **Consistency attributes:** Length noticeably longer than a regular shirt; side slits present at hem; point collar; tonal buttons; no decorative embroidery.
- **Prompt:** "Flat-lay studio photograph of a white elongated women's long-sleeve cotton shirt in a shirtdress length; point collar, full front placket with tonal buttons, visible side slits at the hem; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic cotton poplin texture."

### 4.3 SS26 — Trousers & Shorts

#### UQ-SS26-TR-001 — Chino Shorts 7"
- **Filename:** `UQ-SS26-TR-001.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Men's beige cotton chino shorts, 7-inch inseam, slim-straight leg, slant front pockets, flat waistband with belt loops.
- **View / composition:** Flat-lay top-down, waistband at top, both legs straight and parallel.
- **Background / lighting:** Light-grey background; soft even light.
- **Consistency attributes:** Short 7-inch inseam clearly visible; slant pockets at hips; tonal buttons; no cargo pockets.
- **Prompt:** "Flat-lay studio photograph of men's beige cotton chino shorts with a short 7-inch inseam, slim-straight leg, slant front pockets, flat waistband with belt loops and a single tonal button closure; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic cotton chino texture."

#### UQ-SS26-TR-002 — Linen Blend Trousers
- **Filename:** `UQ-SS26-TR-002.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Men's drawstring trousers in linen-cotton blend. Elasticated waist with visible drawcord, tapered leg to ankle.
- **View / composition:** Flat-lay top-down, waistband at top, tapered legs ending straight.
- **Background / lighting:** Light-grey background; soft lighting; slight natural linen creasing permitted.
- **Consistency attributes:** Drawcord ends tucked but visible at waistband; tapered (not wide) leg; no cuffs.
- **Prompt:** "Flat-lay studio photograph of men's beige linen-cotton drawstring trousers; elasticated waistband with a visible fabric drawcord, tapered leg to ankle, no cuffs; slight natural linen creasing; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic linen-cotton texture."

#### UQ-SS26-TR-003 — Pleated Wide Shorts
- **Filename:** `UQ-SS26-TR-003.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Women's high-waisted pleated shorts in 100% cotton. Wide leg, two deep front pleats per leg, back zip, no belt loops.
- **View / composition:** Flat-lay top-down, waistband at top, wide hem clearly flared.
- **Background / lighting:** Light-grey background; soft even light.
- **Consistency attributes:** Deep front pleats visible on each leg; wide (not slim) silhouette; smooth clean waistband (no belt loops).
- **Prompt:** "Flat-lay studio photograph of women's beige high-waisted pleated shorts in 100% cotton; two deep front pleats on each leg, wide leg silhouette, smooth clean waistband without belt loops, back zip; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic cotton twill texture."

#### UQ-SS26-TR-004 — Ankle Pants
- **Filename:** `UQ-SS26-TR-004.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's cropped ankle pants in polyester-viscose. Mid-rise, slim-straight leg, side pockets, cropped length ending above the ankle.
- **View / composition:** Flat-lay top-down, cropped length clearly visible.
- **Background / lighting:** Light-grey background; soft even lighting.
- **Consistency attributes:** Clear ankle-length crop (shorter than full-length); slim-straight (not flared, not wide); side (not slant) pockets; no belt loops; concealed hook-and-bar waistband.
- **Prompt:** "Flat-lay studio photograph of women's black cropped ankle pants in polyester-viscose; mid-rise, slim-straight leg, side pockets at hip, concealed hook-and-bar waistband, length ending just above the ankle; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic smooth-weave fabric texture."

### 4.4 SS26 — Jeans

#### UQ-SS26-JN-001 — Slim Fit Light Wash Jeans
- **Filename:** `UQ-SS26-JN-001.png`
- **Garment color:** BLU (Light wash blue denim).
- **Garment type / silhouette:** Men's slim-fit jeans in cotton-elastane denim, mid-rise, light stone wash, five-pocket construction, button fly, belt loops.
- **View / composition:** Flat-lay top-down, waistband at top, five-pocket front visible.
- **Background / lighting:** Light-grey background; soft lighting that preserves wash contrast.
- **Consistency attributes:** Light stone wash (not raw, not dark); classic five-pocket construction; metal rivets tonal; no distressing; no embroidery on the back pocket.
- **Prompt:** "Flat-lay studio photograph of men's slim-fit cotton-elastane jeans in a light stone wash; mid-rise, five-pocket construction, button fly, belt loops, plain back pockets without embroidery, tonal metal rivets; no logos, no leather patch, no prints; soft diffuse studio light on light-grey seamless background; realistic denim weave texture."

#### UQ-SS26-JN-002 — High-Rise Straight Jeans
- **Filename:** `UQ-SS26-JN-002.png`
- **Garment color:** BLU (Mid-wash blue denim).
- **Garment type / silhouette:** Women's high-rise straight-leg jeans in cotton-elastane denim. Mid-wash, button fly, five-pocket construction, longer rise visible at the waistband.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** High-rise clearly visible (longer waistband-to-crotch); mid blue wash; straight leg (not slim, not flared); no distressing; plain back pockets.
- **Prompt:** "Flat-lay studio photograph of women's high-rise straight-leg cotton-elastane jeans in a mid blue wash; prominent high-rise waistband, button fly, five-pocket construction, straight leg, plain back pockets without embroidery, tonal metal rivets; no logos, no leather patch; soft diffuse studio light on light-grey seamless background; realistic denim weave texture."

### 4.5 SS26 — Dresses & Skirts

#### UQ-SS26-DR-001 — Linen Shift Dress
- **Filename:** `UQ-SS26-DR-001.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Women's knee-length shift dress in linen-viscose. Round neckline, cap sleeves, straight shift silhouette, side slit pockets.
- **View / composition:** Flat-lay top-down, shoulders at top, hem at knee.
- **Background / lighting:** Light-grey background; soft lighting; slight natural linen creasing permitted.
- **Consistency attributes:** Cap sleeves (short, over the shoulder, not sleeveless); round neckline; straight shift (not fit-and-flare); side slit pockets visible along the hip seam.
- **Prompt:** "Flat-lay studio photograph of a beige women's knee-length linen-viscose shift dress; round neckline, cap sleeves, straight shift silhouette, slit side pockets along the hip seam; slight natural linen creasing; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic linen-viscose texture."

#### UQ-SS26-DR-002 — Jersey Flare Dress
- **Filename:** `UQ-SS26-DR-002.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's A-line jersey dress with gathered waist. V-neckline, three-quarter sleeves, knee-length hem, smooth stretch jersey.
- **View / composition:** Flat-lay top-down, shoulders at top, A-line hem flared gently at the bottom.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Gathered waist seam visible across the body; V-neckline; three-quarter sleeve length; soft jersey drape (not stiff).
- **Prompt:** "Flat-lay studio photograph of a black women's A-line jersey dress; V-neckline, three-quarter sleeves, gathered waist seam, knee-length A-line hem; soft stretch jersey drape; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic jersey knit texture."

#### UQ-SS26-DR-003 — Pleated Midi Skirt
- **Filename:** `UQ-SS26-DR-003.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's midi skirt in satin-finish polyester with knife pleats and an elasticated waistband with grosgrain tape.
- **View / composition:** Flat-lay top-down, waistband at top, knife pleats visible along full length to the hem.
- **Background / lighting:** Light-grey background; soft lighting with controlled highlight to reveal satin sheen without blow-out.
- **Consistency attributes:** Fine knife pleats evenly spaced; subtle satin sheen; grosgrain tape visible at the inside waistband; midi length (mid-calf).
- **Prompt:** "Flat-lay studio photograph of a black women's midi skirt in satin-finish polyester with fine knife pleats running from waist to hem; elasticated waistband with grosgrain tape just visible on the inside; midi mid-calf length; subtle satin sheen without glare; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

### 4.6 SS26 — Knitwear

#### UQ-SS26-KN-001 — Lightweight Cotton Cardigan
- **Filename:** `UQ-SS26-KN-001.png`
- **Garment color:** OFW (Off-White).
- **Garment type / silhouette:** Women's open-front cardigan in 100% cotton knit. V-neckline, three-quarter sleeves, raw hem (no ribbing).
- **View / composition:** Flat-lay top-down, cardigan open (no buttons), shoulder seams visible.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** No buttons on the open front; V-opening; raw cut hem (not ribbed); three-quarter sleeves; fine cotton knit texture.
- **Prompt:** "Flat-lay studio photograph of a women's off-white open-front cotton cardigan in fine knit; no buttons, open V-neckline, three-quarter sleeves, raw cut hem without ribbing; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic fine cotton knit texture."

#### UQ-SS26-KN-002 — Linen Blend V-Neck Sweater
- **Filename:** `UQ-SS26-KN-002.png`
- **Garment color:** OFW (Off-White).
- **Garment type / silhouette:** Men's fine-knit summer sweater in linen-cotton blend. V-neckline, ribbed cuffs and hem, long sleeves.
- **View / composition:** Flat-lay top-down, V-neck centered.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** V-neck; ribbed cuffs and hem (tight ribbing contrasting with the smoother body knit); fine lightweight knit (summer weight, not chunky).
- **Prompt:** "Flat-lay studio photograph of a men's off-white fine-knit V-neck summer sweater in linen-cotton blend; long sleeves with ribbed cuffs, ribbed hem, light airy knit; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic linen-cotton knit texture."

### 4.7 SS26 — Lightweight Jackets

#### UQ-SS26-LJ-001 — Pocketable Windbreaker
- **Filename:** `UQ-SS26-LJ-001.png`
- **Garment color:** NVY (Navy).
- **Garment type / silhouette:** Unisex ultra-light windbreaker in 100% nylon with DWR coating. Hood, elastic cuffs and hem, full-length front zip, two side pockets.
- **View / composition:** Flat-lay top-down, jacket zipped, hood laid flat behind the collar.
- **Background / lighting:** Light-grey background; soft lighting with slight sheen highlight on technical nylon.
- **Consistency attributes:** Lightweight paper-thin look of ripstop nylon; subtle sheen; elastic cuffs; small drawstring at hem (allowed, no logo); hood laid flat.
- **Prompt:** "Flat-lay studio photograph of a navy ultra-light unisex nylon windbreaker; full-length front zip, hood laid flat behind the collar, elastic cuffs, drawstring hem, two side zip pockets; paper-thin ripstop nylon with subtle sheen; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

#### UQ-SS26-LJ-002 — Spring Blouson
- **Filename:** `UQ-SS26-LJ-002.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Men's casual blouson in cotton-polyester twill. Stand collar, ribbed cuffs and hem, full-length front zip, two front slit pockets.
- **View / composition:** Flat-lay top-down, zipped, hem ribbing clearly visible at the bottom.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Blouson shape (gathered at hem via ribbing); ribbed cuffs and hem clearly visible; stand collar (no hood); no padding.
- **Prompt:** "Flat-lay studio photograph of a men's beige cotton-polyester blouson jacket; stand collar, full-length front zip, ribbed cuffs and hem gathering the shape, two front slit pockets, no padding, no hood; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic twill texture."

#### UQ-SS26-LJ-003 — Trench Shell Jacket
- **Filename:** `UQ-SS26-LJ-003.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Women's lightweight trench in 100% polyester. Double-breasted front with buttons, notched lapel collar, adjustable belt at the waist, storm flap at shoulder.
- **View / composition:** 3/4 front on an invisible ghost mannequin to preserve the drape of a long garment.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Classic trench features (notched lapel, storm flap, adjustable belt tied naturally at the waist, double-breasted buttons); knee-length; no hood; no fur; lightweight shell appearance (not padded).
- **Prompt:** "Three-quarter front studio photograph of a women's beige lightweight polyester trench coat on an invisible ghost mannequin; double-breasted button front, notched lapel collar, storm flap at the shoulder, adjustable fabric belt tied naturally at the waist, knee-length, no hood; lightweight unpadded shell; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

### 4.8 SS26 — Accessories

#### UQ-SS26-AC-001 — Wide-Brim Straw Hat
- **Filename:** `UQ-SS26-AC-001.png`
- **Garment color:** BEI (Beige, natural straw tone).
- **Garment type / silhouette:** Women's packable wide-brim straw hat with a plain inner band.
- **View / composition:** 3/4 front isolated on background, slight brim tilt visible.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Natural straw weave; plain inner band; no ribbon trim, no decorative pin, no logo.
- **Prompt:** "Three-quarter studio photograph of a women's natural beige straw wide-brim hat; plain woven straw crown and brim, plain inner band, no ribbon, no decoration; isolated on a light-grey seamless background; soft diffuse studio lighting; realistic straw weave texture."

#### UQ-SS26-AC-002 — Cotton Baseball Cap
- **Filename:** `UQ-SS26-AC-002.png`
- **Garment color:** NVY (Navy).
- **Garment type / silhouette:** Unisex six-panel cotton baseball cap with pre-curved brim and adjustable rear strap.
- **View / composition:** 3/4 front isolated.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Six panels; small eyelets on each panel; adjustable rear strap; no logo, no front embroidery, no printed graphics.
- **Prompt:** "Three-quarter studio photograph of a navy unisex six-panel cotton baseball cap; small tonal eyelets on each panel, pre-curved brim, adjustable rear strap with tonal buckle; no logos, no embroidery, no prints; isolated on a light-grey seamless background; soft diffuse studio lighting; realistic cotton twill texture."

#### UQ-SS26-AC-003 — Lightweight Scarf
- **Filename:** `UQ-SS26-AC-003.png`
- **Garment color:** PNK (Pink).
- **Garment type / silhouette:** Women's lightweight viscose scarf, 170 × 50 cm, folded in a loose rectangle to show the drape.
- **View / composition:** Flat-lay top-down, folded.
- **Background / lighting:** Light-grey background; soft lighting that preserves fabric translucency.
- **Consistency attributes:** Lightweight airy appearance; soft solid pink; no pattern; no fringe.
- **Prompt:** "Flat-lay studio photograph of a soft pink women's lightweight viscose scarf folded loosely into a rectangle, slight edge drape visible; plain solid color, no pattern, no fringe, no logos; soft diffuse studio light on light-grey seamless background; realistic viscose fabric texture."

#### UQ-SS26-AC-004 — UV-Protection Sunglasses
- **Filename:** `UQ-SS26-AC-004.png`
- **Garment color:** BLK (Black acetate frame).
- **Garment type / silhouette:** Unisex sunglasses, black acetate frame, polycarbonate lens.
- **View / composition:** Flat-lay 3/4 angle with lenses visible and no scene reflections.
- **Background / lighting:** Light-grey background; soft lighting controlled to avoid glare on the lenses.
- **Consistency attributes:** Classic frame shape (rectangular or slight-rounded square); solid black acetate; dark lens; no visible brand on the temple; no logo etched into the lens.
- **Prompt:** "Flat-lay three-quarter studio photograph of a pair of unisex sunglasses with a solid black acetate frame and dark polycarbonate lenses; classic rectangular silhouette; no logos on the temples, no lens etching; lenses matte-dark without scene reflections; isolated on a light-grey seamless background; soft diffuse studio lighting."

---

### 4.9 AW26 — T-shirts & Tops

#### UQ-AW26-TS-010 — ThermaCore Crew Long Sleeve
- **Filename:** `UQ-AW26-TS-010.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Unisex long-sleeve base-layer tee in ThermaCore blend (rayon-acrylic-polyester-elastane). Crew neck, close athletic fit.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Smooth technical knit; close fit; no logos or technology labels.
- **Prompt:** "Flat-lay studio photograph of a black unisex long-sleeve crew-neck base-layer top in smooth technical knit; close athletic fit; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic technical knit texture."

#### UQ-AW26-TS-011 — Premium Cotton Mock Neck
- **Filename:** `UQ-AW26-TS-011.png`
- **Garment color:** OFW (Off-White).
- **Garment type / silhouette:** Women's long-sleeve mock-neck top in cotton-elastane. Fitted silhouette, short mock-neck collar.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Mock neck (short standing collar, no fold); fitted (not boxy); smooth cotton-elastane jersey.
- **Prompt:** "Flat-lay studio photograph of an off-white women's long-sleeve mock-neck top in cotton-elastane; short standing mock neck, fitted silhouette; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic smooth jersey texture."

#### UQ-AW26-TS-012 — Flannel Pocket Tee
- **Filename:** `UQ-AW26-TS-012.png`
- **Garment color:** NVY (Navy).
- **Garment type / silhouette:** Men's heavier short-sleeve cotton tee with brushed finish. Chest pocket, relaxed fit.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Heavier gauge fabric visible; soft brushed cotton texture; left chest pocket plain; relaxed (not slim) fit.
- **Prompt:** "Flat-lay studio photograph of a navy men's short-sleeve brushed-cotton heavier-weight T-shirt with a plain left chest pocket; relaxed fit, round neckline, straight hem; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic brushed cotton texture."

### 4.10 AW26 — Shirts & Blouses

#### UQ-AW26-SH-010 — Flannel Checked Shirt
- **Filename:** `UQ-AW26-SH-010.png`
- **Garment color:** BRG check (Burgundy and off-white check).
- **Garment type / silhouette:** Men's long-sleeve brushed-cotton flannel shirt. Button-down collar, chest pocket, straight hem.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Woven check pattern of burgundy and off-white (not printed on top); brushed cotton surface; button-down collar; tonal buttons.
- **Prompt:** "Flat-lay studio photograph of a men's burgundy-and-off-white woven-check flannel shirt in brushed cotton; button-down collar, left chest pocket, straight hem, tonal buttons; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic brushed flannel weave with woven check pattern."

#### UQ-AW26-SH-011 — Corduroy Shirt
- **Filename:** `UQ-AW26-SH-011.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Unisex long-sleeve fine-wale corduroy shirt. Spread collar, two chest pockets, straight hem.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting that reveals the vertical wale.
- **Consistency attributes:** Fine vertical wale clearly visible; two symmetrical chest pockets; tonal buttons; no shoulder yoke decoration.
- **Prompt:** "Flat-lay studio photograph of a beige unisex long-sleeve fine-wale corduroy shirt; spread collar, two symmetrical chest pockets, straight hem, tonal buttons; clear vertical corduroy wale; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic corduroy texture."

#### UQ-AW26-SH-012 — Satin Blouse
- **Filename:** `UQ-AW26-SH-012.png`
- **Garment color:** OFW (Off-White).
- **Garment type / silhouette:** Women's long-sleeve satin blouse with concealed placket and buttoned cuffs. Fluid drape, soft sheen.
- **View / composition:** Flat-lay top-down with soft draping along the hem.
- **Background / lighting:** Light-grey background; soft, well-controlled lighting to show sheen without blowing out.
- **Consistency attributes:** Satin sheen; concealed front placket; small tonal buttoned cuffs; no decorative buttons on the front; no lace.
- **Prompt:** "Flat-lay studio photograph of an off-white women's long-sleeve satin blouse; concealed front placket (no front buttons visible), small tonal buttoned cuffs, soft fluid drape with controlled satin sheen; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

### 4.11 AW26 — Trousers & Shorts

#### UQ-AW26-TR-010 — Winter Chinos
- **Filename:** `UQ-AW26-TR-010.png`
- **Garment color:** CHA (Charcoal).
- **Garment type / silhouette:** Men's cotton chinos with brushed inner. Straight leg, slant front pockets, belt loops, flat-front waistband.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Charcoal grey, matte finish; subtle warmth suggested by slightly thicker fabric appearance; slant front pockets; tonal buttons; no cargo pockets.
- **Prompt:** "Flat-lay studio photograph of men's charcoal cotton chinos with a straight leg, slant front pockets, flat-front waistband with belt loops, tonal buttons; slightly thicker warm fabric appearance; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic cotton chino texture."

#### UQ-AW26-TR-011 — Corduroy Trousers
- **Filename:** `UQ-AW26-TR-011.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Women's wide-wale corduroy trousers. High rise, straight leg, side pockets.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting that reveals the wale.
- **Consistency attributes:** Pronounced wide corduroy wale running vertically; high-rise waistband visible; straight leg (not flared, not slim-tapered).
- **Prompt:** "Flat-lay studio photograph of women's beige wide-wale corduroy trousers; high-rise waistband, straight leg, side pockets at hip; pronounced vertical corduroy wale; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic wide-wale corduroy texture."

#### UQ-AW26-TR-012 — Wool Blend Dress Pants
- **Filename:** `UQ-AW26-TR-012.png`
- **Garment color:** CHA (Charcoal).
- **Garment type / silhouette:** Men's tailored wool-blend dress trousers. Flat front, straight leg with a hemmed cuff.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting with controlled highlight to show wool twill without glare.
- **Consistency attributes:** Flat front (no pleats); hemmed cuff at the bottom; wool twill texture; tailored smooth finish; no visible lining.
- **Prompt:** "Flat-lay studio photograph of men's charcoal wool-blend tailored dress trousers; flat front, straight leg with a visible hemmed cuff, side pockets; smooth wool twill finish; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic wool twill texture."

### 4.12 AW26 — Jeans

#### UQ-AW26-JN-010 — ThermaCore Lined Jeans
- **Filename:** `UQ-AW26-JN-010.png`
- **Garment color:** BLU (Dark wash blue denim).
- **Garment type / silhouette:** Men's dark-wash jeans with ThermaCore thermal lining through hip and thigh. Five-pocket construction, button fly, straight leg.
- **View / composition:** Flat-lay top-down with the waistband folded slightly to reveal the pale technical lining at the inside.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Dark wash; smooth off-white or light-grey technical lining visible only through the folded waistband; no distressing; plain back pockets.
- **Prompt:** "Flat-lay studio photograph of men's dark-wash cotton-blend jeans with a folded waistband revealing a smooth light-grey technical thermal lining inside; five-pocket construction, button fly, straight leg, plain back pockets, tonal rivets; no logos, no leather patch; soft diffuse studio light on light-grey seamless background; realistic denim weave texture."

#### UQ-AW26-JN-011 — Stretch Slim Jeans
- **Filename:** `UQ-AW26-JN-011.png`
- **Garment color:** BLU (Dark wash blue denim).
- **Garment type / silhouette:** Women's slim-fit jeans in cotton-polyester-elastane stretch denim. Mid-rise, five-pocket construction, button fly.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Dark wash; slim leg (not skinny, not straight); plain back pockets; subtle stretch visible in the slight relaxed drape of the fabric.
- **Prompt:** "Flat-lay studio photograph of women's dark-wash slim-fit stretch cotton-polyester-elastane jeans; mid-rise, five-pocket construction, button fly, slim leg, plain back pockets, tonal rivets; no logos, no leather patch; soft diffuse studio light on light-grey seamless background; realistic stretch denim texture."

### 4.13 AW26 — Dresses & Skirts

#### UQ-AW26-DR-010 — Jersey Knit Dress
- **Filename:** `UQ-AW26-DR-010.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's long-sleeve midi dress in viscose jersey. Soft drape, round neckline, slim through the body, side slit at the hem.
- **View / composition:** Flat-lay top-down with side slit at the hem visible.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Soft jersey drape (not stiff); round neckline (not V, not mock); long sleeves; single side slit along one leg of the midi hem.
- **Prompt:** "Flat-lay studio photograph of a black women's long-sleeve midi dress in viscose jersey; round neckline, slim through the body, soft drape, a single side slit at the midi hem; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic viscose jersey texture."

#### UQ-AW26-DR-011 — Corduroy A-Line Skirt
- **Filename:** `UQ-AW26-DR-011.png`
- **Garment color:** BEI (Beige).
- **Garment type / silhouette:** Women's knee-length A-line corduroy skirt. Button-front detail, side pockets.
- **View / composition:** Flat-lay top-down, waistband at top.
- **Background / lighting:** Light-grey background; soft lighting that reveals the wale.
- **Consistency attributes:** Front row of tonal buttons running from waist to hem; A-line (narrower at waist, wider at hem); medium-wale corduroy; two side pockets.
- **Prompt:** "Flat-lay studio photograph of a beige women's knee-length A-line corduroy skirt; a vertical row of tonal buttons running down the front from waist to hem, two side pockets, medium-wale corduroy; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic corduroy texture."

### 4.14 AW26 — Knitwear

#### UQ-AW26-KN-010 — Merino Blend Crewneck
- **Filename:** `UQ-AW26-KN-010.png`
- **Garment color:** NVY (Navy).
- **Garment type / silhouette:** Unisex fine-knit crewneck sweater in merino wool and nylon. Classic fit, long sleeves, ribbed cuffs, collar, and hem.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Fine, smooth knit (not chunky); ribbed trim on crew collar, cuffs, and hem; classic (not oversized) fit.
- **Prompt:** "Flat-lay studio photograph of a navy unisex fine-knit crewneck merino-blend sweater; long sleeves, ribbed crew collar, ribbed cuffs, ribbed hem, classic fit; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic fine merino knit texture."

#### UQ-AW26-KN-011 — Cashmere V-Neck Sweater
- **Filename:** `UQ-AW26-KN-011.png`
- **Garment color:** CHA (Charcoal).
- **Garment type / silhouette:** Men's 100% cashmere V-neck sweater. Classic fit, ribbed cuffs and hem, soft matte surface.
- **View / composition:** Flat-lay top-down, V-neck centered.
- **Background / lighting:** Light-grey background; soft lighting to show matte cashmere surface.
- **Consistency attributes:** Soft matte cashmere (no sheen); V-neck; ribbed cuffs and hem; classic fit; no visible pilling.
- **Prompt:** "Flat-lay studio photograph of a charcoal men's 100% cashmere V-neck sweater; long sleeves with ribbed cuffs, ribbed hem, classic fit; soft matte cashmere surface, no sheen; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic cashmere knit texture."

#### UQ-AW26-KN-012 — Chunky Cable Cardigan
- **Filename:** `UQ-AW26-KN-012.png`
- **Garment color:** OFW (Off-White).
- **Garment type / silhouette:** Women's oversized cable-knit cardigan in wool-nylon blend. Button-front closure (five tonal buttons), ribbed cuffs and hem.
- **View / composition:** Flat-lay top-down, cardigan closed to show the cable pattern across the body.
- **Background / lighting:** Light-grey background; soft lighting to reveal the dimensional cable texture.
- **Consistency attributes:** Pronounced cable-knit pattern down the front panels; chunky gauge; oversized (not fitted); five tonal buttons.
- **Prompt:** "Flat-lay studio photograph of an off-white women's chunky cable-knit cardigan in wool-nylon blend; oversized relaxed fit, pronounced vertical cable pattern across the front panels, five tonal buttons, ribbed cuffs and hem; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic chunky cable-knit texture."

#### UQ-AW26-KN-013 — Fine Knit Turtleneck
- **Filename:** `UQ-AW26-KN-013.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's fine-knit turtleneck in wool-viscose. Slim fit, long sleeves, folded turtleneck collar.
- **View / composition:** Flat-lay top-down, turtleneck folded naturally.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Smooth fine knit (not ribbed body); turtleneck folded (not funnel-neck); slim fit designed to layer under coats.
- **Prompt:** "Flat-lay studio photograph of a black women's fine-knit slim-fit turtleneck sweater in wool-viscose; long sleeves, folded turtleneck collar, smooth knit body; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic fine knit texture."

### 4.15 AW26 — Lightweight Jackets

#### UQ-AW26-LJ-010 — Fleece Full-Zip Jacket
- **Filename:** `UQ-AW26-LJ-010.png`
- **Garment color:** NVY (Navy).
- **Garment type / silhouette:** Unisex mid-layer fleece in 100% polyester. Full-length front zip, stand collar, chest pocket, adjustable hem.
- **View / composition:** Flat-lay top-down, zipped.
- **Background / lighting:** Light-grey background; soft lighting that reveals fleece pile.
- **Consistency attributes:** Soft fleece pile texture visible; small zippered chest pocket; stand collar (no hood); drawstring at the hem allowed.
- **Prompt:** "Flat-lay studio photograph of a navy unisex full-zip polyester fleece jacket; stand collar, full-length front zip, small zippered chest pocket, elastic cuffs, drawstring hem, no hood; soft fleece pile texture; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

### 4.16 AW26 — Coats & Insulated Jackets

#### UQ-AW26-CJ-001 — Ultra Light Down Jacket
- **Filename:** `UQ-AW26-CJ-001.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Unisex packable down jacket in 100% nylon shell with 90/10 duck down fill. Horizontal baffle quilting, stand collar, full-length front zip, elastic cuffs.
- **View / composition:** 3/4 front on invisible ghost mannequin.
- **Background / lighting:** Light-grey background; soft lighting with slight sheen highlight on nylon.
- **Consistency attributes:** Thin lightweight down baffles (not thick puffer); stand collar (no hood); matte-to-subtle-sheen nylon; no fur trim; no logos.
- **Prompt:** "Three-quarter front studio photograph of a black unisex ultra-light down jacket on an invisible ghost mannequin; thin horizontal baffle quilting, stand collar without a hood, full-length front zip, elastic cuffs, two side zip pockets; lightweight packable appearance; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic lightweight nylon texture."

#### UQ-AW26-CJ-002 — Seamless Down Parka
- **Filename:** `UQ-AW26-CJ-002.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's seam-welded hooded down parka. 100% polyester shell, 90/10 duck down fill. Hood, full-length front zip with storm placket, hip length, two side pockets.
- **View / composition:** 3/4 front on invisible ghost mannequin, hood resting against the collar.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Smooth shell with welded seams rather than visible stitched quilt lines; hood attached (not detachable fur-trim style); hip length; matte finish.
- **Prompt:** "Three-quarter front studio photograph of a black women's hooded down parka on an invisible ghost mannequin; smooth seam-welded polyester shell with no visible stitched quilt lines, attached hood resting on the collar, full-length front zip with a storm placket, two side pockets, hip length; no fur trim, no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic matte polyester shell texture."

#### UQ-AW26-CJ-003 — Hybrid Down Puffer
- **Filename:** `UQ-AW26-CJ-003.png`
- **Garment color:** NVY (Navy).
- **Garment type / silhouette:** Men's puffer with duck down baffles on the front and back, and smooth ThermaCore stretch side panels at the ribs and underarms. Stand collar, full-length front zip, hip length.
- **View / composition:** 3/4 front on invisible ghost mannequin to show both the quilted front and the smooth side panel.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Clear visual contrast between the horizontal down baffles on the front and the smooth stretch panels down the sides and under the arms; stand collar (no hood); hip length.
- **Prompt:** "Three-quarter front studio photograph of a navy men's hybrid down puffer jacket on an invisible ghost mannequin; horizontal quilted down baffles across the front and back, smooth matte stretch side panels under the arms and down the ribs, stand collar without a hood, full-length front zip, two side pockets, hip length; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

#### UQ-AW26-CJ-004 — Wool Blend Chesterfield Coat
- **Filename:** `UQ-AW26-CJ-004.png`
- **Garment color:** CHA (Charcoal).
- **Garment type / silhouette:** Men's tailored wool-blend chesterfield coat. Notched lapel, single-breasted (three tonal buttons), knee-length, two welt pockets, no belt.
- **View / composition:** 3/4 front on invisible ghost mannequin, coat buttoned.
- **Background / lighting:** Light-grey background; soft lighting with controlled highlight to show wool texture without glare.
- **Consistency attributes:** Tailored lapels sharply pressed; three-button single-breasted front; welt pockets (no flap); knee-length; no belt; no fur; no visible lining.
- **Prompt:** "Three-quarter front studio photograph of a charcoal men's tailored wool-blend chesterfield coat on an invisible ghost mannequin; notched lapels, single-breasted front with three tonal buttons, two welt pockets, knee-length, no belt; smooth wool twill with a subtle matte finish; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

#### UQ-AW26-CJ-005 — Wool Blend Wrap Coat
- **Filename:** `UQ-AW26-CJ-005.png`
- **Garment color:** CHA (Charcoal).
- **Garment type / silhouette:** Women's belted wrap coat in wool-polyester blend. Notched lapel, long length (below the knee), fabric belt tied at the waist, no visible buttons.
- **View / composition:** 3/4 front on invisible ghost mannequin, belt tied naturally at the waist.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Wrap front secured only by the fabric belt (no visible buttons on the front); notched lapel; long below-the-knee length; no fur; two welt side pockets.
- **Prompt:** "Three-quarter front studio photograph of a charcoal women's wool-blend wrap coat on an invisible ghost mannequin; notched lapel, no front buttons, a self-fabric belt tied naturally at the waist to close the wrap front, two welt side pockets, long below-the-knee length; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic wool-blend texture."

### 4.17 AW26 — Thermal Base Layers

#### UQ-AW26-TH-001 — ThermaCore Crew Top
- **Filename:** `UQ-AW26-TH-001.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Unisex long-sleeve base-layer top in ThermaCore standard blend. Crew neck, close fit.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Smooth technical knit; close fit; no logos; subtle brushed inside implied by soft matte appearance.
- **Prompt:** "Flat-lay studio photograph of a black unisex long-sleeve crew-neck thermal base-layer top in smooth technical knit; close athletic fit, matte finish; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic thermal technical knit texture."

#### UQ-AW26-TH-002 — ThermaCore Extra Warm Top
- **Filename:** `UQ-AW26-TH-002.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Unisex long-sleeve base-layer top with higher acrylic ratio for extra warmth. Crew neck, close fit, slightly thicker surface than TH-001.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Slightly thicker, warmer-looking knit than TH-001; same close silhouette; no logos.
- **Prompt:** "Flat-lay studio photograph of a black unisex long-sleeve crew-neck extra-warm thermal base-layer top; close athletic fit, visibly thicker and warmer technical knit than a standard base layer, matte finish; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background."

#### UQ-AW26-TH-003 — ThermaCore Leggings
- **Filename:** `UQ-AW26-TH-003.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's base-layer leggings in ThermaCore standard blend. Elastic waistband, ankle length, close athletic fit.
- **View / composition:** Flat-lay top-down, waistband at top, legs straight.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Smooth technical knit; close fit; plain elastic waistband (no visible branding or stripe).
- **Prompt:** "Flat-lay studio photograph of black women's thermal base-layer leggings in smooth technical knit; plain elastic waistband, ankle length, close athletic fit; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic thermal knit texture."

#### UQ-AW26-TH-004 — ThermaCore Tights Thermal
- **Filename:** `UQ-AW26-TH-004.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Men's base-layer tights in ThermaCore standard blend. Elastic waistband, ankle length, close athletic fit.
- **View / composition:** Flat-lay top-down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Visually similar to TH-003 but cut for men's proportions (slightly longer rise, different silhouette); plain waistband; no fly opening visible.
- **Prompt:** "Flat-lay studio photograph of black men's thermal base-layer tights in smooth technical knit; plain elastic waistband, ankle length, close athletic men's fit; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic thermal knit texture."

### 4.18 AW26 — Accessories

#### UQ-AW26-AC-010 — Wool Blend Knit Beanie
- **Filename:** `UQ-AW26-AC-010.png`
- **Garment color:** NVY (Navy).
- **Garment type / silhouette:** Unisex ribbed knit beanie in wool-acrylic blend. Classic ribbed cuff, snug fit.
- **View / composition:** 3/4 isolated, cap positioned upright, no face.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Clear vertical ribbing; folded cuff; no pom-pom; no logo patch, no embroidery.
- **Prompt:** "Three-quarter studio photograph of a navy unisex ribbed knit beanie in wool-acrylic blend; vertical rib texture, folded cuff, snug fit, no pom-pom; no logos, no prints, no labels, no face; isolated on a light-grey seamless background; soft diffuse studio lighting; realistic wool-blend knit texture."

#### UQ-AW26-AC-011 — ThermaCore-Lined Gloves
- **Filename:** `UQ-AW26-AC-011.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Unisex gloves with smooth matte polyester shell and ThermaCore lining. Elastic cuff, five-finger construction.
- **View / composition:** Flat-lay side by side, palms down.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Matching pair; smooth matte shell; elastic cuff; natural finger relaxation; no touchscreen fingertip graphic visible as a logo; no decoration.
- **Prompt:** "Flat-lay studio photograph of a pair of black unisex gloves with a smooth matte polyester shell and a soft thermal lining, placed side by side with palms down and relaxed fingers, elastic cuff; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic matte polyester texture."

#### UQ-AW26-AC-012 — Cashmere Blend Scarf
- **Filename:** `UQ-AW26-AC-012.png`
- **Garment color:** BRG (Burgundy).
- **Garment type / silhouette:** Unisex woven scarf in wool-cashmere blend, 180 × 30 cm, folded loosely into a rectangle. Short fringed ends.
- **View / composition:** Flat-lay top-down, folded with short fringed ends visible.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Solid burgundy; soft brushed wool-cashmere surface; short fringe ends (typical woven scarf finish); no stripe, no check, no pattern.
- **Prompt:** "Flat-lay studio photograph of a solid burgundy unisex woven wool-cashmere scarf folded loosely into a rectangle, short fringed ends visible, soft brushed surface, no pattern; no logos, no prints, no labels; soft diffuse studio light on light-grey seamless background; realistic brushed wool-cashmere texture."

#### UQ-AW26-AC-013 — Fleece-Lined Earmuffs
- **Filename:** `UQ-AW26-AC-013.png`
- **Garment color:** BLK (Black).
- **Garment type / silhouette:** Women's adjustable earmuffs with fleece-lined earpieces and a soft fabric headband.
- **View / composition:** 3/4 isolated.
- **Background / lighting:** Light-grey background; soft lighting.
- **Consistency attributes:** Fleece-lined inner side of the earpieces visible from the angle; smooth matte fabric headband; no logos; no decorative patches.
- **Prompt:** "Three-quarter studio photograph of a pair of black women's fleece-lined earmuffs with soft matte fabric earpieces, visible fleece lining on the inner side of each earpiece, and an adjustable soft fabric headband; no logos, no prints, no labels; isolated on a light-grey seamless background; soft diffuse studio lighting."

---

## 5. Editorial Outfit Image Manifest

**Filename convention:** `{SEASON}-ED-{SEQ}.png` (e.g., `SS26-ED-01.png`). Each scenario maps 1:1 to a style-guide outfit scenario.

Editorial images are **not** product-only shots and may include multiple canonical products in a single frame. They must preserve the exact garment color listed per SKU. Faces, if a figure is used, must be turned, cropped, or softly out of focus. No real-person likenesses.

### 5.1 SS26 Editorial

#### SS26-ED-01 — "Weekday Hybrid" (men, CP-02 Tomáš)
- **Filename:** `SS26-ED-01.png`
- **Source scenario:** `UQ-SS26-STG-v1.0.md` §4.1.
- **Products shown and required colors:**
  - UQ-SS26-TS-001 Basic Cotton Crew Tee — NVY
  - UQ-SS26-SH-001 Oxford Short Sleeve Shirt — BLU (worn open as a layer over the tee)
  - UQ-SS26-TR-002 Linen Blend Trousers — BEI
  - UQ-SS26-AC-002 Cotton Baseball Cap — NVY
- **Garment types / silhouettes:** Short-sleeve crew-neck tee under an open short-sleeve Oxford shirt; relaxed tapered linen trousers; six-panel baseball cap.
- **View / composition:** Three-quarter full-body on a male figure, face cropped above the mouth or turned away; standing in a neutral workspace-adjacent setting (plain pale wall with a minimalist chair just suggested in the background).
- **Background / lighting:** Soft daylight-feel studio light, pale neutral background; no clutter.
- **Attributes to preserve:** Oxford shirt layered open (not buttoned); trousers show visible drawcord at waist; baseball cap plain (no logo).
- **Prompt:** "Editorial retail photograph of a male figure in a neutral indoor setting; wearing a navy short-sleeve crew-neck cotton T-shirt under an open light-blue short-sleeve Oxford shirt, beige linen-cotton drawstring trousers with a visible fabric drawcord, and a plain navy six-panel baseball cap with no logo; face cropped at the mouth or turned away; three-quarter full-body framing; soft daylight-feel studio lighting on a pale neutral background; realistic fabric textures; no visible logos, no text, no watermarks."

#### SS26-ED-02 — "Market Saturday" (women, CP-01 Markéta)
- **Filename:** `SS26-ED-02.png`
- **Source scenario:** `UQ-SS26-STG-v1.0.md` §4.2.
- **Products shown and required colors:**
  - UQ-SS26-TS-003 Breeze Linen Tank — PNK
  - UQ-SS26-TR-003 Pleated Wide Shorts — BEI
  - UQ-SS26-AC-001 Wide-Brim Straw Hat — OFW
  - UQ-SS26-AC-004 UV-Protection Sunglasses — BLK
- **Garment types / silhouettes:** Sleeveless linen tank, high-waisted pleated wide shorts, wide-brim straw hat, black sunglasses.
- **View / composition:** Three-quarter full-body on a female figure, face hidden by hat brim or turned away; outdoor-adjacent plain studio setting.
- **Background / lighting:** Softly diffused "sunny" light, pale neutral background; no sky, no scene reflections in sunglasses.
- **Attributes to preserve:** Hat natural straw, no ribbon; sunglasses frame and lenses solid black with no logos.
- **Prompt:** "Editorial retail photograph of a female figure in a bright but softly diffused neutral studio setting; wearing a pink linen-viscose sleeveless tank with a scooped neckline, high-waisted beige pleated wide shorts in cotton, a natural straw wide-brim hat with a plain inner band, and black sunglasses with a plain acetate frame; face shaded by the hat brim or turned away; three-quarter full-body framing; soft bright studio lighting on a pale neutral background; no sky, no reflections in the sunglasses, no logos, no text, no watermarks."

#### SS26-ED-03 — "Office + Dinner Pivot" (women, CP-01 Markéta)
- **Filename:** `SS26-ED-03.png`
- **Source scenario:** `UQ-SS26-STG-v1.0.md` §4.3.
- **Products shown and required colors:**
  - UQ-SS26-DR-002 Jersey Flare Dress — BLK
  - UQ-SS26-KN-001 Lightweight Cotton Cardigan — OFW
  - UQ-SS26-LJ-003 Trench Shell Jacket — BEI (worn open, draped on shoulder, or held)
- **Garment types / silhouettes:** Knee-length black jersey A-line dress, off-white open-front cardigan over the shoulders, beige trench open over both.
- **View / composition:** Full-body on a female figure, face cropped or turned away, poised neutral stance.
- **Background / lighting:** Pale neutral studio background; soft, slightly warmer evening-feel diffuse light.
- **Attributes to preserve:** Dress gathered waist and V-neck visible under the cardigan; trench shows notched lapel and tied belt or open front.
- **Prompt:** "Editorial retail photograph of a female figure in a neutral studio setting with a slightly warm evening tone; wearing a black women's V-neck jersey A-line dress with a gathered waist and three-quarter sleeves (knee length), an off-white open-front fine-knit cotton cardigan over the shoulders, and a beige lightweight polyester trench coat worn open with a notched lapel and self-fabric belt; face cropped above the mouth or turned away; full-body framing; soft diffused studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### SS26-ED-04 — "Weekend Hike" (men, CP-02 Tomáš)
- **Filename:** `SS26-ED-04.png`
- **Source scenario:** `UQ-SS26-STG-v1.0.md` §4.4.
- **Products shown and required colors:**
  - UQ-SS26-TS-005 UV-Shield Long Sleeve — GRY
  - UQ-SS26-TR-001 Chino Shorts 7" — OLI
  - UQ-SS26-LJ-001 Pocketable Windbreaker — OLI
  - UQ-SS26-AC-002 Cotton Baseball Cap — BLK
- **Garment types / silhouettes:** Grey technical long-sleeve top, olive cotton chino shorts, olive packable windbreaker worn open or carried, black baseball cap.
- **View / composition:** Three-quarter full-body on a male figure, face cropped or turned; neutral studio setting with a suggestion of outdoor light but no landscape.
- **Background / lighting:** Soft diffuse neutral studio light; pale neutral background.
- **Attributes to preserve:** Thumbholes visible at long-sleeve cuff; windbreaker shows paper-thin ripstop appearance; chino shorts clearly 7-inch inseam.
- **Prompt:** "Editorial retail photograph of a male figure in a neutral studio setting with a soft daylight-feel tone; wearing a grey unisex long-sleeve technical top in nylon-elastane with small thumbhole openings at the cuffs, olive cotton 7-inch chino shorts with slant pockets, an olive ultra-light nylon windbreaker worn open with the hood down, and a plain black cotton baseball cap; face turned away or cropped; three-quarter full-body framing; soft diffused studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### SS26-ED-05 — "Student Budget Everyday" (men, CP-04 David)
- **Filename:** `SS26-ED-05.png`
- **Source scenario:** `UQ-SS26-STG-v1.0.md` §4.5.
- **Products shown and required colors:**
  - UQ-SS26-TS-004 Striped Pocket Tee — NVY/WHT
  - UQ-SS26-TR-001 Chino Shorts 7" — BEI
  - UQ-SS26-AC-002 Cotton Baseball Cap — WHT
- **Garment types / silhouettes:** Breton-style striped T-shirt with contrasting navy chest pocket, beige 7-inch cotton chino shorts, plain white baseball cap.
- **View / composition:** Three-quarter full-body on a young male figure, face cropped at the brow line or turned away.
- **Background / lighting:** Pale neutral studio background; soft, slightly bright casual light.
- **Attributes to preserve:** Stripe pattern even and continuous; chest pocket solid navy; cap plain white with no logo.
- **Prompt:** "Editorial retail photograph of a young male figure in a neutral studio setting with casual bright soft lighting; wearing a navy-and-white horizontally striped short-sleeve cotton T-shirt with a solid-navy chest pocket, beige cotton 7-inch chino shorts with slant pockets, and a plain white six-panel cotton baseball cap; face turned away or cropped; three-quarter full-body framing; soft studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### SS26-ED-06 — "Teacher's Spring" (women, CP-05 Eva)
- **Filename:** `SS26-ED-06.png`
- **Source scenario:** `UQ-SS26-STG-v1.0.md` §4.6.
- **Products shown and required colors:**
  - UQ-SS26-SH-004 Cotton Shirtdress Shirt — BLU
  - UQ-SS26-TR-004 Ankle Pants — BLK
  - UQ-SS26-AC-003 Lightweight Scarf — OFW
- **Garment types / silhouettes:** Elongated light-blue cotton shirt worn over black cropped ankle pants, with a soft off-white viscose scarf loosely wrapped around the neck.
- **View / composition:** Three-quarter full-body on a female figure, face cropped at the mouth or turned away.
- **Background / lighting:** Pale neutral studio background; soft diffuse light.
- **Attributes to preserve:** Shirt elongated past the hip with side slits visible; ankle pants crop clearly above the ankle; scarf solid off-white, no pattern.
- **Prompt:** "Editorial retail photograph of a female figure in a neutral studio setting; wearing an elongated light-blue cotton shirtdress-length shirt with a point collar and visible side slits at the hem, worn over black cropped ankle pants in polyester-viscose with length ending above the ankle, and a soft solid off-white lightweight viscose scarf wrapped loosely around the neck; face turned away or cropped; three-quarter full-body framing; soft diffused studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

### 5.2 AW26 Editorial

#### AW26-ED-01 — "Office Winter Day" (women, CP-01 Markéta)
- **Filename:** `AW26-ED-01.png`
- **Source scenario:** `UQ-AW26-STG-v1.0.md` §5.1.
- **Products shown and required colors:**
  - UQ-AW26-TH-001 ThermaCore Crew Top — BLK (base layer, suggested as collar line only)
  - UQ-AW26-KN-013 Fine Knit Turtleneck — BLK
  - UQ-AW26-TR-011 Corduroy Trousers — BEI
  - UQ-AW26-CJ-005 Wool Blend Wrap Coat — CHA (worn open or tied)
  - UQ-AW26-AC-012 Cashmere Blend Scarf — BRG
- **Garment types / silhouettes:** Base layer at the neckline only, black fine-knit turtleneck, high-rise beige wide-wale corduroy trousers, charcoal wrap coat, burgundy scarf.
- **View / composition:** Three-quarter full-body on a female figure, face cropped or turned.
- **Background / lighting:** Pale neutral studio background; soft cool-neutral light that evokes a winter morning.
- **Attributes to preserve:** Wrap coat closed only by a self-fabric belt (no buttons); corduroy wale clearly visible on trousers; scarf solid burgundy with short fringe.
- **Prompt:** "Editorial retail photograph of a female figure in a neutral studio with cool-toned soft daylight; wearing a black fine-knit slim turtleneck sweater, beige high-rise wide-wale corduroy trousers with a straight leg, a charcoal wool-blend women's wrap coat closed only with a self-fabric belt at the waist (no front buttons, notched lapel, long below-the-knee length), and a solid burgundy wool-cashmere scarf with short fringe loosely wrapped at the neck; face turned away or cropped; three-quarter full-body framing; soft cool studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### AW26-ED-02 — "Weekend Trek, Krkonoše" (men, CP-02 Tomáš)
- **Filename:** `AW26-ED-02.png`
- **Source scenario:** `UQ-AW26-STG-v1.0.md` §5.2.
- **Products shown and required colors:**
  - UQ-AW26-TH-002 ThermaCore Extra Warm Top — GRY (base layer, implied under knit)
  - UQ-AW26-TH-004 ThermaCore Tights Thermal — BLK (base layer, implied under jeans)
  - UQ-AW26-KN-010 Merino Blend Crewneck — NVY
  - UQ-AW26-JN-010 ThermaCore Lined Jeans — BLU (dark wash)
  - UQ-AW26-CJ-003 Hybrid Down Puffer — OLI
  - UQ-AW26-AC-010 Wool Blend Knit Beanie — GRY
  - UQ-AW26-AC-011 ThermaCore-Lined Gloves — BLK
- **Garment types / silhouettes:** Olive hybrid down puffer over a navy fine-knit merino crewneck, dark-wash thermal-lined jeans, grey ribbed knit beanie, black gloves. Base layers implied (not visibly on-camera).
- **View / composition:** Full-body on a male figure, face cropped or turned; neutral studio setting with suggestion of a cold-weather mood but no landscape.
- **Background / lighting:** Pale neutral studio background; soft cool diffuse light.
- **Attributes to preserve:** Puffer shows horizontal down baffles on the front and smooth stretch panels on the sides; beanie plain ribbed with folded cuff; gloves matte black with elastic cuff.
- **Prompt:** "Editorial retail photograph of a male figure in a neutral studio setting with cool soft lighting evoking cold weather; wearing a navy fine-knit merino-blend crewneck sweater, dark-wash straight-leg jeans with a subtle thermal lining implied, an olive hybrid down puffer jacket with horizontal quilted down baffles on the front and smooth stretch side panels, a grey ribbed wool-blend knit beanie with folded cuff, and plain black insulated gloves; face turned away or cropped; full-body framing; soft diffuse studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### AW26-ED-03 — "Formal Dinner" (men, CP-02 Tomáš)
- **Filename:** `AW26-ED-03.png`
- **Source scenario:** `UQ-AW26-STG-v1.0.md` §5.3.
- **Products shown and required colors:**
  - UQ-AW26-KN-011 Cashmere V-Neck Sweater — NVY
  - UQ-AW26-TR-012 Wool Blend Dress Pants — CHA
  - UQ-AW26-CJ-004 Wool Blend Chesterfield Coat — CHA (worn open over the sweater)
  - UQ-AW26-AC-012 Cashmere Blend Scarf — CHA
- **Garment types / silhouettes:** Navy cashmere V-neck sweater over an implied shirt, charcoal wool-blend tailored trousers, charcoal chesterfield coat open, charcoal cashmere scarf.
- **View / composition:** Three-quarter full-body on a male figure, face cropped or turned.
- **Background / lighting:** Pale neutral studio background; soft, slightly warm evening-feel light.
- **Attributes to preserve:** Chesterfield single-breasted with notched lapels and three tonal buttons (visible on the coat even when open); dress pants with hemmed cuff; scarf solid charcoal, no stripe.
- **Prompt:** "Editorial retail photograph of a male figure in a neutral studio setting with a slightly warm evening tone; wearing a navy men's cashmere V-neck sweater, charcoal wool-blend tailored dress trousers with a flat front and a hemmed cuff, a charcoal men's tailored wool-blend chesterfield coat worn open with notched lapels and three tonal buttons visible on the front edge, and a solid charcoal wool-cashmere scarf with short fringe; face turned away or cropped; three-quarter full-body framing; soft diffused studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### AW26-ED-04 — "School Day" (women, CP-03 Lenka)
- **Filename:** `AW26-ED-04.png`
- **Source scenario:** `UQ-AW26-STG-v1.0.md` §5.4.
- **Products shown and required colors:**
  - UQ-AW26-TS-011 Premium Cotton Mock Neck — NVY
  - UQ-AW26-KN-012 Chunky Cable Cardigan — OFW
  - UQ-AW26-JN-011 Stretch Slim Jeans — BLK
  - UQ-AW26-CJ-002 Seamless Down Parka — BLK (worn open or draped)
  - UQ-AW26-AC-010 Wool Blend Knit Beanie — OFW
  - UQ-AW26-AC-013 Fleece-Lined Earmuffs — BLK (not worn simultaneously with the beanie; place as a held or background accessory to avoid visual conflict)
- **Garment types / silhouettes:** Navy mock-neck top under an off-white chunky cable cardigan, black stretch slim jeans, black seamless hooded down parka worn open, off-white ribbed beanie.
- **View / composition:** Three-quarter full-body on a female figure, face cropped or turned.
- **Background / lighting:** Pale neutral studio background; soft cool neutral light.
- **Attributes to preserve:** Cable cardigan shows pronounced vertical cable pattern on the front panels and tonal buttons; parka seam-welded shell with no visible stitched quilt lines, hood resting on the collar; earmuffs shown as a held accessory not on the head so the beanie remains the primary head accessory.
- **Prompt:** "Editorial retail photograph of a female figure in a neutral studio setting with cool soft lighting; wearing a navy long-sleeve mock-neck cotton top, an off-white chunky cable-knit wool-blend cardigan with tonal buttons buttoned over it, black stretch slim-fit jeans, an off-white ribbed wool-blend knit beanie, and a black women's seamless hooded down parka worn open with the hood resting on the collar; carrying a pair of black fleece-lined earmuffs in one hand (not worn on the head); face turned away or cropped; three-quarter full-body framing; soft diffused studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### AW26-ED-05 — "Student Commute" (men, CP-04 David)
- **Filename:** `AW26-ED-05.png`
- **Source scenario:** `UQ-AW26-STG-v1.0.md` §5.5.
- **Products shown and required colors:**
  - UQ-AW26-TH-001 ThermaCore Crew Top — BLK (base layer, implied)
  - UQ-AW26-TS-010 ThermaCore Crew Long Sleeve — GRY
  - UQ-AW26-SH-010 Flannel Checked Shirt — OLI check
  - UQ-AW26-JN-011 Stretch Slim Jeans — BLU (dark wash)
  - UQ-AW26-LJ-010 Fleece Full-Zip Jacket — NVY (worn open or carried)
  - UQ-AW26-AC-010 Wool Blend Knit Beanie — BLK
- **Garment types / silhouettes:** Grey long-sleeve ThermaCore crew under an open olive-check flannel, with a navy full-zip fleece worn open over both, dark-wash slim jeans, black ribbed beanie.
- **View / composition:** Three-quarter full-body on a young male figure, face cropped or turned.
- **Background / lighting:** Pale neutral studio background; soft neutral light.
- **Attributes to preserve:** Flannel shirt's woven olive-and-off-white check (not printed); fleece shows soft pile texture; beanie plain ribbed black.
- **Prompt:** "Editorial retail photograph of a young male figure in a neutral studio setting with soft daylight-feel lighting; wearing a grey unisex long-sleeve ThermaCore crew-neck technical top under an open olive-and-off-white woven-check brushed-cotton flannel shirt, with a navy unisex full-zip polyester fleece jacket worn open on top, dark-wash slim-fit stretch jeans, and a plain black ribbed wool-blend knit beanie; face turned away or cropped; three-quarter full-body framing; soft diffuse studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### AW26-ED-06 — "Classical Teacher" (women, CP-05 Eva)
- **Filename:** `AW26-ED-06.png`
- **Source scenario:** `UQ-AW26-STG-v1.0.md` §5.6.
- **Products shown and required colors:**
  - UQ-AW26-TS-011 Premium Cotton Mock Neck — OFW
  - UQ-AW26-KN-012 Chunky Cable Cardigan — GRY
  - UQ-AW26-DR-011 Corduroy A-Line Skirt — BRN
  - UQ-AW26-CJ-005 Wool Blend Wrap Coat — BEI
  - UQ-AW26-AC-012 Cashmere Blend Scarf — BEI
- **Garment types / silhouettes:** Off-white mock-neck top under a grey chunky cable cardigan, brown knee-length A-line corduroy skirt with button front, beige women's wool-blend wrap coat worn open, beige cashmere-blend scarf.
- **View / composition:** Three-quarter full-body on a female figure, face cropped or turned.
- **Background / lighting:** Pale neutral studio background; soft warm neutral light.
- **Attributes to preserve:** Skirt shows vertical row of tonal buttons from waist to hem; wrap coat closed only by its self-fabric belt (if closed) or worn open with the belt loose at the sides; cardigan shows chunky cable pattern.
- **Prompt:** "Editorial retail photograph of a female figure in a neutral studio setting with warm soft lighting; wearing an off-white long-sleeve mock-neck cotton top under a grey chunky cable-knit wool-blend cardigan, a brown knee-length A-line corduroy skirt with a vertical row of tonal buttons from waist to hem, a beige women's wool-blend wrap coat worn open with its self-fabric belt loose at the sides, and a solid beige wool-cashmere scarf; face turned away or cropped; three-quarter full-body framing; soft diffused studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

#### AW26-ED-07 — "Minimalist Capsule" (men, CP-06 Honza)
- **Filename:** `AW26-ED-07.png`
- **Source scenario:** `UQ-AW26-STG-v1.0.md` §5.7.
- **Products shown and required colors:**
  - UQ-AW26-TS-010 ThermaCore Crew Long Sleeve — BLK
  - UQ-AW26-KN-010 Merino Blend Crewneck — OFW
  - UQ-AW26-TR-012 Wool Blend Dress Pants — CHA
  - UQ-AW26-CJ-001 Ultra Light Down Jacket — BLK
- **Garment types / silhouettes:** Black long-sleeve technical crew under an off-white fine merino crewneck sweater, charcoal wool-blend dress pants, black ultra-light down jacket worn open.
- **View / composition:** Three-quarter full-body on a male figure, face cropped or turned; strict two-color (charcoal/off-white) palette with the black ultra-light down as a neutral outer.
- **Background / lighting:** Pale neutral studio background; soft, slightly cool minimalist light.
- **Attributes to preserve:** Ultra-light down shows thin horizontal baffles and no hood; merino crewneck ribbed trim at collar, cuffs, and hem; dress pants with hemmed cuff.
- **Prompt:** "Editorial retail photograph of a male figure in a minimalist neutral studio setting with cool soft lighting; wearing a black unisex long-sleeve crew-neck technical top under an off-white fine-knit merino-blend crewneck sweater with ribbed trim at the collar, cuffs, and hem, charcoal wool-blend tailored dress trousers with a flat front and hemmed cuff, and a black unisex ultra-light down jacket with thin horizontal baffle quilting and a stand collar (no hood) worn open on top; face turned away or cropped; three-quarter full-body framing; soft diffuse studio lighting on a pale neutral background; realistic fabric textures; no logos, no text, no watermarks."

---

## 6. Image Manifest Summary Table

| # | Filename | SKU / Scenario | Season | Type | Hero color |
|---|----------|----------------|--------|------|------------|
| 1 | UQ-SS26-TS-001.png | UQ-SS26-TS-001 | SS26 | Product | WHT |
| 2 | UQ-SS26-TS-002.png | UQ-SS26-TS-002 | SS26 | Product | BLK |
| 3 | UQ-SS26-TS-003.png | UQ-SS26-TS-003 | SS26 | Product | WHT |
| 4 | UQ-SS26-TS-004.png | UQ-SS26-TS-004 | SS26 | Product | NVY/WHT |
| 5 | UQ-SS26-TS-005.png | UQ-SS26-TS-005 | SS26 | Product | GRY |
| 6 | UQ-SS26-SH-001.png | UQ-SS26-SH-001 | SS26 | Product | BLU |
| 7 | UQ-SS26-SH-002.png | UQ-SS26-SH-002 | SS26 | Product | OLI |
| 8 | UQ-SS26-SH-003.png | UQ-SS26-SH-003 | SS26 | Product | OFW |
| 9 | UQ-SS26-SH-004.png | UQ-SS26-SH-004 | SS26 | Product | WHT |
| 10 | UQ-SS26-TR-001.png | UQ-SS26-TR-001 | SS26 | Product | BEI |
| 11 | UQ-SS26-TR-002.png | UQ-SS26-TR-002 | SS26 | Product | BEI |
| 12 | UQ-SS26-TR-003.png | UQ-SS26-TR-003 | SS26 | Product | BEI |
| 13 | UQ-SS26-TR-004.png | UQ-SS26-TR-004 | SS26 | Product | BLK |
| 14 | UQ-SS26-JN-001.png | UQ-SS26-JN-001 | SS26 | Product | BLU (light) |
| 15 | UQ-SS26-JN-002.png | UQ-SS26-JN-002 | SS26 | Product | BLU (mid) |
| 16 | UQ-SS26-DR-001.png | UQ-SS26-DR-001 | SS26 | Product | BEI |
| 17 | UQ-SS26-DR-002.png | UQ-SS26-DR-002 | SS26 | Product | BLK |
| 18 | UQ-SS26-DR-003.png | UQ-SS26-DR-003 | SS26 | Product | BLK |
| 19 | UQ-SS26-KN-001.png | UQ-SS26-KN-001 | SS26 | Product | OFW |
| 20 | UQ-SS26-KN-002.png | UQ-SS26-KN-002 | SS26 | Product | OFW |
| 21 | UQ-SS26-LJ-001.png | UQ-SS26-LJ-001 | SS26 | Product | NVY |
| 22 | UQ-SS26-LJ-002.png | UQ-SS26-LJ-002 | SS26 | Product | BEI |
| 23 | UQ-SS26-LJ-003.png | UQ-SS26-LJ-003 | SS26 | Product | BEI |
| 24 | UQ-SS26-AC-001.png | UQ-SS26-AC-001 | SS26 | Product | BEI |
| 25 | UQ-SS26-AC-002.png | UQ-SS26-AC-002 | SS26 | Product | NVY |
| 26 | UQ-SS26-AC-003.png | UQ-SS26-AC-003 | SS26 | Product | PNK |
| 27 | UQ-SS26-AC-004.png | UQ-SS26-AC-004 | SS26 | Product | BLK |
| 28 | UQ-AW26-TS-010.png | UQ-AW26-TS-010 | AW26 | Product | BLK |
| 29 | UQ-AW26-TS-011.png | UQ-AW26-TS-011 | AW26 | Product | OFW |
| 30 | UQ-AW26-TS-012.png | UQ-AW26-TS-012 | AW26 | Product | NVY |
| 31 | UQ-AW26-SH-010.png | UQ-AW26-SH-010 | AW26 | Product | BRG check |
| 32 | UQ-AW26-SH-011.png | UQ-AW26-SH-011 | AW26 | Product | BEI |
| 33 | UQ-AW26-SH-012.png | UQ-AW26-SH-012 | AW26 | Product | OFW |
| 34 | UQ-AW26-TR-010.png | UQ-AW26-TR-010 | AW26 | Product | CHA |
| 35 | UQ-AW26-TR-011.png | UQ-AW26-TR-011 | AW26 | Product | BEI |
| 36 | UQ-AW26-TR-012.png | UQ-AW26-TR-012 | AW26 | Product | CHA |
| 37 | UQ-AW26-JN-010.png | UQ-AW26-JN-010 | AW26 | Product | BLU (dark) |
| 38 | UQ-AW26-JN-011.png | UQ-AW26-JN-011 | AW26 | Product | BLU (dark) |
| 39 | UQ-AW26-DR-010.png | UQ-AW26-DR-010 | AW26 | Product | BLK |
| 40 | UQ-AW26-DR-011.png | UQ-AW26-DR-011 | AW26 | Product | BEI |
| 41 | UQ-AW26-KN-010.png | UQ-AW26-KN-010 | AW26 | Product | NVY |
| 42 | UQ-AW26-KN-011.png | UQ-AW26-KN-011 | AW26 | Product | CHA |
| 43 | UQ-AW26-KN-012.png | UQ-AW26-KN-012 | AW26 | Product | OFW |
| 44 | UQ-AW26-KN-013.png | UQ-AW26-KN-013 | AW26 | Product | BLK |
| 45 | UQ-AW26-LJ-010.png | UQ-AW26-LJ-010 | AW26 | Product | NVY |
| 46 | UQ-AW26-CJ-001.png | UQ-AW26-CJ-001 | AW26 | Product | BLK |
| 47 | UQ-AW26-CJ-002.png | UQ-AW26-CJ-002 | AW26 | Product | BLK |
| 48 | UQ-AW26-CJ-003.png | UQ-AW26-CJ-003 | AW26 | Product | NVY |
| 49 | UQ-AW26-CJ-004.png | UQ-AW26-CJ-004 | AW26 | Product | CHA |
| 50 | UQ-AW26-CJ-005.png | UQ-AW26-CJ-005 | AW26 | Product | CHA |
| 51 | UQ-AW26-TH-001.png | UQ-AW26-TH-001 | AW26 | Product | BLK |
| 52 | UQ-AW26-TH-002.png | UQ-AW26-TH-002 | AW26 | Product | BLK |
| 53 | UQ-AW26-TH-003.png | UQ-AW26-TH-003 | AW26 | Product | BLK |
| 54 | UQ-AW26-TH-004.png | UQ-AW26-TH-004 | AW26 | Product | BLK |
| 55 | UQ-AW26-AC-010.png | UQ-AW26-AC-010 | AW26 | Product | NVY |
| 56 | UQ-AW26-AC-011.png | UQ-AW26-AC-011 | AW26 | Product | BLK |
| 57 | UQ-AW26-AC-012.png | UQ-AW26-AC-012 | AW26 | Product | BRG |
| 58 | UQ-AW26-AC-013.png | UQ-AW26-AC-013 | AW26 | Product | BLK |
| 59 | SS26-ED-01.png | SS26 §4.1 Weekday Hybrid | SS26 | Editorial | — |
| 60 | SS26-ED-02.png | SS26 §4.2 Market Saturday | SS26 | Editorial | — |
| 61 | SS26-ED-03.png | SS26 §4.3 Office + Dinner Pivot | SS26 | Editorial | — |
| 62 | SS26-ED-04.png | SS26 §4.4 Weekend Hike | SS26 | Editorial | — |
| 63 | SS26-ED-05.png | SS26 §4.5 Student Budget Everyday | SS26 | Editorial | — |
| 64 | SS26-ED-06.png | SS26 §4.6 Teacher's Spring | SS26 | Editorial | — |
| 65 | AW26-ED-01.png | AW26 §5.1 Office Winter Day | AW26 | Editorial | — |
| 66 | AW26-ED-02.png | AW26 §5.2 Weekend Trek Krkonoše | AW26 | Editorial | — |
| 67 | AW26-ED-03.png | AW26 §5.3 Formal Dinner | AW26 | Editorial | — |
| 68 | AW26-ED-04.png | AW26 §5.4 School Day | AW26 | Editorial | — |
| 69 | AW26-ED-05.png | AW26 §5.5 Student Commute | AW26 | Editorial | — |
| 70 | AW26-ED-06.png | AW26 §5.6 Classical Teacher | AW26 | Editorial | — |
| 71 | AW26-ED-07.png | AW26 §5.7 Minimalist Capsule | AW26 | Editorial | — |

Totals: **58 product-only images** + **13 editorial outfit images** = **71 image assets**.

---

## 7. Generation Guidance (Batching)

When image-generation tools are available, generate in the following batches to keep review manageable:

1. SS26 product-only — TS, SH, TR (14 images).
2. SS26 product-only — JN, DR, KN, LJ, AC (13 images).
3. AW26 product-only — TS, SH, TR, JN (11 images).
4. AW26 product-only — DR, KN, LJ (7 images).
5. AW26 product-only — CJ (ghost-mannequin batch, 5 images).
6. AW26 product-only — TH, AC (8 images).
7. SS26 editorial (6 images).
8. AW26 editorial (7 images).

After each batch, verify against the manifest row before moving on. Do not generate a replacement that silently changes color, silhouette, pocket count, or any other canonical attribute.

---

## 8. Notes for the AI Shopping Consultant

- Images in this manifest are **illustrative** — they depict the hero color only. All canonical colorways in the catalogs remain valid and offerable to the customer regardless of which color is in the image.
- If the customer asks about a color or detail that disagrees with an image, the canonical dataset in the catalog, PDS, and price list is the source of truth (`UQ-GLO-v1.0.md` §11, `UQ-CSP-v1.0.md` §9).
- The consultant must not describe the image as an official brand asset. If asked whether the image is "a real UNIQLO photo", the consultant must clarify this is a fictional training corpus.

---

*End of document.*
