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
