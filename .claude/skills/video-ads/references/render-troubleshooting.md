# Render troubleshooting (known failure modes, measured fixes)

Every entry here was hit for real. Check these before re-deriving anything.

## "The video has no sound" / silent audio

The #1 report, and it's configuration, not a bug: without a music key the
mock music client supplies the bed. It used to be *literally silent*; now
it's an audible synthetic chord loop labeled `placeholder` in title and
license. Either way the fix is the same: `JAMENDO_CLIENT_ID` in `.env`
(free, devportal.jamendo.com). `shopagent doctor` shows the key state; the
approval result's `music.note` says when a placeholder was used.

## ffmpeg engine gotchas (all verified the hard way)

- **`zoompan` is unusable for stills**: 45–90s to render ONE 2.8s shot
  (it rescales the source every output frame). The renderer uses an animated
  `crop` window instead — 1.5s for the same shot, ~30× faster. Never
  reintroduce zoompan.
- **An `fps` filter after `overlay` drops the final frame at EOF.** Isolated
  repro: 6 frames without it, 5 with. Normalize frame rate at the *inputs*
  (`-framerate` on stills, `r=` on lavfi) and only pixel format
  (`format=yuv420p`) inside the graph — that's the part xfade actually
  needs.
- **`-shortest` does not reliably cut a filtered audio stream** — it left a
  20s soundtrack on an 11.2s video. Use `atrim=0:<total>` with the total
  computed from the real segment math: `n·d − (n−1)·t` for crossfades, plus
  the end card. Verify by probing *per-stream* durations, not the container.
- **drawtext text must go through `textfile=`, never inline `text=`** —
  product copy is full of `:` `'` `%` that break inline escaping. Filter
  paths need `C:\` colons escaped (`_filter_path`).
- **Square supplier photos must be contained, not cover-cropped**: 1:1 →
  9:16 cover discards ~44% of width and slices wide products. The renderer
  picks per-image via `image_size` (which also rejects ffprobe's silent
  `0x0` answer for corrupt files — usually a supplier URL that returned an
  error page).
- **A crossfade longer than half the shortest segment** would consume it;
  the renderer clamps `fade = min(transition, min(durations)/2)`.

## json2video engine

- Client at `integrations/json2video_client.py`; movie JSON built by the
  pure `build_movie()` — tests pin its shape. Schema was written from docs
  without a live account; **field-name drift is expected** on first live
  render.
- Two safety nets, in order: the executor's LLM repair loop (max 2 attempts;
  the model gets the API error + the movie JSON, returns a fixed JSON), then
  fallback to the ffmpeg engine. The approval result records
  `repaired_after` (fixed, succeeded) or `repair_errors` + `fallback`
  (gave up, ffmpeg rendered).
- Colors: config uses ffmpeg `0xRRGGBB`; their API wants CSS `#RRGGBB` —
  `build_movie` converts. If a color renders wrong, look there first.
- Never send a `mock://` music URL to the cloud engine — their servers
  can't fetch it and the whole render fails. The executor already filters
  to http(s) URLs.
- `check_auth()` is the doctor probe: any authenticated response passes,
  401/403 means bad key.

## Voiceover

- json2video engine: their TTS via `voice` elements — reliable, included in
  credits.
- ffmpeg engine: edge-tts (`pip install -e .[voice]`, `video.voiceover:
  true`) — rides an unofficial Microsoft endpoint. Failures downgrade to a
  music-only render with a `voiceover: skipped` note; that is intended, not
  a bug to fix.

## Performance expectations (1080×1920, 4 shots + end card)

ffmpeg engine ~20s locally. json2video: seconds to submit, then their queue
(poll shows `running`); timeout is 300s. If a *test* render is slow, check it
is using the SMALL sizes (180×320, fps 10) like the existing suite does.
