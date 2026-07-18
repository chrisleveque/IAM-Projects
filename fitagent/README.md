# fitagent — an AI agent team for a fitness motivation YouTube channel

fitagent runs a team of Claude-powered agents that produce classic-style
men's fitness motivation videos — dark cinematic stock b-roll, deep AI
voiceover, burned-in captions, ducked music — and queue them for review.
**Nothing is uploaded until you approve it.**

```
                       ┌──────────────────────┐
                       │       Pipeline        │  deterministic per-video run
                       └──────────┬───────────┘
      ┌────────────┬──────────────┼──────────────┐
┌─────▼─────┐ ┌────▼────────┐ ┌───▼──────────┐ ┌─▼─────────┐
│ Ideation  │ │ Scriptwriter│ │ VisualDirector│ │ Metadata  │   Claude agents
└─────┬─────┘ └────┬────────┘ └───┬──────────┘ └─┬─────────┘
      └────────────┴───────┬──────┴──────────────┘
                           ▼
        TTS ─ footage ─ captions ─ music ─ ffmpeg render      deterministic media
                           ▼
                 ┌───────────────────┐        ┌──────────────────┐
                 │   Review queue     │──────▶│  YOU approve or   │
                 │ (SQLite, in_review)│        │  reject via CLI   │
                 └───────────────────┘        └────────┬─────────┘
                                                       ▼
                                              ┌──────────────────┐
                                              │     Executor      │
                                              │  YouTube upload   │
                                              └──────────────────┘
```

Every run produces **one long-form 16:9 video (5–10 min)** plus **2–3
vertical Shorts** cut from the strongest segments.

## Copyright-safe by construction

The channel is built to be monetizable, so every layer is copyright-clean:

- **Scripts**: ~80% original writing by Claude; ~20% built on public-domain
  texts (Marcus Aurelius, Seneca, Henley's *Invictus*, Kipling's *If—*),
  with attribution added to the description. No modern speaker audio, ever.
- **Voice**: AI text-to-speech — free Microsoft Edge neural voice by
  default, ElevenLabs as an optional upgrade.
- **Footage**: Pexels / Pixabay stock video (both licenses allow monetized
  commercial use); every clip's provider, id, and license is recorded.
- **Music**: your local `assets/music/` library, sourced from the YouTube
  Audio Library (zero Content-ID risk).

## The safety model

Agents cannot publish. The pipeline renders videos into a review queue;
a separate executor — invoked only by `fitagent approve` / `fitagent
upload` — performs uploads. The gate is structural, not instructional.
When you're ready to go hands-off, set `publishing.auto_upload: true`;
approvals are then created and executed automatically but still recorded.

## Quickstart (no API keys except Anthropic)

```bash
cd fitagent
pip install -e ".[dev]"
sudo apt-get install -y ffmpeg        # the only system dependency
cp .env.example .env                  # add your ANTHROPIC_API_KEY

fitagent doctor                       # check the setup
fitagent run                          # produce a video (dry_run: mock footage)
fitagent queue                        # see what landed for review
fitagent show 1                       # inspect metadata + file path
fitagent approve 1 && fitagent upload # "uploads" to the mock client
```

In `dry_run` mode stock footage and YouTube are mocked (generated test
patterns / an upload receipt file), but the agents and the free edge-tts
voice are real — you get a genuine watchable video with zero paid keys.

Run the tests (no network, no keys; render tests auto-skip without ffmpeg):

```bash
python -m pytest tests/
```

## Going live

1. **Stock footage** (free): get keys at pexels.com/api and
   pixabay.com/api/docs, put them in `.env`, set `mode: live`.
2. **Music**: download instrumental tracks from the YouTube Audio Library
   into `assets/music/` using the mood naming (`epic__title.mp3` …) — see
   `assets/music/README.md`.
3. **YouTube upload**:
   - Google Cloud Console → new project → enable *YouTube Data API v3*.
   - OAuth consent screen (External, testing) → add yourself as test user.
   - Credentials → OAuth client ID → *Desktop app* → download JSON as
     `client_secret.json` in the project root.
   - `pip install -e ".[youtube]"` then `fitagent auth youtube`.
   - Know the platform rules: **unverified API projects upload
     private-only** until Google's audit passes; testing-mode refresh
     tokens expire every 7 days; upload quota is ~6 videos/day by default.
4. **Voice upgrade** (optional): set `ELEVENLABS_API_KEY` +
   `ELEVENLABS_VOICE_ID` in `.env` and `tts.provider: elevenlabs` in the
   preset.

## Scaling up

- **Daily cadence**: `cron` →
  `0 6 * * * cd ~/IAM-Projects/fitagent && fitagent run && fitagent upload`
  (run generates; upload pushes whatever you've approved from your phone).
- **More volume**: `fitagent run --count 2`, or multiple cron lines.
- **More channels**: add a preset per channel in `config.yaml`; each gets
  its own YouTube token (`.youtube_token.<preset>.json`).
- **AI-generated visuals later**: the shot plan already carries
  `query` + `target_seconds` per shot — implement a generator client with
  the same `search/download` interface in `integrations/stock.py` and
  swap it in without touching the agents.

## Configuration reference (`config.yaml`)

| Key | Meaning |
|---|---|
| `mode` | `dry_run` (mock stock + YouTube) or `live` |
| `active_preset` | which channel preset `run` uses |
| `presets.<name>.original_ratio` | share of original vs public-domain scripts (0.8 = 80/20) |
| `presets.<name>.tts` | provider (`edge`/`elevenlabs`/`mock`), voice, rate, pitch |
| `video.long_form` / `video.shorts` | resolution, fps, length bounds, shorts count |
| `audio.*` | loudness targets (voice −16 LUFS, master −14) and duck ratio |
| `publishing.auto_upload` | `true` = skip the manual approval step (still logged) |
| `publishing.default_privacy` | `private` (recommended at first) / `unlisted` / `public` |
| `ai.model` | Claude model for all agents |

## Project layout

```
src/fitagent/
├── cli.py            # all commands
├── config.py         # config.yaml + .env loading, mode resolution
├── store.py          # SQLite: runs, videos, assets, approvals, agent_runs
├── pipeline.py       # deterministic per-video run driver
├── executor.py       # the ONLY code that uploads
├── pd_library.py     # public-domain source loader
├── ai/client.py      # Anthropic wrapper + manual tool-use loop
├── agents/           # ideation, scriptwriter, visual_director, metadata
├── media/            # ffmpeg, tts, captions, footage, music, assemble, shorts
└── integrations/     # pexels/pixabay/mock stock, youtube + mock
```

## Roadmap ideas

- Thumbnail generation from `thumbnail_text` + a frame grab
- Crossfade transitions and beat-synced cuts
- A/B title testing via the YouTube Analytics API
- Per-preset posting schedules with a morning approval digest
