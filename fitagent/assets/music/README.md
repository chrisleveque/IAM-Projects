# Background music library

Drop copyright-free tracks in this folder. **Recommended source: the YouTube
Audio Library** (YouTube Studio → Audio Library) — its tracks are explicitly
cleared for monetized YouTube use with no Content ID claims, which is why
fitagent prefers a local library over third-party free-music APIs.

Audio files here are gitignored; only this README is committed.

## Naming convention

Prefix the filename with a mood, double-underscore, then the title:

```
epic__rising-tide.mp3
dark__low-ember.mp3
gritty__iron-work.mp3
calm__first-light.mp3
```

Moods the visual director assigns (and the pipeline matches against):
`epic`, `dark`, `gritty`, `calm`. Files without a mood prefix are still
usable as a fallback pool.

Keep at least 2-3 tracks per mood so back-to-back videos don't repeat music
(`fitagent doctor` will warn if the library is thin). Instrumental tracks
only — vocals fight the voiceover.
