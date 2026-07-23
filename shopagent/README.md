# shopagent — an AI agent team for your Shopify dropshipping business

shopagent runs a team of five AI agents (Claude-powered) coordinated by a
deterministic daily pipeline. The agents research products, write listings,
prepare supplier orders, draft customer replies, and generate marketing copy —
**but nothing touches your store, your supplier account, or a customer until
you approve it.**

```
                        ┌──────────────────────┐
                        │     Orchestrator      │  deterministic daily pipeline
                        └──────────┬───────────┘
       ┌────────────┬─────────────┼─────────────┬─────────────┐
 ┌─────▼─────┐ ┌────▼─────┐ ┌─────▼──────┐ ┌────▼────┐ ┌─────▼─────┐
 │ Research  │ │ Listings │ │Fulfillment │ │ Support │ │ Marketing │
 └─────┬─────┘ └────┬─────┘ └─────┬──────┘ └────┬────┘ └─────┬─────┘
       │            │             │             │            │
       └────────────┴──────┬──────┴─────────────┴────────────┘
                           ▼
                 ┌───────────────────┐        ┌──────────────────┐
                 │  Approval queue    │──────▶│  YOU approve or   │
                 │  (SQLite, pending) │        │  reject via CLI   │
                 └───────────────────┘        └────────┬─────────┘
                                                       ▼
                                              ┌──────────────────┐
                                              │     Executor      │
                                              │ Shopify + CJ APIs │
                                              └──────────────────┘
```

## The safety model

Agents have **no tools that can change anything external**. Their only write
path is `propose_action`, which files a pending row in the approval queue with
the exact payload, a one-line title, and the agent's rationale. A separate
executor — invoked only by `shopagent approvals approve <id>` — performs
approved actions against the real APIs. A misbehaving prompt cannot bypass the
gate, because the gate is structural, not instructional.

What executes what:

| Action | On approval |
|---|---|
| `shopify.create_product` / `update_product` | Real Shopify Admin API call (product photos from the CJ listing are attached automatically) |
| `shopify.fulfill_order` | Marks the Shopify order fulfilled with the CJ tracking number and emails the customer |
| `cj.create_order` | Real CJ Dropshipping order (costs money) |
| `support.send_reply` | Writes a copy-ready reply to `output/replies/` (you send it) |
| `marketing.publish` | Writes content to `output/marketing/` (you post it) |

## The agents

- **Research** — searches the CJ catalog by niche, gets freight quotes,
  computes retail pricing from your configured markup, and saves candidates
  that clear your minimum margin. Shortlists the strongest.
- **Listings** — writes an SEO title, honest HTML description, and tags for
  each shortlisted product, then proposes creating it on your store.
- **Fulfillment** — syncs unfulfilled Shopify orders, maps line items to CJ
  variants, proposes CJ orders, polls tracking, and flags anything unmappable
  for your attention.
- **Support** — reads customer messages from `inbox/`, looks up real order
  status and tracking before answering, and proposes replies. Never invents
  shipping dates.
- **Marketing** — drafts social captions, promo emails, and ad copy grounded
  in the actual listing content of live products.

## Quickstart (no store credentials needed)

Everything works out of the box in **dry-run mode** against a built-in mock
Shopify store and mock CJ catalog:

```bash
cd shopagent
pip install -e ".[dev]"
cp .env.example .env        # add your ANTHROPIC_API_KEY (the only key needed for dry-run)

shopagent doctor            # check config and credentials
shopagent run daily         # full pipeline against the mock backends
shopagent approvals list    # see what the agents proposed
shopagent approvals show 1  # inspect the exact payload
shopagent approvals approve 1
shopagent status
```

Or drive agents individually:

```bash
shopagent research "pet accessories"   # find products
shopagent products list
shopagent draft listings               # write listings for shortlisted products
shopagent orders sync                  # pull store orders (no AI)
shopagent support draft                # draft replies to inbox messages
shopagent marketing draft              # promote listed products
```

Run the tests (no network or API keys needed):

```bash
python -m pytest tests/
```

## Going live

Set `mode: live` in `config.yaml` **and** provide credentials in `.env`. Any
integration whose credentials are missing quietly stays on the mock backend
(the mode banner on every command shows the effective state per integration).

### Connect your Shopify store (Dev Dashboard app)

Since January 1, 2026 custom apps are created in the **Dev Dashboard**
(dev.shopify.com), and they no longer expose a permanent `shpat_` token.
Instead the app has a Client ID + Client secret, and shopagent exchanges them
for short-lived (~24h) Admin API tokens automatically (cached in the
gitignored `.shopify_token.json`, refreshed on expiry).

1. Go to **dev.shopify.com**, sign in with your store's account, and
   **Create app** (e.g. `shopagent`). Choose "Start from Dev Dashboard".
2. In the app's configuration, set the **App scopes**:
   `read_products, write_products, read_orders, read_fulfillments,
   write_fulfillments, read_customers, read_inventory, write_inventory` —
   then **Release** the version (config takes effect only when released).
3. From the app's **Home** panel, click **Install app** and pick your store.
   Client-credential tokens only work for stores in your own organization
   with the app installed.
4. From the app's **Settings** page, copy the **Client ID** and
   **Client secret**.
5. In `.env`, set `SHOPIFY_STORE_DOMAIN=your-store.myshopify.com`,
   `SHOPIFY_CLIENT_ID=…` and `SHOPIFY_CLIENT_SECRET=…`.

(If you still have a pre-2026 custom app with a `shpat_` token, set
`SHOPIFY_ACCESS_TOKEN` instead — it takes precedence.)

### Connect CJ Dropshipping

1. Create an account at cjdropshipping.com and top up balance (CJ orders are
   paid from balance).
2. In **My CJ → Authorization → API**, generate an API key.
3. In `.env`, set `CJ_EMAIL` (your CJ login email) and `CJ_API_KEY`.
4. Token exchange is automatic; the ~15-day token is cached in
   `.cj_token.json` (gitignored). Note CJ rate-limits the auth endpoint
   heavily — don't delete the cache file needlessly.

> ⚠️ Before your first live CJ order, verify the field mapping in
> `src/shopagent/integrations/cj_client.py` against the current docs at
> developers.cjdropshipping.com — CJ occasionally revises payload fields —
> and test with one small order.

## Adding the Amazon channel

shopagent can cross-list the same pipeline products onto Amazon (merchant
fulfilled / FBM, shipped by CJ) and manage those orders through the same
approval queue. In dry-run it works against a mock Amazon backend.

### Prerequisites (one-time, in Seller Central)

1. **Professional selling plan** ($39.99/mo) — required for API access — and
   completed seller identity verification.
2. **Register as a developer & create a private app**: Seller Central →
   **Partner Network → Develop Apps**. In the developer profile, request the
   roles your app needs — crucially the **Direct-to-Consumer Shipping
   (restricted) role**: without it, buyer shipping addresses are redacted and
   dropshipping is impossible. Amazon reviews this request; it can take days,
   so do it first.
3. Create the app, then click **Authorize** and copy the **refresh token**
   shown (long `Atzr|...` string). Collect the **LWA Client ID / Client
   Secret** from the app's credentials view.
4. Your **Seller ID** (a.k.a. Merchant Token): Settings → Account Info →
   Merchant Token.
5. Put all four in `.env` (`AMZ_CLIENT_ID`, `AMZ_CLIENT_SECRET`,
   `AMZ_REFRESH_TOKEN`, `AMZ_SELLER_ID`). Token exchange and refresh are
   automatic (cached in gitignored `.amazon_token.json`).
6. **GTIN/UPC exemption**: generic dropshipped products have no UPC barcodes.
   Apply for a GTIN exemption for brand "Generic" (Seller Central → Apply for
   GTIN exemption) *before* approving Amazon listings — creation fails
   without it. Often auto-approved.

### Amazon dropshipping policy — read this

Amazon allows dropshipping ONLY if:
- **You are the seller of record.** All packing slips, invoices, and external
  packaging must identify **your store** and nobody else — no CJ branding, no
  promotional inserts. Configure this in CJ (Settings → dropshipping/no
  invoice) before your first Amazon order.
- You are responsible for accepting and processing returns.
- Set honest handling time (`amazon.lead_time_days`, default 5) — CJ takes
  1–3 days to process — and realistic transit expectations in your Seller
  Central shipping templates (CJ delivery is typically 8–15 days).

Violations risk account suspension. Amazon also tracks valid-tracking-rate:
`carrier_default: Other` + carrier name works but scores worse than a real
carrier code — when CJ hands off to USPS/UPS last-mile, prefer that code.

### How it works day-to-day

- `shopagent amazon draft` — the Amazon agent cross-lists eligible store
  products (Amazon-optimized title/bullets, price from the pipeline,
  photos from CJ, SKU = the CJ variant id) and files `amazon.create_listing`
  approvals. It pre-validates every payload with Amazon's validation mode and
  fixes issues before proposing.
- `shopagent orders sync` / `run daily` — pulls unshipped Amazon orders next
  to Shopify ones (`channel` column); the fulfillment agent proposes CJ
  orders for them, and once CJ ships, proposes `amazon.confirm_shipment`,
  which uploads the tracking number to Amazon on approval.
- Listing creation on Amazon is **asynchronous**: an accepted submission can
  still surface issues minutes later. The agent re-checks on later runs and
  marks blocked listings with notes.
- The Orders API is rate-limited to ~1 call/minute — sync once, don't hammer.

## Configuration reference (`config.yaml`)

| Key | Meaning |
|---|---|
| `mode` | `dry_run` (mock everything) or `live` |
| `business.niches` | Niches the research agent rotates through |
| `business.pricing.markup_multiplier` | Retail = supplier cost × this, rounded to .99 |
| `business.pricing.min_margin_usd` | Candidates below this margin are rejected |
| `business.max_new_products_per_run` | Research cap per run |
| `business.min_candidate_pool` | Daily pipeline researches only below this |
| `ai.model` / `ai.max_tokens` / `ai.max_tool_iterations` | Agent model settings |
| `supplier.ship_to_country` | Country used for freight quotes |

## Project layout

```
src/shopagent/
├── cli.py            # all commands
├── config.py         # config.yaml + .env loading, mode resolution
├── store.py          # SQLite: products, orders, approvals, agent_runs
├── executor.py       # the ONLY code that performs external actions
├── orchestrator.py   # deterministic daily pipeline
├── ai/client.py      # Anthropic wrapper + manual tool-use loop
├── agents/           # base + research, listings, fulfillment, support, marketing
└── integrations/     # Shopify GraphQL client, CJ API client, + mocks/fixtures
```

## Roadmap ideas

- Real inbox integration (Gmail/Shopify Inbox) instead of the `inbox/` directory
- A second supplier implementation behind the same interface
- Scheduled daily runs (cron) with a morning approval digest
