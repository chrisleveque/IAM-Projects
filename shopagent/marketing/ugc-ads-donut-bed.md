<!-- Standalone brief: written so a fresh Claude session can execute it
     with no other context. Invoke with:
     "Run the UGC ad plan in shopagent/marketing/ugc-ads-donut-bed.md
      using Higgsfield" -->

# Context for a fresh session

FurrFlow is a pet-niche dropshipping store (Shopify + Amazon, supplier: CJ
Dropshipping). The Calming Donut Dog Bed is LIVE on Amazon as a 4-color
variation family (parent DONUTBED-PARENT; children Pink 2036693145754832898,
Light Grey ...899, Brown ...900, Dark Grey ...901). Product photos: the four
round-bed images on the CJ listing (pid 2036693145205379073) — one per color,
white background. The operator (Chris) has these photos on hand; ask him to
attach them if media upload needs local files.

Execution order — do not skip step 2 or 3:
1. Higgsfield MCP: get_workflow_instructions (no arg) -> catalog -> load the
   UGC/ads workflow and follow it exactly.
2. Check credit balance BEFORE generating anything; report the expected total
   spend for 10 videos to Chris.
3. Generate ad #1 ALONE as a validation pass. Stop. Let Chris judge it.
   Only batch the remaining 9 after he approves the style.
4. Batch via generate_video_batch + jobs_wait + one show_generation_by_ids.

# 10 UGC-style ad briefs — FurrFlow Calming Donut Bed

Product truth (every claim must trace to these): calming donut shape,
ultra-soft plush, supportive rim, non-slip bottom, machine washable,
23.6", for small dogs & cats. Colors: Pink, Light Grey, Brown, Dark Grey.
No invented authorities (no "my vet said"), no fabricated stats, no
before/after medical claims. Personas are clearly stylized creators, not
fake named customers.

| # | Hook (first 2s) | Angle / beats | Color | Setting |
|---|---|---|---|---|
| 1 | "My dog stopped sleeping in my bed... for THIS?" | playful betrayal → dog curled in donut → rim = pillow for their chin → CTA | Brown | cozy bedroom |
| 2 | "If your dog follows you room to room, watch this" | velcro-dog problem → a bed they actually settle in → non-slip stays put on hard floors | Dark Grey | living room, wood floor |
| 3 | "Things in my apartment that just make sense — pet edition" | trend format, list of 3, bed is #1 → plush close-up finger-press | Light Grey | aesthetic apartment |
| 4 | "I was today years old when I learned why donut beds are round" | mini-explainer: curling instinct + raised rim = security → cat demo | Pink | sunny corner |
| 5 | "My cat rejected every bed I bought. Attempt #7:" | serial-returner persona → hesitant cat → kneads → settles → "finally" | Light Grey | minimal bedroom |
| 6 | "POV: it's laundry day and your dog's bed actually survives the wash" | machine washable demo → out of washer still fluffy → dog reclaims it | Brown | laundry room |
| 7 | "Rating things I bought for my anxious dog" | review-show format → focus on cuddle-curl into the rim, calming shape | Dark Grey | couch talking-head + b-roll |
| 8 | "The 23-inch rule for small dogs nobody tells you" | sizing tip: room to curl, rim all around → tape-measure gag | Brown | hallway → bed corner |
| 9 | "My senior cat picked the pink one. Obviously." | color-choice bit → all 4 colors flash → cat on pink → "she has taste" | Pink (all 4 cameo) | bright living room |
| 10 | "Don't buy a donut bed until you flip it over" | skeptic angle → flips bed → non-slip bottom close-up → slide test on tile | Dark Grey | kitchen tile |

Format for all: 9:16 vertical, 15–25s, creator voice-to-camera + product
b-roll from the four real listing photos, caption-style text overlays,
CTA "Link in bio". Voiceover: AI voice via the generation platform.
Music: platform-provided/licensed only — and if any of these run as paid
TikTok ads from the Business account, swap in a Commercial Music Library
track at post time, same rule as everything else.

Generation plan (when Higgsfield is back):
1. get_workflow_instructions → catalog → load the UGC/ads workflow
2. balance check FIRST — 10 videos is a real credit spend
3. Generate ad #1 alone as a validation pass; judge it before batching
4. Batch the remaining 9 via generate_video_batch + jobs_wait

# Run report — 2026-08-08 (stopped at step 2: insufficient credits)

Workflow identified: `ugc-flow` (talking-head UGC pipeline; Seedance 2.0
clips seeded from gpt_image_2 storyboards + a soul_2 creator image, with a
mandatory seedream_v5_pro de-slop pass). Pinned settings: 9:16, 1080p,
one 15s clip per ad at our 15s duration (N=1 board).

Balance at check time: **110 credits** (Plus plan). Measured per-ad cost at
pinned settings (get_cost preflights, 15s ad):

| Component | Model | Credits |
|---|---|---|
| Creator image (reusable across ads) | soul_2, 3:4, 2k | ~0.12 |
| Storyboard (1 per 15s ad) | gpt_image_2, 16:9, 2k high | 7 |
| De-slop pass (1 per board) | seedream_v5_pro, 16:9, 2k | 3 |
| Video clip, 15s | seedance_2_0, 9:16, 1080p | 135 |
| **Per ad (1080p)** | | **~145** |

- All 10 ads at 1080p: **~1,450 credits** (+ re-rolls for QA failures).
- Cheaper options measured: 15s clip at **720p = 67.5** (~78/ad, ~780 for
  10); 10s clip at 1080p = 90. Seedance 2.0 supports unlim generations but
  no unlim trial is active on this account (`unlim.available: false`).
- Blocker: 110 credits cannot cover even the ad #1 validation pass at the
  pinned 1080p spec (~145). Nothing was generated; no credits were spent.
- Product photos: not in the repo and no direct image URLs on hand — the
  four CJ listing photos (pid 2036693145205379073) must be attached or
  linked before the product-intake step can run.

Next session: top up (or approve 720p ≈ 78 credits for ad #1, or start the
unlim trial), provide the 4 product photos, then resume at step 3
(ad #1 validation pass) with `ugc-flow` loaded.

# Update — 2026-08-08: pivoted to Google Veo (Gemini API)

Chris dropped Higgsfield in favor of Google's Veo (via the Gemini API).
Full pipeline is now built into shopagent — briefs, client, stitcher, CLI:

- Briefs: `marketing/donut-bed-briefs.yaml` — these 10 ads as 2×8s clip
  prompts with dialogue inline (edit prompts there, not here).
- Photos: drop the 4 CJ listing photos into `marketing/assets/donut-bed/`
  (see its README for exact filenames).
- Key: set `GEMINI_API_KEY` in .env (aistudio.google.com/apikey).
- Run: `shopagent veo doctor` → `shopagent veo estimate` →
  `shopagent veo generate` (ad #1 validation pass, same gate as step 3
  above) → judge it → `shopagent veo generate --all`.
- Cost in dollars, not credits: ~$24 for all 10 on the default fast model,
  ~$64 on the standard model (`config.yaml` veo.model). The CLI shows the
  projected cost and confirms before spending.
