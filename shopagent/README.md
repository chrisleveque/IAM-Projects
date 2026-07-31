# shopagent — an AI agent team for your Shopify dropshipping business

shopagent runs a team of AI agents (Claude-powered) coordinated by a
deterministic daily pipeline. The agents research products, write listings,
cross-list to Amazon, prepare supplier orders, draft customer replies, write
marketing copy, and build vertical video ads —
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
executor — invoked by `shopagent approvals approve <id>`, or by the equivalent
HTTP endpoint if you run `shopagent serve` — performs approved actions against
the real APIs. A misbehaving prompt cannot bypass the gate, because the gate is
structural, not instructional.

The one way to give that structure away is to hand an LLM the approve endpoint
as a tool. See [Remote control from your phone](#remote-control-from-your-phone-n8n).

What executes what:

| Action | On approval |
|---|---|
| `shopify.create_product` / `update_product` | Real Shopify Admin API call (product photos from the CJ listing are attached automatically) |
| `shopify.fulfill_order` | Marks the Shopify order fulfilled with the CJ tracking number and emails the customer |
| `cj.create_order` | Real CJ Dropshipping order (costs money) |
| `support.send_reply` | Writes a copy-ready reply to `output/replies/` (you send it) |
| `marketing.publish` | Writes content to `output/marketing/` (you post it) |
| `tiktok.render_video` | Renders a vertical ad to `output/video/` from the product's real photos |
| `tiktok.upload_draft` | Sends a rendered ad to your TikTok drafts (optional; needs TikTok credentials) |

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
- **Amazon** — cross-lists store products onto Amazon as merchant-fulfilled
  offers, pre-validating each listing before proposing it.
- **Content** — writes vertical TikTok/Reels ad scripts for listed products
  and proposes renders built from their real supplier photos.

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

### Reconciling manually-sourced products

If you source or list a product outside shopagent — by hand on CJ's site, through
CJ's own Shopify app, or in Seller Central directly — shopagent's pipeline has
no record of it, so fulfillment can't map its orders to a CJ variant (they'll
show up as `attention` instead of being auto-fulfilled, which is safe but not
automatic). Register it after the fact with:

```bash
shopagent products import <cj-product-id> --price 79.99 \
    --shopify-id gid://shopify/Product/123456789 --status listed
```

This looks the product up on CJ by id to fill in cost, the variant id, a
freight quote, and photos automatically — you only supply your selling price
and, optionally, the Shopify product id and an existing Amazon SKU/status
(`--amazon-sku`, `--amazon-status`) if you already listed it there too, so the
Amazon agent doesn't try to create a duplicate listing. Running it again for
the same product id updates the existing pipeline row rather than duplicating it.

To retire a stale or invalid pipeline row instead — for example dry-run test
data left over from before you connected a real store, which would otherwise
get swept up by `run daily`'s Amazon cross-listing step — use:

```bash
shopagent products reject <id> --note "why"
```

To wipe the pipeline entirely and start clean — e.g. after dry-run practice,
before reconciling your real catalog from scratch — use:

```bash
shopagent products clear
```

Both commands only touch shopagent's own local tracking; neither removes or
unpublishes anything from Shopify, Amazon, or CJ.

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

## TikTok video ads

The content agent writes vertical ad scripts for listed products and proposes
renders; the executor builds the mp4 on approval, from the product's real
supplier photos.

```bash
winget install Gyan.FFmpeg        # Windows — then open a NEW terminal
shopagent trends import           # parse inbox/trends/ (optional)
shopagent content draft           # agent writes scripts, proposes renders
shopagent approvals approve 1     # renders to output/video/
shopagent content videos          # where the files are
```

`shopagent doctor` reports whether ffmpeg is on PATH. Nothing else in shopagent
needs it, so it only blocks video work.

### Three things about this that are not negotiable

**1. Music: royalty-free is not the same as "trending".** The sounds trending on
TikTok are commercial recordings. Using one on a Business account or in a paid
ad is a copyright violation, and TikTok mutes or removes the video. The
sanctioned catalogue is **TikTok's Commercial Music Library** — a million-plus
pre-cleared tracks, with its own trending section — and it has **no public
API**; it is only browsable in the app.

So the renderer beds in a royalty-free track from Pixabay or Jamendo, which is
safe for a draft, and the agent tells you to swap it for a Commercial Music
Library track before the video runs as an ad. That manual step is the point,
not a gap.

**2. Auto-posting to TikTok is not realistically available.** The Content
Posting API's Direct Post mode requires passing a TikTok audit, and TikTok
rejects audit submissions from apps that read as internal tools or side
projects. Until an app passes, every direct post is forced to SELF_ONLY — only
you can see it. **Draft upload needs no audit**, so that is what
`tiktok.upload_draft` does: the video lands in your TikTok drafts and you post
it from the app. Credentials are optional; without them the mp4 still renders
and you upload it by hand.

**3. Trend data is imported by hand.** No public API exposes trending TikTok
Shop products — the official Shop API only reads shops you already own, and
scraping TikTok violates its terms and breaks constantly. Export or paste what
you see in TikTok Creative Center (or a paid tool like Kalodata) into
`inbox/trends/` as `.md` or `.csv`, then `shopagent trends import`.

Markdown format: `## Section` headings become the category, `- items` become
rows, and a trailing `— 41.2B views` or `(rising)` is captured as the metric.
CSV needs a `label` column; `kind`, `metric`, and `note` are used if present.
If you later subscribe to an analytics API, it writes through the same table
and nothing downstream changes.

### Hearing real music (2 minutes)

Without a music key, renders get an **audible placeholder tone** — clearly
synthetic on purpose, so you can judge pacing but would never post it. For real
tracks: sign up free at **devportal.jamendo.com**, create an app, copy the
client id into `.env` as `JAMENDO_CLIENT_ID`. That's the whole setup; the next
render pulls licensed royalty-free music matched to the agent's mood query.

### Two render engines — set up JSON2Video for the professional one

`tiktok.render_video` picks its engine from `cfg.render_engine()`:

| Engine | When | What you get |
|---|---|---|
| **json2video** | `JSON2VIDEO_API_KEY` set (free tier at json2video.com — 600 credits, no card) | Cloud motion-graphics editor: animated text presets, real transitions, built-in TTS voiceover. The professional look, zero editing. |
| **ffmpeg** | otherwise (or `video.engine: ffmpeg`) | The local renderer described below. Free forever, decent drafts. |

Setup: sign up at json2video.com, copy the API key from the dashboard into
`.env` as `JSON2VIDEO_API_KEY`. `shopagent doctor` verifies the key with a
live probe.

Two safety nets sit behind the cloud engine, because its movie spec was
written from public docs: on a rejected render, an **automated repair loop**
(Claude reads the API's error plus the movie JSON, patches it, retries — max
twice), and if that fails, an automatic **fallback to the ffmpeg engine** so
an approved render always produces a video. The approval result records
`repaired_after` or `repair_errors` so you can see what happened, and the n8n
Store Manager is prompted to surface and explain failed renders (retrying
stays a human decision: `shopagent approvals retry <id>`).

If you eventually want an AI "creator" holding your product and talking about
it — the current state of the art for dropshipping ads — that's Creatify
(creatify.ai, ~$33/mo, web app only; their API is enterprise-gated). Worth a
look once ads are earning; it can't be automated from here yet.

### What the ffmpeg renderer does

Vertical 1080×1920, one shot per product photo with a slow camera move
(square supplier photos are shown whole over a blurred backdrop rather than
cropped), 0.4s crossfades between shots, the hook in a brand-colored box over
the opening, a caption per shot, a closing brand card carrying the CTA, and a
music bed trimmed to the exact video length. Captions render in a bundled
Poppins Bold (SIL OFL) so the type looks the same on every machine. Shot count
is capped by `video.max_seconds` so a long photo list yields a shorter ad
rather than one nobody finishes.

Tune it in `config.yaml` under `video:` — `brand_name` and `accent_color`
(hook box + end card), `transition_seconds` (0 = hard cuts),
`end_card_seconds` (0 = no card), `seconds_per_shot`, `music_volume`, font
sizes.

An experimental **voiceover** exists behind `pip install -e .[voice]` and
`video.voiceover: true` — it narrates the script via Microsoft's free TTS and
ducks the music under it. The endpoint is unofficial; if synthesis fails the
render continues music-only and says so.

Editing helpers for footage you shot yourself, in `inbox/footage/`: `trim`,
`add_captions` (burned in — TikTok ignores sidecar subtitles), and `swap_audio`.

Deliberately **not** AI-generated video: it cannot show your actual product, and
a generated dog using a generated lick mat misrepresents what ships.

### Polishing beyond the renderer

The mp4 imports cleanly into the tools people actually finish TikToks in — use
them on top of the render rather than expecting the renderer to be an editor:

- **CapCut** (free, TikTok's own editor): trending templates, auto-captions,
  effects — and the natural place to add the Commercial Music Library sound
  when you post.
- **Canva** (you already use it): intro/outro cards, logo overlays.
- **remove.bg** (you already use it): cleaner product stills in = cleaner ad
  out. The renderer can only be as good as the photos.

## Remote control from your phone (n8n)

`shopagent serve` exposes the pipeline over HTTP so an external automation —
n8n, a phone shortcut, a cron job — can see what the agents have proposed and
act on it without you being at your desk.

```bash
pip install -e .[api]
# add SHOPAGENT_API_TOKEN to .env first (see .env.example)
shopagent serve                 # http://127.0.0.1:8787, docs at /docs
```

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. The only unauthenticated route; reveals nothing |
| `GET` | `/status` | Modes, pending count, product/order counts, recent runs |
| `GET` | `/approvals?status=pending` | Queue summaries (no payloads) |
| `GET` | `/approvals/{id}` | One approval in full, including the exact payload |
| `GET` | `/products?status=` | Product pipeline |
| `GET` | `/orders?status=&channel=` | Order pipeline, filterable by channel |
| `GET` | `/videos` | Rendered ads and where each file is |
| `GET` | `/trends?kind=` | Imported trend notes |
| `POST` | `/approvals/{id}/approve` | Approve **and execute** |
| `POST` | `/approvals/{id}/reject` | Reject, optional `{"note": "..."}` |
| `POST` | `/approvals/{id}/retry` | Re-execute a failed action |

Every route except `/health` requires `Authorization: Bearer $SHOPAGENT_API_TOKEN`.

### Keeping the approval gate real

There is deliberately **no endpoint that creates an approval**. Proposals only
come from agents running locally, so a network caller can read the pipeline and
decide on existing proposals — nothing more.

That leaves one way to lose the gate, and it is worth being blunt about:
**do not attach the POST endpoints as tools an LLM can call.** An agent holding
`approve` will eventually approve something on its own, and a system prompt
saying "confirm first" is a request, not a control. The GET endpoints are safe
as agent tools — reading is harmless. Decisions should come from you tapping a
button.

### The ready-made workflow

`n8n/store-manager-agent.json` is a chat agent wired to the five GET endpoints,
importable via **Workflows → Import from File**. After importing:

1. Replace `REPLACE-WITH-YOUR-TUNNEL.trycloudflare.com` with your own host in
   all five tool nodes.
2. Select your Header Auth credential on each tool node (the export references
   it by name, not by id, so n8n cannot resolve it automatically).

`tests/test_n8n_workflow.py` checks that file against the API on every test
run: every URL is a real route, every query parameter is one the route accepts,
the values listed in each tool description are values the API actually takes,
and — the one that matters — **no tool points at an endpoint that can change
anything**. Adding an approve tool fails the suite.

A workable n8n shape:

- **Agent tools** — HTTP Request nodes for `/status`, `/approvals`,
  `/approvals/{id}`, `/products`, `/orders`. Now you can ask "what's waiting on
  me?" from your phone and get a real answer.
- **Notification** — a scheduled workflow that polls `/approvals` and messages
  you (Telegram, email, push) when the pending count is above zero.
- **Decision** — buttons in that message hitting `/approvals/{id}/approve` or
  `/reject`. The tap is the gate.

Store the token in n8n as a **Header Auth** credential (name
`Authorization`, value `Bearer <token>`) rather than pasting it into each node.

### Exposing it to n8n Cloud

n8n Cloud runs on the internet and cannot reach `127.0.0.1` on your PC. You
need a tunnel, and your PC has to be awake for any of this to work:

```bash
cloudflared tunnel --url http://localhost:8787
```

That prints a public `https://<random>.trycloudflare.com` URL — use it as the
base URL in n8n. Quick tunnels get a new URL each restart; a named tunnel gives
you a stable hostname once you have a domain.

Keep `--host 127.0.0.1` (the default) and let the tunnel reach in. Binding
`0.0.0.0` puts the API on your local network, and port-forwarding it puts your
store's controls on the open internet behind one shared secret.

If your PC being on is a dealbreaker, the alternative is hosting shopagent on a
small always-on box (a $5 VPS, a Raspberry Pi) instead of tunneling your
desktop.

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
| `video.seconds_per_shot` / `video.max_seconds` | Ad pacing and length cap |
| `video.music_volume` / `video.font_size_*` | Soundtrack level and caption sizing |

## Project layout

```
src/shopagent/
├── cli.py            # all commands
├── config.py         # config.yaml + .env loading, mode resolution
├── store.py          # SQLite: products, orders, approvals, agent_runs
├── api.py            # HTTP API for n8n/phone: reads + approval decisions
├── executor.py       # the ONLY code that performs external actions
├── orchestrator.py   # deterministic daily pipeline
├── trends.py         # parses inbox/trends/ exports into the trends table
├── video/render.py   # ffmpeg: vertical ad rendering + trim/caption/audio edits
├── ai/client.py      # Anthropic wrapper + manual tool-use loop
├── agents/           # base + research, listings, fulfillment, support, marketing
└── integrations/     # Shopify GraphQL client, CJ API client, + mocks/fixtures
```

## Roadmap ideas

- Real inbox integration (Gmail/Shopify Inbox) instead of the `inbox/` directory
- A second supplier implementation behind the same interface
- Scheduled daily runs (cron) with a morning approval digest
