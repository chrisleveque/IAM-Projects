# Seller Central field reference (Add-a-Product, Blank form)

Field-by-field values for a merchant-fulfilled dropshipped product, in the order
the form presents them. Labels and which fields are required vary by product
type — treat anything marked with a red asterisk on the user's actual screen as
authoritative over this list, and reason from real product data when a field
appears that isn't here.

Fields with no red asterisk can be skipped. Skipping genuinely inapplicable
optional fields is better than inventing values for them.

## Contents

- [Product Identity](#product-identity)
- [Description](#description)
- [Product Details](#product-details)
- [Variations](#variations)
- [Offer](#offer)
- [Safety & Compliance](#safety--compliance)

## Product Identity

| Field | Value | Notes |
|---|---|---|
| Item Name | The title | Under 200 chars, no promo language |
| Product Type | Confirm Amazon's suggestion | e.g. PET FEEDER for a lick mat. Never hand-type a guessed type name |
| Item Type Keyword | Leave Amazon's default | Internal placement path; a cat-oriented path doesn't exclude dog shoppers |
| Brand Name | `Generic` | Also toggle ON "This product does not have a brand name" |
| External Product ID | — | Toggle ON "This product does not have a Product ID". Requires an approved GTIN exemption |
| Variations | ON for multi-color/size | Reveals the Variations section |
| Item Highlight | Skip | Only displays when the item name is under 75 chars, which a good title won't be |

## Description

| Field | Value |
|---|---|
| Product Description | One plain-text paragraph, 3–4 sentences |
| Bullet Point | Five separate boxes — click "Add more" for each |
| Images | Skip when using variations; per-color images are set in Variations |

## Product Details

Often 19+ fields, most optional. Common required ones:

| Field | Example value | Notes |
|---|---|---|
| Material | `Silicone` | From CJ's spec |
| Number of Items | `1` | Identical items in one selling unit — 1 unless a multipack |
| Color | Per variant | Auto-filled per variant when variations are on |
| Care Instructions | `Hand Wash` | Don't claim dishwasher-safe without confirmation |
| Capacity + Unit | `100` / `Milliliters` | Odd fit for flat items; approximate and say so |
| Model Number | `PLM-100` | Any consistent internal identifier |
| Model Name | `EasyLick` | A product-line name, not the item type or color |
| Manufacturer | `Generic` | Matches Brand for unbranded goods |
| Special Features | 3 short phrases | e.g. `Suction Cup Base`, `BPA-Free Silicone`, `Slow Feeding Design` |
| Style | `Bear-Shaped` | The real design/shape |
| Specific Uses for Product | Pick from suggestions | Select-from-list, not freeform |
| Target Species | `Dog` + `Cat` | Add both when the copy says both |
| Item Dimensions L×W×H | Converted from CJ mm | The product itself, not its packaging |
| Unit Count + Type | `1` / `Count` | "Count" for individually-sold units |
| Included Components | `Lick Mat` | What's in the box |
| Dog Breed Size | **All Sizes** | Choosing one size narrows search visibility for no reason |
| Item Weight + Unit | `132` / `Grams` | The product alone, excluding packaging |
| Operation Mode | Skip | Applies to powered feeders |
| Power Source | Skip | Non-powered products |
| Is Green Purchasing Law Compliant | Skip | Japan-specific program |

## Variations

**Step 1 — theme**

| Field | Value |
|---|---|
| Parent SKU | Your own identifier, e.g. `LICKMAT-DOGCAT-PARENT` |
| Variation Theme | `Color` |
| Parent Item Name | The plain title, no color mentioned |

**Step 2 — options**: enter the color names exactly as CJ labels them.

**Step 3 — per variant** ("Add details"):

| Field | Value |
|---|---|
| External Product ID | Toggle ON "does not have a Product ID" for each child |
| Item Name | The shared title (color is conveyed by the variant, not the title) |
| Images | That color's own white-background main image |

## Offer

Per variant. This section carries the highest-consequence fields.

| Field | Value | Notes |
|---|---|---|
| SKU | That color's CJ vid | Verify against the `cj variants` table each time |
| Fulfillment Channel Code | **Merchant Fulfilled** | Never FBA for dropshipping |
| Your Price | Selling price | Same across colors unless costs differ |
| List Price | Same as Your Price | |
| Quantity | A committable number | 20–50 per color is a reasonable start; the supplier's stock is the ceiling |
| Item Condition | `New` | A dropdown — a gray "Example: New" means nothing is selected yet |
| Shipping Template | Existing template | Set realistic handling time: supplier processing plus transit |
| Item Package L/W/H + Units | Item dims plus packaging | e.g. 9 × 9 × 1 Inches for an 8.27in item |
| Package Weight + Unit | Item weight plus packaging | e.g. 0.35 Pounds for a 132g item |
| Number of Boxes | `1` | |

If the form reports errors after filling this in, the usual causes are a
dropdown still showing its gray example text (nothing actually selected) or a
unit dropdown left unset next to a filled numeric field.

## Safety & Compliance

| Field | Value |
|---|---|
| Country/Region of Origin | `China` |
| Are batteries required? | `No` |
| Are batteries included? | `No` |
| Dangerous Goods Regulations | `Not Applicable` |
| Directions | Brief real-use guidance, e.g. `For pet use only. Wash before first use. Keep out of reach of small children who may mistake it for a toy.` |

Battery answers change for powered products (a rechargeable nail grinder has an
internal battery: required = Yes, included = Yes), which also triggers lithium
battery questions. Answer those from the supplier's actual battery spec.
