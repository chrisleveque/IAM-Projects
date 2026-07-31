---
name: video-ads
description: Create, review, or troubleshoot short-form product video ads (TikTok/Reels) through shopagent — the content agent, the render pipeline (ffmpeg or JSON2Video engines), music licensing for ads, script quality rules, and diagnosing failed or bad-looking renders. Use whenever the user wants a product video made, asks why a render failed or looks/sounds wrong, shares a screenshot of a rendered ad, asks about TikTok posting or music for ads — even if they don't name this skill.
---

# Product video ads through shopagent

The pipeline is approval-gated like everything else in shopagent: the content
agent *proposes* a `tiktok.render_video` action; nothing renders until the
operator approves it. Never suggest a path that gives an LLM a render/upload
tool directly.

```
shopagent content draft            # agent writes scripts, proposes renders
shopagent approvals show <id>      # read the script before approving
shopagent approvals approve <id>   # renders to output/video/
shopagent content videos           # where the files are
```

Uploading to TikTok is `tiktok.upload_draft` (goes to the operator's TikTok
*drafts* — Direct Post needs an audit TikTok doesn't grant to internal tools),
or manual upload from the app. Both are fine; the file is the same.

## The two render engines

`cfg.render_engine()` decides, shown in the content-command banner and
`doctor`:

- **json2video** (when `JSON2VIDEO_API_KEY` is set; free tier at
  json2video.com) — cloud motion-graphics editor: animated text presets,
  transitions, built-in TTS voiceover. This is the professional-looking one.
  On a render error the executor runs a bounded LLM repair loop (max 2
  fixes), then falls back to ffmpeg — check the approval result's
  `repaired_after` / `repair_errors` fields when debugging.
- **ffmpeg** (always available locally) — the in-house renderer: pan/zoom
  stills, styled captions in bundled Poppins, crossfades, brand end-card.
  Solid draft quality, deliberately conservative.

Engine choice is independent of dry_run/live — rendering isn't a
customer-facing mutation.

## Music: the rule that must never be skipped

The sounds trending on TikTok are commercial recordings. Using one on a
**Business account or in any paid ad** is a copyright violation — TikTok
mutes or removes the video. The legal path has three tiers, and every ad
conversation should state which tier the current video is on:

1. **Placeholder tone** (no music key set): audible synthetic chords, labeled
   `placeholder` in the track title/license. Fine for judging pacing, never
   postable. Fix: free Jamendo key (2 min at devportal.jamendo.com →
   `JAMENDO_CLIENT_ID` in `.env`).
2. **Royalty-free bed** (Jamendo/Pixabay): legal in the rendered draft. The
   live music client already filters out NonCommercial licences — an ad is
   commercial use.
3. **TikTok Commercial Music Library**: the only catalogue cleared for
   Business-account/paid-ad use, browsable **only in the TikTok app**, no
   API. The operator swaps the CML track in when posting. That manual step
   is the design, not a gap.

## Script quality rules (what the content agent is held to)

- Hook under 40 chars, names the viewer's problem, never the product
  ("Your dog eats way too fast", not "Introducing our lick mat")
- 3–6 shots, one idea each, ≤45 chars, **never more shots than the product
  has photos** (`get_video_candidates` reports `photo_count`)
- CTA ≤ 4 words
- Every claim grounded in the product's real listing copy — no invented
  discounts, reviews, or capabilities
- `music_query` is a mood ("upbeat playful ukulele"), not a song title

## Judging a render

Look at actual frames, not just ffprobe. Extract and *view* them:
`ffmpeg -ss <t> -i ad.mp4 -frames:v 1 frame.png`. Check: product fully in
frame (square supplier photos must be contained, not cropped), text readable
at phone size, end card present, audio audible and the right length.

When a render fails or looks wrong, read
[references/render-troubleshooting.md](references/render-troubleshooting.md)
— it carries the known failure modes and their measured fixes.
