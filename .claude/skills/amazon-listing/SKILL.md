---
name: amazon-listing
description: Create an Amazon Seller Central listing for a dropshipped product (merchant-fulfilled / FBM, sourced from CJ Dropshipping). Use this whenever the user is listing or cross-listing a product on Amazon, working through Seller Central's Add-a-Product form, setting up color or size variations, needs Amazon listing copy (title, bullet points, description), asks about main image requirements, GTIN/UPC exemption, or SKU mapping between Amazon and a supplier — even if they don't mention this skill by name or only share a screenshot of the form.
---

# Listing a dropshipped product on Amazon

Amazon's Add-a-Product form is long, its field labels are inconsistent across
categories, and several defaults are actively wrong for a dropshipping business.
This skill captures a workflow proven on a real FurrFlow/CJ Dropshipping listing
so each new product goes faster than the last.

The user is typically working in a browser and sharing screenshots. Give them
copy-pasteable values, one section at a time, and read each screenshot before
advising — the form varies by product type and Amazon revises it often. When a
field appears that isn't covered here, reason from the product's real data
rather than guessing, and say which values are estimates.

## The two rules that matter most

**Merchant Fulfilled, never FBA.** In the Offer section, Fulfillment Channel
Code must be "I want to ship this item myself" (Merchant Fulfilled). FBA means
shipping inventory into Amazon's warehouses, which doesn't exist in a
dropshipping model — picking it silently breaks the whole fulfillment chain.

**SKU = the supplier variant id (vid).** Whatever a color's vid is in CJ, that
is its Amazon SKU. This is what lets order automation map an Amazon sale back to
the right supplier variant later without a lookup table. Getting it wrong ships
the customer the wrong color.

## Never invent product data

Everything in a listing is a promise to a customer, and Amazon penalizes
inaccuracy. Pull specs from the CJ product page (material, dimensions, weight,
features). When a required field has no real answer available:

- Prefer a defensible approximation over a fabricated specific
- Tell the user plainly it's an estimate and what would confirm it
- Never state a capability the product may not have (dishwasher-safe,
  waterproof, a certification) just to fill a box

Estimates that are fine: package dimensions before a sample arrives (item size
plus packaging), model numbers (any consistent internal identifier).

## Step 1 — Gather real data before touching the form

```bash
shopagent cj variants <cj-product-id>    # every color's own vid
```

Copy the label→vid mapping into a table and work from it. **Do not assume the
first variant is whichever color CJ's page happens to display** — on a real
listing the pre-selected swatch was Blue while the API's first variant was
Green, which would have shipped every Blue order a Green product.

Also collect from the CJ product page: cost, item dimensions (usually mm),
item weight (usually grams), material, and the color labels exactly as CJ names
them. Keep CJ's naming even when it's odd ("Transparent" for a cream-colored
mat) — the supplier's label is what matches at fulfillment time.

Convert units for Amazon: mm ÷ 25.4 = inches, g ÷ 453.6 = pounds.

**Sanity-check the margin before building anything.** Amazon takes roughly a 15%
referral fee on top of the supplier cost and your shipping. If the intended
price doesn't clear a real profit, say so now and suggest checking comparable
listings — better to reprice than to discover it after launch.

## Step 2 — Prepare images

Amazon's main-image rules are strict and enforced automatically:

- Product only on a pure white background (#FFFFFF, not near-white, not
  transparent) — no hands, water, faucets, props, text overlays, or logos
- One product per main image; a grid of all colors is not a valid main image
- With variations, **each color needs its own main image** of that color

Secondary images (slots 2–9) are where lifestyle and infographic shots belong —
the hand rinsing the product, the pet using it, CJ's feature callouts. These
convert well and have no white-background requirement.

Practical path when the user has only supplier photos: pick CJ's cleanest
product-only shot, run it through remove.bg, set the background to white
(explicitly white, not transparent), and crop per color in Canva if needed.
Supplier stock photos are acceptable to launch with, but real photos convert
better — remind the user to swap them once samples arrive.

## Step 3 — Work through the form

Seller Central → **List Your Products** → **Blank form** → Start. Search a
keyword to classify the product, then confirm Amazon's suggested product type
if it fits.

Ignore the "Generate Listing Content" AI panel — the copy in Step 4 is better
and already accurate.

Sections appear in the left sidebar with completion counts. Read
`references/seller-central-fields.md` for the field-by-field values, including
the ones whose labels are misleading.

**Tell the user to click "Save as draft" every couple of sections.** A refresh
or timeout loses everything not saved, and re-entering the whole form is
demoralizing. Leaving the "Save product details for future listings" toggle on
also carries some fields into the next product, which helps a lot on products
two and three.

## Step 4 — Write the listing copy

Draft this before the user reaches the Description section so they can paste it
straight in.

**Title** (under 200 characters, no promotional language, no ALL CAPS):
lead with what it is and who it's for, then the two or three attributes a
shopper filters on.

```
Dog & Cat Lick Mat, Silicone Slow Feeder with Suction Cups for Bath Time & Grooming Enrichment
```

**Five bullet points**, each one benefit-led and grounded in a real feature.
Sentence case, no ALL CAPS, no repeated information:

```
Textured silicone surface with raised ridges holds food, purée, or treats and slows down licking
Strong suction cups on the back attach securely to tubs, tile, or other smooth surfaces
Made from soft, BPA-free silicone that's gentle on your pet's tongue and gums
Doubles as an enrichment activity to help keep pets occupied during bath time or grooming
Suitable for both dogs and cats, available in multiple colors
```

**Description**: one plain-text paragraph (three to four sentences) restating
the same facts in a flowing way. No HTML, no bullet characters, no all caps.

## Step 5 — Variations (only for multi-color/size products)

The parent is the family container, not a product anyone buys:

- **Parent SKU**: your own identifier, e.g. `LICKMAT-DOGCAT-PARENT`. It never
  reaches CJ, so it doesn't need to match a vid.
- **Variation Theme**: Color (or Size)
- **Parent item name**: the plain title, with no color in it. If it named a
  color it would misdescribe its own children.

Each child then needs its own main image, and in the Offer section its own SKU
(that color's vid), price, and quantity.

## Step 6 — After submitting

Submission is asynchronous: "Pending additional checks" usually clears in
minutes but can take up to 48 hours. If the listing later shows Inactive, the
"Review blocked reason" link on it explains why — ask the user for a screenshot
and fix from there.

Then reconcile the listing into the local pipeline so order automation knows
about it:

```bash
shopagent products import <cj-product-id> --price <price> \
  --shopify-id gid://shopify/Product/<id> \
  --amazon-sku <vid> --amazon-status submitted
```

Recording `--amazon-sku` and `--amazon-status` matters: it tells the Amazon
agent this product is already listed, so a later `run daily` won't propose
creating a duplicate.

## Prerequisites worth confirming early

- **Professional selling plan** — required for API access and variations
- **GTIN exemption** for brand "Generic" — generic dropshipped goods have no
  UPC barcodes, and listing creation fails without an approved exemption.
  Apply in Seller Central well before it's needed; it isn't instant.
- For automated order sync later, the SP-API app also needs the
  **Direct-to-Consumer Shipping** restricted role, which Amazon reviews by hand
  and can take days. Worth starting early even if API work is deferred.
